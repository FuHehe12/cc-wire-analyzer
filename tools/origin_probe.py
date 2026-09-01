"""取证：轮起源（L2）启发式到底准不准——拿 CC 本地 jsonl 当真值源对账。

**这是开发期探针，不是产物的一部分**（issue 260810 拍板）：读 `~/.claude/projects/` 属用户
隐私数据，只允许在开发机上跑脚本核对判断，绝不进运行时。`tools/` 不在 `build.spec` 的 datas
里，所以这条边界由打包边界保证，不靠一个可关闭的开关（开关会被误开、要维护、要写文档解释）。

背景见 `docs/reference/开发约定.md` §二·六：识别体系七层里，**L2「这轮谁发起的」是唯一在 wire
上没有官方标识符的层**，只能靠 `classifier.TURN_ORIGIN_*` 四条措辞前缀撑着。而 CC 自己的 jsonl
恰好带着那个位。本探针回答四个问题，每个都给数字：

1. **join 健康度** —— 两条 join 链路各覆盖多少轮、剩下多少对不上，如实报不猜。
2. **混淆矩阵** —— 启发式 origin × jsonl 真值，分方向报（两个方向的严重性差一个量级）。
3. **危险方向（零容忍）** —— 判成 synthetic 但 jsonl 说是真人打的字。哪怕 1 例都是事故：
   §二·六 的 fail-safe 方向就是「宁可把伪轮当真轮，不能把真人消息弱化」。
4. **origin 雷达** —— 判成 user 但 jsonl 说是机器发起的，列轮首片段供人/AI 判稳定指纹，
   走 §二·五 的 `KNOWN_*` 循环并入白名单（并入要 bump IDX_SCHEMA，否则旧索引不重建）。

真值口径（jsonl 侧 `promptSource`，CC 自己写的）：
  typed / queued / suggestion_accepted → **human**（真人发起；suggestion_accepted 是人按下了
                                        补全建议，内容来自 CC 但**动作是人做的**，算真人）
  system / sdk                        → **machine**（CC 或 SDK 自己发起）
  轮首在 jsonl 里根本不存在              → **absent**（CC 没把这轮当对话事件记下来，机器侧证据）

用法：
    uv run python tools/origin_probe.py [--date YYYY-MM-DD] [--samples N]
"""
import argparse
import collections
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Windows 默认控制台是 GBK，编不出中文/符号 → print 抛 UnicodeEncodeError，脚本以非零码退出，
# **对账全过也会被读成失败**（260808 的老坑，src/ 自测与 tools/doc_audit 都有这段）。
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import capture_store  # noqa: E402
import classifier  # noqa: E402
import config as CFG  # noqa: E402

CAPTURES = CFG.CONFIG_DIR / "captures"
CC_PROJECTS = Path.home() / ".claude" / "projects"

HUMAN_SOURCES = {"typed", "queued", "suggestion_accepted"}
MACHINE_SOURCES = {"system", "sdk"}
# T2 文本匹配的最短比较长度。两侧的截断方式不同（wire 侧 `turn_user` 只存 TURN_USER_TEXT_LEN
# 字，jsonl 侧是全文），所以按"短的那个是长的那个的前缀"判，而不是等值判。
# **2 不是随便定的**：中文消息按字符算普遍很短，设 4 会把"检查"/"你好"这类整片丢掉（实测一次
# 丢了 1216 轮，占样本一半）。短消息前缀撞车的代价可接受——撞上的两侧本来都是真人轮。
TEXT_MATCH_MIN = 2
# 被打断的轮：CC 把中断标记连同**上一条没说完的消息**一起拼进下一次请求的用户文本，于是 wire
# 侧一条 turn_user 里可能塞着两三条用户消息，而 jsonl 侧它们是分开的行。按标记切段逐段匹配，
# 不切就会整片对不上（实测一个会话 808 轮全被误报成"jsonl 里没有"）。
INTERRUPT_MARKERS = ("[Request interrupted by user for tool use]",
                     "[Request interrupted by user]")


# ===== jsonl 侧：只读，不写回，不落原文 =====

def _msg_text(rec: dict) -> str:
    """jsonl 一行的用户可见文本。tool_result 型消息没有 text 块 → 返回空串。"""
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for blk in content:
            if isinstance(blk, dict) and blk.get("type") == "text":
                return blk.get("text") or ""
    return ""


