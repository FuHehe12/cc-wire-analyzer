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
        blocks.append({"type": "tool_use", "id": f"t{i}",
                       "name": "Read" if i % 2 else "Bash",
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

# C 档：思考块在、明文没回（只有 signature）。260904 全量扫描实测：claude-opus-5 有整条
# 录制 26/26 块都这样，按"块存在"判档就给了 A，brief 于是引导 agent 去读一个空抽屉。
rec_sig = make_record(rid="req_test004b", steps=6)
for m2 in rec_sig["request"]["body"]["messages"]:
    if m2.get("role") == "assistant":
        for b in m2["content"]:
            if b.get("type") == "thinking":
                b["thinking"], b["signature"] = "", "Er8B" + "x" * 40
av_sig = SX.availability(rec_sig)
ok(av_sig["tier"] == "C" and av_sig["reason_code"] == "signature_only",
   "C 档：思考块存在但明文为空（只回签名）不许判 A",
   json.dumps(av_sig, ensure_ascii=False))
ok(av_sig["steps_with_thinking"] == 6 and av_sig["steps_with_plaintext"] == 0,
   "块数与明文步数分别报告（前端靠这两个数说清「有块无明文」）")
ok(SX.level0(rec_sig).get("behavior", {}).get("tool_calls") == 6,
   "C 档同样退到行为链——思考读不到时，行为序列是唯一剩下的原料")

# A 档夹空块：有明文就仍是 A，但"读到的不是全部"必须标出来
rec_mix = make_record(rid="req_test004c", steps=6)
_blanked = 0
for m2 in rec_mix["request"]["body"]["messages"]:
    if m2.get("role") != "assistant" or _blanked >= 2:
        continue
    for b in m2["content"]:
        if b.get("type") == "thinking":
            b["thinking"] = ""
            _blanked += 1
av_mix = SX.availability(rec_mix)
ok(av_mix["tier"] == "A" and av_mix.get("partial_empty") is True
   and av_mix["steps_with_plaintext"] == 4,
   "A 档夹空块：仍判 A，但 partial_empty 标出并非全部可读",
   json.dumps(av_mix, ensure_ascii=False))

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

# ===== 骨架 AI 语义层：步号校验是分层能否成立的分界线（260809）=====
# prompt 里要求「只引用真实步号」是要求，不是保证。没有这道校验，"AI 归纳挂在程序事实上"
# 就只是一句说辞——模型可以归纳出一轮根本不存在的步骤，而界面照样渲染得像模像样。
import app as APP  # noqa: E402

_sk = {"steps": [{"step": 1}, {"step": 2}]}
_raw = {"turns": [{"turn": 1, "steps": [1, 2, 99, "x", None], "title": "t",
                   "intent": "i", "risk": ""}], "summary": "s"}
_clean = APP._sanitize_analysis(_raw, _sk)
ok(_clean["turns"][0]["steps"] == [1, 2], "越界/非整数步号被剔除，只留骨架里真实存在的")
ok(_clean["dropped_steps"] == [99, "x", None], "剔除的步号如实记下来（不静默丢弃）")
ok(len(APP._sanitize_analysis({"turns": "not-a-list"}, _sk)["turns"]) == 0,
   "turns 不是数组时不炸，按空处理")
ok(len(APP._sanitize_analysis({"turns": [{"turn": 1, "steps": [1],
                                          "title": "x" * 9999}]}, _sk)["turns"][0]["title"])
   == APP.ANALYSIS_TEXT_MAX, "超长文本被截断（模型跑飞不该灌满磁盘与界面）")
ok(APP._json_from_llm('```json\n{"a":1}\n```')["a"] == 1, "带 markdown 围栏的 JSON 能解析")
ok(APP._json_from_llm('这是结果：{"a":2} 完毕')["a"] == 2, "前后有闲话的 JSON 能解析")

# 步级简报批处理（260826）：纯工具步不进模型、头尾截断与批预算——都不发网络请求的部分
_bsteps = [
    {"step": 1, "turn": 1, "trigger": {"kind": "user"},
     "thinking": "想先看结构再动手", "reply": "", "tools": []},
    {"step": 2, "turn": 1, "trigger": {"kind": "user"}, "thinking": "", "reply": "",
     "tools": [{"name": "Grep"}, {"name": "Read"}]},
    {"step": 3, "turn": 1, "trigger": {"kind": "user"},
     "thinking": "开头任务设定" + "x" * 9000 + "结尾决定用方案B", "reply": "", "tools": []},
]
_batches = APP._step_brief_batches(_bsteps)
ok([r["step"] for b in _batches for r in b] == [1, 3],
   "纯执行步不单独成条（不为它多花一次调用）")
# 260828：不单独成条 ≠ 被丢掉。它的动作与结果要挂到前一个有判断的步上——
# 否则模型只看得见「决定要做」，看不见「做了什么、成了没有」，got 这一段根本写不出来。
_r1 = _batches[0][0]
ok([a["tool"] for a in _r1["acts"]] == ["Grep", "Read"] and _r1["also_steps"] == [2],
   "纯执行步的动作并入前一步，并记下它原本是第几步（证据链不断）")
# 跨轮不许并：纯执行步偶尔正好落在轮首（用户刚说完，模型不思考直接调工具）。
# 并错了界面上看不出任何异常，但"这一轮做了什么"从此是错的。
_cross = [
    {"step": 1, "turn": 1, "trigger": {"kind": "user"}, "thinking": "第一轮在想", "reply": "",
     "tools": []},
    {"step": 2, "turn": 2, "trigger": {"kind": "user"}, "thinking": "", "reply": "",
     "tools": [{"name": "Write", "verb": "write", "target": "新的.py"}]},
]
_cb = [r for b in APP._step_brief_batches(_cross) for r in b]
ok(len(_cb) == 1 and not _cb[0]["acts"] and "also_steps" not in _cb[0],
   "轮首的纯执行步不并入上一轮（并错了不会报错，只会让整轮归纳变成错的）")
_t3 = _batches[-1][-1]["thinking"]
ok(len(_t3) <= APP.STEP_BRIEF_THINK_HEAD + APP.STEP_BRIEF_THINK_TAIL + 40,
   "超长思考链截断到头+尾预算内")
ok(_t3.startswith("开头任务设定") and "结尾决定用方案B" in _t3 and "中段截断" in _t3,
   "头尾保留、中段截断且自陈（结论常在尾部，一刀切头会丢决定）")
ok(all(len(json.dumps({"steps": b}, ensure_ascii=False)) <= APP.STEP_BRIEF_BATCH_CHARS + 400
       for b in _batches), "每批输入不超字符预算（单步截断后仍可能略超，容包装余量）")


# ===== 结果摘要 / 物料识别 / 轮级新原料（260828，issue 260828_轨迹节点化与步级简报重做）=====
#
# 这一批测的是**这次改动最容易悄悄失效的地方**：结果摘要一旦把 base64 放进去，
# 一次归纳的成本会翻几倍而没有任何东西会报错；物料识别一旦退化成"取命令第一个 token"，
# 一轮里十几件不同的事会被算成同一个物料；用户指令一旦仍被截到 200 字，
# 「AI 有没有照你说的做」就还是答不了。

# 结果摘要：图片只计数，**绝不把 base64 带进原料**（实测单张 33,768 字符）
_img = [{"type": "image", "source": {"type": "base64", "data": "iVBORw0KGgo" + "A" * 30000}}]
_d = SX.result_digest(_img, False)
ok(_d == "1 张图片" and "iVBOR" not in _d, "图片结果只计数，base64 一个字符都不进摘要")
ok(SX.result_digest([{"type": "image", "source": {}}, {"type": "image", "source": {}}], False)
   == "2 张图片", "多张图片报张数")
ok(SX.result_digest("boom: file not found", True).startswith("失败："),
   "报错结果带失败前缀（成败必须一眼可读）")
ok(len(SX.result_digest("x" * 5000, False)) <= SX.RESULT_MAX,
   "长结果摘要不超硬上限（跑飞护栏）")
ok("字/" in SX.result_digest("y" * 900, False), "长结果标出体量（多少字、多少行）")
ok(SX.result_digest("", False) == "（空结果）", "空结果如实说空，不是留白让人猜")

# 物料识别：四个真实反例（260828 画泳道图时逐个撞出来的）
ok(SX.target_of({"command": 'cd "E:/p/lab" && uv run python scripts/x.py'}) == "x.py",
   "剥掉 cd 前缀、跳过解释器，取到真正的脚本")
ok(SX.target_of({"command": "uv run python -c \"print(1)\""}) == "«内联脚本»",
   "python -c 没有脚本文件，归一到内联脚本（不能变成物料 python）")
ok(SX.target_of({"command": 'cat <<EOF\nx\nEOF'}) == "«内联脚本»", "heredoc 同样归一")
ok(SX.target_of({"command": '"C:/Program Files/c/chrome.exe" --headless'}) == "$chrome.exe",
   "带引号的可执行路径取文件名，不是半条路径")
ok(SX.target_of({"file_path": "D:/a/b/json_to_scl.py"}) == "json_to_scl.py", "文件参数取 basename")
ok(SX.target_of({"command": "ls -la"}) == "$ls", "普通命令保留命令名（前缀 $ 表示它不是文件）")

# 轮首用户指令不再被砍到 200 字（实测 teammate 报告 1,838 字，46 轮里 26 轮撞上老上限）
_long = "请按以下要求做：" + "细则内容。" * 900 + "最后一句是完成标准。"
_rec_long = make_record(steps=1)
_rec_long["request"]["body"]["messages"][0] = {"role": "user", "content": _long}
_st = SX.steps_of(_rec_long)
ok(len(_st[0]["trigger"]["text"]) > 1500, "长指令不再被截到 200 字（否则答不了「有没有照你说的做」）")
ok(_st[0]["trigger"]["text"].endswith("最后一句是完成标准。"),
   "取头尾：完成标准常在指令末尾，一刀切头会把它丢掉")
ok("中段截断" in _st[0]["trigger"]["text"], "截断了必须自陈（不许假装是全文）")

# steps_of 现在带动作 / 物料 / 结果
_rs = SX.steps_of(make_record(steps=2))
_t0 = _rs[0]["tools"][0]
ok(_t0["verb"] == "exec" and _t0["target"] == "$ls" and _t0["result"] == "output",
   "每次工具调用都带 动作 / 作用对象 / 结果摘要")
ok(SX.verb_of("Write") == "write" and SX.verb_of("Read") == "read"
   and SX.verb_of("NoSuchTool") == "exec",
   "动作规范化：未知工具算 exec（宁可把只读的算成执行，也不能把改现实的算成只读）")

# 轮级原料：用户说了什么 + 程序事实（碰了什么、写了什么、验没验）
_fsteps = [
    {"step": 1, "turn": 1, "trigger": {"kind": "user", "text": "把 a.py 改好并跑通"},
     "tools": [{"name": "Write", "verb": "write", "target": "a.py"}]},
    {"step": 2, "turn": 1, "trigger": {"kind": "tool_result"},
     "tools": [{"name": "Bash", "verb": "exec", "target": "a.py"}]},
    {"step": 3, "turn": 2, "trigger": {"kind": "user", "text": "再改 b.py"},
     "tools": [{"name": "Write", "verb": "write", "target": "b.py"},
               {"name": "Bash", "verb": "exec", "target": "$ls", "error": True}]},
]
_f = APP._turn_facts(_fsteps)
ok(_f[1]["wrote"] == ["a.py"] and _f[1]["verified"] == ["a.py"]
   and _f[1]["wrote_unverified"] == [],
   "写完又跑过 = 这一轮自己验过（验收状态由程序判，不问模型）")
ok(_f[2]["wrote_unverified"] == ["b.py"] and _f[2]["errors"] == 1,
   "写完没回头碰 = 未验证；失败次数一并记账")
_rows = APP._turn_rollup_rows(_fsteps, [])
ok(_rows[0].get("user_said") == "把 a.py 改好并跑通",
   "轮级原料带上用户这轮说了什么（260828 之前这里一个字都没有）")
ok(_rows[0]["facts"]["touched"] == ["a.py"] and "facts" not in _rows[1],
   "程序事实只挂在每轮第一条（重复挂等于把同一份事实抄 N 遍进原料）")
ok(_rows[0]["acts"] == ["write a.py"], "轮级看得到动作与对象，不只是工具名")

# 三代简报格式并存：换 schema 不能把用户已经写好的 steps_prompt 判死
_v = {1, 2, 3}
_out = APP._brief_rows([{"step": 1, "brief": "老的单段"},
                        {"step": 2, "title": "两段标题", "detail": "两段正文"},
                        {"step": 3, "title": "三段标题", "why": "因为", "got": "CE=0"}], _v)
ok(_out[0]["detail"] == "老的单段" and not _out[0]["title"], "单段格式落进 detail，标题留空")
ok(_out[1]["title"] == "两段标题" and _out[1]["detail"] == "两段正文", "两段格式原样保留")
ok(_out[2]["why"] == "因为" and _out[2]["got"] == "CE=0", "三段格式各字段归位")

# 轮级归纳的新字段要能穿过步号校验（校验只该剔步号，不该把字段吃掉）
_cl = APP._sanitize_analysis(
    {"turns": [{"turn": 1, "steps": [1], "title": "t", "said": "要 x", "solving": "解决 y",
                "done_when": "跑通", "outcome": "成了", "risk": ""}]}, {1})
ok(_cl["turns"][0]["said"] == "要 x" and _cl["turns"][0]["solving"] == "解决 y"
   and _cl["turns"][0]["outcome"] == "成了", "轮级五问字段完整落地")
ok("intent" in _cl["turns"][0], "老字段 intent 仍在（自定义 turns_prompt 是已发布契约）")

# ===== 归纳管线：并发 / 续跑 / 轮级切批（260827，不发网络请求的部分）=====
#
# 这几条测的是**这次改动最容易悄悄失效的地方**：并发跑批乱序、续跑把已有结果算丢、
# 一轮被拆到两批里。三者都不会报错，只会让归纳结果变得似是而非。
import time as _time  # noqa: E402

_order = APP._map_batches([1, 2, 3, 4, 5], lambda b: ([b], [], ""))
ok([r[0][0] for r in _order] == [1, 2, 3, 4, 5],
   "并发跑批**按输入顺序**返回（顺序是叙事的一部分，不能按完成先后拼）")


def _slow(b):
    _time.sleep(0.25)
    return ([b], [], "")


_t0 = _time.time()
APP._map_batches(list(range(8)), _slow)
_wall = _time.time() - _t0
ok(_wall < 8 * 0.25 * 0.6,
   f"并发确实在并发（8 批 × 0.25s 串行要 2s，实测 {_wall:.2f}s）")

_boom = APP._map_batches([1], lambda b: 1 / 0)
ok(_boom[0][0] == [] and _boom[0][2],
   "一批抛异常只算这一批失败并记下原因——绝不连坐掉整次归纳")

ok(APP._ana_workers() >= 1, "并发数有下限（0 会让归纳一批都跑不动）")

_calls = []


def _flaky():
    _calls.append(1)
    return None if len(_calls) < 3 else {"ok": 1}


_got, _err = APP._retrying(_flaky)
ok(_got == {"ok": 1} and len(_calls) == 3, "重试到成功为止（退避，不是马上再来一次）")


def _nokey():
    raise APP.LlmConfigError("no_api_key", "没配 Key")


_c0 = _time.time()
_g2, _e2 = APP._retrying(_nokey)
ok(_g2 is None and "Key" in _e2 and _time.time() - _c0 < 1.0,
   "配置错**立刻**放弃（重试三次还是没填 Key，只会把一次归纳拖成三倍）")

_rows = [{"step": i, "turn": 1 if i <= 30 else 2, "trigger": "u", "tools": [],
          "title": "标题" * 10, "detail": "细节" * 60} for i in range(1, 61)]
_tb = APP._turn_batches(_rows)
ok(len(_tb) >= 2, "长会话的轮级归纳会切批")
for _b in _tb:
    ok(len({r["turn"] for r in _b}) >= 1, "每批至少含一轮")
_seen = {}
for _i, _b in enumerate(_tb):
    for _t in {r["turn"] for r in _b}:
        _seen.setdefault(_t, set()).add(_i)
ok(all(len(v) == 1 for v in _seen.values()),
   "**一轮绝不被拆到两批里**（拆开的话两批各看到半轮，归纳出两个半截意图）")

ok(APP._sanitize_analysis({"turns": [{"turn": 1, "steps": [1, 2, 99]}]}, {1, 2})["turns"][0]["steps"]
   == [1, 2],
   "步号校验收**真实步号集合**：L0 超预算会砍步骤，跟着骨架判合法会把好步号也误杀")

_merged = {b["step"]: b for b in [{"step": 1, "title": "旧"}, {"step": 2, "title": "旧"}]}
_merged.update({b["step"]: b for b in [{"step": 2, "title": "新"}, {"step": 3, "title": "新"}]})
ok([_merged[k]["title"] for k in sorted(_merged)] == ["旧", "新", "新"],
   "续跑合并：已有的保留、重跑的覆盖、新增的补进来（按步号归位，与批次顺序无关）")

_have_steps = [{"step": i, "turn": 1, "trigger": {"kind": "user"},
                "thinking": f"第{i}步在想什么", "reply": "", "tools": []} for i in range(1, 9)]
_todo = [s for s in _have_steps if s["step"] not in {1, 2, 3}]
ok([r["step"] for b in APP._step_brief_batches(_todo) for r in b] == [4, 5, 6, 7, 8],
   "续跑只把缺口送进模型（已有简报的步不再花一次钱）")

# 分析文件跟着快照走（与对话记录同一条清单）
_av = SS.create_capture(make_record(rid="req_test010"))
SS.write_analysis(_av["sid"], {"turns": [], "summary": "x"})
ok(SS.read_analysis(_av["sid"])["summary"] == "x", "语义分析可落盘可读回")
ok(SS.size_of(_av["sid"]) > 0, "size_of 把分析文件算进去")
SS.delete_snapshot(_av["sid"])
ok(not SS.analysis_file(_av["sid"]).exists(), "分析文件跟着快照一起删（不留孤儿文件）")

# ===== 快照便携包：导出 → 导入 往返（260827，issue 260827_快照便携包导出导入）=====
#
# 这几条测的是**搬运过程中最容易悄悄丢东西的地方**：归纳没跟着走、同 sid 被覆盖、
# 来源签名丢失。三者都不报错，只会让对面机器上的东西看起来"少了点什么"。
import snapshot_pack as SP  # noqa: E402

_p1 = SS.create_capture(make_record(rid="req_pack001"), label="待导出", tags=["e2e"])
SS.write_analysis(_p1["sid"], {"turns": [{"turn": 1, "steps": [1], "title": "轮头"}],
                               "steps": [{"step": 1, "title": "标题", "detail": "细节"}],
                               "sub_summary": {"lane-x": {"task": "干活", "outcome": "成了"}},
                               "summary": "整段总结"})
SS.write_semantic(_p1["sid"], {"phases": [{"from": 0, "to": 0, "name": "唯一阶段"}],
                               "briefs": {"main:0": "起步"}})
SS.chat_append(_p1["sid"], "user", "这条问答也该跟着走")

_pkg = TMP / "snapshots-e2e.ccwa"
_man = SP.export_snapshots([_p1["sid"]], _pkg)
ok(_pkg.exists() and _man["count"] == 1, "导出产出单文件包")
ok(_man["items"][0]["has_analysis"] and _man["items"][0]["has_chat"],
   "manifest 上就能看出带没带归纳与问答（不解包就该看得清——这正是它存在的理由）")
ok(_man["items"][0]["has_semantic"], "八视图语义层也在 manifest 上（260828：它和归纳一样是花钱算的）")
ok(_man["host"] and _man["tool_version"] and _man["tool_version"] != "",
   "签名非空：哪台机器、哪个版本产出的（空 = 答不上来，260826 为此查了一整轮）")
ok("\\" not in json.dumps(_man["host"]) and "/" not in _man["host"],
   "host 只取机器名，不带路径/用户名")

_peek = SP.peek(_pkg)
ok(_peek["kind"] == "snapshots", "不解包就能认出这是快照包")

# 同 sid 再导入一次：**不许覆盖**，换个新 sid 落地
_before = (SS._snap_file(_p1["sid"])).read_bytes()
_r = SP.import_snapshots(_pkg)
ok(_r["imported"] == 1 and _r["renamed"] and _r["renamed"][0]["from"] == _p1["sid"],
   "同 sid 冲突时改名落地，不覆盖（拿别人的证据顶替自己的，正是 sources/ 要防的那件事）")
ok(SS._snap_file(_p1["sid"]).read_bytes() == _before, "本机原件一个字节都没被动过")

_new = _r["items"][0]["sid"]
_ana = SS.read_analysis(_new)
ok(_ana and len(_ana["steps"]) == 1 and _ana["sid"] == _new,
   "归纳跟着搬过去了，且 sid 已改写成落地后的（不改就对不上快照）")
ok(_ana.get("sub_summary", {}).get("lane-x", {}).get("outcome") == "成了",
   "子代理线级结论也在包里——原始录制在对面机器上捞不到，它是唯一还能读到的部分")
ok(SS.chat_file(_new).exists(), "问答记录跟着搬")
_sem = SS.read_semantic(_new)
ok(_sem and _sem["briefs"].get("main:0") == "起步",
   "八视图语义层跟着搬（丢了就得在对面机器重跑一遍模型）")
_env = SS.get_snapshot(_new)
ok((_env.get("imported_from") or {}).get("sid") == _p1["sid"]
   and (_env.get("imported_from") or {}).get("host"),
   "落地后记得住来路（哪台机器、原来叫什么）")

try:
    SP.export_snapshots([], TMP / "empty.ccwa")
    ok(False, "空选择必须报错")
except SP.SnapPackError as e:
    ok(e.code == "no_snapshots", "空选择如实报错，不产出一个空包")

_bad = TMP / "notapack.ccwa"
_bad.write_bytes(b"not a zip at all")
try:
    SP.peek(_bad)
    ok(False, "坏文件必须报错")
except SP.SnapPackError as e:
    ok(e.code == "bad_archive", "坏文件如实报错（不静默当成空包）")

# ===== 结果 =====
print()
if FAILED:
    print(f"[FAILED] {len(FAILED)} 条断言未通过：")
    for f in FAILED:
        print("  -", f)
else:
    print("[ALL PASSED] 快照存储 / 精确对比 / 思考链抽取 / 多轮对话与清理 全部通过 ✓")
