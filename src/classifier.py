"""请求分类与 DAG 构建（View D 时序视图后端）。

wire 层记录没有显式拓扑字段，本模块从请求内容 + 头部推断三种结构：
  1. kind 分类 —— 子代理身份取自上游**权威位**（计费头 `cc_is_subagent=true`），
     其余类型靠 system 措辞指纹，第一命中；规则常量集中在顶部
  2. 会话线 lane —— 取 `X-Claude-Code-Session-Id`（回落 `metadata.user_id` 里的 session_id）；
     子代理另按「派生者 + 派生 prompt」分实例列
  3. 边 —— seq（同 lane 相邻，强）/ trigger（主线 tool_use(Task).prompt 子串命中
     子代理首条 user，强）/ near（辅助调用挂最近前一条主线，仅时序邻近示意，弱）

纯函数无状态，不落盘。

判别规则的实证基础（260725，见 issues/closed/260713_泳道主线子代理误判.md）：
`claude -p` 串行派生 Explore / general-purpose / Plan 三个子代理，15 条真实录制人工核对
ground truth。**决定性发现是 CC 自己在 system block[0] 的计费头里标了 `cc_is_subagent=true`**
（8/8 子代理带、7/7 非子代理不带）—— 不需要任何启发式。同批数据把三个原有候选信号全部推翻：
子代理**复用**父会话 id（session_id 只能当 lane 键）、`cc_entrypoint` 被子代理继承、
`general-purpose` 子代理**带** Agent 工具（「禁套娃」不成立）。旧规则准确率 10/15 → 新规则 15/15。
"""
from __future__ import annotations

import hashlib
import json
import re

# ===== 分类规则常量（真实流量回来后在这里迭代） =====
# 子代理权威位：上游在 system block[0] 的计费头里自报身份，比任何 system 措辞启发式都硬。
#   main:     x-anthropic-billing-header: cc_version=2.1.220.8f8; cc_entrypoint=sdk-cli;
#   subagent: x-anthropic-billing-header: cc_version=2.1.220.a83; cc_entrypoint=sdk-cli; cc_is_subagent=true;
SUBAGENT_BILLING_KEY = "cc_is_subagent"
SUBAGENT_BILLING_VALUE = "true"
_BILLING_RE = re.compile(r"x-anthropic-billing-header:\s*([^\n]*)", re.IGNORECASE)
# CC 注入的上下文块：子代理首条 user 也带它，派生 prompt 被推到其后（260717 预测、260725 实测证实）
_REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)

# 主线 system 指纹（小写比对）。两条都必需：
#   "you are claude code"        —— 交互模式（cc_entrypoint=cli）的 block[1]
#   "you are an interactive agent" —— sdk-cli 模式（claude -p）的 block[2] 首句，
#      该模式 block[1] 是 "You are a Claude agent…"，不含上一条指纹 →
#      260725 前 5 条 sdk-cli 主线全落 fallback 被判成 subagent（准确率 10/15 的全部错项）
MAIN_SYSTEM_FPS = ("you are claude code", "you are an interactive agent")
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
PROMPT_MATCH_LEN = 1000      # 派生 prompt 取样长度（lane 实例键用，260726 从 200 加长以区分模板化并行派生）
PROMPT_MATCH_MIN = 40        # 太短的派生 prompt 不参与子串匹配（防误命中）
PROMPT_PROBE_LEN = 300       # 拿派生 prompt 的前多少字去子代理首条 user 里搜（260726 从 120 加长——前 120 字相同的模板化并行派生会让 N 个子代理挤到同一条 lane）

KIND_ORDER = ("main", "subagent", "title", "compact", "security", "count_tokens", "other")

