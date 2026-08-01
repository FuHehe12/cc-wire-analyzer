"""泳道判别探针：把每条录制的「候选判别信号」摊开，核对 main / subagent 判别是否成立。

**规则已于 260725 由真实流量定案**（见 `issues/closed/260713_泳道主线子代理误判.md`）：
决定性信号是 CC 自己在 system block[0] 计费头里给的 `cc_is_subagent=true`
（实测 8/8 子代理带、7/7 非子代理不带），不是任何 system 措辞启发式。同批数据推翻了三个
原候选信号——子代理**复用**父 `X-Claude-Code-Session-Id`（只能当 lane 键）、
`cc_entrypoint` 被子代理继承、`general-purpose` 子代理**带** Agent 工具（「禁套娃」不成立）。

本脚本现在的用途是**回归核对**：换 CC 版本 / 换 harness / 出现新形态时，跑一遍看
权威位是否还在、分类是否还对得上。它不改任何分类逻辑，只把证据摆出来：

    uv run python tools/lane_probe.py                    # 今天
    uv run python tools/lane_probe.py --date 2026-07-14
    uv run python tools/lane_probe.py --date 2026-07-14 --json   # 喂给 AI 分析

采集姿势（260725 定型的零风险路径，不碰用户真 settings.json）：

    export CCWA_HOME='<临时目录>'                            # 录制/marker 落临时目录
    export CCWA_CLAUDE_SETTINGS="$CCWA_HOME/settings.json"   # 真 settings.json 的副本
    uv run python src/desktop.py serve
    claude -p "<会派生子代理的任务>" \
      --settings '{"env":{"ANTHROPIC_BASE_URL":"http://127.0.0.1:5051"}}'

被测 CC 用 `--settings` 把 BASE_URL 盖成代理（进程级 `ANTHROPIC_BASE_URL` 在 CC 2.1.220 实测
**被无视**——设死端口仍直连、录不到；必须走 `--settings`，它深度合并进真 settings，只盖 BASE_URL，
保留真凭据/模型）。所以被测 CC 用的是真配置（真 CLAUDE.md / 真模型 / 真凭据），只有 BASE_URL
被盖掉；工具读写的全是副本。**记 ground truth**（第几次派生、什么 agent、几点）。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import capture_store          # noqa: E402
import classifier             # noqa: E402

SPAWN_TOOLS = ("Task", "Agent", "dispatch_agent")


def _headers(rec: dict) -> dict:
    return (rec.get("request") or {}).get("headers_safe") or {}


def _session_id(rec: dict) -> tuple[str | None, str | None]:
    """(来自 header 的 session_id, 来自 metadata.user_id 的 session_id)。

    两个来源都记：如果子代理复用父会话 id，这个字段只能当 lane 用；
    如果子代理另起 id，它就直接是判别信号。"""
    h = {k.lower(): v for k, v in _headers(rec).items()}
    from_header = h.get("x-claude-code-session-id")
    from_meta = None
    body = (rec.get("request") or {}).get("body") or {}
    if isinstance(body, dict):
        uid = (body.get("metadata") or {}).get("user_id")
        if isinstance(uid, str):
            try:
                from_meta = json.loads(uid).get("session_id")
            except (json.JSONDecodeError, AttributeError):
                pass
    return from_header, from_meta


def _billing(rec: dict) -> dict:
    """system block[0] 的计费头：cc_version / cc_entrypoint。
    entrypoint 若在子代理请求里变值（如 agent/sdk），那就是最干脆的判别信号。"""
    body = (rec.get("request") or {}).get("body") or {}
    sysv = body.get("system") if isinstance(body, dict) else None
    if not isinstance(sysv, list) or not sysv:
        return {}
    t = (sysv[0].get("text") or "") if isinstance(sysv[0], dict) else ""
    if "billing-header" not in t:
        return {}
    out = {}
    for kv in t.split(":", 1)[-1].split(";"):
        if "=" in kv:
            k, v = kv.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _sys_blocks(rec: dict) -> list[str]:
    body = (rec.get("request") or {}).get("body") or {}
    sysv = body.get("system") if isinstance(body, dict) else None
    if isinstance(sysv, str):
        return [sysv]
    if isinstance(sysv, list):
        return [(b.get("text") or "") for b in sysv if isinstance(b, dict)]
    return []


def probe(rec: dict) -> dict:
    body = (rec.get("request") or {}).get("body") or {}
    if not isinstance(body, dict):
        body = {}
    names = [t.get("name") for t in (body.get("tools") or []) if isinstance(t, dict)]
    blocks = _sys_blocks(rec)
    sid_h, sid_m = _session_id(rec)
    users = classifier._user_texts(body)
    billing = _billing(rec)
    return {
        "id": rec.get("id"),
        "ts": rec.get("ts_start"),
        "kind_now": classifier.classify(rec),          # 当前分类器的判断
        # 权威判别位（260725 定案）：上游自报身份，优先于一切启发式
        "is_subagent": billing.get("cc_is_subagent") == "true",
        "session_header": sid_h,
        "session_meta": sid_m,
        "billing": billing,
        "model": body.get("model"),
        "max_tokens": body.get("max_tokens"),
        "n_tools": len(names),
        # 已推翻：general-purpose 子代理也带 Agent 工具，「有派生工具 ≈ 主线」不成立。
        # 保留此列仅为观察工具集形态（deferred tool 按需加载，同一主线 40→77 都出现过）。
        "spawn_tools": [n for n in names if n in SPAWN_TOOLS],
        "n_sys_blocks": len(blocks),
        "sys_head": (blocks[1][:70] if len(blocks) > 1 else (blocks[0][:70] if blocks else "")),
        # 身份指纹（blk[2]）：子代理实例分组用；措辞本身**不能**判 main/subagent
        "agent_fp": classifier._agent_fp(blocks),
        "first_user": (users[0][:90].replace("\n", " ") if users else ""),
        # 剥掉 system-reminder 后的开头 —— 子代理这里逐字就是派生 prompt（对齐锚点）
        "first_user_task": (classifier.strip_reminders(users[0])[:90].replace("\n", " ")
                            if users else ""),
        "n_messages": len(body.get("messages") or []),
    }


def spawns(recs: list[dict]) -> list[dict]:
    """所有响应里的派生调用（谁派生的、派了什么 prompt）。"""
    out = []
    for r in recs:
        for blk in ((r.get("response") or {}).get("content_blocks") or []):
            if blk.get("type") == "tool_use" and blk.get("name") in SPAWN_TOOLS:
                inp = blk.get("input") or {}
                out.append({
                    "by": r.get("id"), "at": r.get("ts_start"), "tool": blk.get("name"),
                    "subagent_type": inp.get("subagent_type") or inp.get("agent_type"),
                    "description": inp.get("description"),
                    "prompt": (inp.get("prompt") or ""),
                })
    return out


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="泳道判别探针：摊开 main/subagent 的候选信号")
    ap.add_argument("--date", help="YYYY-MM-DD，缺省=今天")
    ap.add_argument("--json", action="store_true", help="输出 JSON（喂给 AI 分析）")
    a = ap.parse_args()

    recs = capture_store.list_full(a.date)
    rows = [probe(r) for r in recs]
    sps = spawns(recs)

    # 派生 prompt ↔ 子代理首条 user 对齐。**必须先剥 system-reminder 再按子串搜**：
    # 子代理首条 user 也被注入 reminder，派生 prompt 被推到其后，旧的两头 startswith
    # 实测命中 0 条（260717 预测、260725 证实）。剥掉后开头逐字就是派生 prompt。
    aligned = {}
    for row, rec in zip(rows, recs):
        task = classifier.strip_reminders(
            (classifier._user_texts((rec.get("request") or {}).get("body") or {}) or [""])[0])
        for sp in sps:
            probe_str = sp["prompt"][:classifier.PROMPT_PROBE_LEN]
            if len(sp["prompt"]) >= classifier.PROMPT_MATCH_MIN and probe_str and probe_str in task:
                aligned[row["id"]] = sp["by"]
                break
    for row in rows:
        row["triggered_by"] = aligned.get(row["id"])

    if a.json:
        print(json.dumps({"rows": rows, "spawns": [
            {**s, "prompt": s["prompt"][:200]} for s in sps]}, ensure_ascii=False, indent=2))
        return

    print(f"记录数 {len(recs)}　派生次数 {len(sps)}\n")
    if not recs:
        print("这一天没有录制。先 `cc-wire-analyzer proxy start`，再开一个会派生子代理的 CC 会话。")
        return

    print("=== 逐条信号（is_sub = 上游权威位 cc_is_subagent）===")
    hdr = (f"{'id':13} {'kind_now':13} {'is_sub':7} {'session(hdr)':14} {'entry':8} {'tools':>5} "
           f"{'spawn':6} {'agent_fp':9} {'trig_by':13} first_user(剥 reminder)")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        sid = (r["session_header"] or r["session_meta"] or "-")[:12]
        entry = (r["billing"].get("cc_entrypoint") or "-")[:7]
        spawn = "Y" if r["spawn_tools"] else "·"
        trig = (r["triggered_by"] or "-")[:12]
        sub = "SUB" if r["is_subagent"] else "·"
        print(f"{r['id']:13} {r['kind_now']:13} {sub:7} {sid:14} {entry:8} {r['n_tools']:5} "
              f"{spawn:6} {(r['agent_fp'] or '-'):9} {trig:13} {r['first_user_task'][:40]}")

    print("\n=== 派生调用（ground truth 对照用）===")
    for s in sps:
        print(f"  {s['at']}  {s['by']} → {s['tool']}({s['subagent_type'] or '?'}) "
              f"「{(s['description'] or '')[:30]}」")
        print(f"      prompt: {s['prompt'][:80]!r}")
    if not sps:
        print("  （无）—— 这批数据里没有子代理派生，无法用来定判别规则。")

    print("\n=== 信号可分性 ===")
    for sig, get in [
        ("cc_is_subagent（权威位）", lambda r: "true" if r["is_subagent"] else "<absent>"),
        ("session_id（header）", lambda r: r["session_header"] or r["session_meta"] or "-"),
        ("cc_entrypoint", lambda r: r["billing"].get("cc_entrypoint") or "-"),
        ("agent_fp（blk[2] 指纹）", lambda r: r["agent_fp"] or "-"),
        ("有无派生工具（已推翻）", lambda r: "有 Agent/Task" if r["spawn_tools"] else "无"),
        ("system 块数", lambda r: str(r["n_sys_blocks"])),
        ("system 第二块开头", lambda r: r["sys_head"][:40] or "-"),
    ]:
        c = Counter(get(r) for r in rows)
        print(f"  {sig}:")
        for v, n in c.most_common(6):
            print(f"      [{n:3d}] {v}")

    # 核对表：权威位 × 当前分类。两者不一致就是回归信号（换 CC 版本/新形态时最该看这里）
    print("\n=== 核对：cc_is_subagent × 当前 kind ===")
    cross = defaultdict(Counter)
    for r in rows:
        cross["SUB" if r["is_subagent"] else "非 SUB"][r["kind_now"]] += 1
    for k, c in cross.items():
        print(f"  {k:8} {dict(c)}")
    mismatch = [r for r in rows if r["is_subagent"] and r["kind_now"] != "subagent"]
    if mismatch:
        print("  ⚠ 带权威位却没判成 subagent（分类器回归了）：",
              [r["id"] for r in mismatch])
    ghost = [r for r in rows if not r["is_subagent"] and r["kind_now"] == "subagent"]
    if ghost:
        print("  ℹ 无权威位但判成 subagent（靠 prompt 对齐改判，老录制/旧版本 CC 正常）：",
              [r["id"] for r in ghost])

    trig = [r for r in rows if r["triggered_by"]]
    print(f"\n=== prompt 对齐命中 {len(trig)} 条（剥 reminder 后子串匹配）===")
    for r in trig:
        print(f"  {r['id']} kind_now={r['kind_now']} is_sub={r['is_subagent']} "
              f"← 派生自 {r['triggered_by']}")
    if sps and not trig:
        print("  ⚠ 有派生调用但一条都没对齐 —— 检查 strip_reminders 是否还能露出派生 prompt")


if __name__ == "__main__":
    main()
