"""动作账本：把一条录制压成「这一步做了什么」。

**为什么要单独一层**（260908 实测，样本 2026-09-06 的 54 步主线）：
一条 `/api/captures/<rid>` 返回体 299 KB，其中真正说明这一步做了什么的
`response.content_blocks` 只有 1,780 B —— **0.6%**；`tools[]` 独占 57.6%
（73 个工具定义，每次请求原样重发）。整条主线逐条拉全量 23.8 MB，抽成账本
36.4 KB，**压缩比 639×**。

外环观测者（另开一个 AI，跟"它做了什么 / 在做什么 / 接下来要做什么"）读的就是这一层。
它不该为了知道 `git commit -m ...` 这行命令而把 299 KB 拉下来自己刨，也不能只看
`/api/dag` 的摘要 —— 那里只有 `🔧 Bash`（工具名，没有参数），说不出做了什么。

**账本是派生视图，不是事实源**：截断了就要说截断了（`clip`），要原文回
`/api/captures/<rid>`。这条是硬的 —— 观测者据此声称"已读完"时，得能分清
"给了全部"和"给了摘要"。
"""

from __future__ import annotations

import json

import classifier

# 单个字段的默认截断长度。Bash 的 heredoc 能到几 KB，全给会把账本重新撑回原大小；
# 全不给又看不出做了什么。400 是实测取的折中：44 条 Bash 里绝大多数命令完整可见。
TRUNC = 400


def _brief(v, n: int) -> tuple[str, int]:
    """→ (可能截断的文本, 原始字符数)。非字符串先 JSON 化再截。"""
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    if not isinstance(s, str):
        s = str(s)
    return (s[:n], len(s))


def _prev_results(body: dict, n: int) -> list[dict]:
    """本条请求携带的**上一步**工具返回。

    tool_result 在最后一条 user 消息里 —— 内环把工具返回喂回去才有了这一条请求。
    只看最后一条：再往前是历史，重复计进来就会把同一次行动数成多次（可研第五节的坑）。
    """
    msgs = body.get("messages")
    if not isinstance(msgs, list):
        return []
    for m in reversed(msgs):
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        c = m.get("content")
        if not isinstance(c, list):
            return []
        out = []
        for b in c:
            if not isinstance(b, dict) or b.get("type") != "tool_result":
                continue
            txt, full = _brief(b.get("content"), n)
            out.append({
                "tool_use_id": b.get("tool_use_id"),
                "err": bool(b.get("is_error")),
                "out": txt,
                **({"clip": full} if full > len(txt) else {}),
            })
        return out
    return []


def step(idx: dict, rec: dict | None, seq: int, trunc: int = TRUNC) -> dict:
    """一条索引条目 + 完整记录 → 一步账本。

    `rec` 为 None 表示原文取不到（记录被清理 / 分片不在了）——**要显式说缺**，
    不能安静地少一步：观测者的"完整读取"验收全靠这个。
    """
    out = {
        "seq": seq,
        "id": idx.get("id"),
        "ts": idx.get("ts_start"),
        "turn": idx.get("turn"),
        "lane": idx.get("lane"),
        "kind": idx.get("kind"),
        "model": idx.get("model"),
        "status": idx.get("status"),
        "ms": idx.get("total_ms"),
        "usage": idx.get("usage"),
    }
    if idx.get("has_error"):
        out["has_error"] = True
    if rec is None:
        out["missing"] = True
        return out

    body = (rec.get("request") or {}).get("body") or {}
    out["prev"] = _prev_results(body if isinstance(body, dict) else {}, trunc)

    # 轮首带上**用户这轮说了什么**。260908 两个外环观测者独立报了同一条：没有用户原话，
    # 「它在做什么」和「它为什么这么做」之间永远隔一层猜——阶段边界只能靠时间差推断。
    # 不用索引里的 `turn_user`（写时截到 160 字，够 DAG 轮卡不够观测者）：这里手上是完整
    # body，按 `trunc` 重新剥一遍。**必须 strip_reminders**：CC 注入的 reminder 可达 9960 字，
    # 不剥就是一屏 `<system-reminder>`（见 classifier.strip_reminders 的实测说明）。
    if idx.get("turn_start"):
        users = classifier._user_texts(body if isinstance(body, dict) else {})
        if users:
            txt, full = _brief(classifier.strip_reminders(users[-1]), trunc)
            if txt:
                out["user"] = {"text": txt, **({"clip": full} if full > len(txt) else {})}
        out["turn_start"] = True
        if idx.get("origin"):
            out["origin"] = idx["origin"]

    acts, says, think = [], [], False    # think: False 或 {"text": …}
    for b in ((rec.get("response") or {}).get("content_blocks") or []):
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t == "tool_use":
            txt, full = _brief(b.get("input"), trunc)
            acts.append({
                "id": b.get("id"), "name": b.get("name"), "input": txt,
                **({"clip": full} if full > len(txt) else {}),
            })
        elif t == "text":
            txt, full = _brief((b.get("text") or "").strip(), trunc)
            if txt:
                says.append({"text": txt, **({"clip": full} if full > len(txt) else {})})
        elif t == "thinking":
            # 实测：54 步里只有 2 步有 thinking 正文，其余是空签名（模型没返回思考）。
            # **有正文就给正文**，别只报一个布尔——观测者拿不到推理时只能从动作反推，
            # 拿得到的那几步不该也被降格成"有/无"。
            txt, full = _brief((b.get("thinking") or "").strip(), trunc)
            if txt:
                think = {"text": txt, **({"clip": full} if full > len(txt) else {})}
    out["acts"] = acts
    out["says"] = says
    out["thinking"] = think
    if rec.get("error"):
        out["error"] = _brief(rec["error"], trunc)[0]
    return out
