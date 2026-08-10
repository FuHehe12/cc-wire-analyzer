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
from pathlib import Path

# Windows 默认控制台是 GBK，编不出中文/符号 → print 抛 UnicodeEncodeError，脚本以非零码退出，
# **对账全过也会被读成失败**（260808 的老坑，src/ 自测与 tools/doc_audit 都有这段）。
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
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
    """这行是不是「一轮的开头」——user 且带真实文本。

    与 wire 侧 `classifier._is_turn_start` 是同一个判据的 jsonl 版本：工具循环回传的 user 消息
    只有 tool_result 块，不算轮首。
    """
    return rec.get("type") == "user" and bool(_msg_text(rec).strip())


def load_jsonl_side() -> dict:
    """扫 `~/.claude/projects/` 建三个索引。**只读**。

    - by_uuid:    uuid → 行（走 parentUuid 上溯用）
    - by_request: requestId → 行（JOIN 2 的主键，见 issue 260801）
    - by_session: sessionId → [(promptSource, 文本), …]，只收轮首 user 行（T2 兜底用）
    """
    by_uuid, by_request = {}, {}
    by_session = collections.defaultdict(list)
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
    return {"by_uuid": by_uuid, "by_request": by_request,
            "by_session": by_session, "files": files}


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
    f = CAPTURES / f"{date}.jsonl"
    entries, rid_of, sess_of = [], {}, {}
    if not f.exists():
        return {"turns": [], "nodes": []}, rid_of, sess_of
    with f.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            entry = classifier.index_record(rec)
            entries.append(entry)
            if entry.get("session_id"):
                sess_of[rec.get("id")] = entry["session_id"]
            headers = (rec.get("response") or {}).get("headers_safe") or {}
            for k, v in headers.items():
                if k.lower() == "request-id" and v:
                    rid_of[rec.get("id")] = v
                    break
    return classifier.build_dag(entries), rid_of, sess_of


# ===== 对账 =====

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
    ap = argparse.ArgumentParser(description="轮起源（L2）启发式 × CC jsonl 真值对账")
    ap.add_argument("--date", help="只查某天 YYYY-MM-DD（默认全部录制日）")
    ap.add_argument("--samples", type=int, default=12, help="每类样本最多列几条")
    args = ap.parse_args()

    if not CC_PROJECTS.exists():
        print(f"找不到 CC 本地记录目录：{CC_PROJECTS}")
        return
    print(f"wire 录制目录: {CAPTURES}")
    print(f"CC 本地记录  : {CC_PROJECTS}（只读）")
    js = load_jsonl_side()
    print(f"jsonl: {js['files']} 个文件 / {len(js['by_uuid'])} 行带 uuid / "
          f"{len(js['by_request'])} 个 requestId / {len(js['by_session'])} 个会话有轮首\n")

    dates = ([args.date] if args.date
             else sorted(p.name[:-6] for p in CAPTURES.glob("*.jsonl")
                         if ".idx." not in p.name))
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
    print(f"=== 0. 起源分布（{ok_turns} 个轮首成功的主线轮；"
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