# 索引记录 schema 版本。**改动 index_record 的字段集必须 bump 它**：
# capture_store._read_idx_entries 只校验 off/len，字段集变了它照样把旧索引当有效，
# 于是新字段在老录制上恒缺失、判别逻辑静默退化成回落分支，而中间没有任何东西会报错
# （CLAUDE.md 教训②「键名错位」的同型）。带上版本号，读取侧发现不符就整体重建。
#   v1 → v2（260725）：新增 is_subagent/entrypoint/session_id/agent_fp/first_user_task
#   v2 → v3（260725）：新增诊断原料 err_kind/err_msg/effort/thinking/stream/max_tokens
#   v3 → v4（260726）：task_prompts 加长到 1000（原 200）、first_user_task 加长到 1500（原 600），
#                     修并行同模板派生挤一条 lane 的 bug（前 120 字 probe 撞车，详见
#                     issues/closed/260725_并行同模板子代理泳道撞车.md）
#   v4 → v5（260729）：新增 sec_action/sec_verdict（安全审查的待判定动作与判定结果）。
#                     待判定动作在 transcript **末尾**，而 last_user 只存前 2000 字，够不着，
#                     所以只能加字段（详见 issues/open/260729_安全审查可读性.md）
IDX_SCHEMA = 5


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


# ===== 安全审查解析（260729，实测 07-29 打分式 + 07-26 判定式两种形态）=====
# 解析**只此一份**，前端不再抄——`usage_norm` 的键名归一被抄三份、同一个 bug 犯两次的教训。
SEC_ACTION_MAX = 400      # 待判定动作留多长（进索引，要控体积）
SEC_REASON_MAX = 300


def sec_request(body: dict) -> dict | None:
    """安全审查请求 → {待判定动作, 本次审查的发送量}；不是安全审查则 None。

    实测形状（issues/open/260729_安全审查可读性.md 有完整报文）：
      system[1] 是 ~108K 的规则库，messages[0] 是用户 CLAUDE.md（意图上下文），
      messages[-1] 是 `<transcript>` + N 块动作 + `</transcript>` + 判定指令。
    **判定对象是 transcript 的最后一块**（CC 正要执行的那个动作），前面 170 多块都是历史。
    每块形如 `{"工具名":"参数"}` 或 `{"user":"消息"}`。
    """
    if not isinstance(body, dict):
        return None
    sys_text = _system_text(body)
    if not any(h in sys_text[:2000].lower() for h in SECURITY_HINTS):
        return None
    users = _user_texts(body)
    if not users:
        return None
    # system 可能是 str，也可能是 block 数组（两种形态都实测到）——取最长的那块当规则库体量
    rules_chars = max((len(b.get("text") or "") if isinstance(b, dict) else len(str(b))
                       for b in _system_blocks(body)), default=0)
    # transcript：取 `</transcript>` 之前的部分；没有闭合标签就退回整段（形态变了也不崩）
    tail = users[-1]
    end = tail.rfind("</transcript>")
    inner = tail[:end] if end >= 0 else tail
    start = inner.find("<transcript>")
    if start >= 0:
        inner = inner[start + len("<transcript>"):]
    lines = [ln for ln in inner.split("\n") if ln.strip()]
    tool, arg = "", ""
    if lines:
        last = lines[-1].strip()
        try:                                  # 每块是一个单键 JSON 对象
            obj = json.loads(last)
            if isinstance(obj, dict) and len(obj) == 1:
                k, v = next(iter(obj.items()))
                tool = str(k)
                arg = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
        except Exception:
            pass
        if not tool:                          # 不是预期形状：原样给出，别假装解析成功
            arg = last
    return {
        "action_tool": tool,
        "action_arg": arg[:SEC_ACTION_MAX],
        "action_truncated": len(arg) > SEC_ACTION_MAX,
        "n_actions": len(lines),
        "rules_chars": rules_chars,
        # 意图上下文（实测是用户 CLAUDE.md 全文）——本次审查连它一起发了出去
        "ctx_chars": len(users[0]) if len(users) > 1 else 0,
    }


