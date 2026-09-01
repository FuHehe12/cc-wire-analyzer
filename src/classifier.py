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
from urllib.parse import urlparse

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
# 命名类辅助的**官方位**（260901）：`output_config.format.type == "json_schema"`
# （`structured-outputs-2025-12-15` beta）。CC 让模型给会话起名字时要一个结构化回包，所以它
# 声明了 schema；真的对话请求从不声明。实测全语料 5,032 条：
#   命名类（title 15 + 被措辞漏判成 main 的 11）  26 条 **全部**带 json_schema
#   真主线 3,349 条 / security 1,204 / compact 5 / count_tokens 84 / subagent 372  **零**带
# 跨 CC 2.1.220~2.1.251 五个版本稳定。这是 §二·五「官方标识符优先」第三次复现同一教训——
# 前两次是 `cc_is_subagent`（L1 子代理）与 `cc_entrypoint`（L2 sdk 起源）：答案一直在 CC 自己
# 声明的字段里，而我们在猜措辞（2.1.238 把标题提示词整段重写，七条 TITLE_HINTS 全数失效，
# 从那天起**每一条**标题请求都被判成主线）。
# **合取「且无工具」**：CC 将来可能在别处用 structured outputs，带工具的对话请求即便声明了
# schema 也仍是主线；单看 format 会把那种情形误降级。
NAMING_FORMAT = "json_schema"
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
# 通知判定器（260902 实测）：用户走开后 CC 周期性地把「刚才这段尾巴」发给模型，判
# done/working/blocked，据此决定要不要推手机通知。轮首是 CC 拼的固定模板
# （`Current state: …` / `Tool calls so far: …` / `Assistant message tail (last N chars): …`），
# 响应是一行 JSON（`{"state":…,"detail":…,"tempo":…}`）。**同一轮工作期间会反复发**
# （实测 for 0m/1m/2m/…/22m，越久越稀），所以它在 aux 里是数量最大的新家族。
# 跨版本稳定性：2.1.251 与 2.1.258 两版 system 都是 16,683 字、逐字相似度 0.9998，
# 唯一差异是计费头里的 cc_version。
# **措辞在这里只用来给辅助起名字，不用来判主线归属**（260901 issue §五·A 定的降级用途）——
# 真正挡住它进主线的是「无工具不判主线」那道结构门，措辞漏了只会退回 `other`。
NOTIFY_EVAL_HINTS = (
    "whether to notify the user",
    "decide which of four states it's in",
)
PROMPT_MATCH_LEN = 1000      # 派生 prompt 取样长度（lane 实例键用，260726 从 200 加长以区分模板化并行派生）
PROMPT_MATCH_MIN = 40        # 太短的派生 prompt 不参与子串匹配（防误命中）
PROMPT_PROBE_LEN = 300       # 拿派生 prompt 的前多少字去子代理首条 user 里搜（260726 从 120 加长——前 120 字相同的模板化并行派生会让 N 个子代理挤到同一条 lane）
TURN_USER_TEXT_LEN = 160     # 轮卡上「你这轮说了什么」留多长（按轮折叠的检索键，260802）

# ===== 已知集合（盲区雷达的"已知"基准，260802）=====
# 索引时拿这些集合判"未知"：出现集合外的值 = CC 协议演进的信号，进 idx 的 unknowns 字段，
# /api/unknowns 一键查（issues/open/260802_未知盲区检测与一键查询.md）。
# **硬编码 + 版本号，不动态算频次**——"已知"必须确定可审计，不能漂移；
# 稳定的未知定期并入这里（像 quota_probe/hook_eval 固化成 kind 那样）。
KNOWN_BLOCK_TYPES = {"text", "tool_use", "thinking", "redacted_thinking",
                     "server_tool_use", "web_search_tool_result",
                     # compaction 不是"确认过的 Anthropic 标准块"，是**我们自己组装的**：
                     # proxy 把 compaction_delta 累成这个形状（上下文自动压缩的产物）。
                     # 别拿它当"标准字段"的先例——它在这里的理由是"雷达不该报自己的产物"。
                     "compaction"}
# 每种已知块的标准字段。260802 审查后并入 advanced-tool-use（caller）/ web_search
# （citations、web_search_tool_result）/ redacted_thinking —— 它们是 Anthropic 标准字段、CC
# 启用相应 beta 后出现，不再当未知。剩下的才触发未知（本工具自己的降级标记除外，见
# CAPTURE_ARTIFACT_KEYS —— 那类单列 degraded，不算协议未知）。
KNOWN_BLOCK_KEYS = {
    "text":                   {"type", "text", "citations"},
    "tool_use":               {"type", "id", "name", "input", "caller"},
    "thinking":               {"type", "thinking", "signature"},
    "redacted_thinking":      {"type", "data"},
    "server_tool_use":        {"type", "id", "name", "input", "caller"},
    "web_search_tool_result": {"type", "tool_use_id", "caller", "content"},
    "compaction":             {"type", "content"},
}
# **本工具自己产生的降级标记**，不是上游协议的东西（proxy.py 的 SSE 累积器写的）：
#   _input_raw          —— 流在 content_block_stop 之前断了，工具入参没拼完
#   input_raw_fallback  —— 拼完了但不是合法 JSON
# 它们进雷达的 degraded 维度而不是 block_keys：混在一起时双向坏事——真协议信号被自己的噪声
# 顶掉（实测 07-29 全天 3 条未知全是它），而"这条录制的正文是残的"这个更该管的事实
# 又被埋在"协议演进"的语境里没人当回事。要查的是代理侧，不是上游。
CAPTURE_ARTIFACT_KEYS = {"_input_raw", "input_raw_fallback"}
KNOWN_BODY_FIELDS = {
    "model", "messages", "system", "tools", "tool_choice", "metadata", "max_tokens",
    "thinking", "context_management", "output_config", "stream", "diagnostics", "stop_sequences",
}
KNOWN_STOP_REASONS = {"tool_use", "end_turn", "stop_sequence", "max_tokens"}
KNOWN_THINKING_TYPES = {"enabled", "disabled", "adaptive"}   # adaptive: opus-5/k3 自适应 thinking
# CC 声明过的 `anthropic-beta` 特性基线（实测全量的并集，**不是白名单**）。
# 260802 从 index.html 上提到这里：判别「哪些 beta 是新出现的」这件事此前只有前端做得到，
# 而唯一会去问「有没有新 beta」的消费者（AI 走 /api/unknowns）恰恰拿不到清单——于是雷达只能
# 退而按频次升序猜"长尾即信号"，实测每天把同样 5 个已知的结构性低频特性顶在最前（
# structured-outputs 只在标题请求带、token-counting 只在 count_tokens 探针带，低频是结构性的，
# 不是演进信号）。清单跟着判别逻辑走，前端从模板注入消费，杜绝两处分叉。
KNOWN_BETAS = {
    "claude-code-20250219", "oauth-2025-04-20", "context-1m-2025-08-07",
    "interleaved-thinking-2025-05-14", "redact-thinking-2026-02-12",
    "thinking-token-count-2026-05-13", "context-management-2025-06-27",
    "prompt-caching-scope-2026-01-05", "mid-conversation-system-2026-04-07",
    "advisor-tool-2026-03-01", "advanced-tool-use-2025-11-20", "effort-2025-11-24",
    "fallback-credit-2026-06-01", "afk-mode-2026-01-31", "extended-cache-ttl-2025-04-11",
    "cache-diagnosis-2026-04-07", "structured-outputs-2025-12-15", "token-counting-2024-11-01",
    # server-side-fallback 是 fallback-credit 的旧名（同日期段 2026-06-01）：旧名 07-14 最后
    # 出现、新名 07-25 首次出现，CC 版本间改了名。留着它，浏览改名前的老录制才不会误报。
    "server-side-fallback-2026-06-01",
}

