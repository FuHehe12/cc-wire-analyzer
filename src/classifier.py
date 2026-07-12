"""请求分类与 DAG 构建（View D 时序视图后端）。

wire 层记录没有显式拓扑字段，本模块从请求体内容推断三种结构：
  1. kind 分类 —— 启发式规则，第一命中；规则常量集中在顶部，真实流量验证后在此迭代
  2. 会话线 lane —— 同一 CC 会话的先后请求 messages 是前缀递增关系，
     用「首条真实 user 文本 + metadata.user_id」hash 分组
  3. 边 —— seq（同 lane 相邻，强）/ trigger（主线 tool_use(Task).prompt 文本匹配
     子代理首条 user，强）/ near（辅助调用挂最近前一条主线，仅时序邻近示意，弱）

纯函数无状态，不落盘。安全分类器等未知辅助调用现阶段落 other 桶——
不同上游链路下它是否存在、长什么样，正是要用真实流量回答的问题。
"""
from __future__ import annotations

import hashlib

# ===== 分类规则常量（真实流量回来后在这里迭代） =====
MAIN_SYSTEM_FP = "you are claude code"          # CC 主线 system 指纹（小写比对）
TITLE_HINTS = (
    "5-10 word title",
    "write a short title",
    "summarize this conversation in a short title",
    "generate a concise title",
    "generate a concise, sentence-case title",        # 260712 实测 glm-5v-turbo title
    "sentence-case title",
    "captures the main topic or goal of this coding session",  # 260712 实测
)
COMPACT_HINTS = (
    "detailed summary of the conversation",
    "summary of our conversation so far",
    "create a summary of the conversation",
)
SECURITY_HINTS = (
    "security monitor",            # 260712 实测：CC autonomous 安全监控（glm-5.2, maxtok 2112）
    "you are a security",
)
SECURITY_MAX_TOKENS = 2112   # 安全分类器 max_tokens 指纹（实测）
PROMPT_MATCH_LEN = 200       # 子代理 prompt 前缀匹配长度

KIND_ORDER = ("main", "subagent", "title", "compact", "security", "count_tokens", "other")