def sec_verdict(resp: dict) -> dict | None:
    """安全审查响应 → {severity | blocked, category, reason}；解析不出则 None。

    两种实测形态：`<severity>N</severity>`（0-100，**50 是放行/拦截分界**，两阶段的 stage 1）
    与 `<block>yes|no</block><category>…</category><reason>…</reason>`（单阶段）。
    **标签常常是残缺的**——响应 `stop_reason=stop_sequence`，闭合标签被 stop sequence 吃掉，
    实测最常见的响应文本就是裸的 `<severity>8`。所以一律按「开标签 + 内容」宽松匹配，
    不要求成对，否则真实流量上 100% 解析失败。
    """
    if not isinstance(resp, dict):
        return None
    text = ""
    for blk in resp.get("content_blocks") or []:
        if isinstance(blk, dict) and blk.get("type") == "text":
            text += blk.get("text") or ""
    if not text:
        return None
    out: dict = {}
    m = re.search(r"<severity>\s*(\d+)", text, re.I)
    if m:
        out["severity"] = int(m.group(1))
    m = re.search(r"<block>\s*(yes|no)", text, re.I)
    if m:
        out["blocked"] = m.group(1).lower() == "yes"
    m = re.search(r"<category>\s*([^<]{1,80})", text, re.I)
    if m:
        out["category"] = m.group(1).strip()
    m = re.search(r"<reason>\s*([^<]{1,%d})" % SEC_REASON_MAX, text, re.I)
    if m:
        out["reason"] = m.group(1).strip()
    return out or None


def usage_norm(resp: dict) -> dict:
    """usage 键名归一（**单一真源**，前后端都从这里取）。

    SSE 聚合写进录制的是 Anthropic 全名（`input_tokens` / `cache_read_input_tokens`），
    不是短名。直接读 `u.get("input")` 恒为 None —— 这个错犯过两次（DAG 节点 token 恒空、
    CLI token 统计恒 0），根因是归一化逻辑被各处各抄一份。所以收口到这里，别再抄第四份。"""
    u = resp.get("usage") or {}
    if not isinstance(u, dict):
        return {"input": None, "output": None, "cache_read": None, "cache_creation": None}
    return {
        "input": u.get("input_tokens", u.get("input")),
        "output": u.get("output_tokens", u.get("output")),
        "cache_read": u.get("cache_read_input_tokens", u.get("cache_read")),
        "cache_creation": u.get("cache_creation_input_tokens", u.get("cache_creation")),
    }


def _system_text(body: dict) -> str:
    sysv = body.get("system")
    if isinstance(sysv, str):
        return sysv
    if isinstance(sysv, list):
        return "\n".join((b.get("text") or "") for b in sysv if isinstance(b, dict))
    return ""


def _system_blocks(body: dict) -> list[str]:
    sysv = body.get("system")
    if isinstance(sysv, str):
        return [sysv]
    if isinstance(sysv, list):
        return [(b.get("text") or "") for b in sysv if isinstance(b, dict)]
    return []


def billing_kv(sys_text: str) -> dict:
    """system block[0] 的计费头 → dict（`cc_version` / `cc_entrypoint` / `cc_is_subagent`）。

    实测形态恒为 3 个 system 块，block[0] 就是这一行，所以在 sys_head 前缀里必然完整可见。"""
    m = _BILLING_RE.search(sys_text or "")
    if not m:
        return {}
    out = {}
    for part in m.group(1).split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def strip_reminders(text: str) -> str:
    """剥掉 CC 注入的 `<system-reminder>` 块，露出用户/派生方真正写的那段话。

    为什么必需（260725 实测）：子代理首条 user 也被注入 reminder，派生 prompt 被推到其后，
    于是旧的「派生 prompt 与首条 user 前缀 startswith 对齐」**永远命中 0 条**。
    剥掉之后，首条 user 的开头正好逐字等于派生 prompt（8/8 命中）。
    注入体量还随 agent 类型变（Explore/Plan 只有 email+date 约 550 字，
    general-purpose 带完整 claudeMd 约 9960 字）——所以只能剥，不能靠取前 N 字碰运气。"""
    return _REMINDER_RE.sub("", text or "").strip()


