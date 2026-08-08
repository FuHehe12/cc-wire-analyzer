"""快照自测：存储 / 精确对比 / 思考链抽取 三层，e2e 走真实形状的 record。

用法：uv run python src/snapshot_selftest.py

fixture 全部按**真形状**造（CLAUDE.md 教训④：mock 用了现实中不存在的形状，测试全绿却
什么都没测到）。所以这里的 record 复刻实测结构：system 三块（计费头 / 身份行 / 规则库）、
messages 里 assistant 消息带 thinking 块、thinking 块**不带 signature**（实测 GLM 网关如此，
k3/opus-5 才有）、`Primary working directory:` 写在注入的用户消息里而非 system。

重点断言的是**几处最容易静默失效的地方**：
  - 预算：产出必须真的不超预算（估算过两次、错过两次，见 snapshot_extract._size）
  - 可得性判档：没有思考链时必须给得出原因和行为链，不能是空面板
  - 水印级差异：肉眼不可见的字符差异必须被揭示，且**真实改动不许误报同形异码**
  - 归一化：只差日期的两段必须判成 norm_equal
  - 元数据不是副本：录制快照的信封里不许出现 ctx/src（那是提示词快照才有的）
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import os                                            # noqa: E402
TMP = Path(tempfile.mkdtemp(prefix="ccwa_snap_"))
# **两个都要隔离**：只隔离 CCWA_HOME 会让 settings 那一半仍指向用户真配置
# （260802 实测闯过祸，见开发约定第五节）。这里虽然只读不写，也不留这个口子。
os.environ["CCWA_HOME"] = str(TMP)
os.environ["CCWA_CLAUDE_SETTINGS"] = str(TMP / "fake_settings.json")

import config as CFG                                 # noqa: E402
CFG.CONFIG_DIR = TMP

import snapshot_store as SS                          # noqa: E402
SS.SNAPSHOTS_DIR = TMP / "snapshots"
SS._INDEX_FILE = SS.SNAPSHOTS_DIR / "index.jsonl"

import snapshot_diff as SD                           # noqa: E402
import snapshot_extract as SX                        # noqa: E402

FAILED: list[str] = []


def ok(cond, label: str, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {label}")
    else:
        FAILED.append(label)
        print(f"  ✗ {label}" + (f" —— {detail}" if detail else ""))


# ===== fixture =====

BILLING = "x-anthropic-billing-header: cc_version=2.1.220.abc; cc_entrypoint=cli;\n"
IDENTITY = "You are Claude Code, Anthropic's official CLI for Claude."
RULES = ("\nYou are an interactive agent that helps users with software engineering tasks.\n"
         "Today's date is 2026-08-08.\n" + "Rule line.\n" * 40)
INJECTED = ("<system-reminder>\nContext follows.\n</system-reminder>\n"
            "# Environment\n - Primary working directory: D:\\Claude\n"
            " - Is a git repository: false\n - Platform: win32\n" + "guide line\n" * 200)


def make_record(*, rid="req_test001", thinking=True, steps=6, thinking_type="adaptive"):
    """真形状 record：system 三块 + 用户注入 + N 个 assistant 步（可选带 thinking）。"""
    msgs = [{"role": "user", "content": [{"type": "text", "text": INJECTED}]}]
    for i in range(steps):
        blocks = []
        if thinking:
            # 实测形态：thinking 块**没有 signature**（GLM 网关）。抽取器不许依赖它。
            blocks.append({"type": "thinking",
                           "thinking": (f"第 {i} 步。先看看情况。"
                                        + ("但是这里不对，等等，我重新想想。" if i % 2 else "")
                                        + ("方案 A 是直接改，或者方案 B 是先验证。" if i == 3 else "")
                                        + "细节内容。" * 60)})
        blocks.append({"type": "tool_use", "name": "Read" if i % 2 else "Bash",
                       "input": {"file_path": f"D:/x/{i}.py"} if i % 2 else {"command": "ls"}})
        msgs.append({"role": "assistant", "content": blocks})
        msgs.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": f"t{i}", "content": "output"}]})
    body = {
        "model": "glm-5.2", "stream": True,
        "system": [{"type": "text", "text": BILLING},
                   {"type": "text", "text": IDENTITY},
                   {"type": "text", "text": RULES, "cache_control": {"type": "ephemeral"}}],
        "messages": msgs,
        "tools": [{"name": "Read", "description": "read a file", "input_schema": {}},
                  {"name": "Bash", "description": "run a command", "input_schema": {}}],
    }
    if thinking_type:
        body["thinking"] = {"type": thinking_type}
    return {
        "id": rid, "ts_start": "2026-08-08T10:00:00.000", "ts_end": "2026-08-08T10:00:05.000",
        "method": "POST", "path": "/v1/messages",
        "upstream": "https://open.bigmodel.cn/api/anthropic/v1/messages",
        "request": {"headers_safe": {"anthropic-beta": "interleaved-thinking-2025-05-14"},
                    "body": body},
        "response": {"status": 200, "content_blocks": [{"type": "text", "text": "done"}],
                     "usage": {"input_tokens": 100, "output_tokens": 20}},
        "error": None,
    }


# ===== [1] 存储：两类快照的元数据待遇不对称 =====
print("\n[1] 存储层")
rec = make_record()
cap = SS.create_capture(rec, tags=["基线"])
pr = SS.create_prompt(rec, {"kind": "system", "index": 2}, tags=["基线"])

ok(cap["kind"] == "capture" and "ctx" not in cap and "src" not in cap,
   "录制快照信封不含元数据副本（事实只在 payload 里，副本必然分叉）",
   f"实际键：{sorted(cap.keys())}")
ok(cap.get("summary", {}).get("thinking_blocks") == 6,
   "录制快照的列表字段现算自 payload")
ok(pr["ctx"]["upstream"] == "open.bigmodel.cn",
   "提示词快照带上游供应商指纹", str(pr["ctx"]))
ok(pr["ctx"]["harness"] == "claude-code/2.1.220.abc",
   "harness 取自 system[0] 计费头", pr["ctx"]["harness"])
ok(pr["ctx"]["env"].get("workspace") == "D:\\Claude",
   "工作空间从注入的用户消息里也抽得到（不限定在 system 中找）",
   str(pr["ctx"]["env"]))
ok(pr["ctx"]["env"].get("platform") == "win32", "平台可提取")
ok(pr["origin"]["cache_control"] == "ephemeral", "缓存断点标记落在 origin 上")
ok(pr["origin"]["block_shape"] == [len(BILLING), len(IDENTITY), len(RULES)],
   "块形状记录下来（块被拆分/合并时才看得出）", str(pr["origin"]["block_shape"]))
ok(pr["origin"]["kind_hint"] == "cc_rules", "来源类型判别", pr["origin"]["kind_hint"])
ok(pr["schema"] == SS.SNAP_SCHEMA and pr["ccwa_version"], "带格式版本与工具版本")
ok(not pr.get("label"), "默认不写标题——三语界面里语言相关文案不该进数据")

# messages 来源（证据 6：提示词不只在 system 里）
pm = SS.create_prompt(rec, {"kind": "message", "index": 0, "block": 0})
ok(pm["origin"]["where"] == "messages[0].content[0]" and pm["origin"]["role"] == "user",
   "messages 里的提示词也能备份")

# 索引可重建
before = SS.list_snapshots()
SS._INDEX_FILE.unlink()
ok(SS.list_snapshots() == before, "索引删掉能从快照文件全量重建（索引是缓存不是事实源）")

# 路径穿越
try:
    SS.get_snapshot("../../etc/passwd")
    ok(False, "sid 白名单拦路径穿越")
except SS.SnapshotError as e:
    ok(e.code == "bad_sid", "sid 白名单拦路径穿越", e.code)

# 归一化指纹
f1 = SS.text_fingerprint("date 2026-08-08 id 550e8400-e29b-41d4-a716-446655440000 at 14:03")
f2 = SS.text_fingerprint("date 2026-08-09 id 550e8400-e29b-41d4-a716-446655440099 at 09:11")
ok(f1["sha256"] != f2["sha256"] and f1["norm_sha256"] == f2["norm_sha256"],
   "归一化指纹让「只差日期」判成相同（否则每天的快照两两都有差异）")

# ===== [2] 精确对比：水印级差异 =====
print("\n[2] 精确对比")
base = "Anthropic's official CLI.\nToday's date is 2026-08-08."
d = SD.diff_text(base, base.replace("'", "\u2019"))
hgs = [op for h in d["hunks"] for ln in h["lines"]
       for op in (ln.get("inline") or []) if op.get("hg")]
ok(len(hgs) >= 1 and hgs[0]["hg"] == "撇号", "撇号同形异码被打标（U+0027 → U+2019）")
ok(d["homoglyphs"].get("撇号", {}).get("b", {}).get("U+2019") == 2
   and not d["homoglyphs"].get("撇号", {}).get("a"),
   "同形异码分布进汇总（基准 U+0027 不计入，只报可疑的那个）",
   json.dumps(d["homoglyphs"], ensure_ascii=False))

d = SD.diff_text("a b", "a\u00a0b")
ok(d["invisible"]["b"].get("NBSP") == 1, "NBSP 被计数")
ok("⟨NBSP⟩" in json.dumps(d["hunks"], ensure_ascii=False),
   "NBSP 在正文里被揭示成可见记号（不揭示就是两行看起来一样却标着不同）")

d = SD.diff_text("line\r\nx", "line\nx")
ok(d["invisible"]["a"].get("CR") == 1, "CRLF 与 LF 之差看得见")

d = SD.diff_text("rule A", "rule A ")
ok(d["invisible"]["b"].get("行尾空白") == 1, "行尾空格看得见")

d = SD.diff_text("Today is 2026-08-08.", "Today is 2026-08-09.")
ok(not d["equal"] and d["norm_equal"], "只差日期 → norm_equal 为真")

# **反向断言**：正常改动不许误报同形异码。第一版把半角空格算进同形异码组，
# 于是每一次真实增删（空格数变了）都报一条，恒亮的告警等于没有告警。
d = SD.diff_text("You must run tests.", "You must always run the tests.")
ok(not d["homoglyphs"],
   "真实内容改动不误报同形异码（基准字符不参与比较）", str(d["homoglyphs"]))

# 跨类型拒绝
try:
    SD.diff_snapshots(cap["sid"], pr["sid"])
    ok(False, "跨类型对比被拒")
except SS.SnapshotError as e:
    ok(e.code == "kind_mismatch", "跨类型对比被拒", e.code)

# 对比面
rec2 = make_record(rid="req_test002", steps=8)
cap2 = SS.create_capture(rec2)
r = SD.diff_snapshots(cap["sid"], cap2["sid"], face="messages")
ok(r["face"] == "messages" and r["counts"]["added"] > 0,
   "录制之间比 messages 面（上下文腐烂的观测口）")
r = SD.diff_snapshots(cap["sid"], cap2["sid"], face="system")
ok(r["equal"], "同样的 system 在两条录制间判为相同")

# 可比性护栏
rec3 = make_record(rid="req_test003")
rec3["request"]["body"]["model"] = "claude-opus-5"
pr3 = SS.create_prompt(rec3, {"kind": "system", "index": 2})
m = SD.compare_meta(SS.get_snapshot(pr["sid"]), SS.get_snapshot(pr3["sid"]))
ok(any(w["field"] == "model" for w in m["warnings"]),
   "模型不同时给可比性提醒（提示但不阻止）")

# ===== [3] 思考链抽取 =====
print("\n[3] 思考链抽取")
av = SX.availability(rec)
ok(av["tier"] == "A" and av["steps"] == 6 and av["steps_with_thinking"] == 6,
   "A 档：六步全部有思考", json.dumps(av, ensure_ascii=False))

sig_steps = [s for s in SX.steps_of(rec) if s["signals"]]
ok(len(sig_steps) >= 3, "机械信号命中犹豫/分支措辞", f"命中 {len(sig_steps)} 步")
ok(any("分支" in s["signals"] for s in SX.steps_of(rec)), "分支信号可识别")

# 预算是硬约束——估算错过两次，这里逐档实测
for budget in (2000, 5000, 20000, 80000):
    out = SX.level1(rec, budget=budget)
    ok(out["size"] <= budget or out.get("over_budget"),
       f"L1 预算 {budget} 守住（或如实声明超出）",
       f"size={out['size']} over_budget={out.get('over_budget')}")
out = SX.level1(rec, budget=80000)
ok(out["steps_total"] == 6 and "steps_with_excerpt" in out,
   "砍掉了什么必须说得出（steps_total / steps_with_excerpt）")

l0 = SX.level0(rec)
ok(len(l0["steps"]) == 6 and l0["size"] <= SX.L0_BUDGET,
   "L0 骨架把每一步都摆出来", f"{len(l0['steps'])} 步 / {l0['size']} 字符")

# 步号从 1 开始（fixture 的第 i=3 个 assistant → 第 4 步）
l2 = SX.level2(rec, 4)
ok("方案 A" in l2["step"]["thinking"], "L2 给出该步思考原文",
   l2["step"]["thinking"][:60])

# B 档：显式关闭思考
rec_b = make_record(rid="req_test004", thinking=False, thinking_type="disabled")
av_b = SX.availability(rec_b)
ok(av_b["tier"] == "B" and av_b["reason_code"] == "disabled",
   "B 档：thinking=disabled 被识别", json.dumps(av_b, ensure_ascii=False))
ok(av_b["reason"], "B 档必须说出具体原因，不能只说「没有」")
l0b = SX.level0(rec_b)
ok(l0b.get("behavior", {}).get("tool_calls") == 6,
   "B 档退到行为链（工具调用序列）")

# B 档：未启用 thinking 字段
rec_b2 = make_record(rid="req_test005", thinking=False, thinking_type=None)
ok(SX.availability(rec_b2)["reason_code"] == "absent",
   "B 档：请求体没有 thinking 字段时给出的原因不同于 disabled")

# 行为链的反复证据
rec_r = make_record(rid="req_test006", thinking=False, thinking_type="disabled", steps=6)
for m2 in rec_r["request"]["body"]["messages"]:
    if m2.get("role") == "assistant":
        for b in m2["content"]:
            if b.get("type") == "tool_use":
                b["name"] = "Read"
                b["input"] = {"file_path": "D:/same.py"}
bh = SX.behavior_chain(rec_r)
ok(any(r["kind"] == "same_tool_run" for r in bh["repeats"]), "连续同工具被识别为反复")
ok(any(r["kind"] == "same_target" for r in bh["repeats"]), "反复操作同一目标被识别")

# C 档：上游加密
rec_c = make_record(rid="req_test007", thinking=False, thinking_type="adaptive")
rec_c["request"]["body"]["messages"][1]["content"].insert(
    0, {"type": "redacted_thinking", "data": "encrypted"})
ok(SX.availability(rec_c)["tier"] == "C", "C 档：redacted_thinking 被识别")

# 多源指令清单
srcs = SX.instruction_sources(rec)
wheres = [s["where"] for s in srcs]
ok("system[0]" in wheres and "system[2]" in wheres and "tools" in wheres,
   "多源清单覆盖 system 各块与工具描述", str(wheres))
ok(all(s["chars"] > 0 for s in srcs), "每个来源都有字符数")

# 重复注入合并
rec_d = make_record(rid="req_test008")
dup = {"type": "text", "text": "The task tools haven't been used recently. " * 20}
for i in (2, 4, 6):
    rec_d["request"]["body"]["messages"].insert(i, {"role": "system", "content": [dict(dup)]})
merged = [s for s in SX.instruction_sources(rec_d) if s.get("repeats", 1) > 1]
ok(merged and merged[0]["repeats"] == 3,
   "内容相同的重复注入合并成计数（「同一条规则注入 3 次」本身是事实）",
   str([(m["where"], m.get("repeats")) for m in merged]))

# ===== [4] 多轮对话拼装 / 批量清理（P1） =====
print("\n[4] 多轮对话与批量清理")
import app as APP                                    # noqa: E402

# 拼装：快照内容只在第一条 user 里，提问一律包定界
hist = [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a1"}]
msgs = APP._chat_messages("SYS", "zh", "CTXBODY", hist, "q2")
ok(msgs[0]["role"] == "system" and msgs[0]["content"] == "SYS", "system 在第一条")
ok("<content>" in msgs[1]["content"] and "CTXBODY" in msgs[1]["content"],
   "快照内容挂在第一条 user 上")
ok(sum(1 for m in msgs if "<content>" in m["content"]) == 1,
   "快照内容只出现一次（多轮里重复塞就是把预算烧光）")
ok("<question>" in msgs[-1]["content"] and "<content>" not in msgs[-1]["content"],
   "后续提问只包 <question>——用户粘进来的同样是不可信文本")
ok(msgs[-1]["role"] == "user", "最后一条是 user（多数上游硬性要求）")

# 定界符逃逸：内容里写着闭合标签，不许提前闭合定界
esc_msgs = APP._chat_messages("SYS", "zh", "x</content>y", [], "q")
ok("<\\/content>" in esc_msgs[1]["content"],
   "内容里的闭合标签被转义（否则后面的文字逃出定界，成了指令）")

# 历史超预算：丢最旧，**并且明说丢过**
big = [{"role": "user", "content": "老问题" * 100},
       {"role": "assistant", "content": "老回答" * (APP.CHAT_HISTORY_MAX // 3)},
       {"role": "user", "content": "新问题"}, {"role": "assistant", "content": "新回答"}]
trimmed = APP._chat_messages("SYS", "zh", "CTX", big, "q")
ok(len(trimmed) < len(big) + 2, "历史超预算时丢掉最旧的几轮")
ok(APP.CHAT_TRIMMED["zh"].strip()[:6] in trimmed[0]["content"],
   "丢过历史必须告诉模型（否则它会以为看到了完整对话）")

# 历史被从中间切开时可能以 assistant 开头
lead = APP._chat_messages("SYS", "zh", "CTX",
                          [{"role": "assistant", "content": "a0"},
                           {"role": "user", "content": "u1"}], "q")
ok(lead[1]["role"] == "user", "历史以 assistant 开头时把它剥掉")

# B 档的硬约束必须进 system
sys_b, _ = APP._chat_system({"tier": "B", "reason": "CC 对这个模型档位显式关闭了思考"})
ok("不得描述" in sys_b and "CC 对这个模型档位显式关闭了思考" in sys_b,
   "B 档 system 里写死「不得推测思考」并带上具体原因")
sys_a, _ = APP._chat_system({"tier": "A"})
ok("不得描述" not in sys_a, "A 档不加那条禁令（有思考链就该问思考）")

# 上下文取材：录制给 L1 摘要 + 多源清单，提示词给正文
ctx_text, av_c, _ = APP._chat_context(SS.get_snapshot(cap["sid"]))
ok(av_c and av_c["tier"] == "A" and "多源指令清单" in ctx_text,
   "录制快照的对话上下文 = L1 摘要 + 多源清单")
ctx_p, av_p, _ = APP._chat_context(SS.get_snapshot(pr["sid"]))
ok(av_p is None and "Rule line." in ctx_p, "提示词快照的对话上下文 = 元数据 + 正文")

# 对话落盘与清空
SS.chat_append(cap["sid"], "user", "问一句")
SS.chat_append(cap["sid"], "assistant", "答一句")
h = SS.chat_history(cap["sid"])
ok(len(h) == 2 and h[0]["role"] == "user" and h[0].get("ts"), "对话落盘带时间戳")
SS.chat_clear(cap["sid"])
ok(SS.chat_history(cap["sid"]) == [], "对话可清空")

# 批量清理：先选后删，条件之间是「与」
victim = SS.create_capture(make_record(rid="req_test009"), tags=["待清理"])
SS.chat_append(victim["sid"], "user", "留个对话文件")
ok([e["sid"] for e in SS.select_snapshots(tags=["待清理"])] == [victim["sid"]],
   "按标签选中")
ok(all(e["kind"] == "prompt" for e in SS.select_snapshots(kind="prompt")), "按类型选中")
ok(SS.select_snapshots(tags=["待清理"], before="2000-01-01") == [],
   "条件是「与」不是「或」（早于 2000 年的一条都没有）")
ok(SS.size_of(victim["sid"]) > 0, "清理预览说得出能腾出多少字节")
res = SS.delete_many([victim["sid"]])
ok(res["deleted"] == 1 and res["freed"] > 0 and not res["failed"], "批量删除")
ok(not SS.chat_file(victim["sid"]).exists(), "对话记录跟着快照一起删（不留孤儿文件）")
ok(all(e["sid"] != victim["sid"] for e in SS.list_snapshots()), "索引跟着更新")
res2 = SS.delete_many([victim["sid"]])
ok(res2["deleted"] == 0 and len(res2["failed"]) == 1,
   "删不掉的原样报回来（删一半停下来，用户既不知道删了谁也不知道剩下谁）")

# ===== 结果 =====
print()
if FAILED:
    print(f"[FAILED] {len(FAILED)} 条断言未通过：")
    for f in FAILED:
        print("  -", f)
else:
    print("[ALL PASSED] 快照存储 / 精确对比 / 思考链抽取 / 多轮对话与清理 全部通过 ✓")