def _is_turn_head(rec: dict) -> bool:
    """这行是不是「一轮的开头」——**按 CC 自己的定义判，不用 wire 侧那套启发式**。

    官方判据（260901 实测，349 个 jsonl / 70,267 行）：
      · `promptId`     —— 「轮」的官方 ID，一次发起及它引发的一切共享同一个（14,971 行带）
      · `promptSource` —— typed / queued / suggestion_accepted / system / sdk（718 行带）
      · `origin.kind`  —— human / task-notification / peer（716 行带）
    三者齐备的 user 行才是轮首；工具回传、图片说明、attachment 都只带 `promptId`，
    **共享发起者的那个 id**，CC 不给它们轮首标记。

    ⚠️ **这里原先写的是「user 且带真实文本」——与被测的 `classifier._is_turn_start` 是同一套
    启发式，等于拿被测对象当尺子。** 后果实测存在：CC 把「读图后的 `[Image: original …]` 说明」
    记成一条 `type:user` + `isMeta:true` 的行（文本非空、不是 reminder），旧判据会把它当轮首，
    于是 wire 侧同款误判在对账里**互相抵消**、落进 `unjoined` 而不是被报出来——260810 那次
    99.8% 一致率就是在这个前提下测出来的（它测的是「在我们自己切出来的轮上起源判得对不对」，
    切分本身没进对账）。改用官方位后，切分错误才会现形。
    """
    if rec.get("type") != "user" or not rec.get("promptId"):
        return False
    return bool(rec.get("promptSource") or rec.get("origin"))


def load_jsonl_side() -> dict:
    """扫 `~/.claude/projects/` 建三个索引。**只读**。

    - by_uuid:    uuid → 行（走 parentUuid 上溯用）
    - by_request: requestId → 行（JOIN 2 的主键，见 issue 260801）
    - by_session: sessionId → [(promptSource, 文本), …]，只收轮首 user 行（T2 兜底用）
    """
    by_uuid, by_request = {}, {}
    by_session = collections.defaultdict(list)
    heads = collections.defaultdict(list)      # sessionId -> [轮首行的关键字段]（新三档对账用）
    files = 0
    for f in CC_PROJECTS.rglob("*.jsonl"):
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue                      # 别人正在写/被锁，跳过而不是崩——探针不该干扰 CC
        files += 1
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue                  # CC 正在写这一行，半条 JSON。跳过，不当错误
            if rec.get("uuid"):
                by_uuid[rec["uuid"]] = rec
            if rec.get("requestId"):
                by_request.setdefault(rec["requestId"], rec)
            if _is_turn_head(rec) and rec.get("sessionId"):
                by_session[rec["sessionId"]].append(
                    (rec.get("promptSource"), _msg_text(rec).strip()))
                heads[rec["sessionId"]].append({
                    "prompt_id": rec.get("promptId"),
                    "source": rec.get("promptSource"),
                    "origin": (rec.get("origin") or {}).get("kind"),
                    "ts": rec.get("timestamp") or "",
                    "text": _msg_text(rec).strip()[:120],
                })
    return {"by_uuid": by_uuid, "by_request": by_request,
            "by_session": by_session, "heads": heads, "files": files}


def climb_to_turn_head(rec: dict, by_uuid: dict, max_hops: int = 500):
    """从 jsonl 的 assistant 行沿 parentUuid 上溯到**本轮的轮首 user 行**。

    不能只跳一级：一轮里 assistant 的直接父亲通常是 tool_result（promptSource 为空），
    要一路爬到带真实文本的那条 user 消息，才是「这轮谁发起的」的载体。
    """
    hops = 0
    while rec is not None and hops < max_hops:
        parent = rec.get("parentUuid")
        if not parent:
            return None
        rec = by_uuid.get(parent)
        hops += 1
        if rec is not None and _is_turn_head(rec):
            return rec
    return None


# ===== wire 侧：按天重放 build_dag，拿真正的「轮」而不是原始请求 =====

