"""Pure index/DAG span expansion tests. No recordings, proxy or model calls."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import os
import sys
import tempfile
import unittest

TMP = tempfile.TemporaryDirectory(prefix="ccwa-scope-test-")
os.environ["CCWA_HOME"] = TMP.name
os.environ["CCWA_CLAUDE_SETTINGS"] = str(Path(TMP.name) / "settings.json")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import observe_scope as scope
import observe_store as OB


class SpanTests(unittest.TestCase):
    def setUp(self):
        self.state = {"scope": {"lane": ""}}
        self.dag = {"nodes": [{"id": rid, "lane": lane} for rid, lane in
                              [("req_a", "main"), ("req_x", "other"),
                               ("req_b", "main"), ("req_c", "main")]]}
        self.entries = [{"id": rid} for rid in ("req_a", "req_x", "req_b", "req_c")]

    def op(self, first="req_a", last="req_c"):
        return {"op": "add_item", "text": "阶段", "cover_span": {"first_rid": first, "last_rid": last}}

    def expand(self, ops):
        return scope.expand_spans(self.state, ops, self.dag, self.entries)

    def reject(self, ops):
        before = deepcopy((self.state, ops, self.dag, self.entries))
        with self.assertRaises(OB.ObserveError) as error:
            self.expand(ops)
        self.assertEqual(error.exception.code, "bad_cover_span")
        self.assertEqual((self.state, ops, self.dag, self.entries), before)

    def test_inclusive_same_lane_no_input_mutation(self):
        ops = [self.op()]
        original = deepcopy(ops)
        out = self.expand(ops)
        self.assertEqual(out[0]["covers"], ["req_a", "req_b", "req_c"])
        self.assertNotIn("cover_span", out[0])
        self.assertEqual(ops, original)
        self.assertIsNot(ops[0], out[0])

    def test_update_and_single_boundary(self):
        out = self.expand([{"op": "update_item", "id": "i_123456", "patch": {
            "title": "阶段", "cover_span": {"first_rid": "req_b", "last_rid": "req_b"}}}])
        self.assertEqual(out[0]["patch"], {"title": "阶段", "covers": ["req_b"]})

    def test_recording_order_not_dag_order(self):
        self.dag["nodes"].reverse()
        self.assertEqual(self.expand([self.op()])[0]["covers"], ["req_a", "req_b", "req_c"])
        self.reject([self.op("req_c", "req_a")])

    def test_cross_lane_unknown_and_filtered_endpoint_rejected(self):
        self.reject([self.op("req_a", "req_x")])
        self.reject([self.op("req_missing", "req_c")])
        self.state["scope"]["lane"] = "other"
        self.reject([self.op()])
        self.state["scope"]["lane"] = ""
        self.entries = self.entries[1:]  # caller's session filter excludes req_a
        self.reject([self.op()])

    def test_session_filtered_intersection_excludes_interior(self):
        self.entries = [e for e in self.entries if e["id"] != "req_b"]
        self.assertEqual(self.expand([self.op()])[0]["covers"], ["req_a", "req_c"])

    def test_exact_shape_and_covers_conflict(self):
        for span in [None, [], "req_a", {}, {"first_rid": "req_a"},
                     {"first_rid": "req_a", "last_rid": "req_c", "extra": 1},
                     {"first_rid": 1, "last_rid": "req_c"},
                     {"first_rid": "../req_a", "last_rid": "req_c"},
                     {"first_rid": "req_a\n", "last_rid": "req_c"}]:
            with self.subTest(span=span):
                self.reject([dict(self.op(), cover_span=span)])
        self.reject([dict(self.op(), covers=[])])
        self.reject([{"op": "update_item", "patch": "invalid"}])

    def test_no_span_passthrough_and_detached(self):
        ops = [{"op": "set_cursor", "cursor": 4}, {"op": "update_item", "patch": {"text": "保留"}}]
        output = self.expand(ops)
        self.assertEqual(output, ops)
        output[1]["patch"]["text"] = "改动副本"
        self.assertEqual(ops[1]["patch"]["text"], "保留")

    def test_2000_boundary_and_2001_rejected(self):
        self.dag = {"nodes": [{"id": f"req_{i}", "lane": "main"} for i in range(2001)]}
        self.entries = [{"id": f"req_{i}"} for i in range(2001)]
        self.assertEqual(len(self.expand([self.op("req_0", "req_1999")])[0]["covers"]), 2000)
        self.reject([self.op("req_0", "req_2000")])

    def test_duplicate_identity_or_missing_lane_rejected(self):
        self.entries.append({"id": "req_b"})
        self.reject([self.op()])
        self.entries.pop()
        self.dag["nodes"][0].pop("lane")
        self.reject([self.op()])

    def test_bad_second_span_does_not_mutate_first(self):
        self.reject([self.op(), self.op("req_c", "req_a")])


class SpanApiTests(unittest.TestCase):
    def test_http_expansion_replay_and_conflict(self):
        from unittest.mock import patch
        import app as web
        state = OB.create({"date": "2026-09-06", "lane": "main", "session": "session-a"}, "span test")
        client = web.app.test_client()
        payload = {"id": state["id"], "submission_id": "span-once", "base_revision": 0,
                   "ops": [{"op": "add_item", "kind": "phase", "text": "stage",
                            "cover_span": {"first_rid": "req_a", "last_rid": "req_b"}}]}
        dag = {"nodes": [{"id": "req_a", "lane": "main"}, {"id": "req_b", "lane": "main"}]}
        with patch.object(web, "_dag_of", return_value=dag), patch.object(web.capture_store, "list_index", return_value=[{"id": "req_a"}, {"id": "req_b"}]) as index:
            response = client.post("/api/observations", json=payload)
            self.assertEqual(response.status_code, 200, response.json)
            self.assertEqual(response.json["state"]["items"][0]["covers"], ["req_a", "req_b"])
            index.assert_called_with("2026-09-06", "", "session-a", "")
        # Retrying after capture cleanup must still replay, not re-resolve a span.
        with patch.object(web.capture_store, "list_index", side_effect=AssertionError("must not read")):
            retry = client.post("/api/observations", json=payload)
            self.assertEqual(retry.status_code, 200, retry.json)
            self.assertTrue(retry.json["replayed"])
            payload["submission_id"] = "stale-new-submit"
            conflict = client.post("/api/observations", json=payload)
            self.assertEqual(conflict.status_code, 409)
            self.assertEqual(conflict.json["state"]["revision"], 1)


class CaptureScopeApiTests(unittest.TestCase):
    """从一条录制请求走到覆盖它的观测：范围解析 + 匹配排序 + 无标题时的下拉摘要。"""

    def setUp(self):
        import app as web
        self.web = web
        self.client = web.app.test_client()
        self.dag = {"nodes": [{"id": "req_main1", "lane": "s-aaa"}, {"id": "req_main2", "lane": "s-bbb"},
                              {"id": "req_aux1", "lane": "aux"}]}
        self.index = [{"id": "req_main1", "session_id": "sess-a"},
                      {"id": "req_main2", "session_id": "sess-b"},
                      {"id": "req_aux1", "session_id": "sess-a"}]

    def ask(self, rid, date="2026-09-07"):
        from unittest.mock import patch
        with patch.object(self.web, "_dag_of", return_value=self.dag),              patch.object(self.web.capture_store, "list_index", return_value=self.index):
            return self.client.get("/api/observations?rid=" + rid + "&date=" + date)

    def test_lane_and_session_resolved_and_matches_ranked(self):
        wide = OB.create({"date": "2026-09-07"}, "只按日期")["id"]
        exact = OB.create({"date": "2026-09-07", "lane": "s-aaa"}, "这条泳道")["id"]
        other = OB.create({"date": "2026-09-07", "lane": "s-bbb"}, "另一条泳道")["id"]
        r = self.ask("req_main1")
        self.assertEqual(r.status_code, 200, r.json)
        self.assertEqual(r.json["capture_scope"],
                         {"date": "2026-09-07", "source": "", "lane": "s-aaa", "session": "sess-a"})
        self.assertEqual(r.json["matches"][0], exact)          # 泳道精确匹配排最前
        self.assertIn(wide, r.json["matches"])                 # 未限定泳道的观测也覆盖它
        self.assertNotIn(other, r.json["matches"])             # 别的泳道不算命中

    def test_aux_request_falls_back_to_its_session_main_lane(self):
        """辅助调用归 aux 泳道，它不是任何一场对话的泳道；跳转要落到同会话主线上。"""
        exact = OB.create({"date": "2026-09-07", "lane": "s-aaa"}, "这条泳道")["id"]
        r = self.ask("req_aux1")
        self.assertEqual(r.json["capture_scope"]["lane"], "s-aaa")
        self.assertEqual(r.json["matches"][0], exact)

    def test_unresolvable_request_still_returns_scope_without_matches(self):
        r = self.ask("req_unknown", date="2026-09-11")
        self.assertEqual(r.status_code, 200, r.json)
        self.assertEqual(r.json["capture_scope"]["date"], "2026-09-11")
        self.assertEqual(r.json["matches"], [])

    def test_listing_preview_replaces_untitled_rows(self):
        oid = OB.create({"date": "2026-09-07", "lane": "s-ccc"})["id"]   # 无标题：外环常常不写
        OB.apply(oid, "seed", 0, [{"op": "add_item", "kind": "goal", "text": "记录一场切割引擎评估会话"}])
        row = next(x for x in self.client.get("/api/observations").json["items"] if x["id"] == oid)
        self.assertEqual(row["title"], "")
        self.assertEqual(row["preview"], "记录一场切割引擎评估会话")
        self.assertFalse(row["has_flow"])


class GoalDeltaApiTests(unittest.TestCase):
    """Exercise the public write surface, including cover_span preprocessing."""

    def setUp(self):
        import app as web
        self.web = web
        self.client = web.app.test_client()
        created = self.client.post("/api/observations", json={
            "scope": {"date": "2026-09-09", "source": "", "lane": "main", "session": "s1"}})
        self.assertEqual(created.status_code, 200, created.json)
        self.oid = created.json["id"]
        self.flow = {"anchor": {"user_text": "检查报告", "understanding": "核对报告",
            "evidence": ["req_a"], "basis": "explicit"}, "tasks": [
            {"id": "t1", "title": "报告检查", "start_id": "g1"}], "iterations": [
            {"id": "g1", "actor": "ai", "before": "检查报告", "after": "核对报告及图表",
             "trigger": "明确核对范围", "evidence": ["req_a"], "basis": "explicit",
             "task_id": "t1", "change": "initial"}], "current": self.current()}
        seeded = self.submit("seed", 0, [{"op": "add_item", "kind": "goal", "text": "目标",
            "client_ref": "goal", "goal_flow": self.flow}])
        self.assertEqual(seeded.status_code, 200, seeded.json)
        self.saved = seeded.json["state"]

    def current(self, **fields):
        return {"goal_ids": ["g1"], "understanding": "核对报告和图表",
                "situation": "仍待核对，尚无验收", "evidence": ["req_a"], **fields}

    def submit(self, sid, revision, ops, mode="full"):
        return self.client.post("/api/observations?response=" + mode, json={
            "id": self.oid, "submission_id": sid, "base_revision": revision, "ops": ops})

    def delta(self, value):
        return {"op": "update_item", "id": "goal", "patch": {"goal_flow_delta": value}}

    def test_current_only_http_changed_replay_and_conflict(self):
        from unittest.mock import patch
        new_current = self.current(situation="数据源差异已发现，目标与验收条件未变", evidence=["req_b"])
        ops = [self.delta({"current": new_current}), {"op": "set_cursor", "cursor": 5}]
        with patch.object(self.web.capture_store, "list_index", side_effect=AssertionError("must not read captures")):
            response = self.submit("current", 1, ops, "changed")
            self.assertEqual(response.status_code, 200, response.json)
            self.assertEqual(response.json["revision"], 2)
            self.assertEqual(response.json["cursor"], 5)
            self.assertNotIn("state", response.json)
            goal = response.json["items"][0]
            self.assertEqual(goal["goal_flow"]["current"], new_current)
            self.assertEqual(goal["goal_flow"]["iterations"], self.saved["items"][0]["goal_flow"]["iterations"])
            self.assertEqual(goal["history"][-1]["goal_flow"], self.saved["items"][0]["goal_flow"])
            self.assertNotIn("goal_flow_delta", goal)
            before = OB._file(self.oid).read_bytes()
            replay = self.submit("current", 1, ops, "changed")
            self.assertEqual(replay.status_code, 200, replay.json)
            self.assertTrue(replay.json["replayed"])
            self.assertEqual(replay.json["items"], response.json["items"])
            conflict = self.submit("new-stale", 1, ops)
            self.assertEqual(conflict.status_code, 409, conflict.json)
            self.assertEqual(conflict.json["state"]["revision"], 2)
            self.assertEqual(OB._file(self.oid).read_bytes(), before)
            self.assertEqual(self.client.get("/api/observations/" + self.oid).json["items"][0], goal)

    def test_delta_survives_span_preprocessing_and_combined_references(self):
        from unittest.mock import patch
        delta = {"tasks": [{"id": "t2", "title": "操作指南", "start_id": "g2"}],
            "iterations": [{"id": "g2", "actor": "user", "before": "核对报告", "after": "另写操作指南",
                "trigger": "用户提出另一交付", "evidence": ["req_b"], "basis": "explicit",
                "parent_ids": ["g1"], "task_id": "t2", "change": "turn"}],
            "events": [{"id": "e2", "kind": "status", "target": "g2", "status": "unresolved",
                "text": "指南边界待澄清", "evidence": ["req_b"]}],
            "current": self.current(goal_ids=["g1", "g2"], carryover="报告检查仍未验收")}
        ops = [{"op": "add_item", "kind": "open", "text": "指南边界", "goal_iteration": "g2",
                "cover_span": {"first_rid": "req_a", "last_rid": "req_b"}}, self.delta(delta)]
        dag = {"nodes": [{"id": "req_a", "lane": "main"}, {"id": "req_b", "lane": "main"}]}
        with patch.object(self.web, "_dag_of", return_value=dag), patch.object(
                self.web.capture_store, "list_index", return_value=[{"id": "req_a"}, {"id": "req_b"}]) as index:
            response = self.submit("span-and-turn", 1, ops)
            self.assertEqual(response.status_code, 200, response.json)
            index.assert_called_with("2026-09-09", "", "s1", "")
        items = response.json["state"]["items"]
        self.assertEqual(items[1]["covers"], ["req_a", "req_b"])
        self.assertEqual(items[1]["goal_iteration"], "g2")
        self.assertEqual(items[0]["goal_flow"]["iterations"][0]["status"], "active")
        self.assertEqual(items[0]["goal_flow"]["iterations"][1]["parent_ids"], ["g1"])
        self.assertEqual(items[0]["goal_flow"]["events"], delta["events"])
        self.assertEqual(items[0]["goal_flow"]["current"], delta["current"])
        # Replay bypasses preprocessing after recordings are gone.
        with patch.object(self.web.capture_store, "list_index", side_effect=AssertionError("must not read")):
            replay = self.submit("span-and-turn", 1, ops)
            self.assertEqual(replay.status_code, 200, replay.json)
            self.assertTrue(replay.json["replayed"])

    def test_invalid_http_batch_rolls_back_span_cursor_history_and_submission(self):
        from unittest.mock import patch
        before = OB._file(self.oid).read_bytes()
        dag = {"nodes": [{"id": "req_a", "lane": "main"}]}
        invalid = [self.delta({"current": self.current(goal_ids=["missing"])}),
            {"op": "update_item", "id": "goal", "patch": {
                "goal_flow": self.flow, "goal_flow_delta": {"current": self.current()}}}]
        with patch.object(self.web, "_dag_of", return_value=dag), patch.object(
                self.web.capture_store, "list_index", return_value=[{"id": "req_a"}]):
            for bad in invalid:
                with self.subTest(bad=bad):
                    response = self.submit("failed-retry", 1, [
                        {"op": "set_cursor", "cursor": 99},
                        {"op": "update_item", "id": "goal", "patch": {"text": "不应保存",
                            "cover_span": {"first_rid": "req_a", "last_rid": "req_a"}}}, bad])
                    self.assertEqual(response.status_code, 400, response.json)
                    self.assertEqual(response.json["error"], "bad_goal_flow")
                    self.assertEqual(OB._file(self.oid).read_bytes(), before)
        retry = self.submit("failed-retry", 1, [self.delta({"current": self.current(situation="继续核对")})])
        self.assertEqual(retry.status_code, 200, retry.json)
        self.assertFalse(retry.json["replayed"])
        self.assertEqual(retry.json["state"]["cursor"], 0)


class FeedbackApiTests(unittest.TestCase):
    def setUp(self):
        import app as web
        self.client = web.app.test_client()
        self.state = OB.create({"date": "2026-09-08"})
        self.oid = self.state["id"]
        r = self.submit("seed", [{"op": "add_item", "client_ref": "ph1", "text": "first"},
                                 {"op": "add_item", "client_ref": "ph2", "text": "second"}])
        self.assertEqual(r.status_code, 200)
        self.refs = r.json["refs"]

    def submit(self, sid, ops, mode="full"):
        return self.client.post("/api/observations?response=" + mode,
            json={"id": self.oid, "submission_id": sid, "ops": ops})

    def test_reported_silent_payloads_rejected_atomically(self):
        for op, field in [
            ({"op": "link_items", "from": "ph2", "to": "ph1", "rel": "depends_on"}, "rel"),
            ({"op": "set_cursor", "next": 16}, "next"),
            ({"op": "update_item", "id": "ph1", "title": "new"}, "title"),
            ({"op": "update_item", "id": "ph1", "patch": {"links": []}}, "links"),
        ]:
            before = OB._file(self.oid).read_bytes()
            r = self.submit("invalid", [{"op": "set_cursor", "cursor": 99}, op])
            self.assertEqual(r.status_code, 400, r.json)
            self.assertEqual(r.json["error"], "unknown_field")
            self.assertIn(field, r.json["detail"])
            self.assertEqual(OB._file(self.oid).read_bytes(), before)

    def test_malformed_json_types_return_400_without_write(self):
        for body in [[], None, 4, "body", {"scope": []}, {"scope": {"lane": []}},
                     {"title": []}, {"id": []}, {"ops": []}, {"extra": 1}]:
            before = list(OB.OBS_DIR.glob("obs_*.json"))
            r = self.client.post("/api/observations", json=body)
            self.assertEqual(r.status_code, 400, (body, r.json))
            self.assertEqual(list(OB.OBS_DIR.glob("obs_*.json")), before)
        for op in [
            {"op": []}, {"op": "update_item", "id": "ph1"},
            {"op": "update_item", "id": "ph1", "patch": {}},
            {"op": "update_item", "id": "ph1", "patch": []},
            {"op": "set_cursor"}, {"op": "set_cursor", "cursor": True},
            {"op": "set_cursor", "cursor": 1.5},
            {"op": "add_item", "text": "x", "kind": []},
            {"op": "add_item", "text": "x", "evidence": 7},
            {"op": "add_item", "text": "x", "client_ref": []},
            {"op": "retract_item", "id": "ph1", "reason": []},
            {"op": "link_items", "from": "ph1", "to": "ph2", "remove": "true"},
        ]:
            before = OB._file(self.oid).read_bytes()
            r = self.submit("invalid", [op])
            self.assertEqual(r.status_code, 400, (op, r.json))
            self.assertEqual(OB._file(self.oid).read_bytes(), before)

    def test_remove_cross_batch_refs_and_compact_responses(self):
        r = self.submit("link", [{"op": "link_items", "from": "ph2", "to": "ph1", "type": "depends_on"}], "refs")
        self.assertEqual(set(r.json), {"ok", "replayed", "revision", "refs"})
        r = self.submit("unlink", [{"op": "link_items", "from": "ph2", "to": "ph1", "type": "depends_on", "remove": True}], "changed")
        self.assertEqual(r.status_code, 200, r.json)
        self.assertNotIn("state", r.json)
        self.assertEqual(len(r.json["items"]), 1)
        item = r.json["items"][0]
        self.assertEqual(item["id"], self.refs["ph2"])
        self.assertEqual(item["links"], [])
        self.assertEqual(item["history"][-1]["links"], [{"type": "depends_on", "to": self.refs["ph1"]}])
        replay = self.submit("unlink", [{"op": "set_cursor", "cursor": 999}], "changed")
        self.assertTrue(replay.json["replayed"])
        self.assertEqual(replay.json["items"], r.json["items"])
        missing = self.submit("unlink-again", [{"op": "link_items", "from": "ph2", "to": "ph1", "type": "depends_on", "remove": True}])
        self.assertEqual(missing.status_code, 400)
        self.assertEqual(missing.json["error"], "no_link")
        self.assertEqual(self.client.get("/api/observations/" + self.oid).json, self.client.get("/api/observations?id=" + self.oid).json)
        self.assertEqual(self.client.get("/api/observations/obs_0000000").status_code, 404)
        before = OB._file(self.oid).read_bytes()
        self.assertEqual(self.submit("bad-mode", [{"op": "set_cursor", "cursor": 1}], "typo").status_code, 400)
        self.assertEqual(OB._file(self.oid).read_bytes(), before)

    def test_text_evidence_reason_limits_without_legacy_read_regression(self):
        for op in [
            {"op": "add_item", "text": "x" * 4001},
            {"op": "add_item", "text": "x", "evidence": ["req_a"] * 51},
            {"op": "update_item", "id": "ph1", "patch": {"text": "x" * 4001}},
            {"op": "update_item", "id": "ph1", "patch": {"evidence": ["req_a"] * 51}},
            {"op": "retract_item", "id": "ph1", "reason": "x" * 1001},
        ]:
            before = OB._file(self.oid).read_bytes()
            r = self.submit("over-limit", [{"op": "set_cursor", "cursor": 99}, op])
            self.assertEqual(r.status_code, 400, r.json)
            self.assertEqual(OB._file(self.oid).read_bytes(), before)
        r = self.submit("at-limit", [{"op": "update_item", "id": "ph1",
            "patch": {"text": "x" * 4000, "evidence": ["req_a"] * 50}},
            {"op": "retract_item", "id": "ph2", "reason": "x" * 1000}])
        self.assertEqual(r.status_code, 200, r.json)
        self.assertEqual(len(r.json["state"]["items"][0]["text"]), 4000)
        self.assertEqual(len(r.json["state"]["items"][0]["evidence"]), 50)
        state = OB.read(self.oid)
        state["items"][0]["text"] = "legacy" * 1000
        state["items"][0]["evidence"] = ["legacy reference"] * 51
        OB._write(state)
        self.assertEqual(self.client.get("/api/observations/" + self.oid).json, state)
        r = self.submit("legacy-title", [{"op": "update_item", "id": "ph1", "patch": {"title": "readable legacy"}}])
        self.assertEqual(r.status_code, 200, r.json)
        self.assertEqual(r.json["state"]["items"][0]["text"], state["items"][0]["text"])
        self.assertEqual(self.client.post("/api/observations", json={"title": "x" * 201}).status_code, 400)

    def test_goal_iteration_final_batch_reference_and_history(self):
        flow = {"anchor": {"user_text": "Inspect", "understanding": "Understand then fix",
            "evidence": ["req_a"], "basis": "explicit"}, "iterations": [
            {"id": "g1", "actor": "ai", "before": "inspect", "after": "fix",
             "trigger": "observed failure", "evidence": ["req_b"], "basis": "explicit"}]}
        # Deliberately put the dependent item before its target flow.
        r = self.submit("iteration-seed", [
            {"op": "add_item", "kind": "phase", "client_ref": "work", "text": "Fix errors", "goal_iteration": "g1"},
            {"op": "add_item", "kind": "goal", "client_ref": "goal", "text": "goal", "goal_flow": flow}])
        self.assertEqual(r.status_code, 200, r.json)
        self.assertNotIn("goal_iteration", r.json["state"]["items"][0])
        evolved = deepcopy(flow)
        evolved["iterations"].append({"id": "g2", "actor": "user", "before": "fix", "after": "verify",
            "trigger": "check result", "evidence": ["req_c"], "basis": "explicit", "parent_ids": ["g1"]})
        r = self.submit("iteration-append", [
            {"op": "update_item", "id": "work", "patch": {"goal_iteration": "g2"}},
            {"op": "update_item", "id": "goal", "patch": {"goal_flow": evolved}}])
        self.assertEqual(r.status_code, 200, r.json)
        work = next(x for x in r.json["state"]["items"] if x.get("goal_iteration"))
        self.assertEqual(work["goal_iteration"], "g2")
        self.assertEqual(work["history"][-1]["goal_iteration"], "g1")
        for ops in [
            [{"op": "retract_item", "id": "goal"}],
            [{"op": "update_item", "id": "work", "patch": {"goal_iteration": "missing"}}],
            [{"op": "update_item", "id": "work", "patch": {"kind": "goal"}}],
        ]:
            before = OB._file(self.oid).read_bytes()
            r = self.submit("dangling", [{"op": "set_cursor", "cursor": 100}, *ops])
            self.assertEqual(r.status_code, 400, r.json)
            self.assertEqual(r.json["error"], "bad_goal_iteration")
            self.assertEqual(OB._file(self.oid).read_bytes(), before)
        # Final-state validation also allows retracting the flow before clearing work.
        r = self.submit("clear-before-retract", [{"op": "retract_item", "id": "goal"},
            {"op": "update_item", "id": "work", "patch": {"goal_iteration": "", "kind": "goal"}}])
        self.assertEqual(r.status_code, 200, r.json)
        work = next(x for x in r.json["state"]["items"] if x["id"] == work["id"])
        self.assertEqual(work["goal_iteration"], "")
        self.assertEqual(work["history"][-1]["goal_iteration"], "g2")

    def test_goal_iteration_invalid_shape_missing_flow_and_retracted_items(self):
        for value in [None, 1, [], {}, True, "x" * 65, "_g1", "g 1", "g1\n"]:
            before = OB._file(self.oid).read_bytes()
            r = self.submit("invalid-iteration", [{"op": "add_item", "text": "work", "goal_iteration": value}])
            self.assertEqual(r.status_code, 400, (value, r.json))
            self.assertEqual(r.json["error"], "bad_goal_iteration")
            self.assertEqual(OB._file(self.oid).read_bytes(), before)
        for op in [{"op": "add_item", "text": "no flow", "goal_iteration": "g1"},
                   {"op": "add_item", "kind": "goal", "text": "bad kind", "goal_iteration": "g1"}]:
            self.assertEqual(self.submit("no-target", [op]).status_code, 400)
        r = self.submit("retracted-reference", [
            {"op": "add_item", "text": "historical", "status": "retracted", "goal_iteration": "g1", "client_ref": "old"}])
        self.assertEqual(r.status_code, 200, r.json)
        self.assertEqual(self.submit("reactivate", [{"op": "update_item", "id": "old", "patch": {"status": "supported"}}]).status_code, 400)
        self.assertEqual(self.submit("reactivate-cleared", [{"op": "update_item", "id": "old", "patch": {"status": "supported", "goal_iteration": ""}}]).status_code, 200)

    def test_goal_events_append_is_atomic_and_keeps_work_on_same_goal(self):
        flow = {"anchor": {"user_text": "Inspect", "understanding": "Fix",
            "evidence": ["req_a"], "basis": "explicit"}, "iterations": [
            {"id": "g1", "actor": "ai", "before": "inspect", "after": "fix",
             "trigger": "failure", "evidence": ["req_b"], "basis": "explicit"}]}
        r = self.submit("event-goal", [{"op": "add_item", "kind": "goal", "client_ref": "goal", "text": "goal", "goal_flow": flow},
            {"op": "add_item", "text": "work", "goal_iteration": "g1"}])
        self.assertEqual(r.status_code, 200, r.json)
        saved = next(x for x in r.json["state"]["items"] if "goal_flow" in x)["goal_flow"]
        updated = deepcopy(saved)
        updated["events"] = [{"id": "e1", "kind": "status", "target": "g1", "status": "achieved", "text": "verified",
            "evidence": ["req_c"], "verification": {"method": "independent_check", "text": "assertions pass", "evidence": ["req_c"]}}]
        r = self.submit("event-append", [{"op": "update_item", "id": "goal", "patch": {"goal_flow": updated}}])
        self.assertEqual(r.status_code, 200, r.json)
        goal = next(x for x in r.json["state"]["items"] if "goal_flow" in x)
        self.assertEqual(goal["goal_flow"]["iterations"], saved["iterations"])
        self.assertEqual(goal["history"][-1]["goal_flow"], saved)
        self.assertEqual(r.json["state"]["items"][-1]["goal_iteration"], "g1")
        before = OB._file(self.oid).read_bytes()
        updated["events"][0]["text"] = "rewrite"
        r = self.submit("event-rewrite", [{"op": "set_cursor", "cursor": 777},
            {"op": "update_item", "id": "goal", "patch": {"goal_flow": updated}}])
        self.assertEqual(r.status_code, 400, r.json)
        self.assertEqual(r.json["error"], "goal_flow_frozen")
        self.assertEqual(OB._file(self.oid).read_bytes(), before)

    def test_goal_flow_store_constraints_and_atomic_append(self):
        flow = {"anchor": {"user_text": "Fix live analysis", "understanding": "Inspect then improve",
                "evidence": ["req_a"], "basis": "explicit"}, "iterations": []}
        r = self.submit("goal", [{"op": "add_item", "kind": "goal", "text": "goal", "client_ref": "goal", "goal_flow": flow}])
        self.assertEqual(r.status_code, 200, r.json)
        saved = r.json["state"]["items"][-1]["goal_flow"]
        for patch in [{"kind": "phase"}, {"goal_flow": None},
                      {"goal_flow": dict(saved, anchor=dict(saved["anchor"], user_text="rewrite"))}]:
            before = OB._file(self.oid).read_bytes()
            r = self.submit("bad-goal", [{"op": "set_cursor", "cursor": 99},
                {"op": "update_item", "id": "goal", "patch": patch}])
            self.assertEqual(r.status_code, 400, r.json)
            self.assertEqual(OB._file(self.oid).read_bytes(), before)
        for kind in ("goal", "phase"):
            r = self.submit("second-goal", [{"op": "add_item", "kind": kind, "text": "another", "goal_flow": flow}])
            self.assertEqual(r.status_code, 400, r.json)
        evolved = deepcopy(saved)
        evolved["iterations"].append({"id": "g1", "actor": "ai", "before": "analysis", "after": "strict validation",
            "trigger": "silent writes", "evidence": ["req_b"], "basis": "explicit"})
        r = self.submit("append", [{"op": "update_item", "id": "goal", "patch": {"goal_flow": evolved}}])
        self.assertEqual(r.status_code, 200, r.json)
        self.assertEqual(r.json["state"]["items"][-1]["history"][-1]["goal_flow"], saved)
        r = self.submit("replace", [{"op": "retract_item", "id": "goal"},
            {"op": "add_item", "kind": "goal", "text": "replacement", "goal_flow": flow}])
        self.assertEqual(r.status_code, 200, r.json)

    def test_refs_survive_bounded_submit_log_and_legacy_ambiguity(self):
        state = OB.read(self.oid)
        # Simulate bounded-log eviction after a successful write.
        state["submits"] = []
        OB._write(state)
        r = self.submit("after-eviction", [{"op": "update_item", "id": "ph1", "patch": {"title": "persistent"}}])
        self.assertEqual(r.status_code, 200, r.json)
        for ops in [
            [{"op": "add_item", "client_ref": "ph1", "text": "duplicate"}],
            [{"op": "add_item", "client_ref": "new", "text": "a"}, {"op": "add_item", "client_ref": "new", "text": "b"}],
        ]:
            before = OB._file(self.oid).read_bytes()
            r = self.submit("duplicate", ops)
            self.assertEqual(r.json["error"], "duplicate_ref")
            self.assertEqual(OB._file(self.oid).read_bytes(), before)
        state = OB.read(self.oid)
        state.pop("refs")
        state["submits"] = [{"sid": "old-a", "refs": {"legacy": self.refs["ph1"]}},
                            {"sid": "old-b", "refs": {"legacy": self.refs["ph2"]}}]
        OB._write(state)
        r = self.submit("ambiguous", [{"op": "update_item", "id": "legacy", "patch": {"title": "wrong"}}])
        self.assertEqual(r.json["error"], "ambiguous_ref")
        replay = self.submit("old-a", [{"op": "add_item", "text": "ignored", "client_ref": "legacy"}])
        self.assertTrue(replay.json["replayed"])
        self.assertEqual(replay.json["refs"], {"legacy": self.refs["ph1"]})
        r = self.submit("by-id", [{"op": "update_item", "id": self.refs["ph1"], "patch": {"title": "explicit"}}])
        self.assertEqual(r.status_code, 200, r.json)


if __name__ == "__main__":
    unittest.main(verbosity=2)