def _session_id(record: dict, body: dict) -> str:
    """CC 会话 id：请求头 `X-Claude-Code-Session-Id` 优先，回落 `metadata.user_id` 内的
    session_id（该字段是 JSON 字符串）。实测覆盖率 15/15。

    注意子代理**复用**父会话 id（260725 坐实）——所以它是 lane 分组键，不是 main/subagent 判别位。"""
    hdrs = (record.get("request") or {}).get("headers_safe") or {}
    for k, v in hdrs.items():
        if k.lower() == "x-claude-code-session-id" and isinstance(v, str) and v:
            return v
    uid = (body.get("metadata") or {}).get("user_id")
    if isinstance(uid, str) and uid:
        try:
            sid = json.loads(uid).get("session_id")
        except (json.JSONDecodeError, AttributeError, TypeError):
            return ""
        if isinstance(sid, str):
            return sid
    return ""


def _agent_fp(blocks: list[str]) -> str:
    """身份指纹：system block[2]（正文/agent 专属提示词）的 md5 短码。

    实测把三个子代理实例干净分组（Explore/general-purpose/Plan 各自一码）。
    用途仅限「无派生 prompt 对齐命中时的实例分组回落」——blk[2] 的措辞本身**不能**当
    main/subagent 判别位：`general-purpose` 是 "You are an agent for Claude Code…"，
    而 Explore 是 "file search specialist"、Plan 是 "software architect"，各不相同。"""
    if len(blocks) < 3:
        return ""
    return hashlib.md5(blocks[2].encode("utf-8", "replace")).hexdigest()[:8]


def _is_turn_start(body: dict) -> bool:
    """轮次起点判据（260717，三天真实录制验证）：最后一条 user 消息含「真实 text」
    （string content，或非 <system-reminder> 开头的 text 块）→ 用户新消息触发的请求。
    全是 tool_result（工具循环回传）→ 中间步。实测型态干净：工具回传就是纯 tool_result 块，
    system-reminder 不混入；reminder+text 型是用户新消息被注入 reminder，正确判起点。"""
    last_u = None
    for m in body.get("messages") or []:
        if m.get("role") == "user":
            last_u = m
    if last_u is None:
        return False
    c = last_u.get("content")
    if isinstance(c, str):
        return bool(c.strip())
    if isinstance(c, list):
        for b in c:
            if isinstance(b, dict) and b.get("type") == "text":
                if not (b.get("text") or "").lstrip().startswith("<system-reminder>"):
                    return True
    return False


def _tool_use_count(record: dict) -> int:
    """响应里的 tool_use 块数（纯对话轮判据的原料）。"""
    return sum(1 for b in (record.get("response") or {}).get("content_blocks") or []
               if isinstance(b, dict) and b.get("type") == "tool_use")


def _error_message(record: dict) -> str:
    """失败请求的**人类可读原因**，归一成一句话（诊断聚合按它做指纹）。

    上游的错误体形如 `{"type":"error","error":{"type":"...","message":"..."}}`，
    但录制里存的是 `error.body_snippet`（截断过的原文字符串）——先按 JSON 解析取 message，
    解析不动就退回原文片段。本地错误（连接失败/超时）没有 body，用 `error.detail`。"""
    err = record.get("error")
    if not isinstance(err, dict) or not err:
        return ""
    snippet = err.get("body_snippet") or ""
    if snippet:
        try:
            data = json.loads(snippet)
        except (json.JSONDecodeError, TypeError):
            return snippet[:300]
        if isinstance(data, dict):
            inner = data.get("error")
            if isinstance(inner, dict):
                msg = inner.get("message") or inner.get("type") or ""
                if msg:
                    return str(msg)[:300]
            if data.get("message"):
                return str(data["message"])[:300]
        return snippet[:300]
    return str(err.get("detail") or err.get("kind") or "")[:300]