# ===== 请求体取文本 =====
def _text_of_content(content) -> str:
    """message.content 可能是 string 或 block 数组，拼出纯文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text") or "")
        return "\n".join(parts)
    return ""


def _user_texts(body: dict) -> list[str]:
    """所有 user 消息的纯文本（跳过 tool_result-only 的 user 轮）。"""
    out = []
    for m in body.get("messages") or []:
        if m.get("role") != "user":
            continue
        t = _text_of_content(m.get("content"))
        if t.strip():
            out.append(t)
    return out


def _system_text(body: dict) -> str:
    sysv = body.get("system")
    if isinstance(sysv, str):
        return sysv
    if isinstance(sysv, list):
        return "\n".join((b.get("text") or "") for b in sysv if isinstance(b, dict))
    return ""


# ===== 分类 =====
def classify(record: dict) -> str:
    # count_tokens 探针：path 即可判定（非对话，CC 估上下文 token 用，260712 实测）
    if "count_tokens" in (record.get("path") or "").lower():
        return "count_tokens"
    body = (record.get("request") or {}).get("body") or {}
    if not isinstance(body, dict):
        body = {}
    max_tok = body.get("max_tokens") or 0
    sys_text = _system_text(body)
    users = _user_texts(body)
    last_u = users[-1] if users else ""
    tools_n = len(body.get("tools") or [])

    blob = (sys_text[:2000] + "\n" + last_u[:2000]).lower()
    sys_low = sys_text[:500].lower()
    # 安全分类器（system 含 security monitor，260712 实测）
    if any(h in blob for h in SECURITY_HINTS):
        return "security"
    # title 生成：靠 system title 措辞，必须在 main 之前判（title system 开头也是
    # "You are Claude Code"，会被 MAIN_SYSTEM_FP 抢）。不再用 maxtok 硬阈值——
    # 实测 title max_tokens=32000，旧的 TITLE_MAX_TOKENS=1024 约束反而漏判。
    if any(h in blob for h in TITLE_HINTS):
        return "title"
    if any(h in blob for h in COMPACT_HINTS):
        return "compact"
    if MAIN_SYSTEM_FP in sys_low:
        return "main"
    if tools_n > 0 and sys_text:
        return "subagent"
    return "other"


def _lane_key(body: dict) -> str:
    """会话线分组键：首条真实 user 文本 + user_id。
    已知局限：autocompact 压缩后 messages[0] 变化会断成新 lane（MVP 接受）。"""
    users = _user_texts(body)
    first_u = users[0][:2000] if users else ""
    uid = (body.get("metadata") or {}).get("user_id") or ""
    return hashlib.md5(f"{first_u}|{uid}".encode("utf-8", "replace")).hexdigest()[:8]


def _task_prompts(record: dict) -> list[str]:
    """主线响应里 Task/Agent 类 tool_use 的派生 prompt（用于子代理挂载匹配）。"""
    resp = record.get("response") or {}
    out = []
    for blk in resp.get("content_blocks") or []:
        if blk.get("type") != "tool_use":
            continue
        if blk.get("name") not in ("Task", "Agent", "dispatch_agent"):
            continue
        p = (blk.get("input") or {}).get("prompt") or ""
        if p:
            out.append(p)
    return out


def _node_summary(record: dict, kind: str, lane: str) -> dict:
    body = (record.get("request") or {}).get("body") or {}
    resp = record.get("response") or {}
    summary = ""
    for blk in resp.get("content_blocks") or []:
        if blk.get("type") == "text" and blk.get("text"):
            summary = blk["text"][:60]
            break
    if not summary:
        users = _user_texts(body)
        summary = (users[-1][:60] if users else "")
    u = resp.get("usage") or {}
    return {
        "id": record.get("id"),
        "ts_start": record.get("ts_start"),
        "kind": kind,
        "lane": lane,
        "model": body.get("model"),
        "status": resp.get("status"),
        "total_ms": resp.get("total_ms"),
        "usage": {"input": u.get("input"), "output": u.get("output")},
        "has_error": record.get("error") is not None,
        "summary": summary,
    }


# ===== DAG 构建 =====
def build_dag(records: list[dict]) -> dict:
    """records（同一天全量、任意序）→ {nodes, edges, lanes}。"""
    recs = sorted(records, key=lambda r: r.get("ts_start") or "")
    infos = []   # (record, kind, lane_key)
    for r in recs:
        body = (r.get("request") or {}).get("body") or {}
        kind = classify(r)
        infos.append([r, kind, _lane_key(body)])

    # 子代理后验修正：main 的 Task prompt 前缀匹配其他请求的首条 user 文本。
    # 命中则改判 subagent + 记 trigger 边（比 system 指纹启发式可靠，精确对齐）。
    prompts = []  # (main_node_id, prompt)
    for r, kind, _ in infos:
        if kind == "main":
            for p in _task_prompts(r):
                prompts.append((r.get("id"), p))
    trigger_edges = []
    for info in infos:
        r, kind, _ = info
        if kind == "main":
            continue
        body = (r.get("request") or {}).get("body") or {}
        users = _user_texts(body)
        fu = users[0] if users else ""
        if not fu:
            continue
        for mid, p in prompts:
            a, b = p[:PROMPT_MATCH_LEN], fu[:PROMPT_MATCH_LEN]
            if a and b and (a.startswith(b) or b.startswith(a)):
                info[1] = "subagent"
                info[2] = "agent-" + str(r.get("id"))[-6:]
                trigger_edges.append({"from": mid, "to": r.get("id"), "type": "trigger"})
                break

    # lane 组装：main 每组一列、subagent 每实例一列、辅助合一列
    lane_of: dict[str, dict] = {}
    nodes = []
    for r, kind, lk in infos:
        if kind == "main":
            lane_id = "s-" + lk
            lane_kind = "main"
        elif kind == "subagent":
            lane_id = lk if lk.startswith("agent-") else "agent-" + lk
            lane_kind = "subagent"
        else:
            lane_id = "aux"
            lane_kind = "aux"
        if lane_id not in lane_of:
            lane_of[lane_id] = {"lane_id": lane_id, "kind": lane_kind,
                                "first_ts": r.get("ts_start"), "count": 0}
        lane_of[lane_id]["count"] += 1
        nodes.append(_node_summary(r, kind, lane_id))

    # seq 边：同 lane 相邻
    edges = list(trigger_edges)
    by_lane: dict[str, list[dict]] = {}
    for n in nodes:
        by_lane.setdefault(n["lane"], []).append(n)
    for lane_nodes in by_lane.values():
        for a, b in zip(lane_nodes, lane_nodes[1:]):
            edges.append({"from": a["id"], "to": b["id"], "type": "seq"})

    # near 边：aux 节点 → 时序上最近的前一条 main 节点（弱示意，仅时序邻近非因果）
    main_nodes = [n for n in nodes if n["kind"] == "main"]
    for n in nodes:
        if n["lane"] != "aux":
            continue
        prev = None
        for m in main_nodes:
            if (m["ts_start"] or "") <= (n["ts_start"] or ""):
                prev = m
            else:
                break
        if prev:
            edges.append({"from": prev["id"], "to": n["id"], "type": "near"})

    # lanes 排序：main 按首见时间，subagent 次之，aux 最后
    lanes = sorted(lane_of.values(),
                   key=lambda l: ({"main": 0, "subagent": 1, "aux": 2}[l["kind"]],
                                  l["first_ts"] or ""))
    return {"nodes": nodes, "edges": edges, "lanes": lanes}


if __name__ == "__main__":
    # 轻量自检：跑当天真实/seed 数据
    import json
    import sys
    import capture_store as cs
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    recs = cs.list_full()
    dag = build_dag(recs)
    print(json.dumps({"nodes": len(dag["nodes"]),
                      "edges": [(e["type"]) for e in dag["edges"]],
                      "lanes": [(l["lane_id"], l["kind"], l["count"]) for l in dag["lanes"]],
                      "kinds": [n["kind"] for n in dag["nodes"]]},
                     ensure_ascii=False, indent=1))