KIND_ORDER = ("main", "subagent", "title", "compact", "security", "count_tokens",
              "quota_probe", "hook_eval", "notify_eval", "other")

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
#   v5 → v6（260731）：新增 harness 声明面 beta/agent_id + 请求体特性
#                     ctx_mgmt/diagnostics/stop_seqs_n/thinking_budget。
#                     CC 自己声明的东西此前一条都没进索引，等于放弃了「发现下一个盲区」
#                     最直接的信号源（详见 issues/open/260731_harness事实对账_录制盲区全面审计.md）
#   v6 → v7（260801）：summary 生成逻辑变更——纯工具调用轮（无 text block）fallback 到首个
#                     tool_use 工具名。字段集没变，但 summary 语义变了，旧索引要重建才能让
#                     历史工具调用轮也获得非空 summary（详见 issues/open/260801_列表summary与usage展示补全.md）
#   v7 → v8（260801）：新增 decode_error。响应体解不开时（gzip 流被截断等）上游仍是 200、
#                     转发也无 error，于是失败聚合（只读索引）完全看不见，而那条录制的正文
#                     其实是丢的。与 v0.4.3 修的「流内错误被录成成功致失败率低报」同型，
#                     是它漏掉的另一半（详见 issues/open/260801_decode_error不计入失败统计.md）
#   v8 → v9（260802）：新增 format（output_config.format.type，structured-outputs）。
#   v9 → v10（260802）：新增 unknowns（盲区雷达）。同时 classify_idx 固化 quota_probe
#                     + hook_eval 两个原 other 子类（字段集没变，但旧索引要重建才能让
#                     历史 10 条从 other 改判 + 拿到 unknowns）。
#   v10 → v11（260802）：KNOWN_* 扩充（并入 advanced-tool-use 的 caller / web_search 链的
#                     citations + web_search_tool_result / redacted_thinking / tool_choice /
#                     adaptive thinking），旧索引的 unknowns 按旧 KNOWN 算、会把这些当未知，
#                     需重建。同时 index_record 加 tool_choice 字段。
#   v11 → v12（260802）：unknowns v2——_unknowns 的 blocks/block_keys/body_fields 从 set 改为
#                     value→snippet dict（带内容片段），供 /api/unknowns 的 snippet 字段 +
#                     beta 关联。旧索引的 unknowns 是 list 结构，需重建。
#   v12 → v13（260802）：新增 host（upstream netloc，路由供应商）+ cc_version（user-agent 解析），
#                     供跨天失败聚合 /api/diagnose/trends 按供应商 / CC 版本切片。两者历史录制
#                     均可回填（rec.upstream / headers_safe.user-agent 一直存在），但旧索引无
#                     这两字段 → 必须重建让 trends 维度切片生效。
#   v13 → v14（260802）：unknowns 分流——本工具自己的降级标记（_input_raw /
#                     input_raw_fallback）从 block_keys 移到新的 degraded 维度，同时 KNOWN_*
#                     并入 compaction（proxy 自己组装的块，此前会被雷达报成协议未知）。
#                     旧索引的 unknowns 按旧规则算，degraded 恒缺失、compaction 恒误报，需重建。
#   v14 → v15（260802）：新增 turn_user（轮首用户消息，剥 reminder 后取 160 字），供 DAG 按轮
#                     折叠的轮卡当检索键。必须写时算——last_user 只存 2000 字，而 reminder 可达
#                     9960 字，读时现剥剥不出东西（详见该字段注释）。
#   v15 → v16（260901）：turn_start 判据收口——工具回传的附属文本（`[Image: …]` 图片说明、
#                     WebFetch 正文、打断标记）不再算轮起点。字段集没变，但 turn_start 的语义
#                     变了，旧索引不重建就会新旧两套切分混在一起看不出来（惯犯②「静默降级」
#                     同型）。判据单份在 user_text_kind/opens_turn。
#   v16 → v17（260901）：sec_action 改用双格式 transcript 解析。CC 2.1.238 起 transcript 从
#                     一行一对象换成文本条目（续行缩进两格），旧解析在这种录制上 100% 取错
#                     待判定动作、动作数按物理行虚增。字段集没变，值变了，必须重建。
IDX_SCHEMA = 17


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

# transcript 的两种渲染格式——**这是 CC 自己在安全提示词里声明的**，不是我们猜的：
#   「Assistant-role entries (keyed `assistant` in JSONL format, or prefixed `Assistant:`
#     in text format)」
# 格式 A（JSONL）：一行一个单键对象 `{"Bash":"…"}` / `{"user":"…"}`，参数里的换行是转义的，
#   所以一个条目永远只占一行。
# 格式 B（文本）：条目顶格写 `工具名 参数` 或 `User: 文本`，参数的续行**缩进两格**，
#   参数里带真换行（heredoc、多行脚本、Agent 提示词）时一个条目横跨几十行。
# 260901 实测：本机 684 条全是格式 A，两个导入源 560 条全是格式 B（CC 2.1.238 起）。
# 旧解析只认格式 A、且拿最后一个物理行当动作，格式 B 上 560/560 全错——取到的是末条动作的
# 续行残尾（`  "`、`  EOF`、说明文字的最后一句），界面上「待判定动作」就只剩一个引号；
# 「历史动作」数的也是物理行，把 42 条动作报成 1846 条。
_SEC_HEAD = re.compile(
    r'^(User|Assistant|System):\s*(.*)$'
    r'|^([A-Z][A-Za-z0-9_]*|mcp__[A-Za-z0-9_-]+)\s+(\S.*)$')
# 顶格 ≠ 条目起始：Agent 提示词与 teammate 消息的正文也顶格（实测 `##`、`1.`、
# `<teammate-message` 都出现在列 0）。所以还要求首 token 形似工具名，并排掉英文散文的句首词。
# 两道加起来在 560 条格式 B 上把末条目判成了干净的工具集（Bash 359 / PowerShell 132 /
# SendMessage 32 / Agent 21 / Edit 11 / ScheduleWakeup 1），另 4 条末条目是 user 角色——
# 那是子代理交还控制权后的复查，属真实形态，不是解析失败。
_SEC_TOOLISH = re.compile(r'^(?:[A-Z][a-z0-9]+){1,4}$|^mcp__[A-Za-z0-9_-]+$')
_SEC_PROSE_STARTERS = {
    "This", "That", "These", "Those", "The", "Do", "If", "When", "While", "Note", "Then",
    "You", "Your", "It", "Its", "All", "No", "Yes", "For", "And", "But", "So", "Now", "Use",
    "Read", "Write", "Only", "Also", "Each", "Every", "Any", "Some", "Where", "What", "Which",
    "Who", "How", "Why", "Return", "Report", "Output", "Make", "Keep", "Check", "Run", "Give",
    "Take", "Let", "Please", "First", "Second", "Third", "Finally", "Before", "After",
    "Here", "There", "We", "I",
}


