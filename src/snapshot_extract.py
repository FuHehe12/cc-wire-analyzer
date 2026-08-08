"""思考链抽取：把一条录制压成 AI 吃得下、人看得懂的分析原料。

## 为什么必须有这一层

一条晚期请求的 `messages` 里带着**整条对话到此刻为止的完整思考链**——实测最大一条
66 个 thinking 块、314,286 字符（260808，2026-07-28 录制）。而 LLM 输入硬上限是 20,000
字符：**差 15 倍**。直接丢过去不可能，直接截断则只看得到开头几轮，恰好丢掉"腐烂"发生的
后期。所以压缩质量直接决定这个功能有没有用。

分三层，各自的读者不同：
  L0 骨架  ≤3K   每步一行：谁触发的、思考多少字、调了什么工具、有没有可疑信号
  L1 摘要  ≤15K  每步思考的首尾 + 机械信号标记（喂给低成本 AI 的默认输入）
  L2 全文        单步思考原文（人点开看，或 agent 按需索取）

## 可得性分三档（260808 用户提醒后补的设计）

「没有思考链」不是边缘情况：实测 claude-sonnet-5 档 **23/23 全部 thinking=disabled**、
glm-5v-turbo 44 条里只有 1 条有思考。如果这个模块只在有思考链时有用，它对相当一部分
录制就是个空面板。

  A 有思考   messages 里有 thinking 块          → L0/L1/L2 全功能
  B 无思考   没有 thinking 块                   → 退到**行为链**，并说出**具体原因**
  C 被加密   有 redacted_thinking 块            → 计数并标注，其余按 A/B 处理

**判档在「步」这一级做，不在模型级做**：`adaptive` 是主流形态（GLM/k3/opus-5 都是），
同一个模型内部也会有的步思考、有的步不思考。

## 行为链不许当成思考链

B 档只有行为记录。行为能回答「它做了什么、在哪儿反复」，**回答不了「它当时在犹豫什么」**。
两者混为一谈就是让 AI 对着工具调用记录编造心理活动。所以 B 档的输出里不含任何
"它可能在想…"的措辞，分析提示词也显式禁止推测思考内容。
"""
from __future__ import annotations

import json
import re

import classifier

# 三层的字符预算。L1 是喂给低成本 AI 的默认输入，留足余量给 system guard 与用户提问
# （app.LLM_INPUT_MAX = 20000）。
# L0 的职责是**把每一步都摆出来**——摆不全就不叫骨架。实测 66 步的对话需要约 9.5K
# （最初定的 3K 逼着它砍掉 58 步，那不是压缩，是把功能砍了）。所以 L0 走"行尽量瘦、
# 预算给够"，砍步数只作为极端长对话（数百步）的兜底。
L0_BUDGET = 20000

# L1 分两档，因为**两个消费者的胃口差一个数量级**（260808 用户定：低成本模型不贵，
# 实在不行让 Claude Code 这类工具直接分析）：
#   LOCAL —— 软件内的低成本模型，受 app.ANALYZE_INPUT_MAX 约束
#   AGENT —— 外部 agent 经 HTTP API 取走，上下文远比前者宽裕
# API 可用 ?budget= 覆盖，两档只是默认值。
L1_BUDGET_LOCAL = 20000
L1_BUDGET_AGENT = 80000
L1_BUDGET = L1_BUDGET_LOCAL      # 兼容默认

# 每步摘录的字符保底。**保底与预算冲突时，减少「有摘录的步数」而不是压薄每一步**——
# 把 66 步平摊成每步 100 字，等于把预算摊成谁也读不懂的噪声；不如让信号最强的那些步
# 拿到读得懂的篇幅，其余步骤仍在骨架里占一行（形状不丢）。
EXCERPT_FLOOR = 220
STEP_HEAD = 260         # L1 里每步思考取首尾各多少字
STEP_TAIL = 180