# ===== 轻量索引记录（260719 大流量性能改造） =====
# 单条完整 record 可超 5MB（system prompt + 上百个工具 schema），一天录制能上 GB。
# build_dag / 列表摘要实际只用其中几十个字段——录制时（record 本就在内存）一次性提取
# 成 1~2KB 的索引记录写进 {date}.idx.jsonl，之后 DAG/列表只读索引，
# 不再每次全量 parse 主文件（实测 826MB/2993 条：全量 parse ~9s → 索引 ~50ms）。
def index_record(rec: dict) -> dict:
    """完整 record → 轻量索引记录（capture_store 写时/回填时调用）。

    字段分两组：
      - 列表/SSE 摘要组：id/ts_start/method/path/model/status/ttft_ms/total_ms/
        usage(已归一)/stop_reason/has_error/summary
      - DAG 分类原料组：sys_head/first_user/last_user/tools_n/uid/task_prompts/
        turn_start/tool_uses + is_subagent/entrypoint/session_id/agent_fp/first_user_task
        （classify_idx/_lane_key/_node_summary 只吃这些，不再碰完整 body）
    capture_store 另补 off/len（主文件字节偏移），供 get_capture 直接 seek。

    **改字段集要 bump IDX_SCHEMA**（见该常量注释），否则旧索引不会被重建。
    """
    body = (rec.get("request") or {}).get("body") or {}
    if not isinstance(body, dict):
        body = {}
    resp = rec.get("response") or {}
    blocks = _system_blocks(body)
    sys_text = _system_text(body)
    users = _user_texts(body)
    billing = billing_kv(sys_text[:2000])
    summary = ""
    for blk in resp.get("content_blocks") or []:
        if isinstance(blk, dict) and blk.get("type") == "text" and blk.get("text"):
            summary = blk["text"][:80]
            break
    return {
        "v": IDX_SCHEMA,
        "id": rec.get("id"),
        "ts_start": rec.get("ts_start"),
        "method": rec.get("method"),
        "path": rec.get("path"),
        "model": body.get("model"),
        "status": resp.get("status"),
        "ttft_ms": resp.get("ttft_ms"),
        "total_ms": resp.get("total_ms"),
        "usage": usage_norm(resp),
        "stop_reason": resp.get("stop_reason"),
        "has_error": rec.get("error") is not None,
        "summary": summary,
        # ---- DAG 分类原料 ----
        "sys_head": sys_text[:2000],
        "first_user": (users[0][:2000] if users else ""),
        "last_user": (users[-1][:2000] if users else ""),
        "tools_n": len(body.get("tools") or []),
        "uid": (body.get("metadata") or {}).get("user_id") or "",
        "task_prompts": [p[:PROMPT_MATCH_LEN] for p in _task_prompts(rec)],
        "turn_start": _is_turn_start(body),
        "tool_uses": _tool_use_count(rec),
        # ---- 身份原料（260725 实测确立）----
        "is_subagent": billing.get(SUBAGENT_BILLING_KEY) == SUBAGENT_BILLING_VALUE,
        "entrypoint": billing.get("cc_entrypoint") or "",
        "session_id": _session_id(rec, body),
        "agent_fp": _agent_fp(blocks),
        # 剥 reminder 后的首条 user 开头 = 派生 prompt 原文（对齐锚点，见 strip_reminders）。
        # 260726 从 600 加长到 1500：probe 加长到 300 后需要更宽匹配空间，否则长 reminder 场景
        # 剥掉后剩余不足 300 字会漏命中。
        "first_user_task": (strip_reminders(users[0])[:1500] if users else ""),
        # ---- 诊断原料（260725）----
        # 失败聚合要按「错误消息指纹」归并，并同时摆出**请求侧的相关字段**，否则 agent 拿到
        # 一句 "effort 'max' is not supported when thinking is disabled" 还得再去翻原始 record
        # 才知道这个请求的 effort/thinking 到底是什么。实测这两个字段一摆出来，
        # 「effort=max + thinking=disabled → 400」的因果一眼就能对上。
        "err_kind": (rec.get("error") or {}).get("kind") or "",
        "err_msg": _error_message(rec),
        "effort": ((body.get("output_config") or {}).get("effort")
                   if isinstance(body.get("output_config"), dict) else None),
        "thinking": ((body.get("thinking") or {}).get("type")
                     if isinstance(body.get("thinking"), dict) else None),
        "stream": bool(body.get("stream")),
        "max_tokens": body.get("max_tokens"),
        # ---- 安全审查原料（260729）----
        # 待判定动作在 transcript 末尾，last_user 只存前 2000 字够不着，只能单独提取。
        # 列表行要一眼看出「AI 在确认什么、判了什么」，这两个字段就是那两句话的原料。
        "sec_action": _sec_action_flat(body),
        "sec_verdict": sec_verdict(resp),
    }