def _sec_entries(inner: str) -> list[tuple[str, str]]:
    """transcript 正文 → [(工具名, 参数)]，两种格式统一走这里。

    **认不出的行归给上一个条目**，不另起一条——续行归错位置只是参数少一截，另起一条
    会让「动作数」虚增，那正是旧实现数物理行闯的祸。
    """
    out: list[list] = []
    for line in inner.split("\n"):
        tok = rest = None
        try:                                   # 格式 A：整行是一个单键 JSON 对象
            obj = json.loads(line.strip())
            if isinstance(obj, dict) and len(obj) == 1:
                k, v = next(iter(obj.items()))
                tok = str(k)
                rest = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
        except Exception:
            pass
        if tok is None:                        # 格式 B：顶格 + 工具名/角色名
            m = _SEC_HEAD.match(line)
            if m and m.group(1):
                tok, rest = m.group(1).lower(), m.group(2)
            elif m and m.group(3) and _SEC_TOOLISH.match(m.group(3))                     and m.group(3) not in _SEC_PROSE_STARTERS:
                tok, rest = m.group(3), m.group(4)
        if tok is not None:
            out.append([tok, [rest]])
        elif out:                              # 续行：去掉 CC 加的两格缩进
            out[-1][1].append(line[2:] if line.startswith("  ") else line)
        elif line.strip():                     # 开头就不是已知形状：原样留着，别丢
            out.append(["", [line]])
    return [(t, "\n".join(v).strip()) for t, v in out]