# ===== 机械信号 =====
#
# 这些是**候选信号，不是结论**：命中只说明"这一步值得看"，判断交给 AI 或人。
# 之所以用机械规则而不是让 AI 通读——AI 通读就得先把 31 万字塞进去，正是这层要解决的问题。
_SIGNALS = [
    ("犹豫", [
        r"但是", r"不过", r"实际上", r"其实", r"等等", r"重新想", r"再想想", r"不对",
        r"我错了", r"糟糕", r"奇怪", r"没道理", r"说不通",
        r"\bwait\b", r"\bhmm+\b", r"\bactually\b", r"\bhold on\b", r"\bbut\b",
        r"\bhowever\b", r"\bthat'?s odd\b", r"\bdoesn'?t make sense\b",
    ]),
    ("分支", [
        r"方案\s*[ABC1-3一二三]", r"或者", r"另一种", r"两种", r"要么", r"选项",
        r"权衡", r"取舍",
        r"\boption\s*[ab1-3]\b", r"\balternatively\b", r"\beither\b",
        r"\btwo (?:ways|options|approaches)\b", r"\btrade-?off\b",
    ]),
    ("自我修正", [
        r"我之前", r"刚才(?:错|说错|漏)", r"更正", r"修正一下", r"收回", r"重来",
        r"\bcorrection\b", r"\bi was wrong\b", r"\bearlier i\b", r"\bscratch that\b",
        r"\blet me redo\b",
    ]),
    ("不确定", [
        r"可能", r"也许", r"不确定", r"猜", r"应该是吧", r"待确认", r"存疑",
        r"\bnot sure\b", r"\bprobably\b", r"\bmaybe\b", r"\bi think\b", r"\bunclear\b",
        r"\bassume\b",
    ]),
]
_SIGNAL_RE = [(name, re.compile("|".join(pats), re.IGNORECASE)) for name, pats in _SIGNALS]


def signals_of(text: str) -> dict:
    """文本命中的信号 → {类别: 命中次数}。空 dict = 无信号。"""
    out: dict[str, int] = {}
    for name, rx in _SIGNAL_RE:
        n = len(rx.findall(text))
        if n:
            out[name] = n
    return out


# 句子切分：中英文句末标点 + 换行。粗糙但够用——这里要的是"命中信号的那句话"，
# 不是语言学意义上的分句。
_SENT_SPLIT = re.compile(r"(?<=[。！？!?\n])|(?<=\. )")
MARK_LEN = 90
MARK_PER_STEP = 2


def marks_of(text: str, kinds=("分支", "自我修正", "犹豫")) -> list[dict]:
    """命中信号的**那句话**（不只是次数）。

    信号计数回答"这步值得看吗"，句子回答"它在权衡什么"——树视图上一个只写着
    「分支 ×1」的节点没有信息量，写着「方案 A 是直接改，或者方案 B 是先验证」才有。

    **这是候选不是结论**：命中关键词的句子未必真的在讨论分支。所以只取一两句、
    标明类别，判断仍交给读的人或 AI。
    """
    if not text:
        return []
    sents = [s.strip() for s in _SENT_SPLIT.split(text) if s and s.strip()]
    out: list[dict] = []
    seen: set[str] = set()
    for name, rx in _SIGNAL_RE:
        if name not in kinds:
            continue
        for s in sents:
            if len(out) >= MARK_PER_STEP:
                return out
            if rx.search(s) and s not in seen:
                seen.add(s)
                out.append({"kind": name, "text": s[:MARK_LEN]})
                break        # 每类只取第一句，避免一步刷屏
    return out


# ===== 拆步 =====

def _text_of(blocks, types=("text",)) -> str:
    out = []
    for b in blocks:
        if isinstance(b, dict) and b.get("type") in types:
            out.append(b.get("text") or b.get("thinking") or "")
    return "\n".join(x for x in out if x)


def _brief_args(inp) -> str:
    """工具入参摘要：只留能看出"在对什么东西操作"的部分（路径/命令/模式）。"""
    if not isinstance(inp, dict):
        return ""
    for k in ("file_path", "path", "command", "pattern", "query", "url", "notebook_path",
              "prompt", "description"):
        v = inp.get(k)
        if isinstance(v, str) and v.strip():
            return f"{k}={v.strip()[:120]}"
    try:
        return json.dumps(inp, ensure_ascii=False)[:120]
    except (TypeError, ValueError):
        return ""


