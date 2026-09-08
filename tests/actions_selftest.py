"""`/api/actions` 渲染层测试：dialog 视图形状 + 两级去重（消息级 / 块级）。无录制、无代理。"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

TMP = tempfile.TemporaryDirectory(prefix="ccwa-actions-test-")
os.environ["CCWA_HOME"] = TMP.name
os.environ["CCWA_CLAUDE_SETTINGS"] = str(Path(TMP.name) / "settings.json")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import actions
import capture_store as store

DATE = "2026-09-08"


def node(rid, sec, lane="s-main", turn="t1"):
    return {"id": rid, "lane": lane, "turn": turn, "model": "opus-5",
            "ts_start": f"{DATE}T12:00:{sec:02}", "total_ms": 1000}


def rec(messages, blocks=(), error=None):
    r = {"request": {"body": {"messages": messages}},
         "response": {"content_blocks": list(blocks)}}
    if error:
        r["error"] = error
    return r


def tool_use(name, inp, cid="call_a"):
    return {"type": "tool_use", "id": cid, "name": name, "input": inp}


def tool_result(cid="call_a", content="输出", error=False):
    return {"type": "tool_result", "tool_use_id": cid, "content": content, "is_error": error}


def say(text):
    return {"type": "text", "text": text}


def think(text):
    return {"type": "thinking", "thinking": text, "signature": "sig"}


class DialogViewTests(unittest.TestCase):
    """dialog 视图：剥工具输入输出，每步一行摘要，用户消息剥 harness 噪音。"""

    def render(self, n, r, view="dialog"):
        return actions.render_step(n, r, set(), set(), view)

    def test_full_view_unchanged_shape(self):
        lines = self.render(node("req_a", 1), rec(
            [{"role": "user", "content": "看一下"}],
            [tool_use("Bash", {"command": "ls"}), say("结论")]), view="full")
        self.assertIn("[用户] 看一下", lines)
        self.assertIn('[Bash] {"command": "ls"}', lines)
        self.assertIn("[说] 结论", lines)

    def test_dialog_strips_tool_detail_keeps_dialog(self):
        lines = self.render(node("req_a", 1), rec(
            [{"role": "user", "content": [tool_result(content="很长的工具输出")]}],
            [tool_use("Bash", {"command": "grep -rn near src/"}), say("结论"), think("想一下")]))
        self.assertIn("[用了 Bash] grep -rn near src/", lines)
        self.assertIn("[说] 结论", lines)
        self.assertIn("[思考] 想一下", lines)
        self.assertFalse(any(l.startswith("[工具返回") for l in lines))
        self.assertFalse(any('"command"' in l for l in lines))

    def test_dialog_strips_tool_result_in_history(self):
        lines = self.render(node("req_a", 1), rec(
            [{"role": "user", "content": [tool_result(error=True)]}], []))
        self.assertEqual([l for l in lines if l.startswith("[")], [])

    def test_dialog_user_message_noise_stripped_command_kept(self):
        noisy = ("<system-reminder>规划上下文</system-reminder>"
                 "<command-name>/compact</command-name>"
                 "<local-command-stdout>已压缩 471 条</local-command-stdout>"
                 " 还有一个问题，辅助不会折叠")
        lines = self.render(node("req_a", 1), rec([{"role": "user", "content": noisy}], []))
        user_lines = [l for l in lines if l.startswith("[用户]")]
        self.assertEqual(len(user_lines), 1)
        self.assertIn("/compact", user_lines[0])
        self.assertIn("还有一个问题", user_lines[0])
        self.assertNotIn("system-reminder", user_lines[0])
        self.assertNotIn("已压缩", user_lines[0])

    def test_tool_line_field_priority_and_fallback(self):
        line = actions._tool_line("Edit", {"file_path": "src/app.py", "old_string": "x" * 300})
        self.assertEqual(line, "[用了 Edit] src/app.py")
        line = actions._tool_line("Bash", {"command": "line1\nline2"})
        self.assertEqual(line, "[用了 Bash] line1")
        long_cmd = "python " + "x" * 200
        self.assertEqual(actions._tool_line("Bash", {"command": long_cmd}),
                         "[用了 Bash] " + long_cmd[:80])
        self.assertEqual(actions._tool_line("Task", {"description": "检查前端", "prompt": "…"}),
                         "[派生子代理] 检查前端")
        # mcp__* 等自定义工具没有优先级字段 → 第一个非空字符串值兜底
        line = actions._tool_line("mcp__x__evaluate_script", {"pageId": 3, "function": "() => 1"})
        self.assertEqual(line, "[用了 mcp__x__evaluate_script] () => 1")


class DedupTests(unittest.TestCase):
    """两级去重：消息级挡重发历史，块级挡 [说]→[助手] 的内容级重复。"""

    def test_assistant_text_not_repeated_from_history(self):
        seen, bseen = set(), set()
        blocks = [say("是 bug，不是设计")]
        first = actions.render_step(node("req_a", 1), rec([{"role": "user", "content": "问"}], blocks),
                                    seen, bseen)
        self.assertIn("[说] 是 bug，不是设计", first)
        # 下一次请求的历史里整段重发（user 结果 + assistant 正文）
        second = actions.render_step(node("req_b", 2), rec(
            [{"role": "user", "content": [tool_result()]},
             {"role": "assistant", "content": [blocks[0]]},
             {"role": "user", "content": "下一个问题"}],
            [say("下一答")]), seen, bseen)
        self.assertIn("[工具返回] 输出", second)
        self.assertIn("[用户] 下一个问题", second)
        self.assertIn("[说] 下一答", second)
        self.assertFalse(any("是 bug" in l for l in second))

    def test_verbatim_repeat_still_shown_once_per_utterance(self):
        seen, bseen = set(), set()
        actions.render_step(node("req_a", 1), rec([], [say("再来一遍")]), seen, bseen)
        second = actions.render_step(node("req_b", 2), rec(
            [{"role": "assistant", "content": [say("再来一遍")]}],
            [say("再来一遍")]), seen, bseen)   # 模型逐字又说了一遍
        self.assertEqual(second.count("[说] 再来一遍"), 1)

    def test_pre_recording_history_assistant_kept(self):
        # 录制开始前的历史：没有对应的已录响应，块级 key 必然未见过 → [助手] 照常输出
        lines = actions.render_step(node("req_a", 1), rec(
            [{"role": "assistant", "content": [say("录制之前的结论")]}], []), set(), set())
        self.assertIn("[助手] 录制之前的结论", lines)


class RouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app
        cls.module = app
        cls.client = app.app.test_client()

    def setUp(self):
        self.rows, self.records, self.dag = [], {}, {"nodes": [], "turns": [], "lanes": []}
        self.patches = [patch.object(store, "list_index", side_effect=self.index),
                        patch.object(store, "records_by_index", side_effect=self.read_batch),
                        patch.object(self.module, "_dag_of", return_value=self.dag)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def index(self, date, exclude, session, source):
        return list(self.rows)

    def read_batch(self, entries, date, source):
        return [self.records.get(e["id"]) for e in entries]

    def add(self, rid, sec, r, lane="s-main"):
        self.rows.append({"id": rid, "off": len(self.rows) * 100, "len": 100, "session_id": "s-1"})
        self.records[rid] = r
        self.dag["nodes"].append(node(rid, sec, lane=lane))

    def get(self, **qs):
        qs.setdefault("date", DATE)
        return self.client.get("/api/actions", query_string=qs).get_json()

    def test_view_dialog_and_unknown_falls_back_to_full(self):
        self.add("req_a", 1, rec([{"role": "user", "content": "问"}],
                                 [tool_use("Bash", {"command": "ls"}), say("答")]))
        dialog = self.get(view="dialog")["content"]
        self.assertIn("[用了 Bash] ls", dialog)
        self.assertNotIn("[Bash] {", dialog)
        full = self.get(view="nonsense")["content"]      # 未知值回退 full，不 500
        self.assertIn("[Bash] {", full)

    def test_since_warm_does_not_replay_say_as_assistant(self):
        self.add("req_a", 1, rec([{"role": "user", "content": "问一"}], [say("答一")]))
        self.add("req_b", 2, rec(
            [{"role": "user", "content": [tool_result()]},
             {"role": "assistant", "content": [say("答一")]},
             {"role": "user", "content": "问二"}], [say("答二")]))
        page2 = self.get(since=1)["content"]
        self.assertIn("[说] 答二", page2)
        self.assertNotIn("答一", page2)                  # warm 块级预热挡住重出
        whole = self.get()["content"]
        self.assertEqual(whole.count("答一"), 1)          # 全量读同样只出一次

    def test_idle_poll_is_done_without_reading_history(self):
        self.add("req_a", 1, rec([{"role": "user", "content": "问题"}], [say("答案")]))
        for since in (1, 9):
            with self.subTest(since=since), patch.object(store, "records_by_index") as read:
                result = self.get(since=since)
                self.assertTrue(result["done"])
                self.assertEqual(result["next"], since)
                self.assertNotIn("#req_", result["content"])
                read.assert_not_called()

    def test_aux_filter_preserves_global_cursor_and_subagents_across_pages(self):
        lanes = ["s-main", "aux", "agent-child", "s-main", "aux"]
        for i, lane in enumerate(lanes):
            self.add(f"req_{i}", i, rec([], [say(f"响应{i}")]), lane)
        default = self.get(view="dialog")
        self.assertTrue(default["include_aux"])
        self.assertEqual((default["total"], default["next"]), (5, 5))
        pages, cursor = [], 0
        for expected_next in (1, 3, 4):
            result = self.get(view="dialog", include_aux="false", since=cursor, limit=1)
            self.assertEqual(result["next"], expected_next)
            self.assertEqual(result["total"], 3)
            self.assertFalse(result["include_aux"])
            pages.append(result["content"])
            cursor = result["next"]
        self.assertTrue(result["done"])
        combined = "\n".join(pages)
        self.assertIn("泳道=agent-child", combined)
        self.assertIn("泳道=s-main", combined)
        for i in (0, 2, 3):
            self.assertEqual(combined.count(f"#req_{i}"), 1)
        for i in (1, 4):
            self.assertNotIn(f"#req_{i}", combined)
        with patch.object(store, "records_by_index") as read:
            idle = self.get(include_aux="false", since=cursor)
            self.assertTrue(idle["done"])
            read.assert_not_called()
        self.add("req_5", 5, rec([], [say("新增回复")]), "agent-child")
        fresh = self.get(include_aux="false", since=cursor)
        self.assertEqual(fresh["next"], 6)
        self.assertIn("#req_5", fresh["content"])
        self.assertNotIn("#req_4", fresh["content"])

    def test_include_aux_rejects_invalid_values(self):
        for value in ("", "0", "False", "yes", "nonsense"):
            with self.subTest(value=value):
                response = self.client.get("/api/actions", query_string={"date": DATE, "include_aux": value})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json()["error"], "bad_include_aux")


if __name__ == "__main__":
    unittest.main(verbosity=2)