def sec_request(body: dict) -> dict | None:
    """安全审查请求 → {待判定动作, 本次审查的发送量}；不是安全审查则 None。

    实测形状（issues 里有完整报文）：system[1] 是 ~114K 的规则库，messages[0] 是用户
    CLAUDE.md（意图上下文），messages[-1] 是 `<transcript>` + N 条动作 + `</transcript>`
    + 判定指令。**判定对象是 transcript 的最后一条**（CC 正要执行的那个动作），
    前面几十上百条都是历史。条目的两种渲染格式见 `_sec_entries`。
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
    entries = _sec_entries(inner)
    tool, arg = entries[-1] if entries else ("", "")
    return {
        "action_tool": tool,
        "action_arg": arg[:SEC_ACTION_MAX],
        "action_truncated": len(arg) > SEC_ACTION_MAX,
        "n_actions": len(entries),
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


def _header(record: dict, name: str) -> str:
    """取请求头（大小写不敏感），缺失回空串。"""
    hdrs = (record.get("request") or {}).get("headers_safe") or {}
    for k, v in hdrs.items():
        if k.lower() == name and isinstance(v, str):
            return v
    return ""


# user-agent 形如 'claude-cli/2.1.220' 或 dev_seed 旧样 'claude-cli/2.1 (external, cli)'；
# [^\s/()]+ 截到空格/斜杠/括号前，两种形态都拿到主版本号。
_CC_VERSION_RE = re.compile(r"claude-cli/([^\s/()]+)")


def _cc_version(record: dict) -> str | None:
    """user-agent → CC 版本（如 '2.1.220'）。user-agent 在 headers_safe 里**不脱敏**
    （proxy._redact 只脱 SENSITIVE_HEADERS 鉴权类）。无法解析回 None——diagnose 的
    req_fields / Counter 都用 `if v:` 过滤 None，缺版本不会污染值列表。"""
    m = _CC_VERSION_RE.search(_header(record, "user-agent"))
    return m.group(1) if m else None


def _host_of(record: dict) -> str | None:
    """upstream URL → 路由供应商 host（netloc，wire 层直接事实）。

    **不做 model→vendor 硬映射**——同一 model 可能经多供应商/中转（claude-opus-5 可走官方、
    智谱、或别的聚合中转），model 名定不了供应商，host 才是真相。中转背后真正的算力供应商
    wire 层看不到也不该假装能看到；但 host × model 交叉已足够 AI 判断「这次失败经谁」。

    防御性剥掉 userinfo（urlparse 把 'user:pass@host' 整段塞进 netloc），以防 BASE_URL 带凭据。
    空 netloc → None。凭据在 Authorization/x-api-key 头（已脱敏），不在 URL。"""
    netloc = urlparse(record.get("upstream") or "").netloc
    if not netloc:
        return None
    return netloc.rsplit("@", 1)[-1] or None


def _beta_features(record: dict) -> list[str]:
    """`anthropic-beta` 头 → 特性列表。

    这是 CC 声明「我启用了哪些协议扩展」的地方，地位等同于 `Accept-Encoding` 之于解压格式：
    **它就是我们必须留意的能力清单**。实测 10 天出现 18 个特性、18 种组合，随 CC 版本漂移
    ——出现没见过的特性就是「可能有新盲区」的信号（docs/reference/开发约定.md §2.5）。"""
    raw = _header(record, "anthropic-beta")
    return [s.strip() for s in raw.split(",") if s.strip()] if raw else []


def _agent_fp(blocks: list[str]) -> str:
    """身份指纹：system block[2]（正文/agent 专属提示词）的 md5 短码。

    实测把三个子代理实例干净分组（Explore/general-purpose/Plan 各自一码）。
    用途仅限「无派生 prompt 对齐命中时的实例分组回落」——blk[2] 的措辞本身**不能**当
    main/subagent 判别位：`general-purpose` 是 "You are an agent for Claude Code…"，
    而 Explore 是 "file search specialist"、Plan 是 "software architect"，各不相同。"""
    if len(blocks) < 3:
        return ""
    return hashlib.md5(blocks[2].encode("utf-8", "replace")).hexdigest()[:8]


# ===== user 侧文本块的分类（**判据单份**，260901）=====
# user 角色下的 text 块绝大多数**不是人说的话**：状态通知、注入的规则、本地命令回显、
# WebFetch 正文、图片说明、harness 提醒都挂在 user 名下。实测一天 192 段里真人只有约 30 段。
#
# 这份判据此前在仓里有**三份互不相同的实现**，三份判错两份（260901 审计）：
#   1. `classifier._is_turn_start`      —— 只排除 `<system-reminder>`，`[Image:]` 判成新轮
#   2. `trajectory.py` 的 user_events   —— 有完整前缀清单，判对
#   3. `snapshot_extract._trigger_of`   —— 有 tool_result 且无 text 才算回传，`[Image:]` 判成新轮
# 后果不是三个 bug，是同一个 bug 的三份拷贝：时序图的轮、八视图的阶段、步级简报的 `turn` 号
# 各错各的，还互相矛盾。（同型教训：`usage_norm` 键名归一被抄三份、同一个 bug 犯两次。）
#
# CC 自己怎么做的（jsonl 实测，260901）：图片说明记成一条 `type:user` + **`isMeta:true`** 的行，
# 且**沿用发起者的 `promptId`**——归位 + 标记，既不新开轮也不丢弃。下面这份分类就是 wire 侧
# 能拿到的最接近的等价物（`isMeta` 不过 wire）。
TEXT_KIND_PREFIXES = (
    # (前缀, 类别)。**顺序敏感**：先匹配到的赢，长前缀放前面。
    ("<system-reminder", "reminder"),          # CC 注入的上下文块
    ("<total_tokens>", "status"),              # 预算状态通知
    ("This session is being continued", "compact_summary"),   # 压缩后的续接摘要
    ("[Image:", "payload"),                    # **工具回传的图片说明**（Read 读图 / MCP 截图）
    ("Web page content:", "payload"),          # WebFetch 抓回的正文
    ("[Request interrupted by user", "payload"),   # 打断标记本身（真人的话另在别的块里）
    ("<local-command", "harness"),
    ("<command-", "harness"),
    ("[SYSTEM NOTIFICATION", "harness"),
    ("Available agent types", "harness"),
    ("The task tools haven't been used", "harness"),
    ("This is a reminder", "harness"),
    ("Note: ", "harness"),
)
# harness 把「打断插话」包了一层，剥掉之后它就是一句真发言。
INTERRUPT_WRAPPER = "The user sent a new message while you were working:"
# **不开新轮的类别**。故意只有这三类，别往里加：
#   · reminder / status —— 注入物，从来不是一次发起
#   · payload           —— 工具回传的附属文本，CC 自己给它 `isMeta:true` 并沿用原 promptId
# `harness` **不在**这里，两条各自的理由：
#   · `[SYSTEM NOTIFICATION`（后台任务通知）在 jsonl 里**有 promptId**（实测 201 行
#     `origin.kind=task-notification`）——CC 认它是一轮，我们不能比 CC 更严。
#   · 斜杠命令在 jsonl 里没有 promptId，但它是**真人动作**，只是前缀被 CC 改写过；
#     §二·六 的 fail-safe 方向是「宁可把伪轮当真轮，不能把真人消息弱化」。
#   · `compact_summary` 在这里（不开轮）：它是压缩后的续接，不是一次新的发起，
#     CC 用 `system/subtype=compact_boundary` 单独标这件事。本语料 0 例，行为不变。
NON_OPENING_KINDS = {"reminder", "status", "payload", "compact_summary"}


def user_text_kind(text: str) -> tuple[str, str]:
    """user 角色下的一个 text 块 → (类别, 剥掉包装后的正文)。

    类别 ∈ reminder / status / compact_summary / payload / harness / user。
    **这是这件事的唯一判据**——`_is_turn_start`、`trajectory` 的 user_events、
    `snapshot_extract._trigger_of` 全都调它，不各自再写一份。
    """
    norm = (text or "").strip()
    if not norm:
        return "empty", ""
    stripped = norm.lstrip()
    if stripped.startswith(INTERRUPT_WRAPPER):
        return "user", stripped[len(INTERRUPT_WRAPPER):].lstrip()
    for prefix, kind in TEXT_KIND_PREFIXES:
        if stripped.startswith(prefix):
            return kind, norm
    return "user", norm


def opens_turn(text: str) -> bool:
    """这个 text 块能不能开启新的一轮。"""
    kind, _ = user_text_kind(text)
    return kind not in NON_OPENING_KINDS and kind != "empty"


def _is_turn_start(body: dict) -> bool:
    """轮次起点判据：最后一条 user 消息里存在一个「能开启新一轮」的 text 块。

    260717 首版写的是「非 <system-reminder> 开头的 text 块即算真人」，当时的实测结论是
    「工具回传就是纯 tool_result 块，不混文本」。**260901 证伪**：带图片的工具回传（Read 读图、
    MCP 截图）会在 tool_result 之后附一个 `[Image: original …]` 文本块，WebFetch 的正文也走
    user 文本块。实测 359 个主线轮起点里 21 个因此被切错，最坏的一天 08-08 是 17 切成 9（47%）；
    拿 CC 本地 jsonl 的 `promptId` 当真值对账，21 个泳道合计 jsonl 102 轮 vs wire 173 轮（+70%）。

    判据改走 `opens_turn()`（单份，见上）。**不是"识别假轮并丢弃"**——那些请求是真流量、有真
    成本，CC 自己的做法是把它们归到发起者的 `promptId` 下并标 `isMeta`，我们对应的做法是让它们
    留在原轮里当中间步，节点一个不少。"""
    last_u = None
    for m in body.get("messages") or []:
        if m.get("role") == "user":
            last_u = m
    if last_u is None:
        return False
    c = last_u.get("content")
    if isinstance(c, str):
        return opens_turn(c)
    if isinstance(c, list):
        for b in c:
            if isinstance(b, dict) and b.get("type") == "text" and opens_turn(b.get("text") or ""):
                return True
    return False


# ===== 轮起源分类（260809，经 jsonl 真值验证）=====
# 「这轮是谁发起的」：CC 会自己合成伪 user 消息触发一轮（建议补全/后台任务/离开回顾），
# 它们与真人消息在 wire 层结构判据上完全重叠（tools_n/max_tokens/计费头版本哈希实测无一能
# 分），只有措辞是稳定指纹。jsonl 侧有权威标记（origin.kind / promptSource），但不过 wire——
# 那 11 条「wire 有 jsonl 没有」的 main 请求里 10 条正是白名单命中者，另 1 条是被打断的真人消息，
# 所以这份前缀清单是启发式而非真值；命中不了的新形态一律落回 user（宁可把伪轮当真轮，不能把
# 真人消息弱化）。真值层在 ROADMAP 0.6.x：jsonl 在场时用 request-id join 取 origin.kind 覆盖。
TURN_ORIGIN_SYNTHETIC = (
    # ⚠️ 这四族**现在都判 main、进主线泳道**，只是 origin 降档成 synthetic。jsonl 侧的真值是
    # 「CC 根本没把它们写进对话记录」（260902 复测：以 `[SUGGESTION MODE` 开头的 jsonl 消息
    # 行 0 条；T1 归属对账 09-01 的 main absent 2 条全是它）。没改判不是漏，是「一轮的边界是
    # 对话单位还是成本单位」这个前置问题还没论证完——见 issues/open/260902_synthetic族判主线
    # 的归属论证.md。**别在这里顺手改判**，先把那份论证做完。
    "[SUGGESTION MODE",           # CC 建议补全（38 条，判 main）
    "The user stepped away",      # CC 离开回顾
    "Perform a web search for the query:",   # CC 内部检索
    "[SYSTEM NOTIFICATION",       # 后台任务通知（会带出真工作，故只弱化不隐藏）
)
TURN_ORIGIN_COMMAND = (
    "<local-command-caveat>",     # 斜杠命令注入前缀（轮是真人轮，前缀非用户原话）
    "<command-name>",
    "<command-message>",
)
# 程序驱动的会话：`cc_entrypoint` 以 sdk 开头（实测取值 `sdk-cli`；留前缀匹配是给
# sdk-py/sdk-ts 之类的未来取值）。**这是 L2 唯一的官方位**——260810 用 jsonl 对账时，
# 4 条「白名单判 user、jsonl 说是机器发起」的候选全部命中 `promptSource=sdk`，而它们在
# wire 侧的共同点不是措辞（脚本发什么都行、无指纹可提），是这个计费头字段：4/4 entrypoint
# 都是 sdk-cli，反过来 2180 条 cli 真人轮无一误伤。按 §二·五「官方标识符优先」，这类轮不该
# 靠猜——它本来就在头里写着。
TURN_ORIGIN_SDK_ENTRYPOINT_PREFIX = "sdk"


def _turn_origin(turn_start: bool, user_text: str, entrypoint: str = "") -> str:
    """轮起源分类：user / synthetic / command / sdk / partial。

    优先级（partial > 措辞 > entrypoint > user）与「官方标识符优先」不冲突，因为两类信号
    回答的**不是同一个问题**：措辞白名单说「这一轮是 CC 自己合成的」（轮级），entrypoint 说
    「这整个会话是程序驱动的」（会话级）。同一轮两者都命中时，轮级的更具体、信息量更大。
    实测本机全量录制里两者零重叠。

    这不是"噪声过滤"——伪轮会带出真流量、有真实 token 成本，藏了就是惯犯③静默丢数据；
    它是给前端一个"降档显示但留入口"的依据。partial 优先于一切（只录到中间段，起源不明）。
    """
    if not turn_start:
        return "partial"
    t = (user_text or "").strip()
    if t.startswith(TURN_ORIGIN_SYNTHETIC):
        return "synthetic"
    if t.startswith(TURN_ORIGIN_COMMAND):
        return "command"
    if (entrypoint or "").startswith(TURN_ORIGIN_SDK_ENTRYPOINT_PREFIX):
        return "sdk"
    return "user"


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
def _snippet(v) -> str:
    """未知字段值的简短片段（盲区雷达 v2，260802：让 AI 一次调用就判断，省二次调详情）。"""
    if isinstance(v, str):
        return v[:80]
    try:
        return json.dumps(v, ensure_ascii=False)[:80]
    except Exception:
        return str(v)[:80]


def _unknowns(rec: dict, body: dict, resp: dict) -> dict:
    """这条记录命中的未知维度（盲区雷达，260802）。

    blocks / block_keys / body_fields / degraded 是 **value → snippet** dict（不只值名，还带一段
    内容片段，让 AI 不必二次调 /api/captures/{id} 就能判断）；stop_reason / thinking_type 是标量。
    空 dict = 无未知。已知集合见顶部 KNOWN_*——出现集合外的值就是协议演进信号。

    **degraded 与其余维度性质不同**：那是本工具自己的降级标记（CAPTURE_ARTIFACT_KEYS），
    说明这条录制的正文是残的，该查代理侧；其余维度才是"上游给了我们不认识的东西"。"""
    out: dict = {}
    unk_blocks: dict[str, str] = {}    # 块类型 -> 该块片段
    unk_bkeys: dict[str, str] = {}     # "type.key" -> 值片段
    degraded: dict[str, str] = {}      # "type.key" -> 值片段（本工具的降级标记）
    for blk in resp.get("content_blocks") or []:
        if not isinstance(blk, dict):
            continue
        t = blk.get("type")
        if t and t not in KNOWN_BLOCK_TYPES:
            preview = {k: v for k, v in blk.items() if k != "content"}
            unk_blocks[t] = _snippet(preview) or _snippet(blk)
        known_keys = KNOWN_BLOCK_KEYS.get(t) if t else None
        for k in blk.keys():
            if k == "type":
                continue
            if known_keys and k in known_keys:
                continue
            if k in CAPTURE_ARTIFACT_KEYS:
                degraded[f"{t}.{k}"] = _snippet(blk.get(k))
                continue
            unk_bkeys[f"{t}.{k}"] = _snippet(blk.get(k))
    if unk_blocks:
        out["blocks"] = unk_blocks
    if unk_bkeys:
        out["block_keys"] = unk_bkeys
    if degraded:
        out["degraded"] = degraded
    if isinstance(body, dict):
        uf = {k: _snippet(body[k]) for k in body.keys() if k not in KNOWN_BODY_FIELDS}
        if uf:
            out["body_fields"] = uf
    sr = resp.get("stop_reason")
    if sr and sr not in KNOWN_STOP_REASONS:
        out["stop_reason"] = sr
    th = body.get("thinking") if isinstance(body, dict) else None
    if isinstance(th, dict):
        tt = th.get("type")
        if tt and tt not in KNOWN_THINKING_TYPES:
            out["thinking_type"] = tt
    return out


def _tool_choice_flat(body: dict) -> str | None:
    """tool_choice 归一：{type:"tool", name:X} → X；{type:"auto"/"any"} → type；无 → None。
    让 AI 查「哪些请求被强制工具」（如 CC 强制 web_search 联网）。"""
    tc = body.get("tool_choice")
    if not isinstance(tc, dict):
        return None
    if tc.get("type") == "tool" and tc.get("name"):
        return str(tc["name"])
    return tc.get("type") or None


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
    if not summary:
        # 纯工具调用轮（thinking + tool_use，无 text）——子代理中间步、主对话工具循环几乎都这样。
        # 列表/DAG 摘要空白就看不出这一轮做了什么；fallback 到首个 tool_use 工具名才描述动作。
        # 与 💬 chat-only turn 的 emoji 风格一致（260801 能力面审计 A4）。
        for blk in resp.get("content_blocks") or []:
            if isinstance(blk, dict) and blk.get("type") == "tool_use" and blk.get("name"):
                summary = "🔧 " + blk["name"]
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
        # 「用户这轮说了什么」（260802，DAG 按轮折叠的检索键）。**必须在这里算，不能在
        # build_dag 里拿 last_user 现剥**：last_user 只存前 2000 字，而 CC 注入的
        # system-reminder 可达 9960 字（general-purpose 派生），于是索引里存的那 2000 字
        # 常常整段都是 reminder、连闭合标签都没截到——剥不掉，轮卡上就是一片
        # `<system-reminder>…`。这里拿的是完整 body，剥干净再截。
        "turn_user": (strip_reminders(users[-1])[:TURN_USER_TEXT_LEN]
                      if (users and _is_turn_start(body)) else ""),
        # ---- 诊断原料（260725）----
        # 失败聚合要按「错误消息指纹」归并，并同时摆出**请求侧的相关字段**，否则 agent 拿到
        # 一句 "effort 'max' is not supported when thinking is disabled" 还得再去翻原始 record
        # 才知道这个请求的 effort/thinking 到底是什么。实测这两个字段一摆出来，
        # 「effort=max + thinking=disabled → 400」的因果一眼就能对上。
        "err_kind": (rec.get("error") or {}).get("kind") or "",
        "err_msg": _error_message(rec),
        # 解码失败：上游给了 2xx、转发也没报错，但响应体解不开（gzip 流被截断、utf8 解码
        # 失败……），于是 content_blocks/usage 全空——**这条录制的正文是丢的**。
        # 不进索引的话，失败聚合（只读索引）永远看不见它：详情页如实标着 decode_error，
        # 首页却说一切正常（260801 用户实测 req_49f51e4）。存原始字符串而非布尔，
        # 因为归并时要按具体原因分组（gzip 截断 ≠ utf8 失败）。
        "decode_error": (resp.get("decode_error") or ""),
        "effort": ((body.get("output_config") or {}).get("effort")
                   if isinstance(body.get("output_config"), dict) else None),
        # structured-outputs（structured-outputs-2025-12-15）：CC 强制 json_schema 输出
        # （如标题请求只要 {title}）。只存 format.type 小标量，schema 内容详情页 body 可见。
        "format": (((body.get("output_config") or {}).get("format") or {}).get("type")
                   if isinstance((body.get("output_config") or {}).get("format"), dict) else None),
        # tool_choice：CC 强制指定工具（如 web_search）。归一成 name 或 type。
        "tool_choice": _tool_choice_flat(body),
        "thinking": ((body.get("thinking") or {}).get("type")
                     if isinstance(body.get("thinking"), dict) else None),
        "stream": bool(body.get("stream")),
        "max_tokens": body.get("max_tokens"),
        # ---- 安全审查原料（260729）----
        # 待判定动作在 transcript 末尾，last_user 只存前 2000 字够不着，只能单独提取。
        # 列表行要一眼看出「AI 在确认什么、判了什么」，这两个字段就是那两句话的原料。
        "sec_action": _sec_action_flat(body),
        "sec_verdict": sec_verdict(resp),
        # ---- harness 声明面（260731 对账审计）----
        # CC 自己声明的东西，此前一条都没进索引。它们的用处不是当下判别，是**发现下一个盲区**：
        # 出现没见过的 beta 特性或新的请求体字段，就意味着 CC 启用了新能力，
        # 而新能力往往带来我们还不认识的请求字段或响应块（详见 docs/reference/开发约定.md §2.5）。
        "beta": _beta_features(rec),
        # CC 直接在 HTTP 头上给的子代理实例 ID。**取证结论（9 天 4,629 条）：
        # 它与计费头 cc_is_subagent=true 完全一致，225/225 零反例，且 225 条全部是
        # cc_entrypoint=cli** —— 判别定案时悬着的「cli 模式未实测」由此有了实测数据。
        # kind 判别仍以计费头为准（260725 定案，不因多一个一致信号改结论）；
        # 但**泳道实例键 260801 起以它优先**（build_dag：官方实例 ID 比 md5(派生者|prompt)
        # 精确，且能 join CC jsonl 的 subagents/agent-<id>.jsonl），老录制无头时回落对齐键。
        "agent_id": _header(rec, "x-claude-code-agent-id"),
        # 请求体里 CC 实际在用、我们此前完全没解析的特性（G8）。只存小标量，不存内容。
        "ctx_mgmt": bool(body.get("context_management")),
        "diagnostics": bool(body.get("diagnostics")),
        "stop_seqs_n": len(body.get("stop_sequences") or []),
        "thinking_budget": ((body.get("thinking") or {}).get("budget_tokens")
                            if isinstance(body.get("thinking"), dict) else None),
        # ---- 盲区雷达（260802）----
        # 命中已知集合外的值（非标块类型/字段、未解析请求字段、非标 stop_reason/thinking.type）。
        # 空 dict = 无未知。/api/unknowns 聚合它，给 AI 当「协议演进 / 录制盲区」的改进线索。
        "unknowns": _unknowns(rec, body, resp),
        # ---- 跨天趋势维度（260802）----
        # 跨天失败聚合要看「按供应商 / 按 CC 版本」切片。host 取自 upstream netloc（wire 层
        # 直接事实，不做 model→vendor 硬映射——同 model 可能经多供应商/中转）；cc_version 取自
        # user-agent（headers_safe 不脱敏）。两者历史录制均可回填（rec.upstream /
        # headers_safe.user-agent 一直存在），旧索引重建即生效。
        "host": _host_of(rec),
        "cc_version": _cc_version(rec),
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
    # 命名类辅助（标题 / kebab-case slug）——**官方位优先于措辞**，见 NAMING_FORMAT。
    # 必须排在 title 措辞与 main 指纹之前：命名请求的 system 开头同样是 "You are Claude Code"，
    # 措辞一漏就被主线指纹抢走（2.1.238 起实测 10/10 全漏）。
    if idx.get("format") == NAMING_FORMAT and not tools_n:
        return "title"
    # title 生成：措辞作**兜底**（官方位没带时，如老录制、或未来换回非结构化回包）。
    # 不再用 maxtok 硬阈值——实测 title max_tokens=32000，旧的 TITLE_MAX_TOKENS=1024 反而漏判。
    if any(h in blob for h in TITLE_HINTS):
        return "title"
    if any(h in blob for h in COMPACT_HINTS):
        return "compact"
    # 子代理：上游权威位，优先于一切 main 指纹（子代理 system 同样带主线措辞，
    # 靠措辞判必错——这正是「误判成 main = 终身 main」的老根因）
    if idx.get("is_subagent"):
        return "subagent"
    # StopConditions hook 评估（260802）：用户配的 stop hook，让模型判停止条件是否满足。
    # **260901 上移**：它无工具，若留在 main 兜底之后，会被下面那条「无工具不判主线」先截走。
    if "stop-condition hook" in sys_low or "stopping condition" in sys_low:
        return "hook_eval"
    # 通知判定（260902）：CC 判「用户该不该被叫回来」的辅助调用，见 NOTIFY_EVAL_HINTS。
    # 与 hook_eval 同样无工具，**必须排在下面那道「无工具不判主线」的门之前**，否则被截成 other。
    # 合取无工具：CC 将来若在带工具的请求里引用同样措辞（如让主线自己判状态），那仍是主线。
    if not tools_n and any(h in sys_low for h in NOTIFY_EVAL_HINTS):
        return "notify_eval"
    # 结构位：**对话形状但没带工具清单 → 不是主线**（260901）。
    # CC 每次真对话请求都把全量 tools 发一遍，实测 3,352/3,352 条真主线带工具；反过来，
    # 15 条无工具却被判成 main 的**全部**是辅助（命名 11 / WebFetch 正文提炼 4）。
    # 判成 `other` 而不是猜它是哪种辅助：这是 §二·五 的 KNOWN_* 循环——先落 `other` 进雷达
    # （/api/unknowns 的 other_kind_samples），形状稳定了再固化成独立 kind，像 quota_probe /
    # hook_eval 当初那样。**别在这里堆措辞去猜**。
    # fail 方向也在这里翻正：漏判的代价从「混进主线、污染轮与分析地基」降为「显示成 other」。
    if not tools_n and sys_text.strip():
        return "other"
    if any(fp in sys_low for fp in MAIN_SYSTEM_FPS):
        return "main"
    # fallback（260725 方向反转）：带工具的对话请求，既没有子代理权威位、又不含已知主线指纹
    # —— 判 main。原先判 subagent 太宽：sdk-cli 主线不含 "you are claude code" 指纹，
    # 5/5 全被降级成子代理（旧准确率 10/15 的全部错项）。未知形状默认主线，
    # 真子代理另有 build_dag 的派生 prompt 对齐兜底改判。
    if tools_n > 0 and sys_text:
        return "main"
    # 配额/鉴权探测（260802，9 条铁证一致）：user="quota" + maxtok<=1 + 无工具 + 无 system。
    # CC 发的极小请求探上游可用性，多落 429/401/timeout——主对话看不到的隐藏行为。
    fu = (idx.get("first_user") or "").strip().lower()
    if (fu == "quota" and (idx.get("max_tokens") or 0) <= 1
            and not (idx.get("tools_n") or 0) and not sys_text.strip()):
        return "quota_probe"
    return "other"


# ===== L6 雷达 · 主线可疑（260901）=====
# 理念来自 260901 用户定调：**主线的判据不该由我们在 wire 侧拍，要看 CC 自己怎么定义**——
# 「把这个环节拿开，整个上下文仍然是连贯的，那它就不是主线」。CC 的实现字面如此：标题写成
# `type:"ai-title"` 一行（无 uuid/parentUuid/promptId，根本不在对话 DAG 上），安全审查 /
# count_tokens / 配额探测 / 压缩一条都不写进对话记录。
#
# **但 jsonl 不过 wire，运行时读不到**（§二·五 260810 拍板：jsonl 只作开发期真值源）。所以这里
# 走雷达路子而不是分类器路子：运行时**不改判**，只把「判成主线、却缺少主线结构特征」的请求
# 报给 AI（`/api/unknowns` 的 `mainline_suspect` 维度），精确对账留给 `tools/origin_probe.py
# --mode belong`。这与 L6 的定位一致——**雷达不是分类器，是发现"我可能判错了"的信号**。
#
# 当前只有一条判据，因为只有它在实测里零反例：
#   `tools_n == 0` —— 3,360 条判成 main 的请求里 15 条无工具，**15/15 全是辅助误判**
#   （2.1.238 起改了措辞的标题 10 条、kebab 命名 1 条、WebFetch 正文提炼 4 条）。
#   真主线恒带全量工具清单，CC 每次请求都把 tools 全发一遍。
# **别往这里堆措辞前缀**：措辞白名单该待在 classify_idx 里（那是分类），雷达要的是结构信号——
# 措辞会被 CC 改（2.1.238 就改过一次），结构不会。
MAINLINE_DOUBT_REASONS = {
    "no_tools": "判成主线但没带工具清单；实测 3,360 条 main 里 15 条无工具、15/15 是辅助误判",
}


def mainline_doubt(idx: dict, kind: str) -> str | None:
    """这条被判成主线的请求，有没有「其实不是主线」的结构疑点。返回原因码或 None。

    判据单份放这里：雷达（capture_store.unknowns）与将来任何消费方都调它，不各自再写一份
    ——`usage_norm` 键名归一被抄三份、同一个 bug 犯两次的教训。"""
    if kind not in ("main", "subagent"):
        return None
    if not (idx.get("tools_n") or 0):
        return "no_tools"
    return None


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
    node = {
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
    # 轮首节点带上「用户这轮说了什么」（260802）。**这是按轮折叠的检索键**：
    # summary 是模型的回答，而人回溯时找的是自己说过的话。只给轮首带——一天几千个节点，
    # 每个都背一份 160 字不划算，中间步也没有新的 user 消息可言。
    if node["turn_start"]:
        node["user_text"] = idx.get("turn_user") or ""
        # 轮起源要用的官方位（260810）：只给轮首带，理由同上——它只在分轮那一刻被读一次。
        # 不透给前端（`build_dag` 出口会剥掉），前端消费的是算好的 `turns[].origin`。
        node["entrypoint"] = idx.get("entrypoint") or ""
    # 安全审查节点带上待判定动作（260730）：security 的响应正文是 `<severity>8` 这种残片，
    # 拿它当摘要等于什么都没说（列表行 v0.4.1 已改，DAG 当时漏了）。只给 security 带，
    # 其余 kind 不背这个恒 null 的字段——一天几千个节点，每个都带一次不划算。
    # 判定结果一起带（260901）：只带动作不带判定，时序图就只能看出「在审什么」，
    # 看不出「判了什么」——列表行两样都有，两个视图信息量不一致。这是 260730 那次
    # 「列表行改了、DAG 漏了」的同型复发，改一处消费方时把同族字段一次带齐。
    if kind == "security":
        if idx.get("sec_action"):
            node["sec_action"] = idx["sec_action"]
        if idx.get("sec_verdict"):
            node["sec_verdict"] = idx["sec_verdict"]
    return node


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

    # 260801：泳道键 agent_id 优先（X-Claude-Code-Agent-Id 头，CC 官方实例 ID）。
    # 取证（tools/agent_id_probe.py，10 天 225 条）：07-31 起 23/23 全带、实例内稳定、
    # 跨实例零复用，且与 ~/.claude/projects/<proj>/<session>/subagents/agent-<id>.jsonl
    # 文件名 3/3 对上——同一 ID 空间，泳道键能直接 join 子代理完整对话。
    # 对齐循环仍先按 md5 键归位（trigger 边是父子推断的唯一来源，agent_id 不含父信息），
    # 这里把带头的实例统一改写到官方键：同实例混合录制（部分记录有头、部分没有）不裂两列。
    # 老录制（07-31 前的 CC 没这个头）自然留在 md5 键上，兜底路径不变。
    aid_of_aligned: dict[str, str] = {}
    for r, kind, lk in infos:
        if kind == "subagent" and lk.startswith("agent-") and r.get("agent_id"):
            aid_of_aligned[lk] = "agent-" + r["agent_id"]
    for info in infos:
        if info[1] == "subagent" and info[2] in aid_of_aligned:
            info[2] = aid_of_aligned[info[2]]

    # 有权威位但没对齐命中的子代理（老录制缺 prompt、派生方未录到、跨天截断、Workflow
    # 派生 prompt 藏在 JS script 里对不上）：优先用 agent-id（CC 给的实例 ID，Workflow/
    # Agent 派生都带、能区分实例），退到 agent_fp（system 指纹，类型级）。前者让 Workflow
    # 的 wf_a/wf_b 两个并行实例分两列，后者至少同类型合一列。Workflow 子代理无 trigger
    # 边是 A6 设计限制（不修），但 agent-id 至少不让不同实例挤一列（260801）。
    for info in infos:
        r, kind, lk = info
        if kind == "subagent" and not lk.startswith("agent-"):
            key = r.get("agent_id") or r.get("agent_fp") or lk
            info[2] = "agent-" + key

    # lane 组装：main 每会话一列、subagent 每派生实例一列、辅助合一列
    # （subagent 的 lane_key 到这里必然已是 "agent-" 开头：对齐命中时设成派生实例键，
    #   未命中时由上面的 agent_fp 回落循环补上）
    lane_of: dict[str, dict] = {}
    nodes = []
    aux_sid: dict[str, str] = {}   # aux node id → session_id（near 边精确挂接用，260801）
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
        n = _node_summary(r, kind, lane_id)
        if lane_kind == "aux" and r.get("session_id"):
            aux_sid[n["id"]] = r["session_id"]
        nodes.append(n)

    # seq 边：同 lane 相邻
    edges = list(trigger_edges)
    _node_by_id = {n["id"]: n for n in nodes}
    by_lane: dict[str, list[dict]] = {}
    for n in nodes:
        by_lane.setdefault(n["lane"], []).append(n)
    for lane_nodes in by_lane.values():
        for a, b in zip(lane_nodes, lane_nodes[1:]):
            edges.append({"from": a["id"], "to": b["id"], "type": "seq"})

    # 轮聚合（260717 起标 pure_chat，260802 升级成一等公民 `turns`）：main/subagent 泳道内
    # 按 turn_start 分轮。轮是**对话的语义单位**——一次用户消息 + 它引发的所有工具循环步、
    # 派生的子代理、触发的辅助调用。DAG 按轮折叠时每轮一张卡，卡上放的是「你这轮说了什么」，
    # 而不是模型回答的前 60 字（后者是请求视角，不是对话视角）。
    #
    # 整轮 tool_use 总数为 0 且轮首是真起点 → 全轮标 pure_chat（「回顾一下干了什么」这类
    # 没动手的轮次，前端降档渲染）。lane 开头缺起点的残轮（代理中途启动，只录到某轮的中间段）
    # 不标——它属于一个没看全的干活轮。
    turns: list[dict] = []
    turn_of: dict[str, str] = {}          # node id → turn_id

    def _flush_turn(lane_id: str, turn: list[dict]) -> None:
        if not turn:
            return
        if turn[0]["turn_start"] and sum(n["tool_uses"] for n in turn) == 0:
            for n in turn:
                n["pure_chat"] = True
        tid = f"{lane_id}#{len(turns)}"
        for n in turn:
            n["turn"] = tid
            turn_of[n["id"]] = tid
        turns.append({
            "turn_id": tid,
            "lane": lane_id,
            "head": turn[0]["id"],        # 轮首节点 id（折叠时轮卡画在它的位置上）
            "index": 0,                   # 泳道内序号，下面统一编号
            "first_ts": turn[0]["ts_start"],
            "last_ts": turn[-1]["ts_start"],
            "node_ids": [n["id"] for n in turn],
            # 轮首是真起点才有用户消息；残轮（只录到中间段）留空并标 partial
            "user_text": turn[0].get("user_text") or "",
            "partial": not turn[0]["turn_start"],
            # 起源分类（260809）：user/synthetic/command/partial，前端据此降档伪轮、
            # 不把它们与真人轮画成同一种卡。判据单份在这里，前端不重算。
            "origin": _turn_origin(bool(turn[0]["turn_start"]),
                                   turn[0].get("user_text") or "",
                                   turn[0].get("entrypoint") or ""),
            "steps": len(turn),
            "tool_uses": sum(n["tool_uses"] for n in turn),
            "total_ms": sum(n["total_ms"] or 0 for n in turn),
            # errors 给的是**数量**不只是布尔：一轮 31 步里有 1 次瞬时 429 重试，和整轮全挂，
            # 是完全不同的两件事。前端据此决定"标个 ⚠N 徽章"还是"整卡染红"——
            # 实测一天 68 轮里 29 轮含至少一次失败，若一律染红，红色就不再刺眼了。
            "errors": sum(1 for n in turn if n["has_error"]),
            "has_error": any(n["has_error"] for n in turn),
            "pure_chat": bool(turn[0].get("pure_chat")),
            "subagents": [],              # 下面按 trigger 边回填
            "aux": {},                    # 下面按 near 边回填
        })

    for lane_id, lane_nodes in by_lane.items():
        if lane_id == "aux":
            continue
        turn: list[dict] = []
        for n in lane_nodes:
            if n["turn_start"] and turn:
                _flush_turn(lane_id, turn)
                turn = [n]
            else:
                turn.append(n)
        _flush_turn(lane_id, turn)
    per_lane_no: dict[str, int] = {}
    for t in sorted(turns, key=lambda x: x["first_ts"] or ""):
        per_lane_no[t["lane"]] = per_lane_no.get(t["lane"], 0) + 1
        t["index"] = per_lane_no[t["lane"]]

    # 子代理归轮：trigger 边的起点属于哪一轮，被派生的泳道就归哪一轮（嵌套派生天然成立——
    # 子代理派生的子代理归到父子代理的那一轮）。标签取被派生泳道首条的用户文本＝派生 prompt。
    turn_by_id = {t["turn_id"]: t for t in turns}
    first_node_of_lane = {lid: ns[0] for lid, ns in by_lane.items() if ns}
    for e in trigger_edges:
        t = turn_by_id.get(turn_of.get(e["from"], ""))
        head = _node_by_id.get(e["to"])
        if not t or not head:
            continue
        lane = head["lane"]
        if any(s["lane_id"] == lane for s in t["subagents"]):
            continue
        first = first_node_of_lane.get(lane) or head
        t["subagents"].append({
            "lane_id": lane,
            "label": (first.get("user_text") or first.get("summary") or "")[:60],
        })

    # near 边：aux 节点 → 关联主线节点。**260801 起优先精确挂 session**——aux 请求同样带
    # X-Claude-Code-Session-Id（实测 10 天 1163 条 100% 带、1160 条精确对上当天主线），
    # 时序邻近只是挂不上时（会话主线没被录到/跨天，3/1163）的兜底。此前只靠时序邻近，
    # 多会话并发日（07-18 十三会话 746 条 aux）会把辅助挂到别家主线上，
    # 级联隐藏与 assoc-dot 着色跟着错。
    main_by_lane: dict[str, list[dict]] = {
        lid: [n for n in ns if n["kind"] == "main"] for lid, ns in by_lane.items()}
    main_nodes = [n for n in nodes if n["kind"] == "main"]

    def _latest_before(pool: list[dict], ts: str):
        prev = None
        for m in pool:
            if (m["ts_start"] or "") <= ts:
                prev = m
            else:
                break
        return prev

    for n in nodes:
        if n["lane"] != "aux":
            continue
        prev = None
        sid = aux_sid.get(n["id"])
        if sid:   # 精确：与主线泳道键同一算法（"s-" + md5(session_id)，见 _lane_key）
            pool = main_by_lane.get(
                "s-" + hashlib.md5(sid.encode("utf-8", "replace")).hexdigest()[:8])
            if pool:   # 泳道在就只在泳道内找：先取时序前驱，没有（aux 早于本会话首条
                prev = _latest_before(pool, n["ts_start"] or "") or pool[0]
                # 主线，如安全审查抢跑）就挂首条——宁可方向反也不挂到别家会话
        if prev is None:   # 兜底：全局时序邻近（弱示意，仅时序邻近非因果）
            prev = _latest_before(main_nodes, n["ts_start"] or "")
        if prev:
            edges.append({"from": prev["id"], "to": n["id"], "type": "near"})
            # 辅助归轮（260802）：near 边起点属于哪一轮，这次辅助调用就归哪一轮。
            # ⚠️ **只能归到主线的轮，归不到子代理**：9 天 1290 条 aux 里带
            # X-Claude-Code-Agent-Id 的是 0 条，而 session_id 子代理与主线共用（260725 定案），
            # wire 层没有任何标识能说「这次安全审查是在审子代理的工具调用」。靠时序邻近猜
            # 属于启发式，而 §2.5 的定案是官方标识符优先——猜错的代价（把主线的标题请求挂到
            # 子代理头上）比"都挂主线"更糟。等 CC 哪天给了标识再收紧。
            t = turn_by_id.get(turn_of.get(prev["id"], ""))
            if t:
                t["aux"][n["kind"]] = t["aux"].get(n["kind"], 0) + 1
                turn_of[n["id"]] = t["turn_id"]
                n["turn"] = t["turn_id"]
                t["node_ids"].append(n["id"])

    # entrypoint 是**算 origin 用的中间原料**，算完就摘掉：它已经浓缩进 turns[].origin，
    # 留在节点上等于让前端多一个可以自己重算判据的入口（判据必须单份，见 §二·五）。
    for n in nodes:
        n.pop("entrypoint", None)

    # lanes 排序：main 按首见时间，subagent 次之，aux 最后
    lanes = sorted(lane_of.values(),
                   key=lambda l: ({"main": 0, "subagent": 1, "aux": 2}[l["kind"]],
                                  l["first_ts"] or ""))
    return {"nodes": nodes, "edges": edges, "lanes": lanes,
            "turns": sorted(turns, key=lambda t: t["first_ts"] or "")}


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