def _trigger_of(msgs: list, i: int) -> dict:
    """第 i 条 assistant 消息之前那条 user 消息是什么——这一步是被什么触发的。

    两种触发完全不同，必须分开：
      用户新消息   → 这是一个新的用户轮次的开始
      工具返回     → 还在同一轮里继续干活
    分不开的话，"第几轮"就没有意义，而腐烂恰恰是按轮次演进的。
    """
    for j in range(i - 1, -1, -1):
        m = msgs[j]
        if (m.get("role") or "") != "user":
            continue
        c = m.get("content")
        if isinstance(c, str):
            txt = classifier.strip_reminders(c).strip()
            return {"kind": "user", "text": txt[:200], "index": j}
        if not isinstance(c, list):
            continue
        has_tool_result = any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c)
        txt = classifier.strip_reminders(_text_of(c)).strip()
        if has_tool_result and not txt:
            n_err = sum(1 for b in c if isinstance(b, dict) and b.get("type") == "tool_result"
                        and b.get("is_error"))
            return {"kind": "tool_result", "text": "", "index": j, "errors": n_err}
        return {"kind": "user", "text": txt[:200], "index": j}
    return {"kind": "none", "text": "", "index": -1}


def steps_of(record: dict) -> list[dict]:
    """把一条 record 的 messages 拆成「步」——每条 assistant 消息算一步。

    每步带：触发者 / 思考（块数、字数、全文）/ 回复文本 / 工具调用 / 机械信号 / 轮次号。
    """
    body = (record.get("request") or {}).get("body") or {}
    if not isinstance(body, dict):
        body = {}
    msgs = body.get("messages") or []
    steps: list[dict] = []
    turn = 0
    for i, m in enumerate(msgs):
        if (m.get("role") or "") != "assistant":
            continue
        c = m.get("content")
        blocks = c if isinstance(c, list) else [{"type": "text", "text": str(c or "")}]
        think_txt, think_n, red_n = [], 0, 0
        tools: list[dict] = []
        for b in blocks:
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "thinking":
                think_n += 1
                think_txt.append(b.get("thinking") or "")
            elif t == "redacted_thinking":
                red_n += 1
            elif t == "tool_use":
                tools.append({"name": b.get("name") or "", "args": _brief_args(b.get("input"))})
        trig = _trigger_of(msgs, i)
        if trig["kind"] == "user":
            turn += 1
        thinking = "\n\n".join(x for x in think_txt if x)
        reply = _text_of(blocks)
        steps.append({
            "step": len(steps) + 1,
            "turn": turn,
            "msg_index": i,
            "trigger": trig,
            "thinking_blocks": think_n,
            "redacted_blocks": red_n,
            "thinking_chars": len(thinking),
            "thinking": thinking,
            "reply": reply,
            "reply_chars": len(reply),
            "tools": tools,
            "signals": signals_of(thinking) if thinking else {},
        })
    return steps


# ===== 可得性判档 =====

def _why_no_thinking(body: dict) -> tuple[str, str]:
    """（code, 人话原因）。**必须给出具体原因**，不能只说"没有"。"""
    th = body.get("thinking")
    if isinstance(th, dict):
        t = th.get("type")
        if t == "disabled":
            return "disabled", "本次请求显式关闭了思考（thinking.type=disabled）"
        if t == "adaptive":
            return "adaptive_off", "模型自适应决定本轮不思考（thinking.type=adaptive）"
        if t:
            return "other_type", f"thinking.type={t}"
    elif th is not None:
        return "unknown", f"thinking 字段形态未知：{type(th).__name__}"
    return "absent", "本次请求未启用思考（请求体没有 thinking 字段）"