def load_wire_day(date: str) -> tuple[dict, dict, dict]:
    """读一天的全量录制 → (build_dag 结果, id → request-id, id → session_id)。

    用完整录制而非 `.idx.jsonl`：**索引里没有 request-id**（它是响应头，不是分类原料），
    而它正是 JOIN 2 的主键。顺带用 `classifier.index_record` 现算索引，保证与运行时同一份判据。
    session_id 也在这里单独收一份：`build_dag` 的节点只留渲染要用的字段，不透出它。
    """
    entries, rid_of, sess_of = [], {}, {}
    for entry, rid, rec in _iter_day(date):
        entries.append(entry)
        if entry.get("session_id"):
            sess_of[rec.get("id")] = entry["session_id"]
        if rid:
            rid_of[rec.get("id")] = rid
    return classifier.build_dag(entries), rid_of, sess_of


# ===== 三档对账共用的小工具 =====
# 轮首形状的归类前缀。**这不是判据，是给人看的归类**——判据在 jsonl 侧（promptId 有没有）。
# 放这里的唯一理由是把「多切出来的轮」按形状分组，好判下一步该动哪条规则。
PAYLOAD_PREFIXES = (
    ("[Image:", "工具回传的图片说明（Read 读图 / MCP 截图）"),
    ("Web page content:", "WebFetch 正文提炼"),
    ("[SUGGESTION MODE", "建议补全（CC 自发，jsonl 无 promptId）"),
    ("The user stepped away", "离开回顾（CC 自发）"),
    ("Perform a web search", "内部检索派发（CC 自发）"),
    ("[SYSTEM NOTIFICATION", "后台任务通知（jsonl 里**有** promptId，是真轮）"),
    ("<session>", "标题/命名请求（jsonl 记成 ai-title，不在对话 DAG）"),
    ("<local-command-caveat>", "斜杠命令（jsonl 不给 promptId）"),
    ("<command-", "斜杠命令（jsonl 不给 promptId）"),
    ("[Request interrupted by user", "打断标记"),
)


def _payload_bucket(text: str) -> str:
    t = (text or "").lstrip()
    for prefix, label in PAYLOAD_PREFIXES:
        if t.startswith(prefix):
            return f"{prefix} → {label}"
    return "(其它)"


def _extra_bucket(turn: dict) -> str:
    return _payload_bucket(turn.get("user_text") or "")


def _to_local(ts: str):
    """jsonl 时间戳是 UTC（`…Z`），wire 侧记的是本地朴素时间。不换算就永远对不上窗口。"""
    if not ts:
        return datetime.min
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min
    if t.tzinfo is None:
        return t
    return t.astimezone().replace(tzinfo=None)


def _window(turns: list) -> tuple:
    """一条泳道的录制时间窗，两头各放 30 秒——**必须放宽**：轮首请求与 jsonl 落盘有毫秒级到
    数秒的差，卡死边界会把首尾两轮切掉，差值看起来就凭空多两条。"""
    lo = min(datetime.fromisoformat(t["first_ts"]) for t in turns)
    hi = max(datetime.fromisoformat(t["last_ts"]) for t in turns)
    return lo - timedelta(seconds=30), hi + timedelta(seconds=30)


def _iter_day(date: str):
    """一天的录制 → (索引记录, request-id, 原始 record)。归属对账要 request-id，它只在响应头里。

    ⚠️ **走 `capture_store.iter_records` 而不是自己开 `{date}.jsonl`**：v0.4.15 起录制会被压实成
    `{date}.pack`，直接开裸文件的代码在压实之后**静默读到零条**——不报错、不为空提示，只是对账
    面积悄悄缩到"今天"一天。这正是 §二·五 记过的「全仓六处各自拼路径，压实之后各自失效」，
    探针也是那六处之一。
    """
    for rec in capture_store.iter_records(date):
        entry = classifier.index_record(rec)
        resp = rec.get("response") or {}
        headers = resp.get("headers_safe") or resp.get("headers") or {}
        rid = ""
        for k, v in headers.items():
            if k.lower() == "request-id" and v:
                rid = v
                break
        yield entry, rid, rec