def _sec_action_flat(body: dict) -> dict | None:
    """index_record 用：只留列表行需要的几个字段，别把整个 sec_request 塞进索引记录。"""
    s = sec_request(body)
    if not s:
        return None
    return {"tool": s["action_tool"], "arg": s["action_arg"][:200], "n": s["n_actions"]}


# ===== 分类 =====
def classify_idx(idx: dict) -> str:
    """索引记录 → kind。与旧 classify(完整 record) 逐条等价（原料已由 index_record 预提取）。"""
    # count_tokens 探针：path 即可判定（非对话，CC 估上下文 token 用，260712 实测）
    if "count_tokens" in (idx.get("path") or "").lower():
        return "count_tokens"
    sys_text = idx.get("sys_head") or ""
    last_u = idx.get("last_user") or ""
    tools_n = idx.get("tools_n") or 0

    blob = (sys_text + "\n" + last_u).lower()
    sys_low = sys_text[:2000].lower()
    # 安全分类器（system 含 security monitor，260712 实测）
    if any(h in blob for h in SECURITY_HINTS):
        return "security"
    # title 生成：靠 system title 措辞，必须在 main 之前判（title system 开头也是
    # "You are Claude Code"，会被主线指纹抢）。不再用 maxtok 硬阈值——
    # 实测 title max_tokens=32000，旧的 TITLE_MAX_TOKENS=1024 约束反而漏判。
    if any(h in blob for h in TITLE_HINTS):
        return "title"
    if any(h in blob for h in COMPACT_HINTS):
        return "compact"
    # 子代理：上游权威位，优先于一切 main 指纹（子代理 system 同样带主线措辞，
    # 靠措辞判必错——这正是「误判成 main = 终身 main」的老根因）
    if idx.get("is_subagent"):
        return "subagent"
    if any(fp in sys_low for fp in MAIN_SYSTEM_FPS):
        return "main"
    # fallback（260725 方向反转）：带工具的对话请求，既没有子代理权威位、又不含已知主线指纹
    # —— 判 main。原先判 subagent 太宽：sdk-cli 主线不含 "you are claude code" 指纹，
    # 5/5 全被降级成子代理（旧准确率 10/15 的全部错项）。未知形状默认主线，
    # 真子代理另有 build_dag 的派生 prompt 对齐兜底改判。
    if tools_n > 0 and sys_text:
        return "main"
    return "other"


def classify(record: dict) -> str:
    """完整 record → kind（lane_probe 等直接吃完整记录的调用方保留入口）。"""
    return classify_idx(index_record(record))


