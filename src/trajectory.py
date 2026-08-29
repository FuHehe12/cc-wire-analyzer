# -*- coding: utf-8 -*-
"""轨迹八视图数据层：一条录制快照 → 八视图 payload（程序层全量 + 语义层可选）。

自 260828 原型管线产品化（原型的 build_factors.py + optimal.py + build_eight.py 三件；
原型目录已于 260829 收官删除——十一代演进与脚本对应关系见 research/原型演进史.md，
方法论与判据见 research/判据与算法.md）。

分层纪律（与原型一致）：
  事实层（节点/物料/血统/验证/阀门/债/子代理线/必要闭包）——本文件全程序算；
  语义层（阶段划分 + State Snapshot 八元组 + 步级简述）——模型写，
  程序校验覆盖（服务端 app.py 的 POST 管线），本文件只提供机械兜底
  （候选边界机械划分 + 程序简述标签），并在 payload 里标 semantic: "degraded"。

地基：全部主线请求的 blocks 并集（tool_use id / tool_result id / 文本 md5
三键去重）——autocompact 剪掉的前半段历史要从更早的请求里捞回来，
单看最长请求会丢一半 run。
"""
import hashlib
import json
import os
import re
from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta

import capture_store
import classifier
import snapshot_extract as SE

try:                       # 与 app.py 同一条取版本的路子（打包/源码两种形态都能取到）
    from _version import VERSION
except Exception:          # pragma: no cover
    VERSION = "dev"

_V = os.environ.get("CCWA_TRAJ_VERBOSE") == "1"


def _p(*a, **k):
    """诊断输出（原型脚本的 print 残留）。默认静音：serve 日志每次请求
    刷 5KB 诊断没意义；要看得设 CCWA_TRAJ_VERBOSE=1。"""
    if _V:
        print(*a, **k)


GAP_MIN = 120
DISPATCH = {"Task", "Agent", "dispatch_agent", "SendMessage"}

INTERP = {"python", "python3", "py", "node", "npx", "uv", "uvx", "bash", "sh", "pwsh",
          "powershell", "deno", "bun", "ruby", "perl"}
RO_CMDS = {"grep", "rg", "ls", "cat", "head", "tail", "find", "wc", "sed", "awk",
           "which", "md5sum", "type", "dir", "echo", "tree", "diff", "stat"}
FILE_RE = re.compile(r"[\w\-.\u4e00-\u9fff]+\.(py|mjs|js|ts|tsx|json|md|scd|svg|png|jpg|jpeg|"
                     r"html|css|txt|yaml|yml|toml|cfg|xml|sh|ps1|csv|log|output)$", re.I)
ASSERT_RE = re.compile(r"Traceback|AssertionError|\bFAIL(ED)?\b|\bPASS(ED)?\b|\bERROR\b|"
                       r"exit(ed)? (code|status)|\d+ passed|\d+ failed|断言|失败|通过", re.I)
TEST_CMD_RE = re.compile(r"pytest|npm (run )?test|jest|vitest|--check|assert|selftest|自检", re.I)


def _ts(s):
    return datetime.fromisoformat(s)


def _sec(a, b):
    return round((_ts(b) - _ts(a)).total_seconds()) if a and b else 0


def collect(session_id: str, date: str):
    """本会话的全部记录，按 main/subagent/security/other 分组（时序）。"""
    mains, subs, secs, others = [], [], [], []
    for rec in capture_store.iter_records(date):
        i = classifier.index_record(rec)
        if i.get("session_id") != session_id:
            continue
        k = classifier.classify_idx(i)
        row = (rec.get("ts_start") or "", rec, i, k)
        (mains if k == "main" else subs if k == "subagent"
         else secs if k == "security" else others).append(row)
    for lst in (mains, subs, secs, others):
        lst.sort(key=lambda x: x[0])
    return mains, subs, secs, others


def build_factors(mains, subs, secs, others, _sid, _date):
    """录制记录组 → (factors dict, details dict)。原型 build_factors.py 的主体。"""

    # ── 2. Raw Event：全量并集 ───────────────────────────────────────────────────
    def _blocks(rec):
        out = []
        for m in ((rec.get("request") or {}).get("body") or {}).get("messages") or []:
            c = m.get("content")
            if isinstance(c, str):
                out.append((m.get("role"), {"type": "text", "text": c}))
            elif isinstance(c, list):
                for b in c:
                    if isinstance(b, dict):
                        out.append((m.get("role"), b))
        return out


    def _msg_iter(rec):
        """(role, blocks) 一条条 message，保持原序。"""
        for m in ((rec.get("request") or {}).get("body") or {}).get("messages") or []:
            c = m.get("content")
            if isinstance(c, str):
                yield m.get("role"), [{"type": "text", "text": c}]
            elif isinstance(c, list):
                yield m.get("role"), [b for b in c if isinstance(b, dict)]


    def _bsig(role, b):
        t = b.get("type")
        if t == "tool_use":
            return "tu:" + str(b.get("id"))
        if t == "tool_result":
            return "tr:" + str(b.get("tool_use_id"))
        txt = b.get("text") or b.get("thinking") or ""
        return f"{t}:{role}:" + hashlib.md5(txt[:400].encode("utf-8", "replace")).hexdigest()[:12]


    # assistant 消息去重成「步」；user 消息里提取 tool_result 与真人发言
    seen_msg, seen_txt, steps, results, user_events = set(), set(), [], {}, []
    user_texts: list = []
    compact_summary_at = None
    for ri, (ts, rec, idx, _k) in enumerate(mains):
        for role, blocks in _msg_iter(rec):
            sig = role + "|" + "|".join(_bsig(role, b) for b in blocks)
            if role == "assistant":
                if sig in seen_msg:
                    continue
                seen_msg.add(sig)
                steps.append({
                    "ts": ts, "req": ri,
                    "thinking": "".join(b.get("thinking") or "" for b in blocks if b.get("type") == "thinking"),
                    "text": "".join(b.get("text") or "" for b in blocks if b.get("type") == "text"),
                    "tools": [b for b in blocks if b.get("type") == "tool_use"],
                })
            else:
                for b in blocks:
                    if b.get("type") == "tool_result":
                        results.setdefault(b.get("tool_use_id"), {"content": b.get("content"),
                                                                  "is_error": bool(b.get("is_error")),
                                                                  "ts": ts})
                    elif b.get("type") == "text":
                        txt = (b.get("text") or "").strip()
                        if not txt:
                            continue
                        # `<session>…</session>` 是同一段发言的包装版，剥掉后与裸版同哈希，
                        # 否则一句话会被算成两次发话。
                        norm = re.sub(r"^</?session>\s*|\s*</?session>$", "", txt).strip()
                        # **按文本自身去重**，不按整条 message 去重：同一段用户发言会随着
                        # tool_result 的增减出现在很多条 message 里，用 message 签名去重
                        # 会把它算 196 次（实测）。
                        h = hashlib.md5(norm[:400].encode("utf-8", "replace")).hexdigest()[:12]
                        if h in seen_txt:
                            continue
                        seen_txt.add(h)
                        # user 角色下的文本块绝大多数**不是人说的话**：状态通知、注入的规则、
                        # 本地命令回显、WebFetch 正文、图片标注、harness 提醒都挂在 user 名下。
                        # 实测 192 段里真人只有约 30 段，`<total_tokens>` 一项就占 158 段。
                        if norm.startswith("<total_tokens>"):
                            kind = "status"
                        elif norm.startswith("<system-reminder"):
                            kind = "reminder"
                        elif norm.startswith("This session is being continued"):
                            kind = "compact_summary"
                        elif norm.startswith("<local-command") or norm.startswith("<command-"):
                            kind = "harness"
                        elif norm.startswith("Web page content:") or norm.startswith("[Image:"):
                            kind = "payload"
                        elif (norm.startswith("Available agent types")
                              or norm.startswith("The task tools haven't been used")
                              or norm.startswith("This is a reminder")
                              or norm.startswith("[SYSTEM NOTIFICATION")
                              or norm.startswith("Note: ")):
                            kind = "harness"
                        else:
                            kind = "user"
                        # harness 把「打断插话」包了一层，剥掉之后它就是一句真发言
                        m_int = re.match(r"^The user sent a new message while you were working:\s*", norm)
                        if m_int:
                            norm, kind = norm[m_int.end():], "user"
                        # 同一句话的包装版与裸版（328 字 / 137 字）前缀不同、哈希不同，
                        # 用首 80 字包含关系再去一次重，否则一次发话被算两次。
                        if kind == "user":
                            if any(norm[:80] in p or p[:80] in norm for p in user_texts):
                                continue
                            user_texts.append(norm)
                        txt = norm
                        user_events.append({"ts": ts, "text": txt[:4000], "chars": len(txt),
                                            "kind": kind})
                        if kind == "compact_summary" and compact_summary_at is None:
                            compact_summary_at = ts
    _p(f"并集：assistant 步 {len(steps)}，tool_result {len(results)}，"
          f"user 侧文本 {len(user_events)} {dict(Counter(u['kind'] for u in user_events))}")

    # ── 3. Action：动词/物料/结果（沿用产品 verb_of / target_of / result_digest） ──
    INTERP = {"python", "python3", "py", "node", "npx", "uv", "uvx", "bash", "sh", "pwsh",
              "powershell", "deno", "bun", "ruby", "perl"}
    RO_CMDS = {"grep", "rg", "ls", "cat", "head", "tail", "find", "wc", "sed", "awk",
               "which", "md5sum", "type", "dir", "echo", "tree", "diff", "stat"}
    FILE_RE = re.compile(r"[\w\-.\u4e00-\u9fff]+\.(py|mjs|js|ts|tsx|json|md|scd|svg|png|jpg|jpeg|"
                         r"html|css|txt|yaml|yml|toml|cfg|xml|sh|ps1|csv|log|output)$", re.I)
    ASSERT_RE = re.compile(r"Traceback|AssertionError|\bFAIL(ED)?\b|\bPASS(ED)?\b|\bERROR\b|"
                           r"exit(ed)? (code|status)|\d+ passed|\d+ failed|断言|失败|通过", re.I)
    TEST_CMD_RE = re.compile(r"pytest|npm (run )?test|jest|vitest|--check|assert|selftest|自检", re.I)


    def refine_target(target: str, cmd: str) -> str:
        if not target.startswith("$"):
            return target
        name = target[1:]
        if FILE_RE.search(name) or (len(name) > 2 and name):
            return target
        if not cmd:
            return target
        c = re.sub(r'^\s*cd\s+("[^"]*"|\'[^\']*\'|\S+)\s*&&\s*', "", cmd.strip())
        toks = [t.strip('"\'') for t in c.split() if t.strip() and not t.startswith("-")]
        for t in toks:
            base = t.replace("\\", "/").rsplit("/", 1)[-1]
            if FILE_RE.search(base):
                return base
            if base.lower() in INTERP:
                continue
        return "$" + (toks[0].replace("\\", "/").rsplit("/", 1)[-1] if toks else name)


    def mat_class(t: str) -> str:
        if t == "«内联脚本»":
            return "inline"
        if t.startswith("$"):
            return "cmd"
        if "*" in t or "?" in t:
            return "pattern"
        if t.startswith("http"):
            return "url"
        base = t.replace("\\", "/").rsplit("/", 1)[-1]
        return "file" if ("." in base or "/" in t or "\\" in t) else "other"


    actions = []
    for si, s in enumerate(steps):
        for b in s["tools"]:
            inp = b.get("input") or {}
            cmd = inp.get("command") if isinstance(inp.get("command"), str) else ""
            tool = b.get("name") or ""
            res = results.get(b.get("id")) or {}
            raw = res.get("content")
            raw_txt = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False) if raw else ""
            actions.append({
                "i": len(actions), "step": si, "id": b.get("id"), "tool": tool,
                "verb": SE.verb_of(tool), "target": refine_target(SE.target_of(inp), cmd),
                "cmd": cmd[:400], "args": SE._brief_args(inp)[:160],
                "digest": SE.result_digest(raw, bool(res.get("is_error")))[:120],
                "error": bool(res.get("is_error")),
                "ts": s["ts"], "res_ts": res.get("ts") or "",
                "raw_len": len(raw_txt),
                "assertive": bool(raw_txt and ASSERT_RE.search(raw_txt[:2000]))
                or bool(cmd and TEST_CMD_RE.search(cmd)),
                "prompt": (inp.get("prompt") or inp.get("message") or "")[:600] if tool in DISPATCH else "",
            })
    _p(f"动作 {len(actions)}（有结果 {sum(1 for a in actions if a['digest'])}，"
          f"失败 {sum(1 for a in actions if a['error'])}，判定性结果 {sum(1 for a in actions if a['assertive'])}）")

    # ── 4. Node：合并纯执行步 ────────────────────────────────────────────────────
    acts_of_step = defaultdict(list)
    for a in actions:
        acts_of_step[a["step"]].append(a)
    nodes = []
    for si, s in enumerate(steps):
        acts = acts_of_step.get(si) or []
        bare = not s["thinking"].strip() and not s["text"].strip()
        if bare and nodes and acts:
            nodes[-1]["steps"].append(si)
            nodes[-1]["acts"] += acts
            continue
        nodes.append({"i": len(nodes), "steps": [si], "acts": list(acts), "ts": s["ts"],
                      "think": len(s["thinking"]), "reply": s["text"][:240], "req": s["req"]})

    OP_OF = {"write": "write", "read": "read", "search": "read", "fetch": "read",
             "exec": "run", "delegate": "delegate"}
    written = set()
    for n in nodes:
        n["error"] = any(a["error"] for a in n["acts"])
        for a in n["acts"]:
            a["op"] = OP_OF.get(a["verb"], "run")
            a["clears"] = bool(a["target"] in written and a["op"] in ("read", "run"))
            if a["op"] == "write" and mat_class(a["target"]) == "file":
                written.add(a["target"])
        n["mats"] = sorted({a["target"] for a in n["acts"] if a["target"]})
        n["changes"] = sorted({a["target"] for a in n["acts"]
                               if a["op"] == "write" and a["target"]})
        n["reads"] = sorted({a["target"] for a in n["acts"]
                             if a["op"] in ("read", "run") and a["target"]})
        n["verified"] = sorted({a["target"] for a in n["acts"] if a["clears"]})
        verbs = {a["op"] for a in n["acts"]}
        n["kind"] = ("think" if not n["acts"] else "delegate" if "delegate" in verbs
                     else "verify" if n["verified"] else "advance" if n["changes"] or "run" in verbs
                     else "perceive")
        n["pattern"] = "·".join(a["op"][0] for a in n["acts"][:8]) or "t"
    _p(f"节点 {len(nodes)}；类别 {dict(Counter(n['kind'] for n in nodes))}")

    # ── 5. Cost：请求 k 的响应生成了首见于请求 k+1 的那批步 ───────────────────────
    req_meta = []
    for ri, (ts, rec, idx, _k) in enumerate(mains):
        r = rec.get("response") or {}
        u = r.get("usage") or {}
        req_meta.append({"i": ri, "ts": ts, "ttft": r.get("ttft_ms") or 0,
                         "total_ms": r.get("total_ms") or 0,
                         "in": u.get("input_tokens") or 0, "out": u.get("output_tokens") or 0,
                         "cache_read": u.get("cache_read_input_tokens") or 0,
                         "stop": r.get("stop_reason") or "", "model": idx.get("model") or ""})
    for n in nodes:
        g = max(n["req"] - 1, 0)                    # 生成它的是前一条请求
        m = req_meta[g]
        n["cost"] = {"out": m["out"], "in": m["in"], "cache_read": m["cache_read"],
                     "ttft": m["ttft"], "total_ms": m["total_ms"], "req": g}
    tok_out = sum(m["out"] for m in req_meta)
    tok_in = sum(m["in"] for m in req_meta)
    cache = sum(m["cache_read"] for m in req_meta)
    sub_tok = 0
    for ts, rec, idx, _k in subs:
        u = ((rec.get("response") or {}).get("usage") or {})
        sub_tok += u.get("output_tokens") or 0
    sec_ms = sum((rec.get("response") or {}).get("total_ms") or 0 for _, rec, _, _ in secs)
    _p(f"成本：主线 out {tok_out:,} / in {tok_in:,} / cache_read {cache:,}；"
          f"子代理 out {sub_tok:,}；安检在途 {sec_ms/1000:.0f} 秒")

    # ── 6. 物料 + 血统 DAG ───────────────────────────────────────────────────────
    mats = {}
    for n in nodes:
        for a in n["acts"]:
            t = a["target"]
            if not t or a["op"] == "delegate":
                continue
            m = mats.setdefault(t, {"name": t, "class": mat_class(t), "events": [], "first": n["i"],
                                    "last": n["i"], "writes": 0, "reads": 0, "runs": 0,
                                    "clears": 0, "fails": 0, "assertive": 0})
            m["events"].append({"i": n["i"], "op": a["op"], "clears": a["clears"], "error": a["error"],
                                "assertive": a["assertive"], "tool": a["tool"], "ts": n["ts"],
                                "digest": a["digest"]})
            m["last"] = n["i"]
            m[{"write": "writes", "read": "reads", "run": "runs"}.get(a["op"], "reads")] += 1
            m["clears"] += 1 if a["clears"] else 0
            m["fails"] += 1 if a["error"] else 0
            m["assertive"] += 1 if a["assertive"] else 0

    # 血统边：同节点内「读到的」→「写出的」；本节点没读过就回看前一个节点
    # 取证窗口：一次写入的「来源」是它**之前若干个节点里读到的东西**，不只是同一个节点。
    # 只看同节点时血统边只有 38 条、无源产物 11 件——那不是真的无源，是窗口太窄
    # （读完想一想再写，是最常见的形态）。窗口取 5 个节点，且不跨越用户发话（新指令 = 新语境）。
    PROV_WIN = 5
    prov, orphan_reads, sourceless = [], set(), []
    user_node_set = set()
    for n in nodes:
        outs = [t for t in n["changes"] if mat_class(t) == "file"]
        if not outs:
            continue
        lo = max(0, n["i"] - PROV_WIN)
        ins, seen_in = [], set()
        for j in range(n["i"], lo - 1, -1):
            for t in nodes[j]["reads"]:
                if mat_class(t) in ("file", "url") and t not in seen_in:
                    seen_in.add(t)
                    ins.append((t, j))
            if len(ins) >= 6:
                break
        if not ins:
            for o in outs:
                sourceless.append({"target": o, "node": n["i"], "ts": n["ts"]})
            continue
        for o in outs:
            for s, j in ins:
                if s != o:
                    prov.append({"from": s, "to": o, "node": n["i"], "src_node": j,
                                 "dist": n["i"] - j})
    used_as_src = {e["from"] for e in prov}
    for name, m in mats.items():
        if m["class"] in ("file", "url") and not m["writes"] and name not in used_as_src:
            orphan_reads.add(name)
    _p(f"血统边 {len(prov)}；无源产物 {len(sourceless)}；孤儿证据 {len(orphan_reads)}")

    # ── 7. 验证等级 L0–L4 ────────────────────────────────────────────────────────
    # L0 写完即走 / L1 写后回读 / L2 重跑该产物 / L3 结果里有判定 / L4 外部交叉核对
    # 子代理**读过或跑过**才算外部核对；它自己写一遍不是核对（四条线都写过 CLAUDE.md，
    # 按「碰过」算会把 9 件产物误判成 L4）。
    sub_touch = defaultdict(list)
    for ts, rec, idx, _k in subs:
        for m2 in ((rec.get("request") or {}).get("body") or {}).get("messages") or []:
            for b in (m2.get("content") if isinstance(m2.get("content"), list) else []):
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    inp2 = b.get("input") or {}
                    t = refine_target(SE.target_of(inp2), inp2.get("command") or "")
                    if t and OP_OF.get(SE.verb_of(b.get("name") or ""), "run") in ("read", "run"):
                        sub_touch[t].append(ts)
    verify = []
    for name, m in mats.items():
        if m["class"] != "file" or not m["writes"]:
            continue
        last_w = max(e["i"] for e in m["events"] if e["op"] == "write")
        after = [e for e in m["events"] if e["i"] > last_w or (e["i"] == last_w and e["op"] != "write")]
        lvl, why = 0, "写完即走"
        if any(e["op"] == "read" for e in after):
            lvl, why = 1, "写后回读"
        if any(e["op"] == "run" for e in after):
            lvl, why = 2, "写后重跑"
        if any(e["assertive"] for e in after):
            lvl, why = 3, "结果里有判定（PASS/Traceback/退出码）"
        w_ts = [e["ts"] for e in m["events"] if e["op"] == "write"]
        if name in sub_touch and w_ts and any(t > max(w_ts) for t in sub_touch[name]):
            lvl, why = 4, "子代理事后核对"
        ver_i = min([e["i"] for e in after], default=None)
        verify.append({"name": name, "level": lvl, "why": why, "last_write": last_w,
                       "verified_at": ver_i, "age_nodes": (ver_i - last_w) if ver_i else None,
                       "age_seconds": _sec(nodes[last_w]["ts"], nodes[ver_i]["ts"]) if ver_i else None,
                       "writes": m["writes"], "fails": m["fails"]})
    verify.sort(key=lambda v: (v["level"], -v["writes"]))
    _p("验证等级分布:", dict(Counter(v["level"] for v in verify)),
          f"（产物 {len(verify)} 件）")

    # ── 8. 阀门 ─────────────────────────────────────────────────────────────────
    valves = []
    for ts, rec, idx, _k in secs:
        v = idx.get("sec_verdict") or {}
        a = idx.get("sec_action") or {}
        arg = (a.get("arg") or "")
        valves.append({"kind": "security", "ts": ts, "blocked": bool(v.get("blocked")),
                       "category": v.get("category") or "", "reason": (v.get("reason") or "")[:300],
                       "arg": arg[:220], "ms": (rec.get("response") or {}).get("total_ms") or 0})
    for n in nodes:
        for a in n["acts"]:
            if a["error"]:
                valves.append({"kind": "tool_error", "ts": n["ts"], "node": n["i"],
                               "target": a["target"], "tool": a["tool"], "detail": a["digest"][:160]})
    for u in user_events:
        valves.append({"kind": u["kind"], "ts": u["ts"], "chars": u["chars"],
                       "detail": u["text"][:300]})
    for ts, rec, idx, k in others:
        valves.append({"kind": k, "ts": ts, "detail": f"{k} 请求"})
    for n in nodes:
        for a in n["acts"]:
            if a["op"] == "delegate":
                valves.append({"kind": "delegate", "ts": n["ts"], "node": n["i"],
                               "target": a["target"], "detail": a["prompt"][:200], "tool": a["tool"]})
    valves.sort(key=lambda v: v["ts"])
    vk = Counter(v["kind"] for v in valves)
    blocked = [v for v in valves if v["kind"] == "security" and v["blocked"]]
    _p(f"阀门事件 {len(valves)}：{dict(vk)}；其中安检拦截 {len(blocked)} 次")

    # 安检 → 节点：按命令前缀匹配
    for v in valves:
        if v["kind"] != "security":
            continue
        arg = v["arg"]
        probe = re.sub(r"^(PowerShell|Bash|powershell|bash)\s+", "", arg)[:48]
        v["node"] = None
        if probe:
            for n in nodes:
                if any(probe[:40] in (a["cmd"] or "") for a in n["acts"]):
                    v["node"] = n["i"]
                    break

    # 返工回路：同一物料连续写、中间没有清偿；以及被拦后对同一目标的连试
    loops = []
    for name, m in mats.items():
        if m["class"] != "file":
            continue
        seq = [e for e in m["events"] if e["op"] in ("write", "read", "run")]
        run = []
        for e in seq:
            if e["op"] == "write":
                run.append(e)
            elif run and len(run) >= 2:
                loops.append({"target": name, "from": run[0]["i"], "to": run[-1]["i"],
                              "writes": len(run), "exit": e["i"], "kind": "rework"})
                run = []
            else:
                run = []
        if len(run) >= 2:
            loops.append({"target": name, "from": run[0]["i"], "to": run[-1]["i"],
                          "writes": len(run), "exit": None, "kind": "rework_open"})
    if blocked:
        loops.append({"target": "外部仓库构建", "kind": "valve_loop",
                      "from": None, "to": None, "writes": len(blocked),
                      "ts_from": blocked[0]["ts"], "ts_to": blocked[-1]["ts"],
                      "seconds": _sec(blocked[0]["ts"], blocked[-1]["ts"]),
                      "attempts": [b["arg"][:90] for b in blocked]})
    _p(f"返工回路 {len(loops)}（其中开放 {sum(1 for l in loops if l['kind']=='rework_open')}）")

    # ── 9. 约束（Constraint）：注入源 ────────────────────────────────────────────
    best = max(mains, key=lambda x: len(((x[1].get("request") or {}).get("body") or {}).get("messages") or []))[1]
    constraints = []
    for s in SE.instruction_sources(best):
        constraints.append({"where": s.get("where"), "role": s.get("role"), "chars": s.get("chars"),
                            "head": (s.get("head") or "")[:160], "repeats": s.get("repeats")})
    _p(f"约束注入源 {len(constraints)} 处，合计 {sum(c['chars'] or 0 for c in constraints):,} 字")

    # ── 10. 停顿与模板 ──────────────────────────────────────────────────────────
    gaps = []
    for i in range(len(nodes) - 1):
        d = _sec(nodes[i]["ts"], nodes[i + 1]["ts"])
        if d >= GAP_MIN:
            gaps.append({"from": i, "to": i + 1, "seconds": d})
    gaps.sort(key=lambda g: -g["seconds"])
    tpl = Counter(n["pattern"] for n in nodes)
    templates = [{"pattern": p, "n": c,
                  "fpy": round(sum(1 for n in nodes if n["pattern"] == p and not n["error"]) / c, 3),
                  "kinds": dict(Counter(n["kind"] for n in nodes if n["pattern"] == p))}
                 for p, c in tpl.most_common(18)]
    _p("模板 top5:", [(t["pattern"], t["n"], t["fpy"]) for t in templates[:5]])

    # ── 11. 未验债（判据与产品 _turn_facts 一致） ────────────────────────────────
    debt, pending = [], {}
    for n in nodes:
        for a in n["acts"]:
            t = a["target"]
            if not t or mat_class(t) != "file":
                continue
            if a["op"] == "write":
                pending[t] = n["i"]
            elif t in pending:
                pending.pop(t, None)
        debt.append({"i": n["i"], "n": len(pending)})
    _p(f"未验债：峰 {max(d['n'] for d in debt)}，终 {len(pending)}")

    # ── 12. 候选阶段边界（程序出候选，模型在 snapshot_run.py 里取舍） ────────────
    raw_cand = defaultdict(list)
    for n in nodes:
        if n["kind"] == "delegate":
            raw_cand[n["i"]].append("委派")
        if n["i"] and debt[n["i"]]["n"] < debt[n["i"] - 1]["n"]:
            raw_cand[n["i"]].append("清偿")
        if any(g["from"] == n["i"] and g["seconds"] >= 600 for g in gaps):
            raw_cand[n["i"]].append("长停顿")
    user_nodes = []
    for u in user_events:
        if u["kind"] != "user":
            continue
        nx = next((n["i"] for n in nodes if n["ts"] >= u["ts"]), None)
        if nx is not None:
            user_nodes.append(nx)
            raw_cand[nx].append("用户发话")
    for v in valves:
        if v["kind"] == "security" and v.get("blocked") and v.get("node") is not None:
            raw_cand[v["node"]].append("被拦截")
    # 相距 ≤2 个节点的候选并成一处：候选给模型挑，不是越多越好——
    # 第一版 224 个候选（几乎每个节点一个）等于没有候选。
    cand = []
    for at in sorted(raw_cand):
        if cand and at - cand[-1]["at"] <= 2:
            cand[-1]["why"] = sorted(set(cand[-1]["why"] + raw_cand[at]))
            continue
        cand.append({"at": at, "why": sorted(set(raw_cand[at]))})
    _p(f"候选边界 {len(cand)} 处（合并前 {len(raw_cand)}）")

    # ── 12b. 子代理线重建 ────────────────────────────────────────────────────────
    # 前八代只把 `subs` 用来累 token 和判 L4，子代理**自己干了什么一步都没抽出来**。
    # 分组判据是这里唯一的技术点：dsh 的 `Agent` 是 **fork**，子代理继承父上下文，
    # 四条线共享 fork 点之前的 148 个 tool_use id——按「id 重叠」贪心分组会把 175 条
    # 请求合成 1 条线（实测）。正确判据是**前缀增长**：老 lane 的 id 集合必须是
    # 当前请求 id 集合的子集，才算同一条线继续长。产品的 `_subagent_lanes` 在这份
    # 录制上返回 0 条，同一个坑。
    def _tu_ids(rec):
        return {b.get("id") for _r, blocks in _msg_iter(rec) for b in blocks
                if b.get("type") == "tool_use"}


    sub_lanes = []
    for ts, rec, idx, _k in subs:
        s = _tu_ids(rec)
        hit = None
        for L in sub_lanes:
            if L["ids"] <= s and (hit is None or len(L["ids"]) > len(hit["ids"])):
                hit = L
        if hit is None:
            sub_lanes.append({"ids": s, "rows": [(ts, rec, idx)]})
        else:
            hit["ids"], _ = s, hit["rows"].append((ts, rec, idx))

    sub_out_lanes = []
    for li, L in enumerate(sub_lanes):
        rows = L["rows"]
        # fork 继承的父上下文也在 messages 里：不剔掉的话，一条 50 请求的子线会抽出
        # 113 个「节点」——那是父会话的历史，不是子代理干的活。判据是**首条请求里
        # 出现过的 assistant 消息一律是继承来的**（首条请求 = 继承前缀 + 任务提示词）。
        prefix = set()
        for role, blocks in _msg_iter(rows[0][1]):
            if role == "assistant":
                prefix.add(role + "|" + "|".join(_bsig(role, b) for b in blocks))
        s_steps, s_res, s_seen = [], {}, set(prefix)
        for ri, (ts, rec, idx) in enumerate(rows):
            for role, blocks in _msg_iter(rec):
                sig = role + "|" + "|".join(_bsig(role, b) for b in blocks)
                if role == "assistant":
                    if sig in s_seen:
                        continue
                    s_seen.add(sig)
                    s_steps.append({
                        "ts": ts, "req": ri,
                        "thinking": "".join(b.get("thinking") or "" for b in blocks
                                            if b.get("type") == "thinking"),
                        "text": "".join(b.get("text") or "" for b in blocks if b.get("type") == "text"),
                        "tools": [b for b in blocks if b.get("type") == "tool_use"],
                    })
                else:
                    for b in blocks:
                        if b.get("type") == "tool_result":
                            s_res.setdefault(b.get("tool_use_id"),
                                             {"content": b.get("content"),
                                              "is_error": bool(b.get("is_error")), "ts": ts})
        # 与主线同一套 Action/Node 抽象（同样的 verb_of / target_of / 合并纯执行步）
        s_nodes, s_written = [], set()
        for si, s in enumerate(s_steps):
            acts = []
            for b in s["tools"]:
                inp = b.get("input") or {}
                cmd = inp.get("command") if isinstance(inp.get("command"), str) else ""
                res = s_res.get(b.get("id")) or {}
                raw = res.get("content")
                raw_txt = (raw if isinstance(raw, str)
                           else json.dumps(raw, ensure_ascii=False) if raw else "")
                verb = SE.verb_of(b.get("name") or "")
                acts.append({"id": b.get("id"), "tool": b.get("name") or "", "verb": verb,
                             "op": OP_OF.get(verb, "run"),
                             "target": refine_target(SE.target_of(inp), cmd),
                             "cmd": cmd[:400], "args": SE._brief_args(inp)[:160],
                             "digest": SE.result_digest(raw, bool(res.get("is_error")))[:120],
                             "error": bool(res.get("is_error")), "raw_len": len(raw_txt),
                             "assertive": bool(raw_txt and ASSERT_RE.search(raw_txt[:2000]))
                             or bool(cmd and TEST_CMD_RE.search(cmd))})
            bare = not s["thinking"].strip() and not s["text"].strip()
            if bare and s_nodes and acts:
                s_nodes[-1]["steps"].append(si)
                s_nodes[-1]["acts"] += acts
                continue
            s_nodes.append({"i": len(s_nodes), "steps": [si], "acts": acts, "ts": s["ts"],
                            "think": len(s["thinking"]), "reply": s["text"][:240], "req": s["req"]})
        for n in s_nodes:
            n["error"] = any(a["error"] for a in n["acts"])
            for a in n["acts"]:
                a["clears"] = bool(a["target"] in s_written and a["op"] in ("read", "run"))
                if a["op"] == "write" and mat_class(a["target"]) == "file":
                    s_written.add(a["target"])
            n["changes"] = sorted({a["target"] for a in n["acts"] if a["op"] == "write" and a["target"]})
            n["reads"] = sorted({a["target"] for a in n["acts"]
                                 if a["op"] in ("read", "run") and a["target"]})
            n["verified"] = sorted({a["target"] for a in n["acts"] if a["clears"]})
            n["kind"] = ("think" if not n["acts"] else "verify" if n["verified"]
                         else "advance" if n["changes"] else "perceive")
        # 归属：时间上最近的、不晚于本线起点的那个主线派发节点
        # 派发的 tool_use 与子线首条请求几乎同秒（实测差 22~880 毫秒，方向两边都有），
        # 用严格的 `ts <= t_start` 会整体错位一格——留 5 秒容差。
        t_start = rows[0][0]
        lim = (_ts(t_start) + timedelta(seconds=5)).isoformat()
        disp = None
        for n in nodes:
            if n["kind"] == "delegate" and n["ts"] <= lim:
                disp = n["i"]
        task = ""
        if disp is not None:
            for a in nodes[disp]["acts"]:
                if a["op"] == "delegate":
                    task = a["target"] or a["tool"]
        if task in ("SendMessage", ""):
            # SendMessage 唤醒的线：任务名回溯到最近一次 Agent 派发的任务
            for n in reversed(nodes[:disp or 0]):
                for a in n["acts"]:
                    if a["op"] == "delegate" and a["target"] and a["target"] != "SendMessage":
                        task = a["target"]
                        break
                if task and task != "SendMessage":
                    break
        out_tok = sum((r.get("response") or {}).get("usage", {}).get("output_tokens") or 0
                      for _t, r, _i in rows)
        wrote = sorted({t for n in s_nodes for t in n["changes"]})
        # 回传：子代理写过、且主线在它返回之后碰过的物料。两边 target 形态不同
        #（子线常是裸文件名、主线是相对路径），按 basename 匹配而不是全名相等。
        def _base(t):
            return t.replace("\\", "/").rsplit("/", 1)[-1].lower()
        main_ev = defaultdict(list)
        for t, m in mats.items():
            for e in m["events"]:
                main_ev[_base(t)].append(e["i"])
        back = sorted({t for t in wrote
                       if any(i > (disp or 0) for i in main_ev.get(_base(t), []))})
        sub_out_lanes.append({
            "lane": li, "task": task, "dispatch_node": disp, "requests": len(rows),
            "start": rows[0][0], "end": rows[-1][0], "seconds": _sec(rows[0][0], rows[-1][0]),
            "out": out_tok, "errors": sum(1 for n in s_nodes for a in n["acts"] if a["error"]),
            "wrote": wrote, "returned": back,
            # 报告：末步常是纯动作（无正文），取末尾最后一段非空文本
            "report": (next((s["text"] for s in reversed(s_steps) if s["text"].strip()), "")
                       or (s_steps[-1]["text"] if s_steps else ""))[:900],
            "nodes": s_nodes, "_steps": s_steps, "_res": s_res,
        })
    # 派发了却一条请求都没有的：dsh 异步 agent launched 之后处于 idle，
    # 要等 SendMessage 才真正开跑。派发 ≠ 开工，图上要标出来。
    claimed = {L["dispatch_node"] for L in sub_out_lanes}
    idle_dispatch = [n["i"] for n in nodes if n["kind"] == "delegate" and n["i"] not in claimed
                     and any(a["tool"] in ("Agent", "Task", "dispatch_agent") for a in n["acts"])]
    _p(f"子代理线 {len(sub_out_lanes)} 条："
          + "，".join(f"N{L['dispatch_node']}→{len(L['nodes'])}节点/{L['requests']}请求"
                      for L in sub_out_lanes)
          + f"；派发后无请求 {idle_dispatch}")

    # ── 12c. 证据侧车：图默认吃摘要，点开才看原文 ────────────────────────────────
    # factors.json 是分析层，字段截断是对的；但证据层不能只有摘要。
    # 单独出一份 details.json，按 main:<i> / sub:<lane>:<i> 索引。
    TH_CAP, TX_CAP, RAW_CAP, ARG_CAP = 6000, 6000, 2500, 2000


    def _detail(node, step_src, res_src):
        ss = [step_src[k] for k in node["steps"] if k < len(step_src)]
        det = {"think": "".join(s["thinking"] for s in ss)[:TH_CAP],
               "reply": "".join(s["text"] for s in ss)[:TX_CAP], "acts": []}
        for a in node["acts"]:
            r = res_src.get(a["id"]) or {}
            raw = r.get("content")
            raw_txt = (raw if isinstance(raw, str)
                       else json.dumps(raw, ensure_ascii=False, indent=1) if raw else "")
            inp_full = a.get("cmd") or ""
            det["acts"].append({"tool": a["tool"], "op": a["op"], "target": a["target"],
                                "cmd": inp_full[:ARG_CAP], "args": (a.get("args") or "")[:ARG_CAP],
                                "prompt": (a.get("prompt") or "")[:ARG_CAP],
                                "err": bool(a["error"]), "raw_len": a.get("raw_len") or 0,
                                "raw": raw_txt[:RAW_CAP]})
        return det


    details = {f"main:{n['i']}": _detail(n, steps, results) for n in nodes}
    for L in sub_out_lanes:
        for n in L["nodes"]:
            details[f"sub:{L['lane']}:{n['i']}"] = _detail(n, L["_steps"], L["_res"])
        L.pop("_steps"), L.pop("_res")

    # ── 13. 落盘 ────────────────────────────────────────────────────────────────
    t0, t1 = nodes[0]["ts"], nodes[-1]["ts"]
    out = {
        "meta": {
            "sid": _sid[:8], "date": _date, "model": req_meta[0]["model"],
            "span": [t0, t1], "wall_seconds": _sec(t0, t1),
            "requests": {"main": len(mains), "subagent": len(subs), "security": len(secs),
                         "other": len(others)},
            "union": {"steps": len(steps), "actions": len(actions), "nodes": len(nodes),
                      "thinking_blocks": sum(1 for s in steps if s["thinking"].strip()),
                      "results": len(results),
                      # 「并集比单条最长请求多捞回多少」要算出来。此前页脚写死 190——
                      # 那是原型那条录制的数，换一条录制就是一句假话。
                      "longest_actions": max(
                          (sum(1 for _r, _bl in _msg_iter(rec) for _b in _bl
                               if _b.get("type") == "tool_use")
                           for _t, rec, _i, _k in mains), default=0)},
            "compact_at": compact_summary_at,
            "generated_by": f"cc-wire-analyzer {VERSION}",
        },
        "nodes": [{k: v for k, v in n.items() if k != "acts"} | {
            "acts": [{kk: vv for kk, vv in a.items() if kk not in ("prompt",)} for a in n["acts"]]}
            for n in nodes],
        "materials": sorted(mats.values(), key=lambda m: (m["class"] != "file", m["first"])),
        "provenance": prov, "sourceless": sourceless, "orphan_reads": sorted(orphan_reads),
        "verify": verify, "valves": valves, "loops": loops, "constraints": constraints,
        "gaps": gaps, "templates": templates, "debt": debt,
        "candidates": cand, "user_events": user_events,
        "subagents": sub_out_lanes, "idle_dispatch": idle_dispatch,
        "cost": {"main_out": tok_out, "main_in": tok_in, "cache_read": cache,
                 "sub_out": sub_tok, "security_ms": sec_ms,
                 "model_ms": sum(m["total_ms"] for m in req_meta),
                 "requests": req_meta},
    }

    # `snapshot_run.py` 把语义层（阶段名 + State Snapshot）**就地回写**进 factors.json。
    # 直接覆盖等于每次重跑 build 都静默抹掉一次模型调用的成果——保留住。

    return out, details