# ===== 对账 A：归属（这条 wire 请求算不算主线）=====
# 判据来源不是我们自己定的结构位，是 CC 自己的行为：**它有没有把这条请求写进对话记录**。
# 用户 260901 的说法是「把这个环节拿开，整个上下文仍然是连贯的」——CC 的实现就是字面这样：
# 标题写成 `type:"ai-title"` 一行（无 uuid / parentUuid / promptId，根本不在对话 DAG 上），
# 安全审查 / count_tokens / 配额探测 / 压缩一条都不写。拿开它们，链是连的。
#
# ⚠️ 三类「jsonl 里没有」不是辅助信号，必须单列，否则会把主线报成辅助：
#   · 请求失败（429/5xx）—— CC 没等到响应，自然没得写（实测 84 条未命中里 51 条是这个）
#   · `decode_error` —— 我们自己的 gzip 截断，录制侧问题
#   · 子代理 —— 写在 `<session>/subagents/agent-<id>.jsonl`，`isSidechain=true`，不是"没写"

def reconcile_belong(dates: list, js: dict, samples: int) -> None:
    matrix = collections.Counter()          # (wire kind, 归属) -> 数
    orphans = collections.Counter()         # 判 main 但 jsonl 无 -> 轮首措辞归类
    orphan_ids = collections.defaultdict(list)
    joinable = 0
    for date in dates:
        for entry, rid, rec in _iter_day(date):
            if not rid:
                continue                    # 第三方网关不回 request-id，T1 join 不了，不入分母
            joinable += 1
            kind = classifier.classify_idx(entry)
            row = js["by_request"].get(rid)
            if row is not None:
                where = "sidechain" if row.get("isSidechain") else "dialog"
            elif entry.get("status") not in (200, None) or entry.get("has_error"):
                where = "req_failed"        # 失败，CC 无从记 —— 不是辅助证据
            elif entry.get("decode_error"):
                where = "decode_err"      # 我们自己的录制降级 —— 同上
            else:
                where = "absent"            # 真信号：请求成功了，CC 却没写进对话
            matrix[(kind, where)] += 1
            if kind in ("main", "subagent") and where == "absent":
                bucket = _payload_bucket(entry.get("last_user") or "")
                orphans[bucket] += 1
                if len(orphan_ids[bucket]) < samples:
                    orphan_ids[bucket].append((date, entry.get("id")))

    print(f"=== A. 归属对账（T1 request-id join，{joinable} 条可 join）===")
    print("    问的是：这条 wire 请求，CC 有没有把它写进对话记录？")
    cols = ("dialog", "sidechain", "absent", "req_failed", "decode_err")
    print(f"  {'wire kind':13s}" + "".join(f"{c:>12s}" for c in cols) + "   判定")
    for kind in classifier.KIND_ORDER:
        row = [matrix[(kind, c)] for c in cols]
        if not any(row):
            continue
        real = row[0] + row[1]
        verdict = "主线/子代理线" if real else ("辅助（不进对话）" if row[2] else "证据不足")
        print(f"  {kind:13s}" + "".join(f"{v:12d}" for v in row) + f"   {verdict}")
    if orphans:
        print(f"\n判 main/subagent 但 CC 没写进对话的（扣掉失败与解码错之后，**这里应该是 0**）：")
        for bucket, n in orphans.most_common():
            print(f"    {n:5d}  {bucket}")
            for date, rid_ in orphan_ids[bucket][:2]:
                print(f"           样本 {date} {rid_}")
    else:
        print("\n判 main/subagent 且成功的请求全部在 jsonl 对话记录里 —— 归属判据没有漏")


# ===== 对账 B：轮边界（这是不是新的一轮）=====
# 真值是 `promptId`：CC 只给「一次发起」分配它，工具回传/图片说明/插队消息共享发起者的那个 id。
# 所以「轮数」= 该时间窗内不同 promptId 的个数，不是「带文本的 user 消息条数」。