def availability(record: dict) -> dict:
    """这条录制的思考链可得性：档位 + 原因 + 分布。"""
    body = (record.get("request") or {}).get("body") or {}
    if not isinstance(body, dict):
        body = {}
    steps = steps_of(record)
    n_think = sum(1 for s in steps if s["thinking_blocks"])
    n_red = sum(s["redacted_blocks"] for s in steps)
    total_chars = sum(s["thinking_chars"] for s in steps)
    if n_think:
        tier, code, why = "A", "ok", ""
    elif n_red:
        tier, code, why = "C", "redacted", "思考被上游加密（redacted_thinking），内容不可读"
    else:
        code, why = _why_no_thinking(body)
        tier = "B"
    out = {
        "tier": tier,
        "reason_code": code,
        "reason": why,
        "steps": len(steps),
        "steps_with_thinking": n_think,
        "thinking_chars": total_chars,
        "redacted_blocks": n_red,
        "thinking_param": (body.get("thinking") or {}).get("type")
                          if isinstance(body.get("thinking"), dict) else None,
        "model": body.get("model") or "",
    }
    if n_red and n_think:
        # A 档也可能夹带加密块：正文能读，但**有一部分读不到，必须说出来**，
        # 否则分析出的"它没考虑过 X"可能只是那段恰好被加密了。
        out["partial_redacted"] = True
    return out


# ===== 行为链（B 档回退） =====

def behavior_chain(record: dict) -> dict:
    """没有思考链时的替代原料：工具调用序列 + **反复的行为证据**。

    没有思考不等于没有行为。连续多次调同一工具、反复读同一文件、同一命令改参数重跑、
    工具报错后的重试——这些在行为层面就是"反复"，不读思考也看得出来。

    **诚实边界**：这些是行为，不是心理活动。调用方（提示词、界面）必须守住这条线。
    """
    steps = steps_of(record)
    seq: list[dict] = []
    for s in steps:
        for t in s["tools"]:
            seq.append({"step": s["step"], "turn": s["turn"],
                        "name": t["name"], "args": t["args"]})
    repeats: list[dict] = []
    # ① 连续同工具 ≥3 次
    run_name, run_start, run_n = None, 0, 0
    for k, c in enumerate(seq + [{"name": None}]):
        if c["name"] == run_name:
            run_n += 1
            continue
        if run_name and run_n >= 3:
            repeats.append({"kind": "same_tool_run", "name": run_name,
                            "count": run_n, "from_step": seq[run_start]["step"],
                            "to_step": seq[run_start + run_n - 1]["step"]})
        run_name, run_start, run_n = c["name"], k, 1
    # ② 同一入参出现多次（反复读同一文件 / 反复跑同一命令）
    seen: dict[tuple, int] = {}
    for c in seq:
        if not c["args"]:
            continue
        seen[(c["name"], c["args"])] = seen.get((c["name"], c["args"]), 0) + 1
    for (name, args), n in sorted(seen.items(), key=lambda x: -x[1]):
        if n >= 3:
            repeats.append({"kind": "same_target", "name": name, "args": args, "count": n})
    # ③ 工具报错后的重试链
    errs = [s for s in steps if (s["trigger"].get("errors") or 0) > 0]
    if errs:
        repeats.append({"kind": "tool_errors", "count": sum(s["trigger"]["errors"] for s in errs),
                        "steps": [s["step"] for s in errs][:20]})
    return {"tool_calls": len(seq), "sequence": seq[:200], "repeats": repeats[:30]}


# ===== 三层输出 =====

def _clip(text: str, head: int, tail: int) -> tuple[str, bool]:
    if len(text) <= head + tail + 20:
        return text, False
    return text[:head].rstrip() + "\n…\n" + text[-tail:].lstrip(), True


def _size(obj) -> int:
    """产出的**实际**序列化大小。预算必须按这个算，不能按"每行大约多少字"估——
    第一版就是这么估的（L0_BUDGET // 60），实测每行 230 字，产出超预算 4 倍。
    预算的唯一意义是"喂得进 LLM"，估错了等于没有预算。"""
    try:
        return len(json.dumps(obj, ensure_ascii=False))
    except (TypeError, ValueError):
        return 0