def build_optimal(F):
    """factors → optimal（必要闭包/浪费归因/迟滞/缺验证）。原型 optimal.py 的主体。"""

    nodes, PH, prov = F["nodes"], F["phases"], F["provenance"]
    mats = {m["name"]: m for m in F["materials"]}
    verify = {v["name"]: v for v in F["verify"]}
    N = len(nodes)


    def _sec(a, b):
        return round((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds())


    # ── 1. 终态交付集 B ──────────────────────────────────────────────────────────
    tail_from = PH[-2]["from"] if len(PH) >= 2 else int(N * 0.8)
    B = sorted({t for n in nodes[tail_from:] for t in n["mats"]
                if mats.get(t, {}).get("class") == "file"})
    _p(f"终态交付集 B：{len(B)} 件（最后两阶段 N{tail_from}+ 仍在被写或被读的文件）")
    for t in B:
        v = verify.get(t)
        _p(f"   {t}" + (f"  L{v['level']}" if v else "  （只读）"))

    # ── 1·五. 补「运行产出」边 ───────────────────────────────────────────────────
    # factors.json 的血统边只连 read→write，而这条会话里**大多数产物是 exec 产生的**
    # （chrome 截图出 png、脚本输出 svg/jpg），它们没有 write 事件，于是血统链在图片那里断掉：
    # 终态 9 件里 5 件是「只读」的孤岛，必要闭包只剩 45 节点、59% 节点无法归类。
    # 判据：某文件物料**首次出现**在节点 i 或 i+1，且节点 i 有 exec 动作 → 该次运行产出了它。
    run_edges = []
    for n in nodes:
        runs = [a["target"] for a in n["acts"] if a["op"] == "run" and a["target"]]
        if not runs:
            continue
        for name, m in mats.items():
            if m["class"] != "file" or m["first"] not in (n["i"], n["i"] + 1):
                continue
            if name in runs:
                continue
            first_ev = m["events"][0]
            if first_ev["op"] == "write":      # 有 write 的，read→write 那条边已经覆盖
                continue
            for r in runs:
                run_edges.append({"from": r, "to": name, "node": n["i"], "src_node": n["i"],
                                  "kind": "produced_by_run"})
    prov = prov + run_edges
    _p(f"补「运行产出」边 {len(run_edges)} 条 → 血统边合计 {len(prov)}")

    # ── 2. 必要性闭包（沿血统边反向可达） ────────────────────────────────────────
    back = defaultdict(set)
    for e in prov:
        back[e["to"]].add(e["from"])
    need_mat, q = set(B), deque(B)
    while q:
        cur = q.popleft()
        for src in back.get(cur, ()):
            if src not in need_mat:
                need_mat.add(src)
                q.append(src)
    _p(f"必要物料：{len(need_mat)} / 全部 {len(mats)}（沿血统边从 B 反向可达）")

    need_node = set()
    for n in nodes:
        if any(t in need_mat for t in n["changes"]):        # 写出了必要物料
            need_node.add(n["i"])
        elif any(t in need_mat for t in n["verified"]):     # 验证了必要物料
            need_node.add(n["i"])
    for e in prov:                                          # 提供了必要写入的输入
        if e["to"] in need_mat:
            need_node.add(e["src_node"])
            need_node.add(e["node"])
    _p(f"必要节点：{len(need_node)} / {N}")

    # ── 3. 浪费分类（每个非必要节点归一类，逐条挂号） ─────────────────────────────
    blocked = [v for v in F["valves"] if v["kind"] == "security" and v.get("blocked")]
    blocked_nodes = {v["node"] for v in blocked if v.get("node") is not None}
    err_nodes = {n["i"] for n in nodes if n["error"]}

    # 重复读：同一物料在同一/相邻节点被读两次，或结果里带 Wasted call
    redundant = []
    seen_read = {}
    for n in nodes:
        for a in n["acts"]:
            if a["op"] != "read" or not a["target"]:
                continue
            if "Wasted call" in (a["digest"] or ""):
                redundant.append({"node": n["i"], "target": a["target"], "why": "工具明说 Wasted call"})
            elif a["target"] in seen_read and n["i"] - seen_read[a["target"]] <= 2:
                redundant.append({"node": n["i"], "target": a["target"], "why": "两个节点内重复读同一物料"})
            seen_read[a["target"]] = n["i"]
    redundant_nodes = {r["node"] for r in redundant}

    # 返工：同一物料的连续写之间没有任何验证——除最后一次写以外都是事后可省的
    rework_nodes = set()
    for name, m in mats.items():
        if m["class"] != "file":
            continue
        run = []
        for e in m["events"]:
            if e["op"] == "write":
                run.append(e["i"])
            elif e["op"] in ("read", "run"):
                if len(run) >= 2:
                    rework_nodes |= set(run[:-1])
                run = []
        if len(run) >= 2:
            rework_nodes |= set(run[:-1])

    # 死胡同：写出的产物既不在必要集，也没喂给任何必要写入
    dead_nodes = set()
    for n in nodes:
        outs = [t for t in n["changes"] if mats.get(t, {}).get("class") == "file"]
        if outs and not any(t in need_mat for t in outs):
            dead_nodes.add(n["i"])

    # 「必要」只认**最后一次写**：中间版本之后被覆盖且中间没验证，事后看是可以省掉的。
    # 第一版把 rework 放在 necessary 之后判，结果返工类恒为空——因为中间版本写的也是
    # 必要物料，被 necessary 先截胡了。这是判据顺序的错，不是数据没有返工。
    last_write = {}
    for name, m in mats.items():
        ws = [e["i"] for e in m["events"] if e["op"] == "write"]
        if ws:
            last_write[name] = max(ws)
    final_writer = set()
    for n in nodes:
        for t in n["changes"]:
            if t in need_mat and last_write.get(t) == n["i"]:
                final_writer.add(n["i"])

    klass, why = {}, {}
    for n in nodes:
        i = n["i"]
        superseded = [t for t in n["changes"]
                      if t in need_mat and last_write.get(t, -1) > i]
        if i in final_writer or (i in need_node and any(t in need_mat for t in n["verified"])):
            klass[i] = "necessary"
        elif superseded:
            klass[i], why[i] = "rework", f"写的是中间版本，之后被覆盖：{'、'.join(superseded[:3])}"
        elif i in blocked_nodes:
            klass[i], why[i] = "blocked_retry", "被安检拦下的尝试"
        elif i in dead_nodes:
            klass[i], why[i] = "dead_end", "产出没进入终态、也没喂给终态"
        elif i in redundant_nodes:
            klass[i], why[i] = "redundant", "重复读同一物料（含工具明说 Wasted call）"
        elif any(t in need_mat for t in n["mats"]):
            klass[i], why[i] = "evidence", "为必要物料取证（读/跑到了必要闭包里的东西）"
        elif any(a["op"] == "delegate" for a in n["acts"]):
            klass[i], why[i] = "delegate", "派发子代理（其代价另在子代理线上）"
        elif not n["acts"]:
            klass[i], why[i] = "think_only", "纯思考，没有动作"
        else:
            # 读项目文件、glob、网页——真实存在的「先摸清楚再动手」，
            # 但这一趟读到的东西最终没有喂给任何交付物。
            ext = any((a["target"] or "").startswith("http") for a in n["acts"])
            klass[i], why[i] = ("external_research" if ext else "orientation"), \
                ("查外部资料，结果没进入终态" if ext else "读项目/文档摸情况，结果没进入终态")

    cnt = Counter(klass.values())
    _p("\n节点分类：", dict(cnt))

    # ── 4. 每一类的代价 ─────────────────────────────────────────────────────────
    def cost_of(idxs):
        ns = [nodes[i] for i in sorted(idxs)]
        return {"nodes": len(ns), "acts": sum(len(n["acts"]) for n in ns),
                "out": sum(n["cost"]["out"] for n in ns),
                "model_ms": sum(n["cost"]["total_ms"] for n in ns)}


    by_class = {}
    for k in ("necessary", "evidence", "orientation", "external_research", "delegate",
              "rework", "dead_end", "blocked_retry", "redundant", "think_only", "unattributed"):
        idxs = [i for i, v in klass.items() if v == k]
        if idxs:
            by_class[k] = cost_of(idxs)
            by_class[k]["share"] = round(len(idxs) / N * 100, 1)
    tot_out = sum(n["cost"]["out"] for n in nodes)
    tot_ms = sum(n["cost"]["total_ms"] for n in nodes)
    _p("\n各类代价（节点 / 动作 / out token / 模型在途秒）：")
    for k, v in by_class.items():
        _p(f"  {k:14s} {v['nodes']:4d} 节点 {v['acts']:4d} 动作 "
              f"{v['out']:7,d} out {v['model_ms']//1000:5d}s  占节点 {v['share']}%")

    # ── 5. ex-ante / ex-post 判定 ───────────────────────────────────────────────
    # 被拦重试：第一次拦截是信息，之后的同类重试是 ex-ante 可避免（理由已给出）
    first_blocked = blocked[0] if blocked else None
    avoidable_blocked = [v for v in blocked[1:]] if len(blocked) > 1 else []
    # 死胡同分支：找该分支上第一条否定性证据（失败 / 用户否定 / 判定性结果），
    # 到分支实际结束之间的距离 = 迟滞代价
    users = [u for u in F["user_events"] if u["kind"] == "user"]
    user_node = {}
    for u in users:
        nx = next((n["i"] for n in nodes if n["ts"] >= u["ts"]), N - 1)
        user_node.setdefault(nx, []).append(u["text"][:160])

    dead_sorted = sorted(dead_nodes)
    branches, cur = [], []
    for i in dead_sorted:
        if cur and i - cur[-1] > 3:
            branches.append(cur); cur = []
        cur.append(i)
    if cur:
        branches.append(cur)
    lag = []
    for br in branches:
        lo, hi = br[0], br[-1]
        first_neg = next((i for i in range(lo, hi + 1)
                          if i in err_nodes or i in user_node
                          or any(a["assertive"] for a in nodes[i]["acts"])), None)
        lag.append({"from": lo, "to": hi, "nodes": len(br),
                    "first_negative": first_neg,
                    "lag_nodes": (hi - first_neg) if first_neg is not None else None,
                    "lag_seconds": _sec(nodes[first_neg]["ts"], nodes[hi]["ts"]) if first_neg is not None else None,
                    "out": sum(nodes[i]["cost"]["out"] for i in br),
                    "targets": sorted({t for i in br for t in nodes[i]["changes"]})[:5]})
    lag.sort(key=lambda x: -(x["lag_nodes"] or 0))
    _p("\n死胡同分支的迟滞代价（第一条否定性证据 → 分支实际结束）：")
    for x in lag[:6]:
        _p(f"  N{x['from']}–N{x['to']}（{x['nodes']} 节点）首个否定证据 "
              f"{('N'+str(x['first_negative'])) if x['first_negative'] is not None else '无'}"
              f" → 迟滞 {x['lag_nodes']} 节点 / {x['lag_seconds']}秒；产出 {x['targets']}")

    # 缺失的验证：必要产物里没到 L2 的
    missing_verify = [{"name": t, "level": verify[t]["level"], "writes": verify[t]["writes"]}
                      for t in sorted(need_mat)
                      if t in verify and verify[t]["level"] < 2]
    _p(f"\n必要产物里验证不足（< L2）：{len(missing_verify)} 件 "
          f"{[m['name'] for m in missing_verify][:6]}")

    # ── 6. 下界估算：必要节点 + 每件必要产物补一次验证 ────────────────────────────
    # 下界必须用**分类之后**的保留集，否则与归因表对不上：need_node 里有一部分
    # 在分类时被判成了返工/死胡同（写的是中间版本），不能再算进骨架。
    keep = {i for i, v in klass.items() if v in ("necessary", "evidence")}
    need_cost = cost_of(keep)
    add_verify_nodes = len(missing_verify)
    avg_verify_out = 300
    lower = {
        "nodes": need_cost["nodes"] + add_verify_nodes,
        "acts": need_cost["acts"] + add_verify_nodes,
        "out": need_cost["out"] + add_verify_nodes * avg_verify_out,
        "model_ms": need_cost["model_ms"] + add_verify_nodes * 8000,
    }
    _p(f"\n下界（必要 {need_cost['nodes']} 节点 + 补 {add_verify_nodes} 次验证）："
          f"{lower['nodes']} 节点 / {lower['out']:,} out / {lower['model_ms']//1000}s 模型在途")
    _p(f"实际：{N} 节点 / {tot_out:,} out / {tot_ms//1000}s")
    _p(f"压缩比：节点 {lower['nodes']/N:.0%}，out {lower['out']/max(tot_out,1):.0%}，"
          f"在途 {lower['model_ms']/max(tot_ms,1):.0%}")

    # ── 7. 阶段级对照：每个阶段的必要/浪费构成 ──────────────────────────────────
    ph_rows = []
    for p in PH:
        idxs = list(range(p["from"], p["to"] + 1))
        c = Counter(klass[i] for i in idxs)
        ph_rows.append({"id": p["id"], "name": p["name"], "from": p["from"], "to": p["to"],
                        "counts": dict(c),
                        "necessary_share": round((c.get("necessary", 0) + c.get("evidence", 0)) / len(idxs) * 100),
                        "out": sum(nodes[i]["cost"]["out"] for i in idxs),
                        "waste_out": sum(nodes[i]["cost"]["out"] for i in idxs
                                         if klass[i] not in ("necessary", "evidence"))})
    _p("\n阶段级必要占比：")
    for r in ph_rows:
        _p(f"  {r['id']} {r['name'][:12]:14s} 必要 {r['necessary_share']:3d}%  "
              f"废 out {r['waste_out']:,}")

    out = {
        "meta": {"nodes": N, "generated_by": "trajectory.build_optimal",
                 "definition": "必要 = 从终态交付集沿血统边反向可达；其余按四类浪费归类",
                 "caveat": "这是事后可复算的下界，不是当时能走出来的路；"
                           "ex-post 的探索代价不算错误，ex-ante 的才算"},
        "B": B, "need_mat": sorted(need_mat), "need_node": sorted(need_node),
        "klass": {str(i): klass[i] for i in klass}, "why": {str(i): why.get(i, "") for i in klass},
        "by_class": by_class, "totals": {"out": tot_out, "model_ms": tot_ms, "nodes": N},
        "lower_bound": lower, "keep": sorted(keep), "missing_verify": missing_verify,
        "dead_branches": lag, "redundant": redundant,
        "blocked": [{"ts": b["ts"], "arg": b["arg"][:120], "node": b.get("node"),
                     "reason": b.get("reason", "")[:200], "category": b.get("category", "")}
                    for b in blocked],
        "avoidable_blocked": len(avoidable_blocked),
        "phases": ph_rows, "user_node": {str(k): v for k, v in user_node.items()},
    }


    return out

class TrajectoryError(ValueError):
    """带 error_code 的轨迹层错误（ValueError 子类：向后兼容裸 except 的调用方）。"""

    def __init__(self, code: str, msg: str):
        super().__init__(msg)
        self.code = code


def factors_of(rec: dict):
    """录制 payload → (F, details, session_id, mains_n, think_blocks_raw)。

    事实层单独出口：语义层管线（app.py 的 POST）只需要候选边界与节点摘要，
    不必连带跑 optimal；compute 内部也走这里，两处永远同一份事实。
    think_blocks_raw 是主线请求里 thinking 块的**存在数**（含空文本块）——
    GLM 经智谱网关回 signature-only 思考块时 blocks=0 但 raw>0，前端据此
    显示「块存在，明文未回传」而不是误导性的「无思考」。
    """
    _idx = classifier.index_record(rec)
    session_id = _idx.get("session_id") or ""
    date = (rec.get("ts_start") or "")[:10] or datetime.now().strftime("%Y-%m-%d")
    mains, subs, secs, others = collect(session_id, date)
    if not mains:
        raise TrajectoryError(
            "archived_or_missing",
            "这条录制在同日存储里找不到主线请求——当天数据可能已被归档（.ccwa），"
            "八视图的地基是当日全量 blocks 并集，只能分析未归档的录制")
    F, details = build_factors(mains, subs, secs, others, session_id[:8], date)
    think_raw = sum(1 for row in mains
                    for b in ((row[1].get("response") or {}).get("content_blocks") or [])
                    if b.get("type") == "thinking")
    return F, details, session_id, len(mains), think_raw


def compute(sid: str, rec: dict, semantic: dict | None = None) -> dict:
    """一条录制快照 → 八视图 payload。

    rec: snapshot 的 payload（主线录制，用来取 session_id/date）；
    semantic: 可选的语义层缓存（{"phases": [...], "briefs": {node_i: text}}），
    缺省时机械兜底并标 degraded。
    """
    F, details, session_id, mains_n, think_raw = factors_of(rec)
    if not F["nodes"]:
        raise TrajectoryError("empty_run", "并集为空：主线请求在，但抽不出任何 assistant 步")
    F.setdefault("meta", {}).setdefault("union", {})["thinking_blocks_all"] = think_raw
    if mains_n <= 1:
        F.setdefault("meta", {})["basis"] = "single"

    # ── 语义层喂入：有缓存用缓存，没有机械兜底（degraded）。
    #    必须在 build_optimal 之前——optimal 的终态交付集 B 用「最后两阶段」。──
    sem = semantic if isinstance(semantic, dict) else {}
    ph_cache = sem.get("phases")
    if not (isinstance(ph_cache, list) and ph_cache):
        ph_cache = _fallback_phases(F)
        degraded = True
    else:
        degraded = False
    _attach_phase_facts(F, ph_cache)   # 事实格程序算完盖掉（两条路径统一走这里）
    F["phases"] = ph_cache
    F["phase_meta"] = {"source": "model" if not degraded else "fallback",
                       "candidates": len(F.get("candidates") or []),
                       # 语义层管线自己记了耗时（semantic.meta.seconds）。此前页脚读的是
                       # 一个根本不存在的字段，于是每条录制的页脚都写着「undefined 秒」。
                       "seconds": ((sem.get("meta") or {}).get("seconds")
                                   if isinstance(sem.get("meta"), dict) else None)}
    briefs = sem.get("briefs") or {}
    for n in F["nodes"]:
        b = (briefs.get(f"main:{n['i']}") or briefs.get(str(n["i"]))
             or briefs.get(n["i"]))
        if isinstance(b, str) and b.strip():
            n["brief"] = b.strip()[:40]
    for L in F.get("subagents") or []:
        for m in L["nodes"]:
            b = briefs.get(f"sub:{L['lane']}:{m['i']}")
            if isinstance(b, str) and b.strip():
                m["brief"] = b.strip()[:40]

    OPT = build_optimal(F)
    D, DET = F, details

    slim_nodes = [{"i": n["i"], "kind": n["kind"], "ts": n["ts"], "error": n["error"],
                   "think": n["think"], "changes": n["changes"], "reads": n["reads"],
                   "verified": n["verified"], "pattern": n["pattern"], "cost": n["cost"],
                   "brief": n.get("brief") or "",
                   "acts": [{"op": a["op"], "target": a["target"], "tool": a["tool"],
                             "error": a["error"], "digest": a["digest"], "assertive": a["assertive"]}
                            for a in n["acts"]][:12],
                   "reply": n["reply"][:160]}
                  for n in D["nodes"]]
    payload = {k: F[k] for k in ("meta", "materials", "provenance", "sourceless", "orphan_reads",
                                 "verify", "valves", "loops", "constraints", "gaps", "templates",
                                 "debt", "phases", "phase_meta", "user_events", "candidates")}
    payload["nodes"] = slim_nodes
    # V1 钻取要展示证据原文（思考/命令/返回），侧车整份带上（~0.9MB，页面可承受）
    # （details 由 compute 尾部统一附上）
    payload["cost"] = {k: v for k, v in D["cost"].items() if k != "requests"}
    # 「节点口径在途」：阶段连续覆盖全部节点（切分校验过），阶段 model_ms 求和即
    # 只算进过轨迹节点的主线请求——与 V1 阶段标注、V6 归因表同一口径。
    # cost.model_ms 则是全部请求（含安检/title/压缩摘要等辅助）：两个都是真值，
    # 但同屏混用会被读成自相矛盾（V5 卡片 vs 阶段合计，260828 视觉审查 P1-1）。
    payload["cost"]["nodes_model_ms"] = sum(
        p["cost"]["model_ms"] for p in F["phases"]) or payload["cost"].get("model_ms", 0)
    payload["optimal"] = OPT
    payload["requests"] = [{"i": r["i"], "ts": r["ts"], "ttft": r["ttft"], "total_ms": r["total_ms"],
                            "out": r["out"], "in": r["in"], "cache_read": r["cache_read"]}
                           for r in D["cost"]["requests"]]

    # ============ V7 物料生命线 + 未验债曲线（在统一地基 factors.json 上重建） ============
    # 第七代 2D 版的地基是「单条最长请求」（只看到后半段 run），这里换成与 V1-V6/V8
    # 同一份 factors.json：节点数、时间范围、物料名全部对得上。
    V7X0, V7PITCH = 190, 21
    V7ROW_H, V7TOP = 26, 118
    v7_names, seen7 = [], set()
    for nm in (OPT or {}).get("B", []) + [v["name"] for v in D["verify"]]:
        if nm not in seen7:
            v7_names.append(nm)
            seen7.add(nm)
    heat = sorted(D["materials"], key=lambda m: -(m["writes"] * 3 + m["reads"] + m["runs"]))
    for m in heat:
        if len(v7_names) >= 24:
            break
        if m["name"] not in seen7:
            v7_names.append(m["name"])
            seen7.add(m["name"])
    mats7 = {m["name"]: m for m in D["materials"]}
    ver7 = {v["name"]: v for v in D["verify"]}
    def _v7_rows(names):
        out = []
        for ri, nm in enumerate(names):
            m = mats7.get(nm)
            if not m:
                continue
            out.append({
                "name": nm, "y": V7TOP + ri * V7ROW_H,
                "level": (ver7.get(nm) or {}).get("level"),
                "in_B": nm in (OPT or {}).get("B", []),
                "writes": m["writes"], "reads": m["reads"], "runs": m["runs"],
                "first": m["first"], "last": m["last"],
                "marks": [{"i": e["i"], "op": e["op"],
                           "clears": bool(e["clears"]), "error": bool(e["error"]),
                           "ts": e["ts"], "tool": e["tool"], "d": (e.get("digest") or "")[:90]}
                          for e in m["events"]][:220],
            })
        return out


    rows_key = _v7_rows(v7_names)
    names_all = [m["name"] for m in D["materials"]
                 if m["class"] in ("file", "url", "pattern") and m["events"]]
    names_cmd = names_all + [m["name"] for m in
                             sorted([m for m in D["materials"] if m["class"] == "cmd"],
                                    key=lambda m: -(m["runs"] + m["reads"]))][:12]
    rows_all, rows_cmd = _v7_rows(names_all), _v7_rows(names_cmd)
    v7_debt = [{"i": d["i"], "n": d["n"]} for d in D["debt"]]
    v7_gapx = [{"from": g["from"], "to": g["to"], "sec": g["seconds"]} for g in D["gaps"]]
    v7_subs = []
    for L in D.get("subagents") or []:
        endn = next((n["i"] for n in D["nodes"] if n["ts"] >= L["end"]), L["dispatch_node"])
        v7_subs.append({"disp": L["dispatch_node"], "endn": endn, "task": L["task"][:34],
                        "seconds": L["seconds"], "start": L["start"], "end": L["end"],
                        "requests": L["requests"], "out": L["out"],
                        "returned": L.get("returned") or [], "errors": L.get("errors") or 0})
    payload["v7"] = {"W": V7X0 + len(D["nodes"]) * V7PITCH + 260, "X0": V7X0,
                     "PITCH": V7PITCH, "row_h": V7ROW_H, "top": V7TOP,
                     "rows_key": rows_key, "rows_all": rows_all, "rows_cmd": rows_cmd,
                     "n_all": len(rows_all), "n_cmd": len(rows_cmd),
                     "debt": v7_debt, "gaps": v7_gapx, "subs": v7_subs,
                     "t0": D["nodes"][0]["ts"], "t1": D["nodes"][-1]["ts"]}

    # ============ V8 最优轨迹时序节点图（自 build_optimal_graph.py 移植，数据同源） ============
    nodes8 = D["nodes"]
    klass = {int(k): v for k, v in (OPT or {}).get("klass", {}).items()}
    why8 = {int(k): v for k, v in (OPT or {}).get("why", {}).items()}
    KEEP = {"necessary", "evidence"}
    SUBS8 = D.get("subagents") or []
    IDLE8 = D.get("idle_dispatch") or []
    mats8 = {m["name"]: m for m in D["materials"]}
    verify8 = {v["name"]: v for v in D["verify"]}
    skeleton = [n for n in nodes8 if klass.get(n["i"]) in KEEP]


    def _sec(a, b):
        from datetime import datetime
        try:
            return round((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds())
        except Exception:
            return 0


    X0, PITCH, YM = 190, 21, 402
    LANES8 = [("rework", 452), ("dead_end", 492), ("blocked_retry", 532), ("redundant", 566),
              ("orientation", 606), ("external_research", 640), ("delegate", 674), ("think_only", 706)]
    MAT_Y, SUB_Y0, SUB_DH, YCOMP8, H8 = 196, 736, 30, 884, 944
    ins = {}
    bands8 = []
    for li, L in enumerate(SUBS8):
        w = max(L["seconds"] * .55, 9 * len(L["nodes"]) + 60, 200)
        ins[L["dispatch_node"]] = ins.get(L["dispatch_node"], 0) + w + 46
        bands8.append({"lane": L["lane"], "li": li, "w": round(w)})
    pos8, acc8 = {}, 0.0
    for n in nodes8:
        pos8[n["i"]] = X0 + n["i"] * PITCH + acc8
        acc8 += ins.get(n["i"], 0)
    W8 = round(pos8[nodes8[-1]["i"]] + 340)
    for bi, b in enumerate(bands8):
        L = SUBS8[bi]
        x0 = pos8[L["dispatch_node"]] + 16
        b.update({"x0": round(x0), "x1": round(x0 + b["w"]), "y": SUB_Y0 + b["li"] * SUB_DH,
                  "task": L["task"], "disp": L["dispatch_node"], "seconds": L["seconds"],
                  "out": L["out"], "requests": L["requests"], "errors": L["errors"],
                  "wrote": L["wrote"], "report": L["report"], "start": L["start"], "end": L["end"]})
        b["resume"] = next((n["i"] for n in nodes8 if n["ts"] >= L["end"]), None)
        t0, t1 = L["start"], L["end"]
        span = _sec(t0, t1) or 1
        b["nodes"] = [{"i": m["i"], "kind": m["kind"], "ts": m["ts"], "err": m["error"],
                       "nacts": len(m["acts"]), "brief": m.get("brief") or "",
                       "changes": m["changes"][:3], "reads": m["reads"][:3],
                       "x": round(b["x0"] + 8 + min(max(_sec(t0, m["ts"]) / span, 0), 1) * (b["w"] - 16)),
                       "y": b["y"]} for m in L["nodes"]]
    idle8 = []
    for i in IDLE8:
        nxt = next((n["i"] for n in nodes8 if n["i"] > i and n["kind"] == "delegate"
                    and any(L["dispatch_node"] == n["i"] for L in SUBS8)), None)
        idle8.append({"node": i, "x": pos8.get(i, X0), "x2": pos8.get(nxt) if nxt else None,
                      "wake": nxt, "seconds": _sec(nodes8[i]["ts"], nodes8[nxt]["ts"]) if nxt else 0})
    ph8 = []
    for p in D["phases"]:
        xs = [pos8[i] for i in range(p["from"], p["to"] + 1) if i in pos8]
        if xs:
            ph8.append({"id": p["id"], "name": p["name"], "x0": min(xs), "x1": max(xs),
                        "from": p["from"], "to": p["to"], "from_state": p["from_state"],
                        "to_state": p["to_state"], "seconds": p["seconds"],
                        "debt_in": p["debt_in"], "debt_out": p["debt_out"]})
    km8, seen8m = [], set()
    for name in (OPT or {}).get("B", []) + [v["name"] for v in D["verify"]]:
        if name in seen8m or name not in mats8:
            continue
        seen8m.add(name)
        m = mats8[name]
        writer = next((n["i"] for n in reversed(nodes8) if name in n["changes"]), None)
        km8.append({"name": name, "first": m["first"], "writer": writer,
                    "x_src": pos8.get(writer if writer is not None else m["first"], X0),
                    "level": (verify8.get(name) or {}).get("level"),
                    "in_B": name in (OPT or {}).get("B", []),
                    "writes": m["writes"], "reads": m["reads"], "runs": m["runs"]})
    km8.sort(key=lambda m: m["x_src"])
    prevx = -1e9
    for m in km8:
        m["x"] = max(m["x_src"], prevx + 132)
        prevx = m["x"]


    def lab8(n):
        if n.get("brief"):
            return n["brief"]
        if n["kind"] == "delegate":
            t = next((a["target"] for a in n["acts"] if a["op"] == "delegate" and a["target"]), "")
            return "派发 " + (t or "子代理")
        if n["changes"]:
            return "写 " + "、".join(n["changes"][:2])
        for a in n["acts"]:
            if a["target"]:
                return (a["tool"] or a["op"]) + " " + str(a["target"])[:30]
        return (n["reply"] or "")[:36].replace("\n", " ")


    lag8 = [{"from": b["from"], "to": b["to"], "neg": b["first_negative"], "lag_nodes": b["lag_nodes"],
             "lag_seconds": b["lag_seconds"], "x_neg": pos8.get(b["first_negative"], X0),
             "x_end": pos8.get(b["to"], X0), "targets": b["targets"]}
            for b in (OPT or {}).get("dead_branches", []) if b.get("first_negative") is not None]
    miss8 = []
    for mv in (OPT or {}).get("missing_verify", []):
        w = next((n["i"] for n in reversed(nodes8) if mv["name"] in n["changes"]), None)
        miss8.append({"name": mv["name"], "x": pos8.get(w, X0) + PITCH * .5, "node": w})
    CP8 = max((W8 - X0 - 360) / max(len(skeleton) + len(miss8), 1), 6)
    payload["v8"] = {
        "meta": {"W": W8, "H": H8, "YM": YM, "X0": X0, "PITCH": PITCH, "MAT_Y": MAT_Y,
                 "lanes": LANES8, "sub_y0": SUB_Y0, "sub_dh": SUB_DH},
        "totals": (OPT or {}).get("totals", {}), "lower": (OPT or {}).get("lower_bound", {}),
        "by_class": (OPT or {}).get("by_class", {}),
        "phases": ph8, "mats": km8, "lag": lag8, "missing": miss8,
        "comp": {str(n["i"]): X0 + j * CP8 for j, n in enumerate(skeleton)},
        "comp_pitch": CP8, "ycomp": YCOMP8, "skeleton_n": len(skeleton),
        "subs": bands8, "idle": idle8,
        "sub_stats": {"lanes": len(bands8), "requests": sum(b["requests"] for b in bands8),
                      "out": sum(b["out"] for b in bands8),
                      "nodes": sum(len(b["nodes"]) for b in bands8)},
        "nodes": [{"i": n["i"], "k": klass.get(n["i"], "unattributed"), "why": why8.get(n["i"], ""),
                   "lab": lab8(n), "x": pos8.get(n["i"], X0), "sk": klass.get(n["i"]) in KEEP,
                   "kind": n["kind"], "ts": n["ts"], "out": n["cost"]["out"],
                   "ms": n["cost"]["total_ms"], "err": n["error"],
                   "changes": n["changes"][:4], "verified": n["verified"][:3],
                   "acts": [{"op": a["op"], "t": a["target"], "tool": a["tool"], "e": a["error"],
                             "d": a["digest"][:80]} for a in n["acts"]][:8]}
                  for n in nodes8],
    }

    payload["meta"]["semantic"] = "degraded" if degraded else "model"
    payload["meta"]["session_id"] = session_id
    payload["meta"]["brief_cover"] = sum(1 for n in F["nodes"] if n.get("brief")) + sum(
        1 for L in F.get("subagents") or [] for m in L["nodes"] if m.get("brief"))
    payload["details"] = DET
    return payload


def _fallback_phases(F):
    """机械兜底：候选边界上按耗时聚成 6~10 段，from/to_state 用程序事实拼。"""
    nodes, cands = F["nodes"], F.get("candidates") or []
    cuts = sorted({0} | {c["at"] for c in cands} | {len(nodes)})
    segs = [(a, b) for a, b in zip(cuts, cuts[1:])]
    target = 8
    while len(segs) > target:            # 合并最短的段直到 ≤target
        j = min(range(len(segs) - 1), key=lambda k: segs[k][1] - segs[k][0])
        a1, b1 = segs[j]
        a2, b2 = segs[j + 1]
        segs[j:j + 2] = [(a1, b2)]
    out = []
    debt = F.get("debt") or []
    for k, (a, b) in enumerate(segs):
        ns = nodes[a:b]
        wr = sorted({t for n in ns for t in n.get("changes") or []})[:3]
        rd = sorted({t for n in ns for t in n.get("reads") or []})[:2]
        d_in = (debt[a] or {}).get("n", 0) if a < len(debt) else 0
        d_out = (debt[b - 1] or {}).get("n", 0) if b - 1 < len(debt) else 0
        out.append({
            "id": f"P{k + 1}", "name": f"N{a}-N{b - 1}",
            "from": a, "to": b - 1,
            "seconds": _sec(ns[0]["ts"], ns[-1]["ts"]) if ns else 0,
            "debt_in": d_in, "debt_out": d_out,
            "from_state": ("读 " + "、".join(rd)) if rd else "起点",
            "to_state": ("写 " + "、".join(wr)) if wr else "无写出",
            "known": [], "assumed": [], "unknown": [], "decisions": [],
        })
    return out


def _attach_phase_facts(F, phases):
    """事实回填（原型 snapshot_run.py 尾段的产品化）。

    无论 phases 来自模型还是机械兜底，每段的 id/秒/kinds/成本/债 + 八元组的
    事实四格（artifacts/pending/errors_detail/constraints）与事件两列
    （blocked/user_said）都由程序算完**盖掉**模型输出——模型不得改事实，
    这是八视图管线的分层纪律。语义四格（known/assumed/unknown/decisions）
    模型路径已有值，兜底路径补空数组。
    """
    nodes, debt = F["nodes"], F["debt"]
    users = [u for u in F.get("user_events") or [] if u.get("kind") == "user"]
    blocked = [v for v in F.get("valves") or []
               if v.get("kind") == "security" and v.get("blocked")]
    cands = {c["at"] for c in F.get("candidates") or []}
    for i, p in enumerate(phases):
        ns = nodes[p["from"]:p["to"] + 1]
        p["id"] = f"P{i + 1}"
        p["nodes_n"] = len(ns)
        p["ts"] = [ns[0]["ts"], ns[-1]["ts"]] if ns else [None, None]
        p["seconds"] = _sec(ns[0]["ts"], ns[-1]["ts"]) if ns else 0
        p["kinds"] = {k: sum(1 for n in ns if n["kind"] == k)
                      for k in ("advance", "perceive", "verify", "delegate", "think")}
        p["errors"] = sum(1 for n in ns for a in n["acts"] if a["error"])
        p["debt_in"] = (debt[max(p["from"] - 1, 0)] or {}).get("n", 0)
        p["debt_out"] = (debt[p["to"]] or {}).get("n", 0) if p["to"] < len(debt) else 0
        p["cost"] = {"out": sum(n["cost"]["out"] for n in ns),
                     "in": sum(n["cost"]["in"] for n in ns),
                     "cache_read": sum(n["cost"]["cache_read"] for n in ns),
                     "model_ms": sum(n["cost"]["total_ms"] for n in ns)}
        p["off_candidate"] = i > 0 and p["from"] not in cands
        # —— 事实四格 + 事件两列（模型不得改）——
        p["artifacts"] = sorted({t for n in ns for t in n["changes"]})
        p["pending"] = sorted({v["name"] for v in F["verify"]
                               if v["level"] == 0 and v["last_write"] <= p["to"]})
        p["errors_detail"] = [next(a["digest"][:70] for a in n["acts"] if a["error"])
                              for n in ns if n["error"]][:4]
        p["constraints"] = sorted({u["text"][:60] for u in users
                                   if ns and ns[0]["ts"] <= u["ts"] <= ns[-1]["ts"]})[:3]
        p["blocked"] = [b["arg"][:70] for b in blocked
                        if ns and ns[0]["ts"] <= b["ts"] <= ns[-1]["ts"]][:4]
        p["user_said"] = [u["text"][:200] for u in users
                          if ns and ns[0]["ts"] <= u["ts"] <= ns[-1]["ts"]][:3]
        for k in ("known", "assumed", "unknown", "decisions"):
            if not isinstance(p.get(k), list):
                p[k] = []


HTML = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>轨迹观测 · 八视图</title>
<script>
/* 外观与嵌入形态必须在首屏绘制前定下来，否则会先闪一下深色再变浅。
   来源优先级：URL 参数（父页嵌入时带上）> cookie（独立打开时跟随主界面）> 深色。
   cookie 与主界面同一把钥匙 ccwa_ui_theme——外观只属于 UI，绝不进后端 config.json。 */
(function(){
  var q=new URLSearchParams(location.search);
  var ok={classic:1,dark:1,light:1}, t=q.get('theme')||'';
  if(!ok[t]){
    try{var m=document.cookie.match(/(?:^|;\s*)ccwa_ui_theme=([^;]+)/);
        t=m?decodeURIComponent(m[1]):'';}catch(e){}
  }
  if(!ok[t]) t='dark';
  var r=document.documentElement;
  r.dataset.theme=t;
  r.style.colorScheme=(t==='dark')?'dark':'light';
  if(q.get('embed')==='1') r.dataset.embed='1';
})();
</script>
<style>
/* ===== 打包字体：与主界面同一份文件、同一套栈（均 SIL OFL，见根 LICENSE）=====
   此前这页用的是系统字体栈（YaHei / Consolas），等于绕过了「字体打包进产物保证
   跨平台视觉一致」这条前端约定——嵌在主界面里两套字形并排，一眼就是两个软件。 */
@font-face{font-family:'Inter';src:url('/static/fonts/Inter.ttf') format('truetype');font-weight:100 900;font-style:normal;font-display:swap}
@font-face{font-family:'JetBrains Mono';src:url('/static/fonts/JetBrainsMono.ttf') format('truetype');font-weight:100 800;font-style:normal;font-display:swap}
@font-face{font-family:'Noto Sans SC';src:url('/static/fonts/NotoSansSC.ttf') format('truetype');font-weight:100 900;font-style:normal;font-display:swap}

/* ===== 主题无关 token（三套外观共用）=====
   软底一律由基色 color-mix 派生：换外观只换基色，所有软底自动跟着换，
   不用三份各写一遍——也就没有「改了深色忘了改浅色」这种腐化面。 */
:root{
  --mono:"JetBrains Mono","SF Mono",Menlo,"Courier New",monospace;
  --body:"Inter","Noto Sans SC",-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;
  --s1:4px;--s2:8px;--s3:12px;--s4:16px;--s5:24px;--s6:32px;--s7:48px;
  --r:8px;--r2:12px;
  --agent-t1:color-mix(in srgb,var(--agent) 7%,transparent);
  --agent-t2:color-mix(in srgb,var(--agent) 15%,transparent);
  --agent-t3:color-mix(in srgb,var(--agent) 32%,transparent);
  --mat-t1:color-mix(in srgb,var(--material) 10%,transparent);
  --mat-t2:color-mix(in srgb,var(--material) 45%,transparent);
  --art-t1:color-mix(in srgb,var(--artifact) 12%,transparent);
  --art-t2:color-mix(in srgb,var(--artifact) 40%,transparent);
  --err-t1:color-mix(in srgb,var(--error) 9%,transparent);
  --err-t2:color-mix(in srgb,var(--error) 38%,transparent);
  --ok-t1:color-mix(in srgb,var(--ok) 12%,transparent);
  --ok-t2:color-mix(in srgb,var(--ok) 45%,transparent);
  --dele-t1:color-mix(in srgb,var(--dele) 12%,transparent);
  --dele-t2:color-mix(in srgb,var(--dele) 42%,transparent);
  --advance:var(--material);--verify:var(--ok);
}
/* ===== 深色（默认外观，取值与主界面 dark 同源：#131318 炭底 + 驼金）===== */
:root{
  color-scheme:dark;
  --void:#131318;--deep:#25252F;--surf:#1E1E26;--surf2:#2A2A35;
  --sheet:rgba(19,19,24,.86);--grid:rgba(255,255,255,.10);
  --panel:rgba(30,30,38,.97);--top-bg:rgba(19,19,24,.90);--tip-bg:rgba(30,30,38,.98);
  --line:#2E2E38;--line2:#262630;
  --ink:#F5F5F7;--muted:#C8C8D0;--dim:#9797A0;
  --agent:#E8B855;--agent2:#F2D08C;
  --material:#F0A05A;--artifact:#FBBF24;--error:#F87171;--ok:#4ADE80;
  --focus:#60A5FA;--dele:#C2A4FF;--evid:#5FD3C0;--perceive:#7FB6D8;
  --gap:#74747F;--think:#8A8A95;
  --shadow-card:0 8px 24px rgba(0,0,0,.45),0 2px 8px rgba(0,0,0,.30);
  --shadow-panel:0 16px 44px rgba(0,0,0,.55),0 6px 16px rgba(0,0,0,.40);
  --canvas-pattern:none;--canvas-pattern-size:auto;
}
/* 经典暖灰 */
html[data-theme="classic"]{
  color-scheme:light;
  --void:#DED8CC;--deep:#F4F2EF;--surf:#FFFFFF;--surf2:#FBFAF8;
  --sheet:#FFFFFF;--grid:rgba(91,72,45,.22);
  --panel:rgba(255,255,255,.98);--top-bg:rgba(255,255,255,.90);--tip-bg:rgba(255,255,255,.99);
  --line:#E1DBD0;--line2:#EDE7DC;
  --ink:#1A1A1A;--muted:#5C564C;--dim:#5E5748;
  --agent:#C98A25;--agent2:#6B4A12;
  --material:#A9591A;--artifact:#6D5016;--error:#A83C2A;--ok:#356A2B;
  --focus:#2B5488;--dele:#61409A;--evid:#1F6F7A;--perceive:#356585;
  --gap:#6E675C;--think:#6E675C;
  --shadow-card:0 3px 12px rgba(45,35,20,.08),0 1px 3px rgba(45,35,20,.07);
  --shadow-panel:0 14px 36px rgba(45,35,20,.14),0 4px 10px rgba(45,35,20,.10);
  --canvas-pattern:none;--canvas-pattern-size:auto;
}
/* 实验室日光：与主界面同一块冷矿物纸面，连 24px 网格都保留——嵌进去才不像贴片 */
html[data-theme="light"]{
  color-scheme:light;
  --void:#E8EEF0;--deep:#EDF3F5;--surf:#FFFFFF;--surf2:#F7FAFB;
  --sheet:#FFFFFF;--grid:rgba(55,85,96,.22);
  --panel:rgba(255,255,255,.98);--top-bg:rgba(247,250,251,.90);--tip-bg:rgba(255,255,255,.99);
  --line:#C7D4D9;--line2:#DEE7EA;
  --ink:#17212B;--muted:#3D4C57;--dim:#46545D;
  --agent:#1E6972;--agent2:#12474E;
  --material:#9C5518;--artifact:#7A5B13;--error:#A93635;--ok:#237A53;
  --focus:#1F5490;--dele:#5C3E96;--evid:#0E6F84;--perceive:#31627E;
  --gap:#5F6E77;--think:#5F6E77;
  --shadow-card:0 8px 22px rgba(31,57,66,.11),0 2px 6px rgba(31,57,66,.07);
  --shadow-panel:0 18px 42px rgba(31,57,66,.17),0 6px 14px rgba(31,57,66,.09);
  --canvas-pattern:
    linear-gradient(rgba(30,105,114,0.045) 1px,transparent 1px),
    linear-gradient(90deg,rgba(30,105,114,0.045) 1px,transparent 1px);
  --canvas-pattern-size:24px 24px;
}
*{box-sizing:border-box}
html,body{margin:0;background:var(--void);color:var(--ink);font-family:var(--body);
  -webkit-font-smoothing:antialiased}
body{background-image:var(--canvas-pattern);background-size:var(--canvas-pattern-size);
  padding-bottom:var(--s7)}
button{font:inherit;color:inherit;background:none;border:0}
::selection{background:var(--agent-t3)}
/* ── 嵌入模式：母体画布透出来，不再是「页中页」 ──
   背景透明 + 去掉自己的 sticky 顶栏 + 高度交给父页（见页尾 embed 桥）， */
html[data-embed="1"],html[data-embed="1"] body{background:transparent}
html[data-embed="1"] body{padding-bottom:var(--s4)}
html[data-embed="1"] .top{position:static;height:auto;padding:0 0 var(--s3);
  border-bottom:1px solid var(--line2);background:transparent;backdrop-filter:none}
html[data-embed="1"] .brand b{display:none}
html[data-embed="1"] .view{padding:var(--s4) 0 0}
html[data-embed="1"] footer.foot{margin-left:0;margin-right:0}
/* ── 顶栏 ── */
.top{position:sticky;top:0;z-index:60;display:flex;align-items:center;gap:var(--s4);
  padding:0 var(--s4);height:54px;border-bottom:1px solid var(--line);
  background:var(--top-bg);backdrop-filter:blur(10px)}
.brand{display:flex;align-items:baseline;gap:10px;flex-shrink:0;min-width:0}
.brand b{font-family:var(--mono);font-size:12.5px;letter-spacing:.12em}
.brand span{font-family:var(--mono);font-size:10.5px;color:var(--dim);letter-spacing:.06em;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
/* 单行不折：宽度不够就横向滚，绝不把导航折成两行（嵌入时宽度比独立打开窄） */
nav{display:flex;gap:2px;margin-left:auto;flex-wrap:nowrap;overflow-x:auto;
  scrollbar-width:none;justify-content:flex-end}
nav::-webkit-scrollbar{display:none}
.tab{font-family:var(--mono);font-size:11px;letter-spacing:.03em;padding:6px 11px;
  border:1px solid transparent;border-radius:var(--r);cursor:pointer;color:var(--muted);
  transition:.13s;white-space:nowrap;flex-shrink:0}
.tab:hover{color:var(--ink);background:var(--agent-t1)}
.tab[aria-selected="true"]{color:var(--agent2);border-color:var(--agent-t3);
  background:var(--agent-t2)}
.tab i{font-style:normal;color:var(--dim);margin-right:6px}
.tab[aria-selected="true"] i{color:var(--agent2)}
/* ── 视图头 ── */
.view{display:none;padding:var(--s5) var(--s5) 0;max-width:1760px}
/* V7/V8 全高画布：SVG 必须显式 width/height 100%（inset:0 对替换元素不生效，
   这是第九代整页空白的教训） */
.zstage{position:relative;height:var(--stage-h,calc(100vh - 168px));min-height:420px;margin-top:var(--s4);
 border:1px solid var(--line);border-radius:var(--r2);overflow:hidden;
 background:radial-gradient(1100px 480px at 72% -8%,var(--agent-t1),transparent 60%),var(--surf2)}
.zscene{position:absolute;inset:0;width:100%;height:100%;display:block;cursor:grab;touch-action:none}
.zscene.pan{cursor:grabbing}
.zbar{position:absolute;top:10px;right:12px;display:flex;gap:6px;z-index:5}
.zbtn{border:1px solid var(--line);padding:4px 9px;cursor:pointer;font-family:var(--mono);
 font-size:10.5px;background:var(--surf);color:var(--muted)}
.zbtn:hover{border-color:var(--agent);color:var(--ink)}
.zbtn[aria-pressed="true"]{background:var(--agent-t2);border-color:var(--agent);color:var(--agent2)}
/* V8 画布常驻统计/图例（原时序图形态：全览时也在画布角落） */
.zstats{position:absolute;top:46px;right:12px;display:flex;gap:6px;z-index:4;
 pointer-events:none;flex-wrap:wrap;justify-content:flex-end;max-width:58%}
.zstats .st{border:1px solid var(--line);background:var(--surf);padding:5px 9px;text-align:right}
.zstats .st b{display:block;font-family:var(--mono);font-size:13px}
.zstats .st span{font-family:var(--mono);font-size:10.5px;color:var(--dim)}
.zstats .st.bad b{color:var(--error)}.zstats .st.ok b{color:var(--ok)}
.zstats .st.warn b{color:var(--artifact)}.zstats .st.dele b{color:var(--dele)}
.zlegend{position:absolute;right:14px;bottom:34px;z-index:4;display:flex;flex-direction:column;gap:3px;
 font-family:var(--mono);font-size:10px;color:var(--muted);pointer-events:none;
 background:var(--surf);border:1px solid var(--line2);padding:8px 10px;max-width:240px}
/* V7 STATE A/B 起终点面板（原 2D 版解释层） */
.s7ab{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:var(--s3) 0}
.s7ab .sb{border:1px solid var(--line);border-radius:8px;padding:10px 13px;background:var(--deep)}
.s7ab h4{margin:0 0 6px;font-family:var(--mono);font-size:10px;letter-spacing:.1em;color:var(--agent2)}
.s7ab .s7g{margin:0 0 8px;font-size:12px;color:var(--ink);line-height:1.55}
.s7c{display:inline-flex;flex-direction:column;border:1px solid var(--line2);border-radius:5px;
 padding:4px 9px;margin:0 6px 6px 0;background:var(--surf2)}
.s7c b{font-family:var(--mono);font-size:13px;color:var(--muted)}
.s7c.ok b{color:var(--ok)} .s7c.bad b{color:var(--error)}
.s7f{display:flex;flex-wrap:wrap;gap:5px;margin-top:4px}
.s7f span{font-family:var(--mono);font-size:10px;color:var(--muted);border:1px solid var(--line2);
 padding:2px 7px;border-radius:4px}
.s7f.warn span{border-color:var(--err-t2);color:var(--error)}
.zhint{position:absolute;left:14px;bottom:10px;z-index:5;color:var(--dim);font-family:var(--mono);
 font-size:10px;pointer-events:none}
.zmm{position:absolute;left:14px;bottom:30px;z-index:5;background:var(--panel);
 border:1px solid var(--line);border-radius:var(--r);padding:4px;cursor:pointer;
 box-shadow:var(--shadow-card);opacity:.92}
.zmm:hover{opacity:1}
text{font-family:var(--mono)}
.view.on{display:block}
.eyebrow{font-family:var(--mono);font-size:10px;letter-spacing:.18em;color:var(--agent2);
  text-transform:uppercase}
h1{font-size:24px;line-height:1.15;margin:7px 0 9px;font-weight:660;letter-spacing:-.01em}
.lede{margin:0;color:var(--muted);font-size:12.5px;line-height:1.7;max-width:1000px}
.lede b{color:var(--ink);font-weight:600}
.lede code{font-family:var(--mono);font-size:11.5px;color:var(--artifact)}
.stats{display:flex;flex-wrap:wrap;gap:var(--s2);margin:var(--s4) 0 var(--s5)}
.stat{border:1px solid var(--line);border-radius:var(--r);
  background-color:var(--surf);background-image:linear-gradient(180deg,var(--surf),var(--surf2));
  padding:9px 13px;min-width:104px}
.stat .v{font-family:var(--mono);font-size:17px;line-height:1.1;color:var(--ink)}
.stat .k{font-family:var(--mono);font-size:10.5px;color:var(--dim);letter-spacing:.06em;margin-top:3px}
.stat.warn .v{color:var(--artifact)} .stat.bad .v{color:var(--error)} .stat.ok .v{color:var(--ok)}
.note{border-left:2px solid var(--artifact);padding:2px 0 2px 10px;margin:var(--s3) 0 0;
  font-family:var(--mono);font-size:10.5px;line-height:1.6;color:var(--artifact);max-width:1000px}
.sub{font-family:var(--mono);font-size:10.5px;color:var(--dim);letter-spacing:.06em;
  margin:var(--s5) 0 var(--s2);text-transform:uppercase}
/* ── 通用图容器 ── */
.frame{border:1px solid var(--line);background:var(--surf);margin-bottom:var(--s4)}
.scroll{overflow-x:auto}
.scroll::-webkit-scrollbar{height:9px}
.scroll::-webkit-scrollbar-thumb{background:var(--line);border:2px solid var(--void)}
svg{display:block}
text{font-family:var(--mono);fill:var(--muted)}
/* ── V1 快照卡 ── */
.snap.sel{border-color:var(--agent);box-shadow:0 0 0 1px var(--agent),var(--shadow-card)}
.drillwrap{padding:0 var(--s3) var(--s2)}
.drill{border:1px solid var(--agent);border-left:3px solid var(--agent);background:var(--deep);
  border-radius:6px;overflow:hidden;animation:drillin .18s ease-out}
@keyframes drillin{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:none}}
.drill>header{display:flex;justify-content:space-between;align-items:center;gap:12px;
  padding:10px 14px;border-bottom:1px solid var(--line);background:var(--agent-t1)}
.drill>header b{font-size:14px}
.drill>header span{display:block;font-family:var(--mono);font-size:11px;color:var(--muted);margin-top:3px}
/* 节点横向流：N51→N52 从左到右（**左右视图**），每块底部色条=类别（一眼区分推进）；
   点块在下方展开证据 */
.nflow{display:flex;flex-wrap:wrap;gap:7px;padding:12px 14px}
.ditem{flex:0 0 auto;width:158px;padding:5px 9px 7px;cursor:pointer;
 border:1px solid var(--line2);border-bottom:4px solid var(--dim);border-radius:5px;
 background:var(--surf2)}
.ditem:hover{border-color:var(--agent);transform:translateY(-1px)}
.ditem.sel{border-color:var(--agent);background:var(--agent-t2);
 box-shadow:0 0 0 1px var(--agent)}
.ditem[data-k="advance"]{border-bottom-color:var(--material)}
.ditem[data-k="verify"]{border-bottom-color:var(--ok)}
.ditem[data-k="perceive"]{border-bottom-color:var(--perceive)}
.ditem[data-k="delegate"]{border-bottom-color:var(--dele)}
.ditem[data-k="think"]{border-bottom-color:var(--dim)}
.drow1{display:flex;align-items:baseline;gap:7px}
.drow2{font-size:11.5px;color:var(--ink);line-height:1.45;margin-top:2px;
 display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.dch{display:block;font-family:var(--mono);font-size:10px;color:var(--artifact);
 margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.nt{font-family:var(--mono);font-size:10.5px;color:var(--focus);flex-shrink:0}
.nts{font-family:var(--mono);font-size:10.5px;color:var(--dim);flex-shrink:0}
.nerr{color:var(--error);font-size:11px}
.nout{font-family:var(--mono);font-size:10.5px;color:var(--dim);margin-left:auto}
.ddetail{max-height:520px;overflow-y:auto;padding:12px 16px;border-top:1px solid var(--line)}
.ddh{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:8px;
 border-bottom:1px solid var(--line2);padding-bottom:8px}
.ddh .dn{font-family:var(--mono);font-size:12px;color:var(--focus)}
.ddh .db{font-size:12.5px;color:var(--ink);flex:1;min-width:200px}
.dlegend{display:flex;gap:12px;flex-wrap:wrap;font-family:var(--mono);font-size:10px;
 color:var(--muted);margin-top:5px}
.dlegend i{display:inline-block;width:14px;height:4px;margin-right:5px;vertical-align:2px}
.actd{border:1px solid var(--line2);border-radius:4px;margin:4px 0;background:var(--surf2)}
.actd summary{display:flex;gap:10px;align-items:baseline;padding:5px 10px;cursor:pointer;
  font-family:var(--mono);font-size:10px;color:var(--muted);list-style:none}
.actd summary::-webkit-details-marker{display:none}
.actd summary::before{content:'▸';color:var(--agent2)}
.actd[open] summary::before{content:'▾'}
.actd summary:hover{color:var(--ink)}
.actd .ai{color:var(--agent2);min-width:30px}
.actd .at{color:var(--ink);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.actd .ae{color:var(--error)}
.actd .al{color:var(--dim)}
.actd pre{margin:0;border-top:1px solid var(--line2)}
.snaps{display:flex;gap:0;overflow-x:auto;padding:var(--s3);align-items:stretch}
.snapcol{display:flex;align-items:stretch;flex:0 0 auto}
.snap{flex:0 0 320px;width:320px;min-width:0;border:1px solid var(--line);
  background-color:var(--surf);background-image:linear-gradient(180deg,var(--surf),var(--surf2));
  display:flex;flex-direction:column;cursor:pointer;transition:.14s}
.snap:hover{border-color:var(--agent);transform:translateY(-2px)}
.snap header{padding:10px 12px;border-bottom:1px solid var(--line2);display:flex;
  justify-content:space-between;align-items:baseline;gap:8px}
.snap header b{font-size:13.5px;font-weight:640}
.snap header span{font-family:var(--mono);font-size:10.5px;color:var(--dim);white-space:nowrap}
.states{padding:9px 12px;border-bottom:1px solid var(--line2);font-size:11px;line-height:1.55}
.states .from{color:var(--dim)} .states .to{color:var(--ink)}
.states .arr{color:var(--agent2);margin:0 5px}
.grid8{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--line2);flex:1;min-width:0}
.cell{background:var(--surf);padding:8px 10px;min-height:62px;min-width:0;overflow:hidden}
.cell h5{margin:0 0 5px;font-family:var(--mono);font-size:10px;letter-spacing:.08em;
  color:var(--dim);display:flex;align-items:center;gap:5px}
.cell h5 em{font-style:normal;font-size:9px;padding:1px 4px;border:1px solid var(--line);color:var(--dim)}
.cell.sem h5{color:var(--agent2)} .cell.fact h5{color:var(--focus)}
.cell li{font-size:11.5px;line-height:1.5;color:var(--ink);list-style:none;margin:0 0 3px;
  padding-left:9px;position:relative;overflow:hidden;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.cell li:before{content:"·";position:absolute;left:1px;color:var(--dim)}
.cell ul{margin:0;padding:0}
.cell .empty{font-size:10.5px;color:var(--dim)}
.snap footer{padding:7px 12px;border-top:1px solid var(--line2);display:flex;gap:10px;
  font-family:var(--mono);font-size:10.5px;color:var(--dim);flex-wrap:wrap}
.diff{flex:0 0 78px;width:78px;display:flex;flex-direction:column;align-items:center;justify-content:center;
  gap:4px;font-family:var(--mono);font-size:10.5px;color:var(--dim);flex-shrink:0}
.diff .line{width:100%;height:1px;background:linear-gradient(90deg,transparent,var(--line),transparent)}
.diff .up{color:var(--artifact)} .diff .down{color:var(--ok)} .diff .err{color:var(--error)}
/* ── V3 验证矩阵 ── */
table{border-collapse:collapse;width:100%;font-size:12px}
th{font-family:var(--mono);font-size:10px;letter-spacing:.07em;color:var(--dim);text-align:left;
  padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap;
  background:var(--surf)}
td{padding:7px 10px;border-bottom:1px solid var(--line2);vertical-align:middle}
tr:hover td{background:var(--agent-t1)}
.lv{display:inline-flex;align-items:center;gap:6px;font-family:var(--mono);font-size:10px}
.lvbar{display:flex;gap:2px}
.lvbar i{width:12px;height:9px;background:var(--line);display:block}
.lvbar i.on{background:var(--agent)}
.lvbar i.on0{background:var(--error)}
.mono{font-family:var(--mono);font-size:11.5px}
.tag{display:inline-block;font-family:var(--mono);font-size:10px;padding:1px 6px;border:1px solid var(--line);
  color:var(--muted);margin-right:4px}
.tag.bad{border-color:var(--err-t2);color:var(--error)}
.tag.warn{border-color:var(--art-t2);color:var(--artifact)}
.tag.ok{border-color:var(--ok-t2);color:var(--ok)}
/* ── V4 阀门 ── */
.lanes{padding:var(--s3) 0}
.lane{display:grid;grid-template-columns:120px 1fr;align-items:center;
  border-bottom:1px solid var(--line2)}
.lane .nm{font-family:var(--mono);font-size:10px;color:var(--muted);padding:0 10px}
.blocked{border:1px solid var(--err-t2);background:var(--err-t1);padding:var(--s3);
  margin-bottom:var(--s3)}
.blocked ol{margin:6px 0 0;padding-left:20px}
.blocked li{font-family:var(--mono);font-size:10.5px;line-height:1.75;color:var(--ink)}
.blocked li span{color:var(--dim)}
/* ── 侧栏 ── */
#panel{position:fixed;top:62px;right:12px;bottom:12px;width:430px;max-width:calc(100% - 24px);
  background:var(--panel);border:1px solid var(--line);border-top:2px solid var(--agent);
  border-radius:var(--r2);backdrop-filter:blur(16px);overflow-y:auto;z-index:70;display:none;
  box-shadow:var(--shadow-panel)}
/* 嵌入时页面自己不滚（高度=内容高度），fixed 会把抽屉钉在文档顶端。
   改成 absolute + 父页喂来的可视区，抽屉才像原生抽屉一样浮在眼前那一屏。 */
html[data-embed="1"] #panel{position:absolute;top:var(--panel-top,12px);bottom:auto;
  height:auto;max-height:var(--panel-h,70vh)}   /* 内容短就短，别撑成一根空柱子 */
#panel.open{display:block}
.phead{display:flex;justify-content:space-between;gap:10px;padding:12px 14px;
  border-bottom:1px solid var(--line);position:sticky;top:0;background:var(--surf)}
.pk{font-family:var(--mono);font-size:10px;color:var(--agent2);letter-spacing:.09em;display:block}
.pt{margin:5px 0 0;font-size:15px;line-height:1.3}
.pclose{border:1px solid var(--line);width:26px;height:26px;cursor:pointer;flex-shrink:0}
.pclose:hover{border-color:var(--error);color:var(--error)}
.pb{padding:12px 14px 24px;font-size:12px;line-height:1.65}
.pb h4{margin:15px 0 6px;font-family:var(--mono);font-size:10px;letter-spacing:.1em;color:var(--agent2)}
.pb h4:first-child{margin-top:0}
.kv{display:grid;grid-template-columns:80px 1fr;gap:3px 10px;font-size:11px}
.kv dt{color:var(--dim);font-family:var(--mono);font-size:10.5px}
.kv dd{margin:0}
.ev{display:flex;gap:8px;padding:3px 0;border-bottom:1px solid var(--line2);
  font-family:var(--mono);font-size:11.5px}
.ev .i{color:var(--dim);width:44px;flex-shrink:0}
.ev .r{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--muted)}
.jump{border:1px solid var(--line);padding:3px 8px;cursor:pointer;font-family:var(--mono);
  font-size:10.5px;margin:5px 5px 0 0}
.jump:hover{border-color:var(--agent)}
pre.raw{font-family:var(--mono);font-size:11.5px;line-height:1.6;white-space:pre-wrap;
  word-break:break-word;color:var(--muted);margin:0;max-height:230px;overflow:auto}
/* ── tooltip ── */
.tip{position:fixed;z-index:90;pointer-events:none;background:var(--tip-bg);
  border:1px solid var(--agent);padding:7px 9px;font-family:var(--mono);font-size:10px;
  line-height:1.6;max-width:340px;display:none;box-shadow:var(--shadow-card)}
.tip b{color:var(--artifact)}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-family:var(--mono);font-size:10.5px;
  color:var(--muted);margin:var(--s3) 0}
.legend i,.zlegend i{display:inline-block;width:9px;height:9px;margin-right:5px;
  vertical-align:-1px;border-radius:2px;flex-shrink:0}
.zlegend span{display:flex;align-items:center}
footer.foot{margin:var(--s6) var(--s5) 0;color:var(--dim);font-family:var(--mono);font-size:10.5px;
  line-height:1.8;max-width:1100px;border-top:1px solid var(--line2);padding-top:var(--s3)}
</style></head>
<body>
<div class="top">
  <div class="brand"><b>TRAJECTORY OBSERVATORY</b><span id="bmeta"></span></div>
  <nav id="nav"></nav>
</div>

<section class="view on" id="v1"></section>
<section class="view" id="v2"></section>
<section class="view" id="v3"></section>
<section class="view" id="v4"></section>
<section class="view" id="v5"></section>
<section class="view" id="v6"></section>
<section class="view" id="v7"></section>
<section class="view" id="v8"></section>

<footer class="foot" id="foot"></footer>
<div class="tip" id="tip"></div>
<aside id="panel"><div class="phead"><div><span class="pk" id="pk"></span><h2 class="pt" id="pt"></h2></div>
  <button class="pclose" id="pclose">×</button></div><div class="pb" id="pb"></div></aside>

<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const N = D.nodes.length, PH = D.phases;
const esc = s => String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const cssv = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
/* SVG 的**呈现属性不解析 var()**（Chrome/WebView2 既有限制，写进去既不报错也不生效），
   所以画布上的颜色一律在 JS 里取值：实色走 cssv()，软底走 tint(基色, alpha)。
   反过来说，颜色是被**取值内联**进 DOM 的——换外观必须整页重渲才会跟着变。 */
function tint(name,a){
  const c=cssv(name);
  if(c.charAt(0)==='#'){
    const h=c.slice(1), n6=h.length===3?h[0]+h[0]+h[1]+h[1]+h[2]+h[2]:h.slice(0,6);
    const v=parseInt(n6,16);
    return 'rgba('+((v>>16)&255)+','+((v>>8)&255)+','+(v&255)+','+a+')';
  }
  const m=c.match(/-?[\d.]+/g);
  return (m&&m.length>=3)?'rgba('+m[0]+','+m[1]+','+m[2]+','+a+')':c;
}
/* 嵌入桥：本页在主界面里是 iframe。高度报给父页（父页照着设 iframe 高，
   于是全页只剩一条滚动条），父页把**可视区**喂回来（用来定位钻取抽屉与画布高度，
   否则 fixed 抽屉会钉在一张几千像素高的文档顶端、滚下去就看不见了）。 */
const EMBED = document.documentElement.dataset.embed==='1';
const VIEW = {top:0,height:0};
const fmtS = s => s<60?s+'秒':s<3600?Math.round(s/60)+'分':(s/3600).toFixed(1)+'小时';
const fmtN = n => n>=1e6?(n/1e6).toFixed(1)+'M':n>=1e3?(n/1e3).toFixed(1)+'k':String(n);
const hhmm = t => t?t.slice(11,16):'—';
const KINDZH = {advance:'推进',perceive:'感知',verify:'验证',delegate:'委派',think:'思考'};
const OPZH = {write:'写',read:'读',run:'跑',delegate:'派'};
const svgns='http://www.w3.org/2000/svg';
function el(tag,attrs,parent){const e=document.createElementNS(svgns,tag);
  for(const k in attrs) e.setAttribute(k,attrs[k]); if(parent)parent.appendChild(e); return e;}
function clear(s){while(s.firstChild)s.removeChild(s.firstChild);}
function fitText(str,maxpx,fs){const w=c=>(/[\u3000-\u9fff\uff00-\uffef]/.test(c)?fs:fs*0.56);
  let acc=0,out='';for(const c of String(str)){if(acc+w(c)>maxpx-fs*0.6)return out+'…';acc+=w(c);out+=c;}
  return out;}
function h(tag,cls,html){const e=document.createElement(tag); if(cls)e.className=cls;
  if(html!=null)e.innerHTML=html; return e;}
const tipEl=document.getElementById('tip');
function tip(e,html){tipEl.innerHTML=html;tipEl.style.display='block';
  const r=tipEl.getBoundingClientRect();
  // 嵌入时 iframe 高度=内容高度、页面自己不滚，clientY 就是文档坐标；
  // 下边界要按**父页的可视区**夹，否则提示框会掉到看不见的地方。
  const bot=(EMBED&&VIEW.height)?(VIEW.top+VIEW.height):innerHeight;
  tipEl.style.left=Math.min(e.clientX+14,innerWidth-r.width-10)+'px';
  tipEl.style.top=Math.max(8,Math.min(e.clientY+14,bot-r.height-10))+'px';}
function hideTip(){tipEl.style.display='none';}
function bind(node,html){node.addEventListener('mousemove',e=>tip(e,html));
  node.addEventListener('mouseleave',hideTip);}
const panel=document.getElementById('panel');
function open(k,t,b){document.getElementById('pk').textContent=k;
  document.getElementById('pt').textContent=t;document.getElementById('pb').innerHTML=b;
  panel.classList.add('open');
  panel.querySelectorAll('[data-node]').forEach(x=>x.onclick=()=>openNode(+x.dataset.node));
  panel.querySelectorAll('[data-mat]').forEach(x=>x.onclick=()=>openMat(x.dataset.mat));}
document.getElementById('pclose').onclick=()=>panel.classList.remove('open');
addEventListener('keydown',e=>{if(e.key==='Escape')panel.classList.remove('open');});

const MAT = {}; D.materials.forEach(m=>MAT[m.name]=m);
const VER = {}; D.verify.forEach(v=>VER[v.name]=v);
const phaseOf = i => PH.find(p=>i>=p.from&&i<=p.to) || PH[0];

function openNode(i){
  const n=D.nodes[i], p=phaseOf(i);
  const acts=n.acts.map(a=>'<div class="ev"><span class="i">'+(OPZH[a.op]||a.op)+'</span>'+
    '<span class="r" title="'+esc(a.digest)+'">'+esc(a.target||a.tool||'—')+
    (a.error?' <span style="color:var(--error)">✖</span>':'')+(a.assertive?' <span style="color:var(--ok)">判定</span>':'')+
    '</span></div>').join('');
  open('N'+i+' · '+KINDZH[n.kind]+' · '+hhmm(n.ts)+' · '+p.id+' '+p.name, n.reply?n.reply.slice(0,40):('节点 '+i),
    '<dl class="kv"><dt>动作</dt><dd>'+n.acts.length+' 个</dd>'+
    '<dt>思考</dt><dd>'+(n.think?n.think+' 字':
      (D.meta.union.thinking_blocks_all>0
        ?'<span style="color:var(--dim)">块存在，明文未回传</span>':'无'))+'</dd>'+
    '<dt>本步成本</dt><dd>out '+fmtN(n.cost.out)+' · ttft '+n.cost.ttft+'ms · 在途 '+
      (n.cost.total_ms/1000).toFixed(1)+'s</dd>'+
    '<dt>当前债</dt><dd>'+D.debt[i].n+'</dd></dl>'+
    '<h4>动作</h4>'+(acts||'<p style="color:var(--dim)">纯思考</p>')+
    (n.changes.length?'<h4>写出</h4>'+n.changes.map(t=>'<span class="tag warn" data-mat="'+esc(t)+'">'+esc(t)+'</span>').join(''):'')+
    (n.verified.length?'<h4>验证</h4>'+n.verified.map(t=>'<span class="tag ok" data-mat="'+esc(t)+'">'+esc(t)+'</span>').join(''):'')+
    (n.reply?'<h4>回复片段</h4><pre class="raw">'+esc(n.reply)+'</pre>':''));
}
function openMat(name){
  const m=MAT[name]; if(!m) return;
  const v=VER[name];
  const evs=m.events.map(e=>'<div class="ev"><span class="i" data-node="'+e.i+'" style="cursor:pointer;color:var(--focus)">N'+e.i+'</span>'+
    '<span class="r">'+(OPZH[e.op]||e.op)+(e.clears?'·验':'')+(e.assertive?'·判定':'')+
    (e.error?' ✖':'')+' — '+esc(e.digest||e.tool||'')+'</span></div>').join('');
  const anc=D.provenance.filter(p=>p.to===name), des=D.provenance.filter(p=>p.from===name);
  open('物料 · '+m.class+' · N'+m.first+'–N'+m.last, name,
    '<dl class="kv"><dt>写</dt><dd>'+m.writes+'</dd><dt>读</dt><dd>'+m.reads+'</dd>'+
    '<dt>跑</dt><dd>'+m.runs+'</dd><dt>失败</dt><dd>'+m.fails+'</dd>'+
    (v?'<dt>验证</dt><dd>L'+v.level+' '+esc(v.why)+(v.age_nodes!=null?'（写后 '+v.age_nodes+' 个节点、'+fmtS(v.age_seconds)+'）':'')+'</dd>':'')+
    '</dl>'+
    '<h4>它由什么来（'+anc.length+'）</h4>'+(anc.length?[...new Set(anc.map(a=>a.from))].map(t=>'<span class="tag" data-mat="'+esc(t)+'">'+esc(t)+'</span>').join(''):'<span style="color:var(--error)">无源产物——写出前没读过任何输入</span>')+
    '<h4>它喂了谁（'+des.length+'）</h4>'+(des.length?[...new Set(des.map(a=>a.to))].map(t=>'<span class="tag" data-mat="'+esc(t)+'">'+esc(t)+'</span>').join(''):'<span style="color:var(--dim)">没有下游</span>')+
    '<h4>它的一生</h4>'+evs);
}
__VIEWS__
/* ── 导航 ── */
const VIEWS=[['v1','状态快照','世界变成了什么样'],['v2','物料血统','产物由什么支撑'],
             ['v3','验证矩阵','质检站够不够硬'],['v4','阀门与回路','什么在控制流向'],
             ['v5','能耗与方差','代价与瓶颈'],
             ['v6','最优轨迹','这趟本可以怎么走'],
             ['v7','物料生命线','一件物料的一生与未验债'],
             ['v8','最优时序图','节点—连线的反事实时序']];
const nav=document.getElementById('nav');
let curView=0;
VIEWS.forEach(([id,name,desc],k)=>{
  const b=h('button','tab','<i>V'+(k+1)+'</i>'+name);
  b.setAttribute('aria-selected', k===0?'true':'false');
  b.title=desc;
  b.onclick=()=>{VIEWS.forEach(([i2],k2)=>{
      document.getElementById(i2).classList.toggle('on',k2===k);
      nav.children[k2].setAttribute('aria-selected',k2===k?'true':'false');});
    curView=k;
    // **显示之后再画**：视图隐藏时 clientWidth 是 0，首屏一次性渲染会让所有图
    // 退到 900px 兜底宽度（实测 V5 只用了一半画布）。
    redrawView(k);
    // 嵌入时自己滚不动（高度=内容高度），要请父页把这块滚到顶上
    if(EMBED) parent.postMessage({t:'ccwa-traj-top'},'*');
    else scrollTo({top:0,behavior:'smooth'});};
  nav.appendChild(b);
});
document.getElementById('bmeta').textContent =
  D.meta.sid+' · '+D.meta.union.actions+' 动作 · '+N+' 节点 · '+PH.length+' 阶段 · '+fmtS(D.meta.wall_seconds);
const PM=D.phase_meta||{}, LONG=D.meta.union.longest_actions;
document.getElementById('foot').innerHTML =
  '数据：会话 '+D.meta.sid+'（'+D.meta.date+'）· 主线 '+D.meta.requests.main+' 请求 + 子代理 '+
  D.meta.requests.subagent+' + 安检 '+D.meta.requests.security+
  '。由 '+esc(D.meta.generated_by||'cc-wire-analyzer')+' 算出。'+
  (D.meta.compact_at
    ? '<br>本页地基是<b style="color:var(--ink)">全部主线请求的 blocks 并集</b>，不是单条最长请求：autocompact 于 '+
      hhmm(D.meta.compact_at)+' 剪掉了前半段历史'+
      (LONG?'，只看最长请求只剩 '+LONG+' 个工具调用（并集 '+D.meta.union.actions+'）':'')+'。'
    : '<br>本页地基是<b style="color:var(--ink)">全部主线请求的 blocks 并集</b>（本会话未发生 autocompact，最长请求即全史）。')+
  '<br>事实层（动作/物料/血统/验证等级/阀门/成本）全部程序算；'+
  (PM.source==='model'
    ? '语义层只有阶段名与状态快照的 known/assumed/unknown/decisions 四格由模型产出（'+
      PM.candidates+' 个程序候选边界里取舍'+(PM.seconds?'，用时 '+PM.seconds+' 秒':'')+
      '，程序校验覆盖），artifacts/pending/errors/constraints 四格由程序覆盖模型输出。'
    : '<b style="color:var(--artifact)">语义层尚未归纳</b>：阶段是 '+PM.candidates+
      ' 个候选边界的机械划分、节点简述是程序标签，八元组里的语义四格为空。点「AI 归纳」升级。');
renderAll();
function redrawView(k){
  if(k===1) drawDag();
  else if(k===3){ drawValves(); drawLoops(); }
  else if(k===4){ drawPhaseBars(); drawLatency(); }
  else if(k===5){ drawCompare(); drawPhaseNec(); }
  else if(k===6 && !v7done){ renderV7(); v7done=true; }
  else if(k===7 && !v8done){ renderV8(); v8done=true; }
}
addEventListener('resize',()=>{redrawView(curView);});

/* ── 外观即时切换 ──
   父页同源直接调 ccwaTrajTheme(t)，或 postMessage 过来。**不能 reload**：
   payload 内嵌在本页里，reload 等于让服务端重算一遍（~20s）。
   必须整页重渲：颜色被 cssv()/tint() 取值内联进了 DOM 与 SVG 属性，
   光换 data-theme 只改到 CSS 变量那一半，图上的颜色不会动。 */
window.ccwaTrajTheme=function(t){
  if(!/^(dark|classic|light)$/.test(t||'')) return;
  const r=document.documentElement;
  if(r.dataset.theme===t) return;
  r.dataset.theme=t; r.style.colorScheme=(t==='dark')?'dark':'light';
  document.getElementById('panel').classList.remove('open');
  drillOpen=null; v7done=false; v8done=false;
  renderAll(); redrawView(curView); applyViewport();
};
/* ── 嵌入桥的另一半：报高度 / 收可视区 ── */
function postHeight(){
  if(!EMBED) return;
  parent.postMessage({t:'ccwa-traj-height',
    h:Math.ceil(document.documentElement.scrollHeight)},'*');
}
function applyViewport(){
  if(!EMBED||!VIEW.height) return;
  const r=document.documentElement.style;
  r.setProperty('--panel-top',(VIEW.top+12)+'px');
  r.setProperty('--panel-h',Math.max(VIEW.height-24,260)+'px');
  r.setProperty('--stage-h',Math.max(Math.min(VIEW.height-140,780),380)+'px');
}
if(EMBED){
  addEventListener('message',e=>{
    const d=e.data||{};
    if(d.t==='ccwa-traj-viewport'){
      VIEW.top=d.top||0; VIEW.height=d.height||0;
      applyViewport();
    }else if(d.t==='ccwa-traj-theme'){ window.ccwaTrajTheme(d.theme); }
  });
  try{ new ResizeObserver(postHeight).observe(document.documentElement); }
  catch(_){ addEventListener('resize',postHeight); }
  postHeight();
}
</script></body></html>
"""

VIEWS = r"""
/* ══════════ V1 状态快照序列 ══════════ */
function renderV1(){
  const v=document.getElementById('v1');
  const totalArt=new Set(), totalErr=D.valves.filter(x=>x.kind==='tool_error').length;
  PH.forEach(p=>p.artifacts.forEach(a=>totalArt.add(a)));
  v.innerHTML='<div class="eyebrow">VIEW 1 · STATE SNAPSHOT SEQUENCE</div>'+
    '<h1>状态快照序列：世界在每个阶段前后是什么样</h1>'+
    '<p class="lede">流水线是它自己长出来的，所以不能按「它做了什么」读，要按<b>状态换了几档</b>读。'+
    '每张卡是一个阶段结束时的世界：上排四格是<b>语义</b>（模型从轨迹里读出来的），'+
    '下排四格是<b>事实</b>（程序从录制里算出来的，模型改不了）。卡与卡之间那一列是 <b>State Diff</b>——'+
    '真正的「工序」就发生在那里。<code>assumed</code> 一格最值得盯：返工几乎都由未验证的假设引起。</p>'+
    '<div class="stats">'+
      stat(PH.length,'个阶段')+stat(N,'个节点')+stat(D.meta.union.actions,'个动作')+
      stat(totalArt.size,'件产物')+stat(D.debt[N-1].n,'件写完没验','warn')+
      stat(totalErr,'次失败','bad')+stat(fmtS(D.meta.wall_seconds),'跨度')+
    '</div>'+
    '<div class="frame"><div class="snaps" id="snaps"></div></div>'+
    '<div class="drillwrap" id="drillwrap"></div>'+
    '<div class="legend">'+
      lg('--agent2','语义格：模型读出来的')+lg('--focus','事实格：程序算出来的')+
      lg('--artifact','债增加')+lg('--ok','债清偿')+lg('--error','失败')+'</div>';
  const host=document.getElementById('snaps');
  PH.forEach((p,k)=>{
    if(k){
      const prev=PH[k-1], d=p.debt_out-prev.debt_out;
      const col=h('div','diff','<div class="line"></div>'+
        '<div>'+(p.artifacts.length?'+'+p.artifacts.length+' 产物':'—')+'</div>'+
        '<div class="'+(d>0?'up':d<0?'down':'')+'">'+(d>0?'债 +'+d:d<0?'债 '+d:'债 ±0')+'</div>'+
        (p.errors?'<div class="err">'+p.errors+' 失败</div>':'')+
        '<div class="line"></div>');
      host.appendChild(col);
    }
    const c=h('div','snapcol'); const card=h('div','snap');
    card.innerHTML=
      '<header><b>'+esc(p.id+' '+p.name)+'</b><span>N'+p.from+'–'+p.to+' · '+fmtS(p.seconds)+'</span></header>'+
      '<div class="states"><span class="from">'+esc(p.from_state)+'</span>'+
        '<span class="arr">→</span><span class="to">'+esc(p.to_state)+'</span></div>'+
      '<div class="grid8">'+
        cell('已知','sem',p.known)+cell('假设','sem',p.assumed)+
        cell('未知','sem',p.unknown)+cell('决策','sem',p.decisions)+
        cell('产物','fact',p.artifacts,'程序')+cell('未验','fact',p.pending,'程序')+
        cell('失败','fact',p.errors_detail,'程序')+cell('约束/发话','fact',p.user_said.map(s=>s.slice(0,60)),'程序')+
      '</div>'+
      '<footer><span>out '+fmtN(p.cost.out)+'</span><span>在途 '+fmtS(Math.round(p.cost.model_ms/1000))+'</span>'+
        '<span>债 '+p.debt_in+'→'+p.debt_out+'</span>'+(p.blocked.length?'<span style="color:var(--error)">拦截 '+p.blocked.length+'</span>':'')+
        (p.off_candidate?'<span style="color:var(--artifact)">非候选切点</span>':'')+'</footer>';
    card.onclick=()=>toggleDrill(p,k,card);
    c.appendChild(card); host.appendChild(c);
  });
}

/* ── V1 钻取：点快照卡就地展开这个阶段的节点序列，节点行再点开证据 ──
   用户反馈「点击每个快照序列后最好能进一步展开，而不是纯粹面板」——
   面板装不下一个阶段的 50 个节点，就地展开才有「钻进去」的层次感：
   阶段卡 → 节点行（一句话简述）→ 动作证据（命令/返回原文）。 */
let drillOpen=null;
function toggleDrill(p,k,card){
  const wrap=document.getElementById('drillwrap');
  document.querySelectorAll('.snap.sel').forEach(x=>x.classList.remove('sel'));
  if(drillOpen===k){wrap.innerHTML='';drillOpen=null;return;}
  drillOpen=k; card.classList.add('sel');
  const ns=D.nodes.slice(p.from,p.to+1);
  const writes=ns.reduce((a,n)=>a+n.changes.length,0);
  const errs=ns.filter(n=>n.error).length;
  const kcnt={}; ns.forEach(n=>kcnt[n.kind]=(kcnt[n.kind]||0)+1);
  wrap.innerHTML='<div class="drill">'+
    '<header><div><b>'+esc(p.id+' '+p.name)+'</b>'+
      '<span>N'+p.from+'–'+p.to+' · '+fmtS(p.seconds)+' · '+ns.length+' 节点 · 写 '+writes+
      (errs?' · 失败 '+errs:'')+'</span>'+
      '<div class="dlegend">'+
        [['advance','推进'],['perceive','感知'],['verify','验证'],['delegate','派发'],['think','思考']]
        .map(([kk,zh])=>'<span><i data-k="'+kk+'"></i>'+zh+(kcnt[kk]||0)+'</span>').join('')+
      '</div></div>'+
      '<button class="jump" id="drillPanel">完整八元组面板</button></header>'+
    '<div class="nflow" id="dlist"></div>'+
    '<div class="ddetail" id="ddetail"></div></div>';
  // 图例色块与条目底部色块同一套颜色
  wrap.querySelectorAll('.dlegend i').forEach(i=>{
    const c={advance:'--material',verify:'--ok',perceive:'--perceive',
             delegate:'--dele',think:'--dim'}[i.dataset.k];
    i.style.background=cssv(c||'--dim');});
  const list=document.getElementById('dlist');
  function selNode(n,it){
    document.querySelectorAll('.ditem.sel').forEach(x=>x.classList.remove('sel'));
    it.classList.add('sel');
    const det=(D.details||{})['main:'+n.i]||{};
    const acts=(det.acts&&det.acts.length?det.acts:n.acts).map(a=>
      '<details class="actd"><summary><span class="ai">'+(OPZH[a.op]||a.op)+'</span>'+
      '<span class="at">'+esc(a.tool||'')+' '+esc(a.target||'')+'</span>'+
      (a.error||a.err?'<span class="ae">✖ 出错</span>':'')+
      '<span class="al">'+((a.raw_len!=null?a.raw_len:(a.digest||'').length)||0)+' 字</span></summary>'+
      ((a.prompt||a.cmd||a.args)?'<pre class="raw">'+esc(a.prompt||a.cmd||a.args)+'</pre>':'')+
      ((a.raw||a.digest)?'<pre class="raw">'+esc(a.raw||a.digest)+'</pre>':'')+
      '</details>').join('');
    const de=document.getElementById('ddetail');
    de.innerHTML='<div class="ddh"><span class="dn">N'+n.i+'</span>'+
      '<span class="nts">'+hhmm(n.ts)+'</span>'+
      (n.error?'<span class="nerr">✖ 出错</span>':'')+
      '<span class="nout">out '+fmtN(n.cost.out)+'</span>'+
      '<span class="db">'+esc(n.brief||('写 '+n.changes.join('、'))||'纯思考')+'</span></div>'+
      (det.think?'<details class="actd" open><summary><span class="ai">思考</span><span class="at">'+det.think.length+' 字</span></summary><pre class="raw">'+esc(det.think)+'</pre></details>':'')+
      (det.reply?'<details class="actd"><summary><span class="ai">回复</span><span class="at">'+det.reply.length+' 字</span></summary><pre class="raw">'+esc(det.reply)+'</pre></details>':'')+
      '<h4 style="margin:10px 0 4px">动作与返回原文</h4>'+(acts||'<div class="empty">纯思考，无动作</div>');
    de.scrollTop=0;
  }
  ns.forEach(n=>{
    const it=h('div','ditem'); it.dataset.k=n.kind;
    const lab=n.brief||('写 '+n.changes.join('、'))||'纯思考';
    it.title=lab+(n.changes.length?'（写 '+n.changes.join('、')+'）':'');
    it.innerHTML='<div class="drow1"><span class="nt">N'+n.i+'</span>'+
      '<span class="nts">'+hhmm(n.ts)+'</span>'+
      (n.error?'<span class="nerr">✖</span>':'')+
      '<span class="nout">out '+fmtN(n.cost.out)+'</span></div>'+
      '<div class="drow2">'+esc(lab)+'</div>'+
      (n.changes.length?'<span class="dch">写 '+n.changes.map(t=>esc(t)).join('、')+'</span>':'');
    it.onclick=()=>selNode(n,it);
    list.appendChild(it);
  });
  // 默认选第一个有写出的节点：钻取通常为了看「推进」
  const fi=Math.max(ns.findIndex(n=>n.changes.length),0);
  selNode(ns[fi], list.children[fi]);
  document.getElementById('drillPanel').onclick=()=>openPhase(p);
  wrap.scrollIntoView({behavior:'smooth',block:'nearest'});
}
function cell(t,cls,arr,badge){
  arr=arr||[];
  return '<div class="cell '+cls+'"><h5>'+t+(badge?' <em>'+badge+'</em>':'')+'</h5>'+
    (arr.length?'<ul>'+arr.slice(0,4).map(x=>'<li title="'+esc(x)+'">'+esc(x)+'</li>').join('')+'</ul>'
              :'<div class="empty">—</div>')+'</div>';
}
function stat(v,k,cls){return '<div class="stat '+(cls||'')+'"><div class="v">'+v+'</div><div class="k">'+k+'</div></div>';}
function lg(c,t){return '<span><i style="background:'+cssv(c)+'"></i>'+t+'</span>';}
function openPhase(p){
  const ns=D.nodes.slice(p.from,p.to+1);
  open('阶段 '+p.id+' · N'+p.from+'–'+p.to+' · '+hhmm(p.ts[0])+'–'+hhmm(p.ts[1]), p.name,
    '<dl class="kv"><dt>起点</dt><dd>'+esc(p.from_state)+'</dd><dt>终点</dt><dd>'+esc(p.to_state)+'</dd>'+
    '<dt>耗时</dt><dd>'+fmtS(p.seconds)+'（模型在途 '+fmtS(Math.round(p.cost.model_ms/1000))+'）</dd>'+
    '<dt>成本</dt><dd>out '+fmtN(p.cost.out)+' · in '+fmtN(p.cost['in'])+' · cache '+fmtN(p.cost.cache_read)+'</dd>'+
    '<dt>未验债</dt><dd>'+p.debt_in+' → '+p.debt_out+'</dd>'+
    '<dt>构成</dt><dd>'+Object.entries(p.kinds).filter(([,c])=>c).map(([k,c])=>KINDZH[k]+' '+c).join(' · ')+'</dd></dl>'+
    (p.user_said.length?'<h4>这一阶段人说了什么</h4>'+p.user_said.map(s=>'<pre class="raw">'+esc(s)+'</pre>').join(''):'')+
    (p.blocked.length?'<h4>被拦截</h4>'+p.blocked.map(s=>'<div class="ev"><span class="r" style="color:var(--error)">'+esc(s)+'</span></div>').join(''):'')+
    (p.errors_detail.length?'<h4>失败</h4>'+p.errors_detail.map(s=>'<div class="ev"><span class="r">'+esc(s)+'</span></div>').join(''):'')+
    '<h4>产物</h4>'+(p.artifacts.map(t=>'<span class="tag warn" data-mat="'+esc(t)+'">'+esc(t)+'</span>').join('')||'—')+
    '<h4>节点</h4>'+ns.map(n=>'<button class="jump" data-node="'+n.i+'">N'+n.i+' '+KINDZH[n.kind]+'</button>').join(''));
}

/* ══════════ V2 物料血统 DAG ══════════ */
let v2mode='file';
function renderV2(){
  const v=document.getElementById('v2');
  v.innerHTML='<div class="eyebrow">VIEW 2 · PROVENANCE</div>'+
    '<h1>物料血统：每件产物由什么支撑</h1>'+
    '<p class="lede">生命线回答「一件物料的一生」，血统回答<b>「谁生了谁」</b>——多出来的那一维是因果。'+
    '边的判据是纯程序的：一次写入的来源，是它<b>前 5 个节点内读到过的东西</b>（读完想一想再写，是最常见的形态）。'+
    '两个报警项：<b>无源产物</b>（写出前没读过任何输入，凭空写的）与<b>孤儿证据</b>（读进来却没喂给任何产出）。</p>'+
    '<div class="stats">'+
      stat(D.provenance.length,'条血统边')+
      stat(D.sourceless.length,'件无源产物',D.sourceless.length?'bad':'ok')+
      stat(D.orphan_reads.length,'件孤儿证据','warn')+
      stat(D.materials.filter(m=>m.class==='file').length,'件文件物料')+
      stat(D.verify.length,'件被写过的产物')+
    '</div>'+
    (D.sourceless.length?'<p class="note">无源产物：'+D.sourceless.map(s=>esc(s.target)+'（N'+s.node+'）').join('、')+'</p>':'')+
    '<div class="sub">血统图 · 横轴是首次出现的节点序，点击任一物料看它的上下游</div>'+
    '<div class="frame scroll" id="dagWrap"><svg id="dag"></svg></div>'+
    '<div class="legend">'+lg('--material','产物（被写过）')+lg('--perceive','证据（只读）')+
      lg('--error','无源产物')+lg('--dim','孤儿证据')+'</div>';
  drawDag();
}
function drawDag(){
  const svg=document.getElementById('dag');
  clear(svg);
  const names=new Set();
  D.provenance.forEach(e=>{names.add(e.from);names.add(e.to);});
  D.sourceless.forEach(s=>names.add(s.target));
  const list=[...names].map(n=>MAT[n]).filter(Boolean)
    .sort((a,b)=>a.first-b.first||a.name.localeCompare(b.name));
  const COLW=176, ROWH=30, PADX=18, PADY=26;
  // 列 = 首次出现所在阶段；行 = 列内顺序
  const colOf={}, cols={};
  list.forEach(m=>{const p=phaseOf(m.first); colOf[m.name]=PH.indexOf(p);
    (cols[colOf[m.name]]=cols[colOf[m.name]]||[]).push(m.name);});
  const pos={};
  Object.entries(cols).forEach(([c,arr])=>arr.forEach((n,i)=>{
    pos[n]={x:PADX+(+c)*COLW, y:PADY+i*ROWH};}));
  const maxRow=Math.max(...Object.values(cols).map(a=>a.length));
  const W=PADX*2+PH.length*COLW, H=PADY+maxRow*ROWH+30;
  svg.setAttribute('width',W); svg.setAttribute('height',H);
  PH.forEach((p,k)=>{
    el('line',{x1:PADX+k*COLW-9,y1:8,x2:PADX+k*COLW-9,y2:H-8,
      stroke:cssv('--grid'),'stroke-dasharray':'2 4'},svg);
    el('text',{x:PADX+k*COLW,y:16,'font-size':10,fill:cssv('--agent')},svg).textContent=p.id+' '+p.name;
  });
  const seen=new Set();
  D.provenance.forEach(e=>{
    const a=pos[e.from], b=pos[e.to]; if(!a||!b) return;
    const key=e.from+'>'+e.to; if(seen.has(key)) return; seen.add(key);
    const x1=a.x+150, y1=a.y+10, x2=b.x, y2=b.y+10;
    el('path',{d:'M '+x1+' '+y1+' C '+(x1+38)+' '+y1+' '+(x2-38)+' '+y2+' '+x2+' '+y2,
      fill:'none',stroke:tint('--material',.45),'stroke-width':1,'stroke-opacity':.45,
      'data-from':e.from,'data-to':e.to,class:'pedge'},svg);
  });
  const sourceless=new Set(D.sourceless.map(s=>s.target));
  const orphan=new Set(D.orphan_reads);
  list.forEach(m=>{
    const p=pos[m.name], v=VER[m.name];
    const g=el('g',{},svg); g.style.cursor='pointer';
    g.onclick=()=>openMat(m.name);
    const col=sourceless.has(m.name)?cssv('--error'):m.writes?cssv('--material'):
              orphan.has(m.name)?cssv('--dim'):cssv('--perceive');
    el('rect',{x:p.x,y:p.y,width:150,height:20,rx:2,fill:cssv('--sheet'),
      stroke:col,'stroke-width':sourceless.has(m.name)?1.6:1},g);
    const t=el('text',{x:p.x+6,y:p.y+14,'font-size':10.5,fill:cssv('--ink')},g);
    t.textContent=fitText(m.name,(v?116:138),10.5);   /* 有 L0 徽标时给它留出 22px */
    if(v) el('text',{x:p.x+144,y:p.y+14,'font-size':10,'text-anchor':'end',
      fill:v.level>=2?cssv('--ok'):cssv('--artifact')},g).textContent='L'+v.level;
    g.addEventListener('mouseenter',()=>hiEdges(m.name));
    g.addEventListener('mouseleave',()=>hiEdges(null));
    bind(g,'<b>'+esc(m.name)+'</b><br>写 '+m.writes+' · 读 '+m.reads+' · 跑 '+m.runs+
      (v?'<br>验证 L'+v.level+' '+esc(v.why):'')+
      (sourceless.has(m.name)?'<br><span style="color:var(--error)">无源产物</span>':'')+
      (orphan.has(m.name)?'<br><span style="color:var(--dim)">孤儿证据：没喂给任何产出</span>':''));
  });
}

function hiEdges(name){
  document.querySelectorAll('#dag .pedge').forEach(e=>{
    const hit = !name || e.dataset.from===name || e.dataset.to===name;
    e.setAttribute('stroke-opacity', name ? (hit?.95:.06) : .45);
    e.setAttribute('stroke-width', name && hit ? 1.8 : 1);
  });
}

/* ══════════ V3 验证矩阵 ══════════ */
function renderV3(){
  const v=document.getElementById('v3');
  const byLv={}; D.verify.forEach(x=>byLv[x.level]=(byLv[x.level]||0)+1);
  const LVTXT=['L0 写完即走','L1 写后回读','L2 写后重跑','L3 结果有判定','L4 外部核对'];
  const rows=D.verify.map(x=>{
    const m=MAT[x.name]||{};
    return '<tr><td class="mono" style="cursor:pointer" data-mat="'+esc(x.name)+'">'+esc(x.name)+'</td>'+
      '<td><span class="lv"><span class="lvbar">'+[0,1,2,3,4].map(i=>
        '<i class="'+(i<=x.level?(x.level===0?'on0':'on'):'')+'"></i>').join('')+
        '</span>L'+x.level+'</span></td>'+
      '<td class="mono" style="color:var(--muted)">'+esc(x.why)+'</td>'+
      '<td class="mono">'+x.writes+'</td>'+
      '<td class="mono">'+(x.age_nodes!=null?x.age_nodes+' 节点 / '+fmtS(x.age_seconds):'<span style="color:var(--error)">未验</span>')+'</td>'+
      '<td class="mono">'+((x.fails?'<span class="tag bad">'+x.fails+' 次失败</span>':'')+
        ((m.assertive||0)?'<span class="tag ok">'+m.assertive+' 次判定结果</span>':'')||
        '<span style="color:var(--dim)">—</span>')+'</td></tr>';
  }).join('');
  v.innerHTML='<div class="eyebrow">VIEW 3 · VERIFICATION</div>'+
    '<h1>验证矩阵：质检站在哪、够不够硬</h1>'+
    '<p class="lede">「验没验」不够用，要问<b>验的强度</b>：回读一遍只证明文件存在，重跑才证明能跑，'+
    '结果里有 <code>PASS</code>/<code>Traceback</code>/退出码才<b>可证伪</b>，子代理事后核对才是外部证据。'+
    '判据与产品 <code>_turn_facts</code> 同源：写只认 <code>write</code>，写过之后被读过或跑过即验过；'+
    '本表按最后一次写之后发生的事定级。<b>债龄</b>是写完到验过之间隔了多远——比债的数量更能说明问题。</p>'+
    '<div class="stats">'+
      [0,1,2,3,4].map(i=>stat(byLv[i]||0,LVTXT[i],i===0?'bad':i>=3?'ok':'warn')).join('')+
      stat(D.verify.length,'件产物')+
    '</div>'+
    '<div class="frame scroll"><table><thead><tr><th>产物</th><th>验证等级</th><th>判据</th>'+
      '<th>写入次数</th><th>债龄（写完→验过，未验标红）</th><th>信号</th></tr></thead><tbody>'+rows+
      '</tbody></table></div>'+
    '<p class="note">L0 的 '+(byLv[0]||0)+' 件是这次运行的真实风险面：写出去之后，一次都没有被读回、跑过或核对过。</p>';
  v.querySelectorAll('[data-mat]').forEach(x=>x.onclick=()=>openMat(x.dataset.mat));
}

/* ══════════ V4 阀门与回路 ══════════ */
function renderV4(){
  const v=document.getElementById('v4');
  const sec=D.valves.filter(x=>x.kind==='security');
  const blocked=sec.filter(x=>x.blocked);
  const errs=D.valves.filter(x=>x.kind==='tool_error');
  const users=D.valves.filter(x=>x.kind==='user');
  const secMs=sec.reduce((a,b)=>a+(b.ms||0),0);
  v.innerHTML='<div class="eyebrow">VIEW 4 · VALVES &amp; LOOPS</div>'+
    '<h1>阀门与回路：什么在控制流向</h1>'+
    '<p class="lede">自己长出来的流水线，唯一的外部约束就是阀门。这里把四类阀门放在同一条真实时间轴上：'+
    '<b>安检</b>（每条 shell 命令都过闸）、<b>失败</b>（环境打回）、<b>人</b>（改方向）、'+
    '<b>上下文</b>（compact 剪掉历史）。下方是<b>返工回路</b>——同一件物料被反复重写而中间没有验证。</p>'+
    '<div class="stats">'+
      stat(sec.length,'次安检')+stat(blocked.length,'次拦截',blocked.length?'bad':'ok')+
      stat(errs.length,'次工具失败','warn')+stat(users.length,'次人工介入')+
      stat(D.loops.filter(l=>l.kind!=='valve_loop').length,'个返工回路','warn')+
      stat(fmtS(Math.round(secMs/1000)),'安检在途')+
    '</div>'+
    (blocked.length?'<div class="blocked"><b style="font-size:12.5px">被拦截后的连试：一个由阀门驱动的回路</b>'+
      '<div style="font-family:var(--mono);font-size:10px;color:var(--dim);margin-top:4px">'+
      hhmm(blocked[0].ts)+' → '+hhmm(blocked[blocked.length-1].ts)+' · '+
      fmtS(Math.round((new Date(blocked[blocked.length-1].ts)-new Date(blocked[0].ts))/1000))+
      ' · 类别：'+esc(blocked.find(b=>b.category)?.category||'—')+'</div>'+
      '<ol>'+blocked.map(b=>'<li><span>'+hhmm(b.ts)+'</span> '+esc(b.arg.slice(0,110))+'</li>').join('')+'</ol>'+
      '<div style="font-size:11px;color:var(--muted);margin-top:8px;line-height:1.6">'+
      esc(blocked.find(b=>b.reason)?.reason||'')+'</div>'+
      (D.meta.compact_at
        ? '<div style="font-size:11px;color:var(--artifact);margin-top:8px">⚠ 这一整段发生在 '+
          hhmm(D.meta.compact_at)+' 的 compact 之前——只看单条最长请求的话，它整段都不在。</div>'
        : '')+'</div>':'')+
    '<div class="sub">阀门时间轴 · 横轴真实时间</div>'+
    '<div class="frame scroll" id="valveWrap"><svg id="valves"></svg></div>'+
    '<div class="sub">返工回路 · 同一物料被反复重写</div>'+
    '<div class="frame" id="loopWrap"><svg id="loops"></svg></div>';
  drawValves(); drawLoops();
}
function drawValves(){
  const svg=document.getElementById('valves');
  const wrap=document.getElementById('valveWrap');
  clear(svg);
  const W=Math.max(wrap.clientWidth-2, 900), LANES=[
    ['user','人工介入','--focus'],['security','安检','--perceive'],['tool_error','工具失败','--error'],
    ['delegate','委派','--dele'],['compact','上下文','--artifact'],['status','状态通知','--dim']];
  const RH=30, H=LANES.length*RH+30, PADL=104, PADR=14;
  svg.setAttribute('width',W); svg.setAttribute('height',H);
  const T0=new Date(D.meta.span[0]).getTime(), T1=new Date(D.meta.span[1]).getTime();
  const X=t=>PADL+((new Date(t).getTime()-T0)/(T1-T0))*(W-PADL-PADR);
  LANES.forEach(([kind,name,col],li)=>{
    const y=14+li*RH+RH/2;
    el('line',{x1:PADL,y1:y,x2:W-PADR,y2:y,stroke:cssv('--line2')},svg);
    el('text',{x:PADL-10,y:y+3.5,'font-size':10.5,'text-anchor':'end'},svg).textContent=name;
    const evs=D.valves.filter(x=>x.kind===kind);
    if(!evs.length) el('text',{x:PADL+8,y:y+3.5,'font-size':10,fill:cssv('--dim'),
      'fill-opacity':.75},svg).textContent='本次运行没有这一类阀门';
    evs.forEach(e=>{
      const x=X(e.ts), blocked=e.kind==='security'&&e.blocked;
      const g=el('g',{},svg); g.style.cursor='pointer';
      if(blocked){
        el('rect',{x:x-3,y:y-9,width:6,height:18,fill:cssv('--error')},g);
      } else if(kind==='user'){
        el('path',{d:'M '+x+' '+(y-7)+' L '+(x+5)+' '+y+' L '+x+' '+(y+7)+' L '+(x-5)+' '+y+' Z',
          fill:cssv(col)},g);
      } else {
        el('circle',{cx:x,cy:y,r:kind==='status'?1.4:3,fill:cssv(col),
          'fill-opacity':kind==='security'?.5:.95},g);
      }
      bind(g,'<b>'+name+'</b> '+hhmm(e.ts)+(blocked?' <span style="color:var(--error)">拦截</span>':'')+
        (e.category?'<br>'+esc(e.category):'')+
        (e.arg?'<br>'+esc(e.arg.slice(0,120)):'')+(e.detail?'<br>'+esc(String(e.detail).slice(0,150)):'')+
        (e.ms?'<br>闸口耗时 '+(e.ms/1000).toFixed(1)+'s':''));
      if(e.node!=null) g.onclick=()=>openNode(e.node);
    });
  });
  // 阶段分隔
  PH.forEach((p,k)=>{ if(!k) return;
    const x=X(p.ts[0]);
    el('line',{x1:x,y1:8,x2:x,y2:H-16,stroke:tint('--agent',.32),'stroke-dasharray':'2 3'},svg);
    el('text',{x:x+3,y:H-6,'font-size':10,fill:cssv('--agent')},svg).textContent=p.id;
  });
  el('text',{x:PADL,y:H-6,'font-size':10},svg).textContent=hhmm(D.meta.span[0]);
  el('text',{x:W-PADR,y:H-6,'font-size':10,'text-anchor':'end'},svg).textContent=hhmm(D.meta.span[1]);
}
function drawLoops(){
  const svg=document.getElementById('loops');
  const wrap=document.getElementById('loopWrap');
  clear(svg);
  const loops=D.loops.filter(l=>l.from!=null).sort((a,b)=>a.from-b.from);
  const W=Math.max(wrap.clientWidth-2,900), RH=26, H=loops.length*RH+46, PADL=190, PADR=16;
  svg.setAttribute('width',W); svg.setAttribute('height',H);
  const X=i=>PADL+(i/(N-1))*(W-PADL-PADR);
  loops.forEach((l,k)=>{
    const y=26+k*RH;   // 顶部留够：曲线与标注要画在 y-16 上
    el('text',{x:PADL-10,y:y+4,'font-size':10.5,'text-anchor':'end'},svg).textContent=
      fitText(l.target,PADL-18,10.5);
    const x1=X(l.from), x2=X(l.to);
    el('line',{x1:PADL,y1:y,x2:W-PADR,y2:y,stroke:cssv('--line2')},svg);
    const g=el('g',{},svg); g.style.cursor='pointer';
    const span=l.to-l.from, tight=span<=25;
    el('path',{d:'M '+x1+' '+y+' Q '+((x1+x2)/2)+' '+(y-(tight?13:8))+' '+x2+' '+y,fill:'none',
      stroke:l.kind==='rework_open'?cssv('--error'):cssv('--artifact'),'stroke-width':tight?1.8:1,
      'stroke-dasharray':tight?'':'3 3'},g);
    el('text',{x:(x1+x2)/2,y:y-(tight?16:11),'font-size':10,'text-anchor':'middle',
      fill:tight?cssv('--artifact'):cssv('--dim')},g).textContent=
      '×'+l.writes+' 写'+(tight?'':' · 跨 '+span+' 节点');
    el('circle',{cx:x1,cy:y,r:3,fill:cssv('--material')},g);
    el('circle',{cx:x2,cy:y,r:3,fill:cssv('--material')},g);
    if(l.exit!=null) el('path',{d:'M '+X(l.exit)+' '+(y-5)+' L '+(X(l.exit)+4)+' '+y+' L '+X(l.exit)+' '+(y+5)+' Z',
      fill:cssv('--ok')},g);
    bind(g,'<b>'+esc(l.target)+'</b><br>N'+l.from+'→N'+l.to+' 连写 '+l.writes+' 次'+
      (l.exit!=null?'<br>在 N'+l.exit+' 被读回/跑过（回路闭合）':'<br><span style="color:var(--error)">回路未闭合：最后一次写之后再没验过</span>'));
    g.onclick=()=>openMat(l.target);
  });
  el('text',{x:PADL,y:H-6,'font-size':10},svg).textContent='N0';
  el('text',{x:W-PADR,y:H-6,'font-size':10,'text-anchor':'end'},svg).textContent='N'+(N-1);
}

/* ══════════ V5 能耗与方差 ══════════ */
function renderV5(){
  const v=document.getElementById('v5');
  const c=D.cost, reqs=D.requests;
  const modelS=Math.round(c.model_ms/1000), wall=D.meta.wall_seconds;
  // 三个量算一次就定下来，卡片/引言/脚注共用——此前各处自己取整，同一个量出现两个数
  const nodeS=Math.round(c.nodes_model_ms/1000), auxS=Math.max(modelS-nodeS,0),
        offS=Math.max(wall-modelS,0);
  const ttft=reqs.map(r=>r.ttft).filter(Boolean).sort((a,b)=>a-b);
  const tot=reqs.map(r=>r.total_ms).filter(Boolean).sort((a,b)=>a-b);
  const q=(a,p)=>a.length?a[Math.floor(a.length*p)]:0;
  v.innerHTML='<div class="eyebrow">VIEW 5 · COST &amp; VARIANCE</div>'+
    '<h1>能耗与方差：代价与瓶颈</h1>'+
    '<p class="lede">《方法》§十一 要的四类指标里，<b>Cost</b> 与<b>方差</b>单条运行就能算。'+
    '关键不是总量，是<b>分布</b>：平均 '+(q(tot,.5)/1000).toFixed(1)+' 秒但最长 '+
    (tot[tot.length-1]/1000).toFixed(0)+' 秒的请求，比稳定 20 秒的更值得查。'+
    '时间去向也一样——会话跨度 '+fmtS(wall)+'，其中进入轨迹节点的模型在途 '+
    fmtS(nodeS)+'（与 V1 阶段标注、V6 归因表同一口径），'+
    '另有 '+fmtS(auxS)+' 在安检/标题等辅助请求上。</p>'+
    '<div class="stats">'+
      stat(fmtN(c.main_out),'主线 output')+stat(fmtN(c.sub_out),'子代理 output')+
      stat(fmtN(c.main_in),'主线 input')+stat(fmtN(c.cache_read),'cache 读取','ok')+
      stat(fmtS(nodeS),'模型在途（节点）')+
      stat(fmtS(auxS),'辅助请求在途','warn')+
      stat(fmtS(offS),'不在模型上')+
    '</div>'+
    '<div class="sub">按阶段分解 · 每阶段的 output token 与模型在途时间</div>'+
    '<div class="frame" id="phBarWrap"><svg id="phBar"></svg></div>'+
    '<div class="sub">请求时延分布 · 每格一条请求，按耗时排序（对数刻度）</div>'+
    '<div class="frame" id="latWrap"><svg id="lat"></svg></div>'+
    '<div class="legend">'+lg('--artifact','output token')+lg('--focus','模型在途')+
      lg('--dele','ttft')+lg('--error','最慢 5%')+'</div>'+
    '<p class="note">时间去向：'+fmtS(wall)+' 里 '+
      Math.round(modelS/wall*100)+'% 在模型侧（节点 + 辅助两块，见上面的卡片），'+
      '其余是工具执行、子代理在跑、以及人在看图。'+
      'cache 读取 '+fmtN(c.cache_read)+' token —— 每一轮都要把整段历史重新喂一遍，这就是自增长流水线的固定开销。</p>';
  drawPhaseBars(); drawLatency();
}
function drawPhaseBars(){
  const svg=document.getElementById('phBar'), wrap=document.getElementById('phBarWrap');
  clear(svg);
  const W=Math.max(wrap.clientWidth-2,900), H=180, PADL=16, PADB=42, PADT=16;
  svg.setAttribute('width',W); svg.setAttribute('height',H);
  const maxOut=Math.max(...PH.map(p=>p.cost.out)), maxMs=Math.max(...PH.map(p=>p.cost.model_ms));
  const bw=(W-PADL*2)/PH.length;
  PH.forEach((p,k)=>{
    const x=PADL+k*bw, hOut=(p.cost.out/maxOut)*(H-PADT-PADB);
    const hMs=(p.cost.model_ms/maxMs)*(H-PADT-PADB);
    const g=el('g',{},svg); g.style.cursor='pointer'; g.onclick=()=>openPhase(p);
    el('rect',{x:x+bw*0.14,y:H-PADB-hOut,width:bw*0.34,height:hOut,fill:cssv('--artifact'),
      'fill-opacity':.85},g);
    el('rect',{x:x+bw*0.52,y:H-PADB-hMs,width:bw*0.34,height:hMs,fill:cssv('--focus'),
      'fill-opacity':.7},g);
    el('text',{x:x+bw/2,y:H-PADB+13,'font-size':10,'text-anchor':'middle',fill:cssv('--ink')},g)
      .textContent=p.id;
    el('text',{x:x+bw/2,y:H-PADB+25,'font-size':10,'text-anchor':'middle'},g)
      .textContent=(p.name.length>9?p.name.slice(0,8)+'…':p.name);
    el('text',{x:x+bw/2,y:H-PADB+36,'font-size':9.5,'text-anchor':'middle',fill:cssv('--dim')},g)
      .textContent=fmtN(p.cost.out)+' / '+fmtS(Math.round(p.cost.model_ms/1000));
    bind(g,'<b>'+esc(p.id+' '+p.name)+'</b><br>output '+fmtN(p.cost.out)+' token<br>'+
      '模型在途 '+fmtS(Math.round(p.cost.model_ms/1000))+'<br>节点 '+p.nodes_n+' · 失败 '+p.errors);
  });
}
function drawLatency(){
  const svg=document.getElementById('lat'), wrap=document.getElementById('latWrap');
  clear(svg);
  const rs=D.requests.slice().sort((a,b)=>a.total_ms-b.total_ms).filter(r=>r.total_ms>0);
  const W=Math.max(wrap.clientWidth-6,900), H=158, PADL=44, PADB=26, PADT=22;
  svg.setAttribute('width',W); svg.setAttribute('height',H);
  const max=rs[rs.length-1].total_ms, min=Math.max(rs[0].total_ms,50);
  const y=v=>H-PADB-(Math.log(Math.max(v,min))-Math.log(min))/(Math.log(max)-Math.log(min))*(H-PADT-PADB);
  [min,1000,10000,60000,240000].filter(v=>v<=max&&v>=min).forEach(v=>{
    el('line',{x1:PADL,y1:y(v),x2:W-8,y2:y(v),stroke:cssv('--line2'),'stroke-dasharray':'2 4'},svg);
    el('text',{x:PADL-6,y:y(v)+3,'font-size':10,'text-anchor':'end'},svg)
      .textContent=v>=1000?(v/1000)+'s':v+'ms';
  });
  const bw=Math.max((W-PADL-10)/rs.length,.6);
  rs.forEach((r,i)=>{
    const x=PADL+i*bw, p95=i>=rs.length*.95;
    const g=el('g',{},svg);
    el('rect',{x,y:y(r.total_ms),width:Math.max(bw-.4,.6),height:H-PADB-y(r.total_ms),
      fill:p95?cssv('--error'):cssv('--focus'),'fill-opacity':p95?.85:.55},g);
    if(r.ttft) el('rect',{x,y:y(r.ttft)-1,width:Math.max(bw-.4,.6),height:1.4,
      fill:cssv('--dele'),'fill-opacity':.8},g);
    bind(g,'请求 #'+r.i+' '+hhmm(r.ts)+'<br>总时长 '+(r.total_ms/1000).toFixed(1)+'s · ttft '+
      r.ttft+'ms<br>out '+fmtN(r.out)+' · in '+fmtN(r['in'])+' · cache '+fmtN(r.cache_read));
  });
  const md=rs[Math.floor(rs.length/2)].total_ms;
  el('text',{x:W-14,y:13,'font-size':10,'text-anchor':'end',fill:cssv('--muted')},svg)
    .textContent='中位 '+(md/1000).toFixed(1)+'s · 最长 '+(max/1000).toFixed(0)+'s · '+rs.length+' 条请求';
}


/* ══════════ V6 最优轨迹对照 ══════════ */
const KCOL={necessary:'--ok',evidence:'--evid',orientation:'--perceive',
  external_research:'--focus',delegate:'--dele',rework:'--artifact',
  dead_end:'--material',blocked_retry:'--error',redundant:'--artifact',
  think_only:'--think',unattributed:'--dim'};
const KZH={necessary:'必要（终版写入/验证）',evidence:'取证（喂给了交付物）',
  orientation:'摸情况（没进终态）',external_research:'查外部资料（没进终态）',
  delegate:'派发子代理',rework:'返工（中间版本被覆盖）',dead_end:'死胡同（产出没进终态）',
  blocked_retry:'被拦后的重试',redundant:'重复读（含 Wasted call）',
  think_only:'纯思考（无动作）',unattributed:'未归类'};
const EXANTE={rework:1,redundant:1,blocked_retry:1};
const KEEP={necessary:1,evidence:1};
function renderV6(){
  const v=document.getElementById('v6'), O=D.optimal;
  if(!O){ v.innerHTML='<div class="eyebrow">VIEW 6 · COUNTERFACTUAL</div>'+
    '<h1>最优轨迹：这一趟本可以怎么走</h1>'+
    '<p class="lede">这条录制算不出反事实骨架——通常是节点太少或没有可追溯的物料。'+
    '其余七个视图不受影响。</p>'; return; }
  const T=O.totals, L=O.lower_bound;
  const sum=(ks,f)=>ks.reduce((a,k)=>a+((O.by_class[k]||{})[f]||0),0);
  const exAnte=sum(['rework','redundant','blocked_retry'],'out');
  const exAnteN=sum(['rework','redundant','blocked_retry'],'nodes');
  const exPost=sum(['dead_end','orientation','external_research'],'out');
  const rows=Object.entries(O.by_class).map(function(kv){
    const k=kv[0], c=kv[1];
    const tag = KEEP[k] ? '<span class="tag ok">保留</span>'
      : EXANTE[k] ? '<span class="tag bad">当时就能避免</span>'
      : (k==='think_only'||k==='delegate') ? '<span class="tag">开销</span>'
      : '<span class="tag warn">事后才知道</span>';
    return '<tr data-klass="'+k+'" style="cursor:pointer"><td><span class="lv">'+
      '<i style="display:inline-block;width:10px;height:10px;background:'+cssv(KCOL[k])+
      ';margin-right:7px"></i>'+KZH[k]+'</span></td><td class="mono">'+c.nodes+
      '</td><td class="mono">'+c.acts+'</td><td class="mono">'+fmtN(c.out)+
      '</td><td class="mono">'+Math.round(c.model_ms/1000)+'s</td><td class="mono">'+
      c.share+'%</td><td>'+tag+'</td></tr>';
  }).join('');
  const branchRows=O.dead_branches.map(function(b){
    return '<tr><td class="mono" data-node="'+b.from+'" style="cursor:pointer;color:var(--focus)">N'+
      b.from+'–N'+b.to+'</td><td class="mono">'+b.nodes+'</td><td class="mono">'+
      (b.first_negative!=null?'N'+b.first_negative:'<span style="color:var(--dim)">无</span>')+
      '</td><td class="mono">'+(b.lag_nodes!=null?b.lag_nodes+' 节点 / '+fmtS(b.lag_seconds):'—')+
      '</td><td class="mono">'+fmtN(b.out)+'</td><td class="mono" style="color:var(--muted)">'+
      esc((b.targets||[]).join('、'))+'</td></tr>';
  }).join('');
  const reason=(O.blocked.find(function(b){return b.reason;})||{}).reason||'';
  v.innerHTML='<div class="eyebrow">VIEW 6 · COUNTERFACTUAL</div>'+
    '<h1>最优轨迹：这一趟本可以怎么走</h1>'+
    '<p class="lede">先说清楚这张图<b>不是</b>什么：它不回答「应该怎么做才对」——那要多次运行才谈得上。'+
    '它只做一件可复算的事：<b>从终态交付物沿血统边反向可达</b>的，是必要骨架；其余按归因分类，'+
    '并分成两种性质——<b>ex-ante</b>（当时手里的信息就足以避免：工具已明说 Wasted call、'+
    '拦截理由已给出、写完没验就接着写）与 <b>ex-post</b>（事后才知道白走：探索分支）。'+
    '<b>ex-post 不算错误</b>，但它有一个可测的量：<b>迟滞</b>——第一条否定性证据出现之后，'+
    '这条分支还跑了多久。</p>'+
    (O.B && O.B.length ? '' :
      '<div class="frame" style="border-color:var(--art-t2);background:var(--mat-t1);padding:var(--s3) var(--s4)">'+
      '<b style="color:var(--material)">⚠ 本录制未识别出文件级终态交付物</b>——最后两阶段没有仍在被写或被读的文件，'+
      'B 为空集，必要闭包退化为 0、下界也按 0 计。这<b>不代表</b>「这趟本可以什么都不做」：'+
      '此会话的产出可能是纯对话/诊断（结论留在回复里而非文件），反事实表仅当归因参考，勿读压缩比。</div>')+
    '<div class="stats">'+
      stat(T.nodes+' → '+L.nodes,'节点（实际→下界）')+
      stat(fmtN(T.out)+' → '+fmtN(L.out),'out token','warn')+
      stat(fmtS(Math.round(T.model_ms/1000))+' → '+fmtS(Math.round(L.model_ms/1000)),'模型在途')+
      stat(Math.round(L.out/T.out*100)+'%','压缩到','ok')+
      stat(exAnteN+' 节点 / '+fmtN(exAnte)+' out','当时就能避免','bad')+
      stat(fmtN(exPost),'探索代价（事后）','warn')+
      stat(O.missing_verify.length,'件必要产物没验','bad')+
    '</div>'+
    '<div class="sub">实际轨迹 vs 必要骨架 · 每格一个节点，按归因着色；下面一条是塌缩后的样子</div>'+
    '<div class="frame" id="cmpWrap"><svg id="cmp"></svg></div>'+
    '<div class="sub">归因表 · 点一行看具体节点</div>'+
    '<div class="frame scroll"><table><thead><tr><th>归因</th><th>节点</th><th>动作</th>'+
      '<th>out</th><th>在途</th><th>占比</th><th>性质</th></tr></thead><tbody>'+rows+'</tbody></table></div>'+
    '<div class="sub">ex-post 的可优化处：探索分支的迟滞代价</div>'+
    '<div class="frame scroll"><table><thead><tr><th>分支</th><th>节点数</th>'+
      '<th>第一条否定性证据</th><th>迟滞</th><th>out</th><th>产出</th></tr></thead><tbody>'+
      (branchRows||'<tr><td colspan="6" style="color:var(--dim);padding:10px 6px">本会话没有可归因的探索分支——死胡同都即时回头，或全部进了骨架。「摸索分支」节点仍计入上面的归因表。</td></tr>')+
      '</tbody></table></div>'+
    '<div class="sub">ex-ante 的三笔：当时手里的信息就够避免</div>'+
    '<div class="frame" style="padding:var(--s3)">'+
      '<div class="ev"><span class="i">返工</span><span class="r">'+
        (((O.by_class.rework||{}).nodes||0)
          ? (O.by_class.rework||{}).nodes+' 个节点写的是中间版本、之后被覆盖，而中间'+
            '<b style="color:var(--error)">一次都没验证</b>——写完就验的话，这些节点大部分不会存在（'+
            fmtN((O.by_class.rework||{}).out||0)+' out）'
          : '<span style="color:var(--dim)">没有被覆盖的中间版本</span>')+'</span></div>'+
      '<div class="ev"><span class="i">重复读</span><span class="r">'+
        (O.redundant.length
          ? O.redundant.length+' 次重复读同一物料，其中若干次工具已经明说 '+
            '<code>Wasted call — file unchanged since your last Read</code>'
          : '<span style="color:var(--dim)">没有重复读</span>')+'</span></div>'+
      '<div class="ev"><span class="i">被拦重试</span><span class="r">'+
        (O.blocked.length
          ? O.blocked.length+' 次拦截'+
            (reason?'，第 1 次就给出了完整理由（'+esc(reason.slice(0,70))+'…）':'')+
            (O.blocked.length>1?'，其后 '+(O.blocked.length-1)+' 次是同类重试':'')
          : '<span style="color:var(--dim)">没有被拦截过</span>')+'</span></div>'+
      '<div class="ev"><span class="i">缺验证</span><span class="r">'+
        (O.missing_verify.length
          ? O.missing_verify.map(function(m){return esc(m.name);}).join('、')+
            ' —— 这不是浪费，是<b>缺失的工作</b>：最优轨迹要<b style="color:var(--ok)">加</b>上这 '+
            O.missing_verify.length+' 个验证节点'
          : '<span style="color:var(--ok)">必要产物都验过了</span>')+'</span></div>'+
    '</div>'+
    '<div class="sub">阶段级：必要占比与可省 out</div>'+
    '<div class="frame" id="phNecWrap"><svg id="phNec"></svg></div>'+
    '<div class="legend">'+lg('--ok','必要占比（左条）')+lg('--material','可省 out（右条）')+'</div>'+
    '<p class="note">读法：下界 '+L.nodes+' 节点是<b>松的</b>——「取证」那 '+
      ((O.by_class.evidence||{}).nodes||0)+' 个节点里必然还有可压的（同一份证据被反复读），'+
      '但判定「读几次才够」需要跨 run 比较，单条录制上不做。所以结论只到这一句：'+
      '<b>这趟运行里，事后可证明与交付物无关的工作占 out 的 '+
      Math.round((T.out-L.out)/T.out*100)+'%，其中 '+
      Math.round(exAnte/Math.max(T.out-L.out,1)*100)+'% 是当时就能避免的。</b></p>';
  v.querySelectorAll('[data-klass]').forEach(function(tr){tr.onclick=function(){openKlass(tr.dataset.klass);};});
  v.querySelectorAll('[data-node]').forEach(function(x){x.onclick=function(){openNode(+x.dataset.node);};});
}
function openKlass(k){
  const O=D.optimal;
  const idxs=Object.entries(O.klass).filter(function(kv){return kv[1]===k;})
    .map(function(kv){return +kv[0];}).sort(function(a,b){return a-b;});
  open('归因 · '+idxs.length+' 个节点', KZH[k],
    '<p style="color:var(--muted);font-size:11.5px">'+esc(O.why[idxs[0]]||'在必要闭包内')+'</p>'+
    '<h4>节点</h4>'+idxs.map(function(i){return '<button class="jump" data-node="'+i+'">N'+i+'</button>';}).join(''));
}
function drawCompare(){
  const O=D.optimal; if(!O) return;
  const svg=document.getElementById('cmp'), wrap=document.getElementById('cmpWrap');
  if(!svg||!wrap) return;
  clear(svg);
  const W=Math.max(wrap.clientWidth-2,900), PADL=86, PADR=14, H=132;
  svg.setAttribute('width',W); svg.setAttribute('height',H);
  const cw=(W-PADL-PADR)/N;
  el('text',{x:PADL-10,y:34,'font-size':10.5,'text-anchor':'end'},svg).textContent='实际 '+N;
  D.nodes.forEach(function(n){
    const k=O.klass[String(n.i)]||'unattributed';
    const g=el('g',{},svg); g.style.cursor='pointer'; g.onclick=function(){openNode(n.i);};
    el('rect',{x:PADL+n.i*cw,y:20,width:Math.max(cw-.5,1),height:22,
      fill:cssv(KCOL[k]),'fill-opacity':KEEP[k]?.95:.6},g);
    bind(g,'<b>N'+n.i+'</b> '+KZH[k]+'<br>'+esc(O.why[String(n.i)]||'在必要闭包内')+
      '<br>out '+fmtN(n.cost.out)+' · '+hhmm(n.ts));
  });
  const keep=D.nodes.filter(function(n){return KEEP[O.klass[String(n.i)]];});
  el('text',{x:PADL-10,y:82,'font-size':10.5,'text-anchor':'end'},svg).textContent='骨架 '+keep.length;
  keep.forEach(function(n,j){
    const g=el('g',{},svg); g.style.cursor='pointer'; g.onclick=function(){openNode(n.i);};
    el('rect',{x:PADL+j*cw,y:68,width:Math.max(cw-.5,1),height:22,
      fill:cssv(KCOL[O.klass[String(n.i)]]),'fill-opacity':.95},g);
    bind(g,'<b>N'+n.i+'</b> → 骨架第 '+(j+1)+' 位<br>'+KZH[O.klass[String(n.i)]]);
  });
  O.missing_verify.forEach(function(m,j){
    el('rect',{x:PADL+(keep.length+j)*cw,y:68,width:Math.max(cw-.5,1),height:22,
      fill:cssv('--ok'),'fill-opacity':.45,stroke:cssv('--ok'),'stroke-dasharray':'2 2'},svg);
  });
  el('text',{x:PADL+(keep.length+O.missing_verify.length)*cw+8,y:83,'font-size':10,
    fill:cssv('--ok')},svg).textContent='+'+O.missing_verify.length+' 补验证';
  PH.forEach(function(p){
    el('line',{x1:PADL+p.from*cw,y1:14,x2:PADL+p.from*cw,y2:96,
      stroke:tint('--agent',.32),'stroke-dasharray':'2 3'},svg);
    el('text',{x:PADL+p.from*cw+3,y:110,'font-size':10,fill:cssv('--agent')},svg).textContent=p.id;
  });
  el('text',{x:PADL,y:126,'font-size':10},svg).textContent='N0';
  el('text',{x:W-PADR,y:126,'font-size':10,'text-anchor':'end'},svg).textContent='N'+(N-1);
}
function drawPhaseNec(){
  const O=D.optimal;
  const svg=document.getElementById('phNec'), wrap=document.getElementById('phNecWrap');
  if(!svg||!wrap||!O) return;
  clear(svg);
  const W=Math.max(wrap.clientWidth-2,900), H=152, PADL=16, PADB=46, PADT=14;
  svg.setAttribute('width',W); svg.setAttribute('height',H);
  const bw=(W-PADL*2)/O.phases.length, maxW=Math.max.apply(null,O.phases.map(function(p){return p.waste_out;}));
  O.phases.forEach(function(p,k){
    const x=PADL+k*bw;
    const hN=(p.necessary_share/100)*(H-PADT-PADB);
    const hW=(p.waste_out/Math.max(maxW,1))*(H-PADT-PADB);
    const g=el('g',{},svg);
    el('rect',{x:x+bw*.14,y:H-PADB-hN,width:bw*.34,height:hN,fill:cssv('--ok'),'fill-opacity':.8},g);
    el('rect',{x:x+bw*.52,y:H-PADB-hW,width:bw*.34,height:hW,fill:cssv('--material'),'fill-opacity':.75},g);
    el('text',{x:x+bw/2,y:H-PADB+13,'font-size':10,'text-anchor':'middle',fill:cssv('--ink')},g).textContent=p.id;
    el('text',{x:x+bw/2,y:H-PADB+25,'font-size':10,'text-anchor':'middle'},g)
      .textContent=fitText(p.name,bw-6,10);
    el('text',{x:x+bw/2,y:H-PADB+37,'font-size':9.5,'text-anchor':'middle',fill:cssv('--dim')},g)
      .textContent='必要 '+p.necessary_share+'% · 废 '+fmtN(p.waste_out);
    bind(g,'<b>'+esc(p.id+' '+p.name)+'</b><br>必要占比 '+p.necessary_share+'%<br>可省 out '+
      fmtN(p.waste_out)+' / 共 '+fmtN(p.out)+'<br>'+
      Object.entries(p.counts).map(function(kv){return KZH[kv[0]]+' '+kv[1];}).join('<br>'));
  });
}

/* ══════════ V7/V8 共用：缩放 + 场景级命中表工厂 ══════════
   命中半径随 1/scale 反向放大（屏幕空间恒 ~18px）——第十代教训：靠 DOM 元素
   自身接事件，全览 0.2 倍下节点塌成 2 屏幕像素，鼠标压不到。 */
function makeStage(host, W, H, withMM){
  // 不清空 host：renderVN 先写标题/统计/图例，画布追加在后。
  // （曾用 host.innerHTML=''，把 renderV7/V8 刚写的头部整个清掉——section 只剩画布）
  const wrap=h('div','zstage');
  const svg=el('svg',{class:'zscene'},null);
  wrap.appendChild(svg); host.appendChild(wrap);
  const gW=el('g',{},svg);
  const bar=h('div','zbar'); wrap.appendChild(bar);
  const S={s:1,tx:0,ty:0};
  const apply=()=>gW.setAttribute('transform','translate('+S.tx+','+S.ty+') scale('+S.s+')');
  const zoomAt=(mx,my,f)=>{const ns=Math.min(4,Math.max(.12,S.s*f));
    S.tx=mx-(mx-S.tx)*ns/S.s;S.ty=my-(my-S.ty)*ns/S.s;S.s=ns;apply();};
  /* 嵌入时整页只有一条滚动条，画布若照单全收滚轮，用户就滚不过这块画布了。
     所以嵌入下滚轮缩放要按住 Ctrl/⌘，裸滚轮留给页面；独立打开时维持原行为。
     两种模式都另有 ＋/－ 按钮，不依赖修饰键也能缩放。 */
  svg.addEventListener('wheel',e=>{
    if(EMBED&&!(e.ctrlKey||e.metaKey)) return;
    e.preventDefault();const r=svg.getBoundingClientRect();
    zoomAt(e.clientX-r.left,e.clientY-r.top,Math.exp(-e.deltaY*.0013));},{passive:false});
  let drag=null,dragged=0;
  svg.addEventListener('pointerdown',e=>{drag={x:e.clientX,y:e.clientY,tx:S.tx,ty:S.ty};dragged=0;
    svg.classList.add('pan');try{svg.setPointerCapture(e.pointerId);}catch(_){}});
  svg.addEventListener('pointermove',e=>{
    if(drag){S.tx=drag.tx+(e.clientX-drag.x);S.ty=drag.ty+(e.clientY-drag.y);
      dragged=Math.max(dragged,Math.abs(e.clientX-drag.x)+Math.abs(e.clientY-drag.y));apply();return;}
    const r=svg.getBoundingClientRect();
    const pk=pick((e.clientX-r.left-S.tx)/S.s,(e.clientY-r.top-S.ty)/S.s);
    if(pk){tip(e,pk.html);svg.style.cursor='pointer';}else{svg.style.cursor='grab';}});
  addEventListener('pointerup',e=>{const wd=dragged>5;drag=null;dragged=0;svg.classList.remove('pan');
    svg.style.cursor='grab';
    if(wd||!e||e.target!==svg)return;
    const r=svg.getBoundingClientRect();
    const pk=pick((e.clientX-r.left-S.tx)/S.s,(e.clientY-r.top-S.ty)/S.s);
    if(pk&&pk.act)pk.act();});
  svg.addEventListener('mouseleave',hideTip);
  const hits=[]; let curGrp=null;
  const hitC=(x,y,r,prio,html,act)=>hits.push({s:'c',x,y,r,prio,html,act,own:curGrp});
  const hitR=(x0,y0,x1,y1,prio,html,act)=>hits.push({s:'r',x0,y0,x1,y1,prio,html,act,own:curGrp});
  function pick(wx,wy){
    const rr=18/S.s;let best=null,bd=1e9,bp=-1;
    for(const q of hits){
      if(q.own&&q.own.style.display==='none')continue;
      if(q.s==='c'){const d=Math.hypot(wx-q.x,wy-q.y);
        if(d<Math.max(q.r,rr)&&(q.prio>bp||q.prio===bp&&d<bd)){best=q;bd=d;bp=q.prio;}}
      else if(wx>=q.x0-4&&wx<=q.x1+4&&wy>=q.y0-4&&wy<=q.y1+4&&q.prio>bp){best=q;bp=q.prio;}
    }
    return best;}
  const mkbtn=(t,fn,attr)=>{const b=h('button','zbtn',t);
    if(attr)b.setAttribute('aria-pressed','true');b.onclick=fn;bar.appendChild(b);return b;};
  const fit=()=>{S.s=Math.min(wrap.clientWidth/W,wrap.clientHeight/H)*.95;
    S.tx=(wrap.clientWidth-W*S.s)/2;S.ty=(wrap.clientHeight-H*S.s)/2;apply();};
  const home=()=>{S.s=Math.min(wrap.clientHeight/H*.92,1.1);S.tx=24;
    S.ty=(wrap.clientHeight-H*S.s)/2;apply();};
  const zoomCenter=f=>zoomAt(wrap.clientWidth/2,wrap.clientHeight/2,f);
  mkbtn('－',()=>zoomCenter(1/1.25)); mkbtn('＋',()=>zoomCenter(1.25));
  mkbtn('全览',fit); mkbtn('复位',home);
  let mm=null;
  if(withMM){
    mm=h('div','zmm'); const ms=el('svg',{},null); mm.appendChild(ms); wrap.appendChild(mm);
    const hint=h('div','zhint',(EMBED?'Ctrl+滚轮缩放':'滚轮缩放')+
      ' · 拖拽平移 · 悬停看简述 · 点击看证据 · 点小地图跳转');
    wrap.appendChild(hint);
    mm._init=(draw)=>{const MW=240,MH=Math.round(MW*H/W);
      ms.setAttribute('width',MW);ms.setAttribute('height',MH);ms._sx=MW/W;ms._sy=MH/H;draw(ms);};
    mm._view=()=>{const vx=-S.tx/S.s,vy=-S.ty/S.s;
      return {vx,vy,vw:wrap.clientWidth/S.s,vh:wrap.clientHeight/S.s};};
    mm._jump=(wx,wy)=>{S.tx=wrap.clientWidth/2-wx*S.s;S.ty=wrap.clientHeight/2-wy*S.s;apply();};
    ms.addEventListener('click',e=>{const r=ms.getBoundingClientRect();
      mm._jump((e.clientX-r.left)/ms._sx,(e.clientY-r.top)/ms._sy);});
  }
  let crossEl=null;
  const enableCross=()=>{
    crossEl=document.createElementNS(svgns,'line');
    crossEl.setAttribute('y1',0);crossEl.setAttribute('y2',H);
    crossEl.setAttribute('stroke',tint('--agent',.32));crossEl.setAttribute('stroke-dasharray','2 4');
    gW.appendChild(crossEl);
    svg.addEventListener('pointermove',e=>{
      if(drag)return;
      const r=svg.getBoundingClientRect();
      const wx=(e.clientX-r.left-S.tx)/S.s;
      crossEl.setAttribute('x1',wx);crossEl.setAttribute('x2',wx);});
  };
  const setWorld=(w2,h2)=>{W=w2;H=h2;
    if(crossEl)crossEl.setAttribute('y2',H);};
  const reset=()=>{hits.length=0;};
  return {wrap,svg,gW,S,apply,zoomAt,fit,home,hitC,hitR,pick,mkbtn,mm,setWorld,reset,enableCross};
}

/* ══════════ V7 物料生命线 + 未验债曲线（统一地基重建版） ══════════ */
const KCOL7={advance:'--material',verify:'--ok',perceive:'--perceive',
             delegate:'--dele',think:'--think'};
let v7mode='seq', v7mat='key';
/* STATE A/B 起终点面板（原 2D 版的解释层，全部程序可算） */
function stateAB(){
  const chip=(t,v,w)=>'<span class="s7c'+(w?' '+w:'')+'"><b>'+v+'</b>'+t+'</span>';
  const startReads=[...new Set(D.nodes.slice(0,8).flatMap(n=>n.reads)
    .filter(t=>/\./.test(t)))].slice(0,6);
  const ver=D.verify||[];
  const unv=ver.filter(v=>v.level<2&&v.writes>0);
  const fails=(D.valves||[]).filter(x=>x.kind==='tool_error').length;
  return '<div class="s7ab">'+
    '<div class="sb"><h4>STATE A · 起点 '+hhmm(D.nodes[0].ts)+'</h4>'+
    '<p class="s7g">'+esc(PH[0].from_state)+'</p>'+
    chip('主线请求',D.meta.requests.main)+chip('产物','0')+
    chip('起点读入',startReads.length+' 文件')+
    (startReads.length?'<div class="s7f">'+startReads.map(t=>'<span>'+esc(t)+'</span>').join('')+'</div>':'')+
    '</div>'+
    '<div class="sb"><h4>STATE B · 终点 '+hhmm(D.nodes[N-1].ts)+'</h4>'+
    '<p class="s7g">'+esc(PH[PH.length-1].to_state)+'</p>'+
    chip('已验(L2+)',ver.filter(v=>v.level>=2).length,'ok')+
    chip('未验',unv.length,'bad')+chip('失败',fails,'bad')+
    chip('子代理线',(D.subagents||[]).length)+
    (unv.length?'<div class="s7f warn">⚠ '+unv.map(v=>'<span>'+esc(v.name)+'</span>').join('')+'</div>':'')+
    '</div></div>';
}
function renderV7(){
  const v=document.getElementById('v7'), Q=D.v7;
  const peak=Math.max(...Q.debt.map(d=>d.n),1);
  v.innerHTML='<div class="eyebrow">VIEW 7 · MATERIAL LIFELINE</div>'+
    '<h1>物料生命线：一件物料的一生与未验债曲线</h1>'+
    '<p class="lede">横轴可切<b>推进序</b>（每节点等距）与<b>真实时间</b>（停顿、子代理时长拉开真实宽度）。'+
    '每一行是一件物料的一生：<b>▲写</b>（橙）· <b>●读</b>（青）· <b>■跑</b>（绿），亮边=清偿未验债，红点=出错。'+
    '底部折线是<b>未验债</b>；紫色泳道是子代理各自的工作区间；竖虚线是停顿。'+
    '悬停联动整列，点标记看全文证据。与 V1–V6/V8 同一份 factors.json 地基。</p>'+
    '<div class="stats">'+
      stat((v7mat==='key'?Q.rows_key.length:v7mat==='all'?Q.rows_all.length:Q.rows_cmd.length),'行物料')+
      stat(D.debt[N-1].n,'件终态未验','warn')+
      stat(peak,'未验债峰值','bad')+stat(Q.subs.length,'条子代理泳道')+
      stat(Q.gaps.length,'次长停顿')+
    '</div>'+stateAB()+
    '<div class="legend">'+
      lg('--material','▲ 写')+lg('--perceive','● 读')+lg('--evid','■ 跑')+
      lg('--ok','亮边=清偿')+lg('--error','红点=出错')+lg('--dele','子代理泳道')+
      lg('--artifact','未验债曲线')+lg('--error','红竖带=停顿')+'</div>';
  const st=makeStage(v,Q.W,800,false);
  st.enableCross();
  // 工具栏：x 模式 + 物料行档（mkbtn 顺序即栏序）
  const bSeq=st.mkbtn('推进序',()=>{if(v7mode!=='seq'){v7mode='seq';bSeq.setAttribute('aria-pressed','true');bTime.setAttribute('aria-pressed','false');drawV7();}},v7mode==='seq');
  const bTime=st.mkbtn('真实时间',()=>{if(v7mode!=='time'){v7mode='time';bTime.setAttribute('aria-pressed','true');bSeq.setAttribute('aria-pressed','false');drawV7();}},v7mode==='time');
  st.mkbtn('关键物料',()=>{v7mat='key';drawV7();},v7mat==='key');
  st.mkbtn('全部',()=>{v7mat='all';drawV7();},v7mat==='all');
  st.mkbtn('含命令',()=>{v7mat='cmd';drawV7();},v7mat==='cmd');

  const t0s=new Date(Q.t0).getTime(), t1s=new Date(Q.t1).getTime();
  const tsOf=i=>new Date(D.nodes[i].ts).getTime();
  const X=i=>v7mode==='seq'?Q.X0+i*Q.PITCH
    :Q.X0+(tsOf(i)-t0s)/Math.max(t1s-t0s,1)*(Q.W-2*Q.X0);
  const H7=()=>Q.top+(v7mat==='key'?Q.rows_key.length:v7mat==='all'?Q.rows_all.length:Q.rows_cmd.length)*Q.row_h+150;

  function drawV7(){
    st.reset(); st.setWorld(Q.W,H7()); clear(st.gW);
    const g=st.gW, rows=v7mat==='key'?Q.rows_key:v7mat==='all'?Q.rows_all:Q.rows_cmd;
    const H=H7();
    // 阶段带
    D.phases.forEach((p,k)=>{
      const x0=X(p.from)-Q.PITCH/2, x1=X(p.to)+Q.PITCH/2;
      el('rect',{x:Math.min(x0,x1),y:96,width:Math.max(Math.abs(x1-x0),2),height:H-96-96,
        fill:k%2?tint('--agent',.035):tint('--agent',.065)},g);
      el('line',{x1:x0,y1:96,x2:x0,y2:H-96,stroke:tint('--agent',.32),'stroke-dasharray':'3 4'},g);
      const bw7=Math.abs(x1-x0);
      el('text',{x:Math.min(x0,x1)+6,y:88,'font-size':10.5,fill:cssv('--agent')},g)
        .textContent=bw7<70?p.id:p.id+' '+fitText(p.name,Math.min(bw7-30,150),10.5);
    });
    // 顶部节点类别色条（橙=推进）
    D.nodes.forEach(n=>{
      const x=X(n.i);
      el('rect',{x:x-3,y:64,width:Math.max(Q.PITCH*.3,3),height:12,
        fill:cssv(KCOL7[n.kind]||'--dim')},g);
      if(n.kind==='delegate') el('path',{d:'M '+x+' 60 l 3.5 5 l -7 0 z',
        fill:cssv('--dele')},g);   // 委派 ▽ 标记
      st.hitC(x,70,8,2,'<b>N'+n.i+'</b> '+esc(n.brief||KINDZH[n.kind])+'<br>'+hhmm(n.ts),
        ()=>openV8Node('main',n.i));
    });
    el('text',{x:Q.X0-158,y:73,'font-size':10,fill:cssv('--dim')},g).textContent='节点类别';
    // 物料行
    rows.forEach(r0=>{
      el('line',{x1:Q.X0,y1:r0.y,x2:Q.W-90,y2:r0.y,stroke:cssv('--line2')},g);
      el('text',{x:Q.X0-10,y:r0.y+3.5,'font-size':10.5,'text-anchor':'end',
        fill:r0.in_B?cssv('--artifact'):cssv('--muted')},g).textContent=fitText(r0.name,150,10.5);
      if(r0.level!=null&&r0.level<2&&r0.writes>0)
        el('text',{x:Q.W-72,y:r0.y+4,'font-size':10,fill:cssv('--error')},g).textContent='⚠L'+r0.level;
      st.hitR(Q.X0-160,r0.y-9,Q.X0,r0.y+9,1,
        '<b>'+esc(r0.name)+'</b><br>写 '+r0.writes+' · 读 '+r0.reads+' · 跑 '+r0.runs+
        (r0.level!=null?'<br>验证 L'+r0.level:'')+(r0.in_B?'<br><span style="color:var(--artifact)">终态交付物</span>':''),
        ()=>openMat(r0.name));
      r0.marks.forEach(mk=>{
        const x=X(mk.i);
        if(x<Q.X0-4||x>Q.W-88) return;
        const col=mk.op==='write'?'--material':mk.op==='run'?'--evid':'--perceive';
        const a={fill:cssv(col),'fill-opacity':.9};
        if(mk.clears){a.stroke=cssv('--ok');a['stroke-width']=1.4;}
        if(mk.op==='write') el('rect',{x:x-3.5,y:r0.y-7,width:7,height:14,...a},g);
        else if(mk.op==='run') el('rect',{x:x-3.5,y:r0.y-3.5,width:7,height:7,...a},g);
        else el('circle',{cx:x,cy:r0.y,r:3,...a},g);
        if(mk.error) el('circle',{cx:x,cy:r0.y-10,r:1.8,fill:cssv('--error')},g);
        st.hitC(x,r0.y,7,2,
          '<b>'+(OPZH[mk.op]||mk.op)+' '+esc(mk.tool||'')+'</b> · N'+mk.i+' · '+hhmm(mk.ts)+
          (mk.clears?'<br><span style="color:var(--ok)">清偿未验债</span>':'')+
          (mk.error?'<br><span style="color:var(--error)">出错</span>':'')+
          (mk.d?'<br>'+esc(mk.d.slice(0,90)):''),
          ()=>openV8Node('main',mk.i));
      });
    });
    // 子代理泳道（每条线一行）
    const SWY0=Q.top+rows.length*Q.row_h+34;
    Q.subs.forEach((sb,k)=>{
      const y=SWY0+k*24, x0=X(sb.disp), x1=Math.max(X(sb.endn),x0+10);
      el('rect',{x:x0,y:y-8,width:Math.max(x1-x0,10),height:16,rx:3,
        fill:tint('--dele',.12),stroke:tint('--dele',.42)},g);
      el('line',{x1:x0,y1:y,x2:x1,y2:y,stroke:cssv('--dele'),'stroke-width':1.6},g);
      const lab=sb.task+' · '+fmtS(sb.seconds)+' · '+sb.requests+' 请求';
      const lx=v7mode==='time'&&x1-x0>lab.length*6.2?x0+6:x1+8;
      el('text',{x:lx,y:y+3.5,'font-size':10,fill:cssv('--dele')},g).textContent=lab;
      st.hitR(x0,y-10,Math.max(x1,x0+80),y+10,1,
        '<b>'+esc(sb.task)+'</b><br>'+hhmm(sb.start)+' → '+hhmm(sb.end)+' · '+fmtS(sb.seconds)+
        '<br>'+sb.requests+' 请求 · out '+fmtN(sb.out)+(sb.errors?' · 失败 '+sb.errors:'')+
        (sb.returned.length?'<br>回传：'+esc(sb.returned.join('、')):'<br>回传：（主线未取用）'),
        ()=>openV8Sub(D.v8.subs.find(x=>x.lane===k)));
    });
    // 停顿带（time 模式看得见宽度）
    Q.gaps.forEach(gp=>{
      const x0=X(gp.from), x1=X(gp.to), w=Math.max(v7mode==='time'?x1-x0:4,3);
      el('rect',{x:x0,y:96,width:w,height:H-96-96,fill:tint('--error',.09),
        stroke:tint('--error',.38),'stroke-dasharray':'2 4'},g);
      el('text',{x:x0+w/2,y:112,'font-size':10,'text-anchor':'middle',fill:cssv('--error')},g)
        .textContent=fmtS(gp.sec);
      st.hitC(x0+w/2,104,8,2,'<b>停顿 '+fmtS(gp.sec)+'</b>（N'+gp.from+'–'+gp.to+'）',null);
    });
    // 未验债曲线
    const DY=H-46, DSCALE=(DY-96)/Math.max(peak,1);
    el('line',{x1:Q.X0,y1:DY,x2:Q.W-90,y2:DY,stroke:tint('--artifact',.40)},g);
    el('polyline',{points:Q.debt.map(d=>X(d.i)+','+(DY-d.n*DSCALE)).join(' '),fill:'none',
      stroke:cssv('--artifact'),'stroke-width':1.6,'stroke-opacity':.9},g);
    Q.debt.filter(d=>d.n===peak).slice(0,1).forEach(d=>{
      el('circle',{cx:X(d.i),cy:DY-d.n*DSCALE,r:3,fill:cssv('--artifact')},g);
      el('text',{x:X(d.i)+8,y:DY-d.n*DSCALE+13,'font-size':10,fill:cssv('--artifact')},g)
        .textContent='峰 '+peak+'（N'+d.i+'）';
    });
    Q.debt.forEach((d,di)=>{ if(di%8) return;
      st.hitC(X(d.i),DY-d.n*DSCALE,9,2,
        '<b>未验债 '+d.n+' 件</b> · N'+d.i+' · '+hhmm(D.nodes[d.i].ts),()=>openV8Node('main',d.i));
    });
    el('text',{x:Q.X0-158,y:DY+4,'font-size':10,fill:cssv('--artifact')},g).textContent='未验债';
    // 刻度
    for(let i=0;i<N;i+=30){
      const x=X(i);
      el('line',{x1:x,y1:H-96,x2:x,y2:H-90,stroke:cssv('--grid')},g);
      el('text',{x,y:H-78,'font-size':10,'text-anchor':'middle',fill:cssv('--dim')},g)
        .textContent=v7mode==='seq'?('N'+i):hhmm(D.nodes[i].ts);
    }
    st.home();   // 默认纵向占满、左起——fit 全览会把 6919 宽世界压成一条 390px 的带子
  }
  drawV7();
}

/* ══════════ V8 最优轨迹时序节点图（自第十代移植，数据同源） ══════════ */
const KCOL8={necessary:'--ok',evidence:'--agent',orientation:'--perceive',
  external_research:'--focus',delegate:'--dele',rework:'--artifact',dead_end:'--material',
  blocked_retry:'--error',redundant:'--artifact',think_only:'--think',unattributed:'--dim'};
const KZH8={necessary:'必要（终版写入/验证）',evidence:'取证（喂给了交付物）',
  orientation:'摸情况（没进终态）',external_research:'查外部资料（没进终态）',delegate:'派发子代理',
  rework:'返工（中间版本被覆盖）',dead_end:'死胡同（产出没进终态）',blocked_retry:'被拦后的重试',
  redundant:'重复读（含 Wasted call）',think_only:'纯思考（无动作）',unattributed:'未归类'};
const SKCOL8={advance:'--material',verify:'--ok',perceive:'--perceive',think:'--think',delegate:'--dele'};
const SKZH8={advance:'推进（写/跑）',verify:'验证（清偿未验债）',perceive:'感知（读/看）',
  think:'纯思考',delegate:'派发'};
function renderV8(){
  const v=document.getElementById('v8'), V=D.v8, M=V.meta;
  const T=V.totals, L2=V.lower, SS=V.sub_stats;
  const exN=['rework','redundant','blocked_retry'].reduce((a,k)=>a+((V.by_class[k]||{}).nodes||0),0);
  v.innerHTML='<div class="eyebrow">VIEW 8 · OPTIMAL TRAJECTORY TIMELINE</div>'+
    '<h1>最优时序图：主线是下界，挂在下面的是可省的</h1>'+
    '<p class="lede">中间实线是<b>骨架</b>：从终态交付物沿血统反向可达的<b>下界轨迹</b>；'+
    '挂在下面的是没进链的工作，按归因分泳道。紫色条带是<b>子代理</b>——主线在派发处留出空档'+
    '（当时确实在等），带内是它自己的时序。<b>悬停任意节点看简述，点击看全文证据</b>。</p>'+
    (V.skeleton_n ? '' :
      '<div class="frame" style="border-color:var(--art-t2);background:var(--mat-t1);padding:var(--s3) var(--s4)">'+
      '<b style="color:var(--material)">⚠ 本录制未识别出文件级终态交付物</b>——骨架为空（同 V6 提示），'+
      '下图只有实际时序与归因泳道，下界轨线与压缩比勿读。</div>')+
    '';
  const st=makeStage(v,M.W,M.H,true);
  // 统计卡与图例常驻画布（原时序图形态：全览时也在角落可读）
  const zs=h('div','zstats',
    '<div class="st"><b>'+T.nodes+' → '+L2.nodes+'</b><span>节点 → 下界</span></div>'+
    '<div class="st warn"><b>'+fmtN(T.out)+' → '+fmtN(L2.out)+'</b><span>out token</span></div>'+
    '<div class="st ok"><b>'+Math.round(L2.out/T.out*100)+'%</b><span>压缩到</span></div>'+
    '<div class="st bad"><b>'+exN+' 个</b><span>当时就能避免</span></div>'+
    '<div class="st dele"><b>'+SS.lanes+' 条</b><span>子代理 · '+SS.requests+' 请求</span></div>'+
    '<div class="st bad"><b>'+V.missing.length+'</b><span>件缺验证</span></div>');
  st.wrap.appendChild(zs);
  st.wrap.appendChild(h('div','zlegend',
    lg('--ok','必要（终版写入/验证）')+lg('--evid','取证（喂给了交付物）')+
    lg('--artifact','返工 / 重复读 — 当时就能避免')+lg('--material','死胡同 — 事后才知道')+
    lg('--error','被拦重试 / 迟滞段')+lg('--perceive','摸情况')+lg('--focus','查外部资料')+
    lg('--think','纯思考')+'<span style="color:var(--dele)">┈ 子代理条带（紫）</span>'));
  const gPh=el('g',{},st.gW), gMat=el('g',{},st.gW), gEdge=el('g',{},st.gW),
        gBranch=el('g',{},st.gW), gMain=el('g',{},st.gW), gLag=el('g',{},st.gW),
        gSub=el('g',{},st.gW), gTop=el('g',{},st.gW);
  const byI8={}; V.nodes.forEach(n=>byI8[n.i]=n);
  const laneY={}; M.lanes.forEach(([k,y])=>laneY[k]=y);
  const det8=k=>(D.details||{})[k]||{};
  const YM=M.YM;
  // 阶段
  st.hitC; let cg=gPh;
  V.phases.forEach((p,k)=>{
    const x0=p.x0-M.PITCH/2, w=p.x1-p.x0+M.PITCH;
    el('rect',{x:x0,y:150,width:w,height:M.H-210,fill:k%2?tint('--agent',.035):tint('--agent',.065)},gPh);
    el('line',{x1:x0,y1:150,x2:x0,y2:M.H-60,stroke:tint('--agent',.32),'stroke-dasharray':'3 4'},gPh);
    const dy=k%2?0:22, short=w<110;   // 阶段太窄画不下全名：只留 P 号（悬停 hit 区仍给全名）
    el('text',{x:x0+8,y:168-dy,'font-size':10,fill:cssv('--agent')},gPh)
      .textContent=short?p.id:p.id+' '+p.name;
    if(!short) el('text',{x:x0+8,y:181-dy,'font-size':10,fill:cssv('--dim')},gPh)
      .textContent='N'+p.from+'–'+p.to+' · '+fmtS(p.seconds)+' · 债 '+p.debt_in+'→'+p.debt_out;
    st.hitR(x0,146,x0+w,190,0,'<b>'+esc(p.id+' '+p.name)+'</b><br>'+esc(p.from_state)+'<br>→ '+esc(p.to_state),
      ()=>open('阶段 '+p.id+' · N'+p.from+'–'+p.to,p.name,'',
        '<dl class="kv"><dt>起点</dt><dd>'+esc(p.from_state)+'</dd><dt>终点</dt><dd>'+esc(p.to_state)+
        '</dd><dt>耗时</dt><dd>'+fmtS(p.seconds)+'</dd><dt>未验债</dt><dd>'+p.debt_in+' → '+p.debt_out+'</dd></dl>'));
  });
  // 物料轨
  cg=gMat;
  V.mats.forEach(m=>{
    const label=fitText(m.name,148,10.5);
    const w=Math.max(label.length*7.2+56,118);
    const col=m.in_B?cssv('--artifact'):cssv('--material');
    el('rect',{x:m.x-w/2,y:M.MAT_Y-11,width:w,height:22,rx:3,fill:cssv('--sheet'),
      stroke:col,'stroke-width':m.in_B?1.4:1},gMat);
    el('text',{x:m.x-w/2+8,y:M.MAT_Y+4,'font-size':10.5,fill:cssv('--ink')},gMat).textContent=label;
    if(m.level!=null) el('text',{x:m.x+w/2-7,y:M.MAT_Y+4,'font-size':10,'text-anchor':'end',
      fill:m.level>=2?cssv('--ok'):cssv('--error')},gMat).textContent='L'+m.level;
    el('path',{d:'M '+m.x_src+' '+(YM-14)+' C '+m.x_src+' '+(YM-90)+', '+m.x+' '+(M.MAT_Y+92)+', '+m.x+' '+(M.MAT_Y+13),
      fill:'none',stroke:col,'stroke-opacity':.34,'stroke-width':1},gEdge);
    st.hitR(m.x-w/2,M.MAT_Y-11,m.x+w/2,M.MAT_Y+11,1,
      '<b>'+esc(m.name)+'</b><br>写 '+m.writes+' · 读 '+m.reads+' · 跑 '+m.runs+
      (m.level!=null?'<br>验证 L'+m.level:'')+(m.in_B?'<br><span style="color:var(--artifact)">终态交付物</span>':''),
      ()=>openMat(m.name));
  });
  // 主线
  cg=gMain;
  const sk=V.nodes.filter(n=>n.sk).sort((a,b)=>a.x-b.x);
  for(let j=0;j<sk.length-1;j++){
    const a=sk[j].x, b=sk[j+1].x, gap=b-a>M.PITCH*1.6;
    el('line',{x1:a,y1:YM,x2:b,y2:YM,stroke:gap?tint('--agent',.32):cssv('--agent'),
      'stroke-width':gap?1:2.2,'stroke-dasharray':gap?'3 4':''},gMain);
  }
  el('text',{x:M.X0-158,y:YM+4,'font-size':11,fill:cssv('--ok')},gMain).textContent='骨架 '+sk.length+' 节点';
  el('text',{x:M.X0-158,y:YM+18,'font-size':10,fill:cssv('--dim')},gMain).textContent='= 这趟的下界轨迹';
  sk.forEach(n=>{
    const col=cssv(KCOL8[n.k]);
    el('rect',{x:n.x-6,y:YM-8,width:12,height:16,rx:2,fill:col,
      'fill-opacity':n.k==='necessary'?.98:.62,stroke:col,'stroke-width':.8},gMain);
    if(n.err) el('circle',{cx:n.x,cy:YM-13,r:2.2,fill:cssv('--error')},gMain);
    st.hitC(n.x,YM,10,2,
      '<b>N'+n.i+'</b> '+esc(n.lab)+'<br>'+KZH8[n.k]+'<br>'+hhmm(n.ts)+' · out '+fmtN(n.out)+
      (n.changes.length?'<br>写：'+esc(n.changes.join('、')):'')+
      (n.verified.length?'<br>验：'+esc(n.verified.join('、')):''),
      ()=>openV8Node('main',n.i));
  });
  // 补验证菱形
  V.missing.forEach(mv=>{
    const x=mv.x;
    el('path',{d:'M '+x+' '+(YM-11)+' L '+(x+8)+' '+YM+' L '+x+' '+(YM+11)+' L '+(x-8)+' '+YM+' Z',
      fill:tint('--ok',.12),stroke:cssv('--ok'),'stroke-dasharray':'2 2','stroke-width':1.2},gMain);
    st.hitC(x,YM,10,2,
      '<b>本应有一次验证</b><br>'+esc(mv.name)+'<br>它在 N'+mv.node+' 最后一次被写之后，再没有被读回或跑过',
      ()=>open('MISSING · 缺一次验证',mv.name,'',
        '<dl class="kv"><dt>物料</dt><dd>'+esc(mv.name)+'</dd><dt>最后写于</dt><dd>N'+mv.node+
        '</dd></dl><p style="color:var(--muted)">最优轨迹要加上这一步——未验债不能带出流水线。</p>'));
  });
  // 支路
  cg=gBranch;
  const gLaneLab=el('g',{},gBranch);
  M.lanes.forEach(([k,y])=>{
    el('line',{x1:M.X0-30,y1:y,x2:M.W-260,y2:y,stroke:cssv('--line2')},gLaneLab);
    el('text',{x:M.X0-40,y:y+3.5,'font-size':10,fill:cssv('--dim')},gLaneLab).textContent=
      {rework:'返工',dead_end:'死胡同',blocked_retry:'被拦重试',redundant:'重复读',
       orientation:'摸情况',external_research:'查资料',delegate:'派发',think_only:'纯思考'}[k]||k;
  });
  V.nodes.filter(n=>!n.sk).forEach(n=>{
    const y=laneY[n.k]||laneY.think_only;
    const col=cssv(KCOL8[n.k]);
    el('line',{x1:n.x,y1:YM+9,x2:n.x,y2:y-5,stroke:col,'stroke-opacity':.22,'stroke-width':1,
      'stroke-dasharray':'2 3'},gBranch);
    el('rect',{x:n.x-4,y:y-5,width:8,height:10,rx:1.5,fill:col,'fill-opacity':.85},gBranch);
    if(n.err) el('circle',{cx:n.x,cy:y-9,r:1.8,fill:cssv('--error')},gBranch);
    st.hitC(n.x,y,9,2,
      '<b>N'+n.i+'</b> '+esc(n.lab)+'<br>'+KZH8[n.k]+'<br>'+esc(n.why)+'<br>'+hhmm(n.ts)+
      ' · out '+fmtN(n.out)+' · 在途 '+(n.ms/1000).toFixed(1)+'s',
      ()=>openV8Node('main',n.i));
  });
  // 迟滞
  cg=gLag;
  V.lag.forEach((l,li)=>{
    const y=laneY.dead_end;
    el('circle',{cx:l.x_neg,cy:y,r:3.4,fill:cssv('--error')},gLag);
    el('line',{x1:l.x_neg,y1:y+10,x2:l.x_end,y2:y+10,stroke:cssv('--error'),
      'stroke-width':2,'stroke-dasharray':'4 3'},gLag);
    el('text',{x:(l.x_neg+l.x_end)/2,y:y+22+(li%2)*11,'font-size':10,'text-anchor':'middle',
      fill:cssv('--error')},gLag).textContent='迟滞 '+l.lag_nodes+' 节点 / '+fmtS(l.lag_seconds);
    st.hitC((l.x_neg+l.x_end)/2,y+10,12,2,
      '<b>迟滞</b><br>第一条否定性证据在 N'+l.neg+'，这条分支到 N'+l.to+' 才停<br>多跑了 '+
      l.lag_nodes+' 个节点 / '+fmtS(l.lag_seconds)+'<br>产出：'+esc((l.targets||[]).join('、')),null);
  });
  // 子代理扩展带
  cg=gSub;
  V.idle.forEach(id=>{
    const y=YM+26;
    if(id.x2!=null&&id.x2>id.x){
      el('line',{x1:id.x+8,y1:y,x2:id.x2-8,y2:y,stroke:cssv('--dele'),'stroke-opacity':.5,
        'stroke-width':1.4,'stroke-dasharray':'1 4'},gSub);
      el('text',{x:(id.x+id.x2)/2,y:y-6,'font-size':10,'text-anchor':'middle',fill:cssv('--dele'),
        'stroke':cssv('--surf2'),'stroke-width':3,'paint-order':'stroke'},gSub)
        .textContent='idle '+fmtS(id.seconds)+'（等 SendMessage 唤醒）';
    }
    st.hitC(id.x,YM,10,2,'<b>N'+id.node+' 派发未开工</b><br>dsh 异步 agent：launch 之后 idle，<br>直到 N'+
      id.wake+' 的 SendMessage 才真正开跑<br>派发 ≠ 开工',null);
  });
  V.subs.forEach(b=>{
    const y=b.y;
    el('line',{x1:b.x0-16,y1:YM+9,x2:b.x0-16,y2:y-12,stroke:cssv('--dele'),'stroke-opacity':.55,
      'stroke-width':1.4,'stroke-dasharray':'4 3'},gSub);
    el('path',{d:'M '+(b.x0-16)+' '+(y-12)+' l -3 6 l 6 0 z',fill:cssv('--dele')},gSub);
    if(b.resume!=null){
      const rx=(byI8[b.resume]||{}).x;
      if(rx!=null){
        el('line',{x1:b.x1,y1:y-10,x2:rx,y2:YM+12,stroke:cssv('--ok'),'stroke-opacity':.4,
          'stroke-width':1,'stroke-dasharray':'2 4'},gSub);
        el('path',{d:'M '+rx+' '+(YM+12)+' l -3 -6 l 6 0 z',fill:cssv('--ok')},gSub);
      }
    }
    el('rect',{x:b.x0-14,y:y-11,width:b.w+28,height:22,rx:4,fill:tint('--dele',.12),
      stroke:tint('--dele',.42),'stroke-dasharray':'3 3'},gSub);
    el('line',{x1:b.x0,y1:y,x2:b.x1,y2:y,stroke:tint('--dele',.42),'stroke-width':1.2},gSub);
    el('text',{x:b.x0-14,y:y-17,'font-size':10.5,fill:cssv('--dele')},gSub)
      .textContent='lane'+b.lane+' · '+b.task+' · '+fmtS(b.seconds)+' · '+b.requests+' 请求 · out '+fmtN(b.out);
    st.hitR(b.x0-14,y-22,b.x1+14,y-6,1,
      '<b>'+esc(b.task)+'</b>（lane'+b.lane+'）<br>'+hhmm(b.start)+' → '+hhmm(b.end)+' · '+fmtS(b.seconds)+
      '<br>'+b.nodes.length+' 节点 · '+b.requests+' 请求 · out '+fmtN(b.out)+
      (b.errors?' · 失败 '+b.errors:'')+(b.wrote.length?'<br>写出：'+esc(b.wrote.join('、')):'')+
      '<br><span style="color:var(--dele)">点节点看它每一步</span>',()=>openV8Sub(b));
    b.nodes.forEach(m=>{
      const col=cssv(SKCOL8[m.kind]||'--perceive');
      el(m.changes.length?'rect':'circle',
        m.changes.length?{x:m.x-4.5,y:y-9,width:9,height:18,rx:2,fill:col,'fill-opacity':.92}
                        :{cx:m.x,cy:y,r:m.kind==='think'?2.8:4.2,fill:col,'fill-opacity':.9},gSub);
      if(m.err) el('circle',{cx:m.x,cy:y-11,r:2,fill:'none',stroke:cssv('--error'),'stroke-width':1},gSub);
      st.hitC(m.x,y,9,2,
        '<b>lane'+b.lane+'·'+m.i+'</b> '+esc(m.brief||(m.changes.length?('写 '+m.changes.join('、')):
        (m.reads.length?('读 '+m.reads[0]):SKZH8[m.kind])))+'<br>'+SKZH8[m.kind]+' · '+hhmm(m.ts)+
        ' · '+m.nacts+' 个动作'+(m.err?' · <span style="color:var(--error)">出错</span>':''),
        ()=>openV8Node('sub',m.i,b.lane));
    });
  });
  // 底部塌缩带
  cg=gTop;
  const YC=V.ycomp, CP=V.comp_pitch;
  el('line',{x1:M.X0-14,y1:YC,x2:M.X0+(V.skeleton_n+V.missing.length)*CP,y2:YC,
    stroke:tint('--ok',.45),'stroke-width':2},gTop);
  el('text',{x:M.X0-158,y:YC+4,'font-size':11,fill:cssv('--ok')},gTop)
    .textContent='最优轨迹 '+(V.skeleton_n+V.missing.length);
  el('text',{x:M.X0-158,y:YC+18,'font-size':10,fill:cssv('--dim')},gTop).textContent='骨架压实 + 补验证';
  sk.forEach(n=>{
    const cx=V.comp[String(n.i)]; if(cx==null) return;
    el('rect',{x:cx-Math.min(CP*.42,7),y:YC-7,width:Math.min(CP*.84,14),height:14,rx:2,
      fill:cssv(KCOL8[n.k]),'fill-opacity':n.k==='necessary'?.98:.6},gTop);
    el('line',{x1:n.x,y1:YM+16,x2:cx,y2:YC-9,stroke:tint('--ok',.12),'stroke-width':.6},gTop);
    st.hitC(cx,YC,9,2,'<b>N'+n.i+'</b> '+esc(n.lab)+'<br>在最优轨迹上的位置<br>'+KZH8[n.k],
      ()=>openV8Node('main',n.i));
  });
  V.missing.forEach((mv,j)=>{
    const cx=M.X0+(V.skeleton_n+j)*CP;
    el('path',{d:'M '+cx+' '+(YC-9)+' L '+(cx+7)+' '+YC+' L '+cx+' '+(YC+9)+' L '+(cx-7)+' '+YC+' Z',
      fill:tint('--ok',.12),stroke:cssv('--ok'),'stroke-dasharray':'2 2'},gTop);
    st.hitC(cx,YC,9,2,'<b>补一次验证</b><br>'+esc(mv.name),null);
  });
  // 图层开关
  st.mkbtn('支路',()=>{const b=bar8('支路');const on=b.getAttribute('aria-pressed')!=='true';
    b.setAttribute('aria-pressed',on?'true':'false');gBranch.style.display=on?'':'none';},true);
  st.mkbtn('物料轨',()=>{const b=bar8('物料轨');const on=b.getAttribute('aria-pressed')!=='true';
    b.setAttribute('aria-pressed',on?'true':'false');gMat.style.display=on?'':'none';gEdge.style.display=on?'':'none';},true);
  st.mkbtn('迟滞',()=>{const b=bar8('迟滞');const on=b.getAttribute('aria-pressed')!=='true';
    b.setAttribute('aria-pressed',on?'true':'false');gLag.style.display=on?'':'none';},true);
  st.mkbtn('子代理',()=>{const b=bar8('子代理');const on=b.getAttribute('aria-pressed')!=='true';
    b.setAttribute('aria-pressed',on?'true':'false');gSub.style.display=on?'':'none';},true);
  function bar8(t){return [...st.wrap.querySelectorAll('.zbtn')].find(b=>b.textContent===t);}
  // 小地图
  if(st.mm){
    st.mm._init(ms=>{
      const sx=ms._sx, sy=ms._sy;
      el('rect',{x:0,y:0,width:240,height:Math.round(240*M.H/M.W),fill:cssv('--surf2')},ms);
      V.phases.forEach((p,k)=>el('rect',{x:p.x0*sx,y:150*sy,width:(p.x1-p.x0)*sx,height:(M.H-210)*sy,
        fill:k%2?tint('--agent',.07):tint('--agent',.15)},ms));
      V.nodes.forEach(n=>el('rect',{x:n.x*sx-.6,y:(n.sk?YM:(laneY[n.k]||YM))*sy-1,width:1.4,height:2.4,
        fill:cssv(KCOL8[n.k]),'fill-opacity':n.sk?.95:.6},ms));
      V.subs.forEach(b=>el('rect',{x:b.x0*sx,y:b.y*sy-1,width:Math.max((b.x1-b.x0)*sx,2),height:2.2,
        fill:cssv('--dele'),'fill-opacity':.8},ms));
      const mv2=el('rect',{x:0,y:0,width:10,height:10,fill:'none',stroke:cssv('--agent'),'stroke-width':1},ms);
      const upd=()=>{const {vx,vy,vw,vh}=st.mm._view();
        mv2.setAttribute('x',vx*sx);mv2.setAttribute('y',vy*sy);
        mv2.setAttribute('width',Math.max(vw*sx,4));mv2.setAttribute('height',Math.max(vh*sy,4));};
      const _apply=st.apply; // hook：缩放平移后同步小地图视口框
      st.apply=()=>{_apply();upd();};
      upd();
    });
  }
  st.home();   // 同 V7：默认纵向占满左起，全览留给按钮
}
/* V8 的节点证据面板（与六视图 openNode 不同：读 details 侧车全文） */
function openV8Node(scope,i,lane){
  if(scope==='sub'){
    const b=D.v8.subs.find(x=>x.lane===lane);
    const m=(b&&b.nodes.find(x=>x.i===i))||{};
    const key='sub:'+lane+':'+i, ds=det8v(key);
    open('lane'+lane+'·'+i+' · '+hhmm(m.ts)+' · 子代理',
      m.brief||(m.changes.length?('写 '+m.changes.join('、')):SKZH8[m.kind]),
      b?('任务：'+b.task):'',
      '<dl class="kv"><dt>类别</dt><dd>'+SKZH8[m.kind]+'</dd><dt>动作</dt><dd>'+(m.nacts||0)+' 个</dd>'+
      (m.err?'<dt>出错</dt><dd style="color:var(--error)">是</dd>':'')+
      ((b&&b.wrote.length)?'<dt>本线写出</dt><dd>'+b.wrote.map(t=>'<span class="tag warn">'+esc(t)+'</span>').join('')+'</dd>':'')+
      '</dl><h4>思考</h4>'+(ds.think?'<details class="actd" open><summary>'+ds.think.length+' 字</summary><pre class="raw">'+esc(ds.think)+'</pre></details>':'<div class="empty">无</div>')+
      '<h4>动作与返回</h4>'+acts8(ds,m));
    return;
  }
  const nv=D.v8.nodes.find(x=>x.i===i); if(!nv) return;
  const ds=det8v('main:'+i);
  open('N'+i+' · '+hhmm(nv.ts)+' · '+(nv.sk?'骨架':'支路'),nv.lab,
    KZH8[nv.k]+' · out '+fmtN(nv.out)+' · 在途 '+(nv.ms/1000).toFixed(1)+'s',
    '<dl class="kv"><dt>归因</dt><dd>'+esc(nv.why||'在必要闭包内')+'</dd></dl>'+
    (nv.changes.length?'<h4>写出</h4>'+nv.changes.map(t=>'<span class="tag warn">'+esc(t)+'</span>').join(''):'')+
    (nv.verified.length?'<h4>验证</h4>'+nv.verified.map(t=>'<span class="tag ok">'+esc(t)+'</span>').join(''):'')+
    '<h4>思考</h4>'+(ds.think?'<details class="actd" open><summary>'+ds.think.length+' 字</summary><pre class="raw">'+esc(ds.think)+'</pre></details>':'<div class="empty">本节点无思考块。</div>')+
    '<h4>回复</h4>'+(ds.reply?'<details class="actd"><summary>'+ds.reply.length+' 字</summary><pre class="raw">'+esc(ds.reply)+'</pre></details>':'<div class="empty">无正文（纯动作步）。</div>')+
    '<h4>动作与返回原文</h4>'+acts8(ds,nv));
}
function det8v(k){return (D.details||{})[k]||{};}
function acts8(ds,fallback){
  const acts=(ds.acts&&ds.acts.length?ds.acts:(fallback&&fallback.acts||[]));
  if(!acts.length) return '<div class="empty">纯思考，无动作。</div>';
  return acts.map(a=>'<details class="actd"><summary><span class="ai">'+(OPZH[a.op]||a.op)+
    ' · '+esc(a.tool||'')+'</span><span class="at">'+esc(a.target||a.t||'')+'</span>'+
    ((a.error||a.e)?'<span class="ae">✖ 出错</span>':'')+'</summary>'+
    ((a.prompt||a.cmd||a.args)?'<pre class="raw">'+esc(a.prompt||a.cmd||a.args)+'</pre>':'')+
    ((a.raw)?'<pre class="raw">'+esc(a.raw)+'</pre>':(a.d||a.digest?'<pre class="raw">'+esc(a.d||a.digest)+'</pre>':''))+
    '</details>').join('');
}
function openV8Sub(b){
  open('SUBAGENT · lane'+b.lane+' · N'+b.disp,b.task,
    hhmm(b.start)+' → '+hhmm(b.end)+' · '+fmtS(b.seconds)+' · '+b.requests+' 请求 · out '+fmtN(b.out),
    '<dl class="kv"><dt>时长</dt><dd>'+fmtS(b.seconds)+'</dd>'+
    '<dt>规模</dt><dd>'+b.nodes.length+' 节点 / '+b.requests+' 请求</dd>'+
    '<dt>token</dt><dd>out '+fmtN(b.out)+'</dd>'+
    (b.errors?'<dt>失败</dt><dd style="color:var(--error)">'+b.errors+' 次</dd>':'')+
    '<dt>写出</dt><dd>'+(b.wrote.length?b.wrote.map(t=>'<span class="tag warn">'+esc(t)+'</span>').join(''):'（经 exec 产出，无文件写）')+'</dd>'+
    '<dt>主线回读</dt><dd><span style="color:var(--dim)">无——报告即回传，主线未再碰这些文件</span></dd></dl>'+
    (b.report?'<h4>最终报告</h4><details class="actd" open><summary>'+b.report.length+' 字</summary><pre class="raw">'+esc(b.report)+'</pre></details>':'')+
    '<h4>带内节点</h4><p style="color:var(--dim)">回到图上点击带内的小节点，可看它每一步的思考/命令/返回。</p>');
}
/* actd 样式在 V1 钻取里定义过；这里给面板复用补一份选择器（若已存在则忽略） */

function renderAll(){ renderV1(); renderV2(); renderV3(); renderV4(); renderV5(); renderV6(); }
/* V7/V8 是固定世界坐标的画布，section 隐藏时 clientWidth=0、fit() 会算出 scale=0
   （「显示之后再画」的教训对缩放画布同样成立）——惰性渲染：首次切到该 tab 才画 */
let v7done=false, v8done=false;
"""



ERR_HTML = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>轨迹观测 · 这条录制没法出图</title>
<script>
(function(){
  var q=new URLSearchParams(location.search);
  var ok={classic:1,dark:1,light:1}, t=q.get('theme')||'';
  if(!ok[t]){try{var m=document.cookie.match(/(?:^|;\s*)ccwa_ui_theme=([^;]+)/);
    t=m?decodeURIComponent(m[1]):'';}catch(e){}}
  if(!ok[t]) t='dark';
  var r=document.documentElement; r.dataset.theme=t;
  r.style.colorScheme=(t==='dark')?'dark':'light';
  if(q.get('embed')==='1') r.dataset.embed='1';
})();
</script>
<style>
@font-face{font-family:'Inter';src:url('/static/fonts/Inter.ttf') format('truetype');font-weight:100 900;font-display:swap}
@font-face{font-family:'Noto Sans SC';src:url('/static/fonts/NotoSansSC.ttf') format('truetype');font-weight:100 900;font-display:swap}
@font-face{font-family:'JetBrains Mono';src:url('/static/fonts/JetBrainsMono.ttf') format('truetype');font-weight:100 800;font-display:swap}
:root{--void:#131318;--surf:#1E1E26;--line:#2E2E38;--ink:#F5F5F7;--muted:#C8C8D0;--artifact:#FBBF24;color-scheme:dark}
html[data-theme="classic"]{--void:#DED8CC;--surf:#FFFFFF;--line:#E1DBD0;--ink:#1A1A1A;--muted:#5C564C;--artifact:#6D5016;color-scheme:light}
html[data-theme="light"]{--void:#E8EEF0;--surf:#FFFFFF;--line:#C7D4D9;--ink:#17212B;--muted:#3D4C57;--artifact:#7A5B13;color-scheme:light}
html,body{margin:0;background:var(--void);color:var(--ink);
  font-family:"Inter","Noto Sans SC",-apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
html[data-embed="1"],html[data-embed="1"] body{background:transparent}
.box{margin:24px;padding:18px 20px;border:1px solid var(--line);border-left:3px solid var(--artifact);
  border-radius:12px;background:var(--surf);max-width:820px}
html[data-embed="1"] .box{margin:16px 0}
h1{margin:0 0 8px;font-size:15px;font-weight:640}
p{margin:0;color:var(--muted);font-size:12.5px;line-height:1.75}
code{font-family:"JetBrains Mono","SF Mono",Menlo,monospace;font-size:11.5px;color:var(--artifact)}
</style></head><body>
<div class="box" id="trajerr"><h1>__TITLE__</h1><p>__MSG__<br><code>__CODE__</code></p></div>
<script>
if(document.documentElement.dataset.embed==='1'){
  var post=function(){parent.postMessage({t:'ccwa-traj-height',
    h:Math.ceil(document.documentElement.scrollHeight)},'*');};
  try{ new ResizeObserver(post).observe(document.documentElement); }catch(e){ addEventListener('resize',post); }
  post();
}
</script></body></html>
"""


def render_error_html(msg: str, code: str) -> str:
    """出不了图时也给一张**同一套外观**的页，而不是把 JSON 丢进 API 浏览面。

    260829 真机踩到：错误走 jsonify，而 `?format=html` 会被浏览面接管渲染成一整页
    「API 响应」，嵌在分析页里就是一块完全不相干的界面，前端再去抓它的 innerText
    拼错误卡，抓出来的是「全部展开 / 复制 / 原始 JSON」这类按钮文案。
    """
    esc = (lambda t: str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    return (ERR_HTML.replace("__TITLE__", "这条录制出不了八视图")
                    .replace("__MSG__", esc(msg))
                    .replace("__CODE__", esc(code)))


def render_html(payload: dict) -> str:
    """payload → 八视图单文件 HTML（与原型 build_eight.py 同一拼装）。"""
    # 录制里带着别人的 HTML/脚本片段，JSON 直插会被里面的 `</script>` 提前闭合，
    # 整页数据当正文渲染出来（实测）。`<` 一律转成 \u003c——JSON 里等价，HTML 解析器不认。
    data = json.dumps(payload, ensure_ascii=False).replace("<", "\u003c")
    return (HTML.replace("__VIEWS__", VIEWS)
                .replace("__DATA__", data))