def reconcile_turns(dates: list, js: dict, samples: int) -> None:
    print("\n=== B. 轮边界对账（jsonl promptId × wire turns）===")
    print("    问的是：CC 给这一轮分配 promptId 了吗？没有 = 它不认为这是新的一轮。")
    tot_j = tot_w = 0
    rows, extra = [], collections.Counter()
    for date in dates:
        dag, rid_of, sess_of = load_wire_day(date)
        node_of = {n["id"]: n for n in dag.get("nodes", [])}
        lanes = collections.defaultdict(list)
        for t in dag.get("turns", []):
            lane = node_of.get(t["head"], {}).get("lane", "")
            if lane.startswith("agent-") or lane == "aux":
                continue
            lanes[lane].append(t)
        for lane, turns in lanes.items():
            sid = next((sess_of.get(t["head"]) for t in turns if sess_of.get(t["head"])), "")
            if not sid or sid not in js["heads"]:
                continue
            lo, hi = _window(turns)
            n_j = len({h["prompt_id"] for h in js["heads"][sid]
                       if lo <= _to_local(h["ts"]) <= hi})
            rows.append((date, lane, n_j, len(turns), sid))
            tot_j += n_j
            tot_w += len(turns)
            if len(turns) > n_j:
                # ⚠️ 这是**形状分布，不是逐条归因**：差值是泳道级的，wire 轮与 jsonl 轮没有
                # 1:1 的键可对（wire 侧没有 promptId）。所以只列"非真人形状"的轮首，
                # 真人形状的轮（`(其它)`）不进这张表——把它们算进来会让人误以为真人轮也多切了。
                for t in turns:
                    bucket = _extra_bucket(t)
                    if not bucket.startswith("(其它)"):
                        extra[bucket] += 1
    print(f"  {'日期':11s} {'泳道':12s} {'jsonl轮':>7s} {'wire轮':>7s} {'差':>5s}")
    for date, lane, n_j, n_w, sid in rows:
        flag = "" if n_w == n_j else ("  ←" if n_w > n_j else "  （录制窗口截断）")
        print(f"  {date:11s} {lane:12s} {n_j:7d} {n_w:7d} {n_w - n_j:+5d}{flag}")
    if rows:
        print(f"  {'合计':11s} {'':12s} {tot_j:7d} {tot_w:7d} {tot_w - tot_j:+5d}"
              f"   （{(tot_w - tot_j) / tot_j:+.0%}）" if tot_j else "")
    if extra:
        print("\nwire 多切出来的轮，按轮首形状归类：")
        for bucket, n in extra.most_common():
            if n:
                print(f"    {n:5d}  {bucket}")

# ===== 对账 C：轮起源（L2 启发式 × jsonl 真值）=====

def _norm(text: str) -> str:
    """压空白。两侧对同一句话的换行/缩进记法不同，不归一会整片对不上。"""
    return " ".join((text or "").split())


def _segments(text: str) -> list[str]:
    """wire 侧轮首文本 → 可与 jsonl 逐条比对的片段列表（按中断标记切）。"""
    parts = [_norm(text)]
    for marker in INTERRUPT_MARKERS:
        parts = [seg for part in parts for seg in part.split(marker)]
    return [p for p in (s.strip() for s in parts) if len(p) >= TEXT_MATCH_MIN]