def level0(record: dict) -> dict:
    """L0 骨架：每步一行。人和 AI 都先看这个，先看见形状再决定往哪儿钻。"""
    av = availability(record)
    steps = steps_of(record)
    rows = []
    for s in steps:
        # 只写非零字段：66 步 × 每步几个恒为 0 的键就是上千字符的纯噪声，
        # 而这些字符直接换算成"能不能把所有步骤都摆出来"。
        row: dict = {"step": s["step"], "turn": s["turn"],
                     "trigger": s["trigger"]["kind"]}
        for k in ("thinking_chars", "reply_chars", "redacted_blocks"):
            if s[k]:
                row[k] = s[k]
        if s["tools"]:
            row["tools"] = [t["name"] for t in s["tools"]]
        if s["signals"]:
            row["signals"] = s["signals"]
            # 只给命中分支/修正/犹豫的步取原句——树视图靠它才有内容，
            # 而全给会让骨架体积翻倍（信号步占多数）
            m = marks_of(s["thinking"])
            if m:
                row["marks"] = m
        rows.append(row)
    out: dict = {"availability": av, "steps": rows}
    if av["tier"] == "B":
        out["behavior"] = behavior_chain(record)

    # 超预算就从中间往外砍（两端最有价值：开头是任务设定，结尾是当前状态；
    # 腐烂恰恰体现在两端的落差上）。**砍了必须说**——omitted_steps 会渲染成一行说明。
    while _size(out) > L0_BUDGET and len(out["steps"]) > 6:
        keep = max(3, len(out["steps"]) // 2)
        half = keep // 2
        out["steps"] = out["steps"][:half] + out["steps"][-half:]
        out["omitted_steps"] = len(rows) - len(out["steps"])
    out["steps_total"] = len(steps)
    out["size"] = _size(out)
    return out


def level1(record: dict, budget: int = L1_BUDGET) -> dict:
    """L1 摘要：每步思考的首尾 + 信号。这是喂给低成本 AI 的默认输入。

    **预算管的是整个产出，不只是思考摘录**——喂进 LLM 的是整份 JSON，
    触发语、工具入参、回复摘录都在里面吃 token。所以先把骨架搭出来量一次，
    剩下的空间才分给思考摘录。第一版只管了摘录，结果摘录 14,945 字、产出 49,528 字。
    """
    av = availability(record)
    steps = steps_of(record)

    def base_row(s: dict) -> dict:
        # 空字段一律不写：骨架每省一个字符，就多一分"所有步骤都摆得下"的余地。
        # 工具入参截到 60（骨架里只需看出"在对什么东西操作"，完整入参是 L2 的事）。
        row: dict = {"step": s["step"], "turn": s["turn"],
                     "trigger": s["trigger"]["kind"]}
        if s["trigger"]["text"]:
            row["trigger_text"] = s["trigger"]["text"][:100]
        if s["tools"]:
            row["tools"] = [f"{t['name']}({t['args'][:60]})" if t["args"] else t["name"]
                            for t in s["tools"]]
        if s["signals"]:
            row["signals"] = s["signals"]
        if s["thinking_chars"]:
            row["thinking_chars"] = s["thinking_chars"]
        if s["redacted_blocks"]:
            row["redacted_blocks"] = s["redacted_blocks"]
        return row

    rows = [base_row(s) for s in steps]
    skeleton: dict = {"availability": av, "steps": rows}
    if av["tier"] == "B":
        skeleton["behavior"] = behavior_chain(record)

    # 骨架本身就超预算（步数极多）→ 先砍步数。留给摘录的比例只取两成：
    # **骨架是地图，摘录是钻探**。宁可 66 步全部看得见、其中 30 步有摘录，
    # 也不要只看见 32 步而每步摘录更长——被砍掉的那些步连"这里有没有信号"都不知道，
    # 而信号恰恰是判断"该往哪儿钻"的唯一依据。
    omitted = 0
    while _size(skeleton) > budget * 0.8 and len(rows) > 6:
        half = max(3, len(rows) // 4)
        rows = rows[:half] + rows[-half:]
        skeleton["steps"] = rows
        omitted = len(steps) - len(rows)
    kept_idx = {r["step"] for r in rows}

    remaining = max(0, budget - _size(skeleton))
    think_rows = [r for r in rows if r.get("thinking_chars")]

    # **按信号加权分配，不平分**。用户要问的恰恰是"哪里有疑惑、考虑过哪些分支"，
    # 而信号命中的那几步就是答案所在。平分的结果是关键那一步和最平淡那一步拿到一样多，
    # 等于把预算摊平成噪声。权重上限压在 4：再高会让一两步吃掉全部预算。
    def weight(r: dict) -> int:
        return 1 + min(3, sum((r.get("signals") or {}).values()))

    # 预算装不下所有步的保底篇幅时，**按权重降序只给前 N 步摘录**（其余仍在骨架里占一行）。
    # 这样"读得懂"和"看得全"两件事各自保住：深度给最值得看的步，形状由骨架保证。
    ordered = sorted(think_rows, key=lambda r: (-weight(r), r["step"]))
    afford = remaining // EXCERPT_FLOOR if EXCERPT_FLOOR else len(ordered)
    excerpt_rows = ordered if afford >= len(ordered) else ordered[:max(1, afford)]
    chosen = {r["step"] for r in excerpt_rows}
    total_w = sum(weight(r) for r in excerpt_rows) or 1

    used, clipped = 0, 0
    by_step = {s["step"]: s for s in steps}
    for r in rows:
        s = by_step[r["step"]]
        if s["thinking_chars"] and r["step"] in chosen:
            per = max(EXCERPT_FLOOR, remaining * weight(r) // total_w)
            head = int(per * 0.6)
            tail = int(per * 0.4)
            txt, cut = _clip(s["thinking"], head, tail)
            r["thinking_excerpt"] = txt
            if cut:
                r["excerpt_truncated"] = True
                clipped += 1
            used += len(txt)
        if s["reply_chars"]:
            r["reply_excerpt"] = s["reply"][:160]

    out = dict(skeleton)
    out["steps"] = rows

    # **构建完按真实尺寸收缩，不相信前面的估算**。这已经是同一个错误的第二次了：
    # 第一次按"每行 60 字"估行数（实测 230 字），这次把 reply_excerpt 加在骨架测量
    # 之外、不进预算的账（实测因此超支 6K）。分配算法再讲究，也必须有一道按真实
    # 序列化尺寸收口的闸门——而且要量**最终产出**（含 behavior 等所有字段），不是量它的近似物。
    # 砍的顺序：先回复摘录（价值低于思考），再按权重从低到高砍思考摘录。
    pool_reply = sorted([r for r in rows if "reply_excerpt" in r], key=weight)
    pool_think = sorted([r for r in rows if "thinking_excerpt" in r], key=weight)

    def _finish() -> None:
        """把统计字段补齐到 out 上。**每次量尺寸前都要补齐**——统计字段自己也占字符，
        量一个缺字段的近似物再宣布"守住预算"，就是第三次犯同一个错。"""
        used = sum(len(r.get("thinking_excerpt") or "") for r in rows)
        chosen = {r["step"] for r in rows if r.get("thinking_excerpt")}
        out["excerpt_chars"] = used
        out["steps_clipped"] = sum(1 for r in rows if r.get("excerpt_truncated"))
        out["steps_with_excerpt"] = len(chosen)
        # 有思考却没拿到摘录的步数——**必须说**，否则读的人（人或 AI）会把
        # "这步没摘录"误读成"这步没思考"，进而得出完全错误的结论
        out["steps_without_excerpt"] = len(think_rows) - len(chosen)
        if omitted:
            out["omitted_steps"] = omitted
        # 全对话共几步：steps_without_excerpt 是相对于**留下来的步**说的，
        # 没有这个总数就会被读成"整条对话只有 N 步没摘录"
        out["steps_total"] = len(steps)
        out["budget"] = budget
        # 压缩比要摆出来：读者有权知道自己看的是原文的百分之几
        out["compression"] = (round(used / av["thinking_chars"], 4)
                              if av["thinking_chars"] else None)
        out["size"] = _size(out)

    while True:
        _finish()
        if out["size"] <= budget:
            break
        if pool_reply:
            pool_reply.pop(0).pop("reply_excerpt", None)
        elif len(pool_think) > 1:
            v = pool_think.pop(0)
            v.pop("thinking_excerpt", None)
            v.pop("excerpt_truncated", None)
        else:
            out["over_budget"] = True   # 砍无可砍仍超（骨架本身太大）——不假装守住了
            _finish()
            break
    return out


def level2(record: dict, step: int) -> dict:
    """L2：某一步的思考原文 + 该步全部上下文。"""
    steps = steps_of(record)
    for s in steps:
        if s["step"] == step:
            return {"availability": availability(record), "step": s}
    raise ValueError(f"步骤 {step} 不存在（共 {len(steps)} 步）")


# ===== 多源指令清单（上下文冲突分析的原料） =====

def instruction_sources(record: dict) -> list[dict]:
    """这条请求里到底有几处在下指令。

    实测（260808，证据 6）一条主线请求的指令来源有**五处**：system 三块 + messages[0]
    的用户 CLAUDE.md + messages[1] 的会话中系统消息。它们互相打架，**这就是"上下文冲突"
    的定义本身**。所以冲突分析的第一步是把这份清单摆出来，而不是笼统问 AI「有没有冲突」。

    工具描述也算一处——工具描述与 system 规则打架是 ROADMAP 点名的冲突类型之一。
    """
    body = (record.get("request") or {}).get("body") or {}
    if not isinstance(body, dict):
        body = {}
    raw: list[dict] = []
    sysv = body.get("system")
    blocks = ([sysv] if isinstance(sysv, str)
              else [(b.get("text") or "") if isinstance(b, dict) else str(b)
                    for b in (sysv or [])])
    for i, t in enumerate(blocks):
        raw.append({"where": f"system[{i}]", "role": "system", "chars": len(t),
                    "head": t[:160], "full": t})

    msgs = body.get("messages") or []
    for i, m in enumerate(msgs):
        role = m.get("role") or ""
        c = m.get("content")
        # 收录门槛：role=system 的一律收（那都是注入的规则/提醒），role=user 的只收够长的
        # ——短的是普通对话不是规则源，而且"用户这轮说了什么"由步骤的 trigger 负责。
        # 两个分支（content 是字符串 / 是块数组）必须用**同一个门槛**，否则同一条消息
        # 换个形态就时收时不收。
        def _take(where: str, text: str) -> None:
            if not text.strip():
                return
            if role == "system" or (role == "user" and len(text) > 800):
                raw.append({"where": where, "role": role, "chars": len(text),
                            "head": text[:160], "full": text})
        if isinstance(c, str):
            _take(f"messages[{i}]", c)
            continue
        if not isinstance(c, list):
            continue
        for j, b in enumerate(c):
            if isinstance(b, dict) and b.get("type") == "text":
                _take(f"messages[{i}].content[{j}]", b.get("text") or "")

    # 合并**内容完全相同**的重复注入。CC 会把同一条系统提醒反复插进对话
    # （实测一条录制里同一条 421 字的提醒出现 9 次）。逐条列出来只是刷屏，
    # 而"同一条规则被重复注入 N 次"本身才是一条值得看的事实——它挤占上下文，
    # 且重复本身可能就是模型忽视它的原因。
    merged: list[dict] = []
    seen: dict[str, int] = {}
    for it in raw:
        key = it["full"]
        if key in seen:
            m = merged[seen[key]]
            m["repeats"] = m.get("repeats", 1) + 1
            m["where_all"].append(it["where"])
            continue
        seen[key] = len(merged)
        merged.append({"where": it["where"], "where_all": [it["where"]],
                       "role": it["role"], "chars": it["chars"],
                       "head": it["head"], "repeats": 1})

    tools = body.get("tools") or []
    if tools:
        desc_chars = sum(len((t.get("description") or "")) for t in tools
                         if isinstance(t, dict))
        merged.append({
            "where": "tools", "where_all": ["tools"], "role": "tool_description",
            "chars": desc_chars, "repeats": 1,
            # 工具描述常常是**全场最大的指令源**（实测 81,911 字，是 system 的 13 倍），
            # 而它与 system 规则打架正是 ROADMAP 点名的冲突类型之一。
            "head": f"{len(tools)} 个工具的描述"})
    for m in merged:
        if m["repeats"] == 1:
            m.pop("where_all", None)
    return merged