def _lane_key(idx: dict) -> str:
    """会话线分组键：优先 CC 会话 id（`X-Claude-Code-Session-Id`，回落 metadata 里的 session_id）。

    260725 前用的是「首条 user 文本 + user_id」的 md5，有两个毛病：autocompact 压缩后
    messages[0] 变了就断成新 lane（旧 docstring 自己承认），且 7-12 那批录制被切得七零八落
    （2 个真实会话被分成 7+2 列）。上游明明在请求头里给了会话 id，实测覆盖率 15/15。
    只在两者都缺时才回落文本 hash（老录制/未知 harness）。"""
    sid = idx.get("session_id") or ""
    if sid:
        return hashlib.md5(sid.encode("utf-8", "replace")).hexdigest()[:8]
    return hashlib.md5(f"{idx.get('first_user') or ''}|{idx.get('uid') or ''}".encode(
        "utf-8", "replace")).hexdigest()[:8]


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


def _node_summary(idx: dict, kind: str, lane: str) -> dict:
    """索引记录 → DAG 节点摘要。usage 在 index_record 里已归一（260719），
    不再有「生产方写全名、消费方读短名」的键名错位空间。"""
    summary = (idx.get("summary") or "")[:60] or (idx.get("last_user") or "")[:60]
    return {
        "id": idx.get("id"),
        "ts_start": idx.get("ts_start"),
        "kind": kind,
        "lane": lane,
        "model": idx.get("model"),
        "status": idx.get("status"),
        "total_ms": idx.get("total_ms"),
        "usage": idx.get("usage"),
        "has_error": bool(idx.get("has_error")),
        "summary": summary,
        # 视觉分层三原料（260717）：turn_start=用户新消息触发；tool_uses=本响应动手次数；
        # pure_chat 由 build_dag 轮聚合后回填（整轮零动手 → 回顾/追问/澄清类轻量轮）
        "turn_start": bool(idx.get("turn_start")),
        "tool_uses": idx.get("tool_uses") or 0,
        "pure_chat": False,
    }