def verdict_for_turn(turn: dict, session: str, rid: str, js: dict) -> tuple[str, str]:
    """一轮 → (真值判定, join 方式)。判定 ∈ human/machine/absent/unjoined。

    两条 join 链路都锚在双方各自的官方 id 上，只有 T2 的最后一公里是文本前缀匹配：
      T1（精确）  wire 响应头 request-id → jsonl requestId → parentUuid 上溯 → promptSource
      T2（兜底）  wire session 头 → jsonl 同 sessionId 的轮首集合 → 轮首文本前缀匹配
    T2 存在的理由：**只有官方上游会回 request-id**，第三方网关不回（实测 bigmodel 1247 条里
    73 条有、kimi 196 条 0 条有），没有 T2 就等于只能对账官方链路那一小片。
    """
    if rid:
        row = js["by_request"].get(rid)
        head = climb_to_turn_head(row, js["by_uuid"]) if row is not None else None
        if head is not None:
            src = head.get("promptSource")
            if src in HUMAN_SOURCES:
                return "human", "T1"
            if src in MACHINE_SOURCES:
                return "machine", "T1"
            return "unjoined", "T1-nosrc"  # 记了但没标来源，不硬判
        # request-id 在 jsonl 里查无此条 → **不能就此判 absent**，要落到 T2 再问一次。
        # 同一句话可能被发多次（打断后重来、上游 429 重试），CC 只对最终写进对话的那次留
        # requestId；拿"这一次没留"当"这轮不是人说的"，就会把真人轮报成候选伪轮（实测踩到）。

    text = (turn.get("user_text") or "").strip()
    if not session or not text:
        return "unjoined", "no-key"
    heads = js["by_session"].get(session)
    if not heads:
        return "unjoined", "session-absent"
    segs = _segments(text)
    if not segs:
        return "unjoined", "no-key"
    for src, cand in heads:
        cand = _norm(cand)
        if not any(cand.startswith(seg[:len(cand)]) or seg.startswith(cand[:len(seg)])
                   for seg in segs if cand):
            continue
        if src in HUMAN_SOURCES:
            return "human", "T2"
        if src in MACHINE_SOURCES:
            return "machine", "T2"
        return "unjoined", "T2-nosrc"
    # 会话在 jsonl 里、这一轮的文本不在 → CC 没把这轮当对话事件
    return "absent", "T2"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="识别体系 × CC jsonl 真值对账（三档：归属 / 轮边界 / 轮起源）")
    ap.add_argument("--date", help="只查某天 YYYY-MM-DD（默认全部录制日）")
    ap.add_argument("--samples", type=int, default=12, help="每类样本最多列几条")
    ap.add_argument("--mode", default="all", choices=("all", "belong", "turns", "origin"),
                    help="belong=这条请求算不算主线 / turns=轮边界 / origin=轮起源 / all=全跑")
    args = ap.parse_args()

    if not CC_PROJECTS.exists():
        print(f"找不到 CC 本地记录目录：{CC_PROJECTS}")
        return
    print(f"wire 录制目录: {CAPTURES}")
    print(f"CC 本地记录  : {CC_PROJECTS}（只读）")
    js = load_jsonl_side()
    print(f"jsonl: {js['files']} 个文件 / {len(js['by_uuid'])} 行带 uuid / "
          f"{len(js['by_request'])} 个 requestId / {len(js['by_session'])} 个会话有轮首\n")

    # 日期清单同理走 capture_store —— 自己 glob `*.jsonl` 会漏掉所有已压实的天
    dates = [args.date] if args.date else sorted(capture_store.list_dates())

    if args.mode in ("all", "belong"):
        reconcile_belong(dates, js, args.samples)
        print()
    if args.mode in ("all", "turns"):
        reconcile_turns(dates, js, args.samples)
        print()
    if args.mode not in ("all", "origin"):
        return

    matrix = collections.Counter()          # (wire origin, 真值) → 数
    how = collections.Counter()             # join 方式 → 数
    share = collections.Counter()           # origin → 数（只统计轮首成功的轮，见下）
    danger, radar, unjoined = [], [], collections.Counter()
    total = failed_head = 0

    for date in dates:
        dag, rid_of, sess_of = load_wire_day(date)
        node_of = {n["id"]: n for n in dag.get("nodes", [])}
        for turn in dag.get("turns", []):
            lane = node_of.get(turn["head"], {}).get("lane", "")
            if lane.startswith("agent-") or lane == "aux":
                continue                    # 子代理是 sidechain，CC 记在 subagents/ 另一套文件里
            if turn.get("partial"):
                continue                    # 残轮起源本就不明，不参与准确率
            total += 1
            truth, method = verdict_for_turn(
                turn, sess_of.get(turn["head"], ""),
                rid_of.get(turn["head"], ""), js)
            # 「jsonl 里没有」有三种成因，只有第一种是起源信号：
            #   ① CC 压根不把这轮当对话事件（真伪轮）
            #   ② 请求失败了（429/5xx）——CC 没等到响应，自然没写进 jsonl（260801 已列
            #      「被拒绝/失败的请求」为 wire 独占面）
            #   ③ 轮被用户打断——同理没落盘
            # 后两种是**录制侧独占**，不是"机器发起"，混进雷达就是纯噪声（实测 3 条 429
            # 重试被报成候选伪轮）。这里按 wire 侧自己就有的证据把它们摘出去。
            head = node_of.get(turn["head"], {})
            if truth == "absent":
                if turn.get("errors") or (head.get("status") not in (200, None)):
                    truth, method = "unjoined", method + "-failed"
                elif any(m in (turn.get("user_text") or "") for m in INTERRUPT_MARKERS):
                    truth, method = "unjoined", method + "-interrupted"
            origin = turn.get("origin") or "user"
            matrix[(origin, truth)] += 1
            how[method] += 1
            # 「伪轮占多少」的分母必须剔掉失败轮：上游 504/429 时 CC 会把同一句话重发几百次，
            # 每次都是一个 turn_start，于是一天能"长"出 2000 轮（实测 07-18：2049 轮里 2000 轮
            # 轮首是 504，真实话题只有三个）。不剔就是拿重试次数稀释占比。
            if head.get("status") == 200:
                share[origin] += 1
            else:
                failed_head += 1
            snippet = (turn.get("user_text") or "").strip()[:70].replace("\n", " ")
            if origin == "synthetic" and truth == "human":
                danger.append((date, method, snippet))
            elif origin == "user" and truth in ("machine", "absent"):
                radar.append((date, truth, method, snippet))
            elif truth == "unjoined":
                unjoined[method] += 1

    ok_turns = sum(share.values())
    print(f"=== C. 轮起源 · 0 分布（{ok_turns} 个轮首成功的主线轮；"
          f"另有 {failed_head} 轮轮首失败，多为重试风暴，不入分母）===")
    for origin, n in share.most_common():
        print(f"  {n:6d}  {origin:10s} {n / ok_turns:6.1%}" if ok_turns else "")

    print(f"\n=== 1. join 健康度（{total} 个完整主线轮）===")
    for method, n in how.most_common():
        print(f"  {n:6d}  {method}")
    if unjoined:
        print("  对不上的原因分布：" + ", ".join(f"{k}={v}" for k, v in unjoined.most_common()))

    print("\n=== 2. 混淆矩阵（启发式 origin × jsonl 真值）===")
    print(f"  {'':12s}{'human':>8s}{'machine':>9s}{'absent':>8s}{'unjoined':>10s}")
    for origin in ("user", "synthetic", "command", "sdk"):
        row = [matrix[(origin, t)] for t in ("human", "machine", "absent", "unjoined")]
        if not any(row):
            continue
        print(f"  {origin:12s}{row[0]:8d}{row[1]:9d}{row[2]:8d}{row[3]:10d}")
    judged = sum(v for (o, t), v in matrix.items() if t != "unjoined")
    agree = sum(v for (o, t), v in matrix.items()
                if (o in ("user", "command") and t == "human")
                or (o in ("synthetic", "sdk") and t in ("machine", "absent")))
    if judged:
        print(f"  判得动的 {judged} 轮里一致 {agree}（{agree / judged:.1%}）"
              "  ← command 归到 human（斜杠命令是真人敲的，只是前缀被 CC 改写）、"
              "sdk 归到 machine（程序驱动）")

    print(f"\n=== 3. 危险方向：判成 synthetic 但 jsonl 说是真人（{len(danger)} 例，"
          "**这里必须是 0**）===")
    for date, method, snippet in danger[:args.samples]:
        print(f"  [{date} {method}] {snippet!r}")
    if not danger:
        print("  0 例 —— fail-safe 方向未被打破")

    # 雷达分两档报，因为两种证据强度不一样：
    #   确证 —— 正面命中了一条 promptSource=system/sdk 的轮首，或 T1（request-id）在 jsonl 里查无此条
    #   存疑 —— T2 只是"这句话在该会话的轮首集合里没找到"，也可能是两侧文本记法不同导致的匹配失败
    strong = [r for r in radar if r[1] == "machine" or r[2].startswith("T1")]
    weak = [r for r in radar if r not in strong]
    print(f"\n=== 4. origin 雷达：判成 user 但 jsonl 说是机器发起"
          f"（确证 {len(strong)} 例 / 存疑 {len(weak)} 例）===")
    for label, group in (("确证", strong), ("存疑（T2 文本没匹配上，也可能是记法差异）", weak)):
        if not group:
            continue
        print(f"  -- {label} --")
        seen = collections.Counter()
        for date, truth, method, snippet in group:
            seen[f"[{method}/{truth}] {snippet!r}"] += 1
        for snippet, n in seen.most_common(args.samples):
            print(f"  {n:4d}  {snippet}")
    if not radar:
        print("  0 例 —— 白名单没漏（就这批数据而言）")
    else:
        print("\n  → 确证项判稳定指纹后并入 classifier.TURN_ORIGIN_SYNTHETIC，"
              "并 bump IDX_SCHEMA（改判据必须让旧索引重建）")


if __name__ == "__main__":
    main()
