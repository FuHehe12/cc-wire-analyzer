"""泳道判别探针：把每条录制的「候选判别信号」摊开，用真实流量定 main / subagent 的规则。

为什么需要它（见 issues/open/260713_泳道主线子代理误判.md）：
当前 classifier 判主线只看一句 system 指纹（`"you are claude code"` 出现在前 500 字），
而 CC 的子代理很可能带着同一句 system 前缀 —— 那样每个子代理都会被判成 main，
再加上 build_dag() 里「已判 main 的不再改判」的短路，误判就永久锁死，
表现为用户看到的「很多子代理被视作了主线」。

**规则必须由真实流量定，不能拍脑袋。** 本脚本不改任何分类逻辑，只负责把证据摆出来：

    uv run python tools/lane_probe.py                    # 今天
    uv run python tools/lane_probe.py --date 2026-07-14
    uv run python tools/lane_probe.py --date 2026-07-14 --json   # 喂给 AI 分析

采集姿势（关键）：先起代理，再开一个**明确派生多个子代理**的 CC 会话（2~3 次，类型不同，
其中一次跑久一点），同时手记 ground truth（第几次派生、什么 agent、大约几点）。
opencode 也跑一轮做对称验证。
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
    return {
        "id": rec.get("id"),
        "ts": rec.get("ts_start"),
        "kind_now": classifier.classify(rec),          # 当前分类器的判断（可能是错的，这正是要查的）
        "session_header": sid_h,
        "session_meta": sid_m,
        "billing": _billing(rec),
        "model": body.get("model"),
        "max_tokens": body.get("max_tokens"),
        "n_tools": len(names),
        "spawn_tools": [n for n in names if n in SPAWN_TOOLS],   # 有派生工具 ≈ 主线（子代理禁套娃）
        "n_sys_blocks": len(blocks),
        "sys_head": (blocks[1][:70] if len(blocks) > 1 else (blocks[0][:70] if blocks else "")),
        "first_user": (users[0][:90].replace("\n", " ") if users else ""),
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

    # 派生 prompt ↔ 首条 user 文本 对齐（最强信号：逐字对齐就是铁证）
    aligned = {}
    for row, rec in zip(rows, recs):
        fu = row["first_user"]
        for sp in sps:
            p, b = sp["prompt"][:90].replace("\n", " "), fu
            if p and b and (p.startswith(b[:60]) or b.startswith(p[:60])):
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

    print("=== 逐条信号 ===")
    hdr = f"{'id':13} {'kind_now':13} {'session(hdr)':14} {'entry':7} {'tools':>5} {'spawn':6} {'blk':>3} {'trig_by':13} first_user"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        sid = (r["session_header"] or r["session_meta"] or "-")[:12]
        entry = (r["billing"].get("cc_entrypoint") or "-")[:6]
        spawn = "Y" if r["spawn_tools"] else "·"
        trig = (r["triggered_by"] or "-")[:12]
        print(f"{r['id']:13} {r['kind_now']:13} {sid:14} {entry:7} {r['n_tools']:5} {spawn:6} "
              f"{r['n_sys_blocks']:3} {trig:13} {r['first_user'][:40]}")

    print("\n=== 派生调用（ground truth 对照用）===")
    for s in sps:
        print(f"  {s['at']}  {s['by']} → {s['tool']}({s['subagent_type'] or '?'}) "
              f"「{(s['description'] or '')[:30]}」")
        print(f"      prompt: {s['prompt'][:80]!r}")
    if not sps:
        print("  （无）—— 这批数据里没有子代理派生，无法用来定判别规则。")

    print("\n=== 信号可分性 ===")
    for sig, get in [
        ("session_id（header）", lambda r: r["session_header"] or r["session_meta"] or "-"),
        ("cc_entrypoint", lambda r: r["billing"].get("cc_entrypoint") or "-"),
        ("有无派生工具", lambda r: "有 Agent/Task" if r["spawn_tools"] else "无"),
        ("system 块数", lambda r: str(r["n_sys_blocks"])),
        ("system 第二块开头", lambda r: r["sys_head"][:40] or "-"),
    ]:
        c = Counter(get(r) for r in rows)
        print(f"  {sig}:")
        for v, n in c.most_common(6):
            print(f"      [{n:3d}] {v}")

    # 交叉表：当前 kind × 有无派生工具 —— 如果 main 里出现「无派生工具」，那些极可能就是被误判的子代理
    print("\n=== 交叉：当前 kind × 有无派生工具 ===")
    cross = defaultdict(Counter)
    for r in rows:
        cross[r["kind_now"]]["有" if r["spawn_tools"] else "无"] += 1
    for k, c in cross.items():
        print(f"  {k:13} 有工具={c['有']:3}  无工具={c['无']:3}"
              + ("   ← main 却没有派生工具：疑似被误判的子代理" if k == "main" and c["无"] else ""))

    trig = [r for r in rows if r["triggered_by"]]
    print(f"\n=== prompt 对齐命中 {len(trig)} 条 ===")
    for r in trig:
        flag = "  ← 已被判成 main，当前 build_dag 永远不会改判它！" if r["kind_now"] == "main" else ""
        print(f"  {r['id']} kind_now={r['kind_now']} ← 派生自 {r['triggered_by']}{flag}")


if __name__ == "__main__":
    main()