# ===== DAG 构建 =====
def build_dag(records: list[dict]) -> dict:
    """索引记录（同一天全量、任意序，capture_store.list_index 提供）→ {nodes, edges, lanes}。"""
    recs = sorted(records, key=lambda r: r.get("ts_start") or "")
    infos = []   # (idx, kind, lane_key)
    for r in recs:
        kind = classify_idx(r)
        infos.append([r, kind, _lane_key(r)])

    # 子代理后验修正：把主线响应里 Task/Agent 的派生 prompt，去匹配其他请求「剥掉
    # system-reminder 后的首条 user」。命中即改判 subagent、归到该次派生的实例泳道、记 trigger 边。
    #
    # 260725 三处修正（每一处都是实测出来的，见 issues/closed/260713_…）：
    #   1. **不再跳过已判 main 的记录** —— 原代码开头 `if kind == "main": continue` 把全场最强的
    #      精确信号锁在门外：只要 classify 先把子代理判成 main，就永远不会被改判（「终身 main」），
    #      每个被误判的子代理还各自变成一条独立"主线"泳道，正是用户看到的满屏主线。
    #   2. **前缀对齐 → 子串包含** —— 子代理首条 user 也被注入 reminder，派生 prompt 被推到其后，
    #      两头 startswith 实测命中 0 条；剥掉 reminder 后开头逐字就是派生 prompt（8/8 命中）。
    #   3. **实例泳道键用「派生者 + prompt」** —— 原代码写 `"agent-" + record 自己的 id`，
    #      同一个子代理的多条请求会各成一列。同一次派生的所有请求必须落同一列。
    prompts = []  # (派生者 node_id, prompt)
    for r, kind, _ in infos:
        if kind in ("main", "subagent"):     # 子代理也能派生（general-purpose 带 Agent 工具，实测）
            for p in r.get("task_prompts") or []:
                prompts.append((r.get("id"), p))
    trigger_edges = []
    triggered_lanes: set[str] = set()        # 每个实例泳道只连一条 trigger 边（首条），其余走 seq
    for info in infos:
        r, kind, _ = info
        task = r.get("first_user_task") or ""
        if not task:
            continue
        for mid, p in prompts:
            if mid == r.get("id"):           # 自己的派生 prompt 不用来匹配自己
                continue
            probe = p[:PROMPT_PROBE_LEN]
            if len(p) < PROMPT_MATCH_MIN or not probe or probe not in task:
                continue
            info[1] = "subagent"
            info[2] = "agent-" + hashlib.md5(
                f"{mid}|{p[:PROMPT_MATCH_LEN]}".encode("utf-8", "replace")).hexdigest()[:8]
            if info[2] not in triggered_lanes:
                triggered_lanes.add(info[2])
                trigger_edges.append({"from": mid, "to": r.get("id"), "type": "trigger"})
            break

    # 有权威位但没对齐命中的子代理（老录制缺 prompt、派生方未录到、跨天截断）：
    # 用 agent_fp（system 正文指纹）分实例，至少同类型子代理归一列，不会每条一列。
    for info in infos:
        r, kind, lk = info
        if kind == "subagent" and not lk.startswith("agent-"):
            fp = r.get("agent_fp") or lk
            info[2] = "agent-" + fp

    # lane 组装：main 每会话一列、subagent 每派生实例一列、辅助合一列
    # （subagent 的 lane_key 到这里必然已是 "agent-" 开头：对齐命中时设成派生实例键，
    #   未命中时由上面的 agent_fp 回落循环补上）
    lane_of: dict[str, dict] = {}
    nodes = []
    for r, kind, lk in infos:
        if kind == "main":
            lane_id = "s-" + lk
            lane_kind = "main"
        elif kind == "subagent":
            lane_id = lk
            lane_kind = "subagent"
        else:
            lane_id = "aux"
            lane_kind = "aux"
        if lane_id not in lane_of:
            lane_of[lane_id] = {"lane_id": lane_id, "kind": lane_kind,
                                "first_ts": r.get("ts_start"), "count": 0,
                                # 泳道标签原料（前端下拉/图例可用；不认这些键的旧前端自然忽略）。
                                # aux 是「所有会话的辅助调用合成一列」，挂某一条的 session
                                # 只会误导，故留空。
                                "session_id": "" if lane_kind == "aux" else (r.get("session_id") or ""),
                                "entrypoint": r.get("entrypoint") or ""}
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

    # 纯对话轮回填（260717）：main/subagent 泳道内按 turn_start 分轮，
    # 整轮 tool_use 总数为 0 且轮首是真起点 → 全轮标 pure_chat（「回顾一下干了什么」
    # 这类没动手的轮次，前端降档渲染）。lane 开头缺起点的残轮（代理中途启动，
    # 只录到某轮的中间段）不标——它属于一个没看全的干活轮。
    def _flush_turn(turn: list[dict]) -> None:
        if turn and turn[0]["turn_start"] and sum(n["tool_uses"] for n in turn) == 0:
            for n in turn:
                n["pure_chat"] = True
    for lane_id, lane_nodes in by_lane.items():
        if lane_id == "aux":
            continue
        turn: list[dict] = []
        for n in lane_nodes:
            if n["turn_start"] and turn:
                _flush_turn(turn)
                turn = [n]
            else:
                turn.append(n)
        _flush_turn(turn)

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
    recs = cs.list_index()
    dag = build_dag(recs)
    print(json.dumps({"nodes": len(dag["nodes"]),
                      "edges": [(e["type"]) for e in dag["edges"]],
                      "lanes": [(l["lane_id"], l["kind"], l["count"]) for l in dag["lanes"]],
                      "kinds": [n["kind"] for n in dag["nodes"]],
                      "turn_starts": sum(1 for n in dag["nodes"] if n["turn_start"]),
                      "pure_chat": sum(1 for n in dag["nodes"] if n["pure_chat"])},
                     ensure_ascii=False, indent=1))
