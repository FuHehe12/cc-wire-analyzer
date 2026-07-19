"""CLI 入口：让 AI agent（Claude Code / opencode / …）能直接调起代理并解析录制。

设计前提：**调用方是 agent，不是 shell 玩家**。因此：
  - 一律输出 JSON（字段稳定、可解析），不做花哨的人类排版；
  - 所有可能吐大内容的命令默认**截断**并显式标注 `truncated`——单条录制可达数 MB
    （一条 main 请求带完整 system prompt + 71~100 个工具的 JSON Schema），
    直接 cat jsonl 会当场炸掉 agent 的上下文；
  - 检索姿势由命令形状强制成「先窄后宽」：list/grep 只回摘要与片段 → 定位到 id → get 取详情。

进程模型（关键）：CLI 是**独立进程**，settings_guard 的模块状态（_patched 等）对它不可见。
所以 status/restore 一律以**磁盘事实**为准：`.patched` marker + settings.json 的真实内容，
绝不依赖内存状态。若检测到已有实例（GUI 或 daemon）在跑，就驱动它的 /api/*，而不是另起一个服务器
——两个进程同时 patch 同一个 settings.json 是灾难。

用法见 docs/AI_USAGE.md。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as CFG          # noqa: E402
import capture_store          # noqa: E402
import classifier             # noqa: E402
import settings_guard         # noqa: E402

PID_FILE = CFG.CONFIG_DIR / "daemon.pid"   # 只记 CLI 起的 headless daemon；GUI 不写这个


# ===== 输出 =====

def _out(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def _die(code: str, msg: str, **extra) -> None:
    _out({"ok": False, "error_code": code, "error": msg, **extra})
    raise SystemExit(1)


# ===== 截断（上下文安全的命脉）=====

def _shrink(obj, max_str: int):
    """递归截断所有长字符串叶子。返回 (对象, 是否发生截断)。"""
    hit = False

    def walk(o):
        nonlocal hit
        if isinstance(o, str):
            if len(o) > max_str:
                hit = True
                return o[:max_str] + f"…[+{len(o) - max_str} chars truncated]"
            return o
        if isinstance(o, list):
            return [walk(x) for x in o]
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        return o

    return walk(obj), hit


# ===== 实例发现 =====

def _read_port() -> int | None:
    try:
        return int(CFG.PORT_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _api(port: int, path: str, method: str = "GET", body: dict | None = None, timeout: float = 5.0):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=(json.dumps(body).encode("utf-8") if body is not None else None),
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:          # 409 already_running 等，body 里有结构化信息
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return None
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return None


def _live_instance() -> int | None:
    """port.txt 指向的实例是否真活着（GUI 或 daemon 都算）。活着返回端口。"""
    port = _read_port()
    if not port:
        return None
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            pass
    except OSError:
        return None                              # 端口文件是陈的（上次的进程已死）
    return port if _api(port, "/api/proxy/status") is not None else None


def _daemon_pid() -> int | None:
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    try:
        if sys.platform == "win32":
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                                 capture_output=True, text=True, timeout=5).stdout
            return pid if str(pid) in out else None
        os.kill(pid, 0)                          # 信号 0 = 只探活不打扰
        return pid
    except (OSError, subprocess.SubprocessError):
        return None


# ===== 录制读取 =====

def _lines(date: str | None) -> list[str]:
    date = date or time.strftime("%Y-%m-%d", time.localtime())
    f = capture_store.CAPTURES_DIR / f"{date}.jsonl"
    if not f.exists():
        return []
    with f.open("r", encoding="utf-8") as fh:
        return fh.readlines()


_usage = classifier.usage_norm   # 键名归一的单一真源在 classifier（别再各抄一份，那正是这个 bug 的根因）


def _brief(rec: dict) -> dict:
    """列表项：摘要 + kind（AI 最常用的定位信息），不含任何 body。"""
    body = (rec.get("request") or {}).get("body") or {}
    if not isinstance(body, dict):
        body = {}
    resp = rec.get("response") or {}
    text = ""
    for blk in resp.get("content_blocks") or []:
        if blk.get("type") == "text" and blk.get("text"):
            text = blk["text"][:100]
            break
    return {
        "id": rec.get("id"),
        "ts_start": rec.get("ts_start"),
        "kind": classifier.classify(rec),
        "model": body.get("model"),
        "path": rec.get("path"),
        "status": resp.get("status"),
        "ttft_ms": resp.get("ttft_ms"),
        "total_ms": resp.get("total_ms"),
        "usage": _usage(resp),
        "stop_reason": resp.get("stop_reason"),
        "has_error": rec.get("error") is not None,
        "summary": text,
    }


# ===== 命令 =====

def cmd_paths(a) -> None:
    today = time.strftime("%Y-%m-%d", time.localtime())
    today_f = capture_store.CAPTURES_DIR / f"{today}.jsonl"
    _out({
        "ok": True,
        "captures_dir": str(capture_store.CAPTURES_DIR),
        "today_file": str(today_f),
        "today_exists": today_f.exists(),
        "archives_dir": str(capture_store.ARCHIVES_DIR),
        "config_dir": str(CFG.CONFIG_DIR),
        "config_file": str(CFG.CONFIG_FILE),
        "log_file": str(CFG.LOG_FILE),
        "claude_settings": str(CFG.CLAUDE_SETTINGS),
        "note": "录制是 append-only JSONL，一行一条记录。不要整文件读入——用 list/grep 定位，再用 get 取单条。",
    })


def cmd_dates(a) -> None:
    _out({"ok": True, "dates": CFG.list_capture_dates()})


def cmd_status(a) -> None:
    """代理状态。以磁盘事实为准（marker + settings.json），不依赖任何进程的内存状态。"""
    marker = settings_guard.check_orphan_backup()     # 只读：marker 在就说明处于 patch 态
    port = _live_instance()
    cur = None
    try:
        cur = json.loads(CFG.CLAUDE_SETTINGS.read_text(encoding="utf-8")) \
            .get("env", {}).get("ANTHROPIC_BASE_URL")
    except (OSError, json.JSONDecodeError):
        pass
    out = {
        "ok": True,
        "patched": marker is not None,
        "current_base_url": cur,
        "app_running": port is not None,
        "app_port": port,
        "daemon_pid": _daemon_pid(),
    }
    if marker:
        out["would_restore_to"] = marker["recovered_to"]
        out["had_key"] = marker["had_key"]
    if port:
        out["app_status"] = _api(port, "/api/proxy/status")
    _out(out)


def cmd_proxy_start(a) -> None:
    port = _live_instance()
    if port is None:
        # 没有活实例 → 起一个 headless daemon（脱离终端，agent 的 Bash 调用不会被挂住）
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "proxy", "start", "--_serve"]
        else:
            cmd = [sys.executable, str(Path(__file__).resolve()), "proxy", "start", "--_serve"]
        kwargs = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = 0x00000008 | 0x08000000   # DETACHED_PROCESS | CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True                   # POSIX：脱离进程组，父进程退出不带走它
        with open(os.devnull, "wb") as null:
            p = subprocess.Popen(cmd, stdin=null, stdout=null, stderr=null, **kwargs)
        CFG.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(p.pid), encoding="utf-8")
        t0 = time.time()
        while time.time() - t0 < 20:
            port = _live_instance()
            if port:
                break
            if p.poll() is not None:
                _die("daemon_died", f"代理进程启动即退出（exit={p.returncode}），查 {CFG.LOG_FILE}")
            time.sleep(0.3)
        if not port:
            _die("daemon_timeout", f"代理 20s 内未就绪，查 {CFG.LOG_FILE}")

    # 统一走 /api/proxy/start：patch settings.json 的逻辑只此一份（备份 + 快照 + 原子改写 + 写 marker）
    res = _api(port, "/api/proxy/start", "POST", {})
    if res is None:
        _die("api_failed", "代理已起但 /api/proxy/start 无响应")
    if res.get("error") == "already_running":
        _out({"ok": True, "already_running": True, "listen": res.get("listen"), "port": port})
        return
    _out({"ok": bool(res.get("running")), "port": port, **res})


def cmd_proxy_stop(a) -> None:
    port = _live_instance()
    result = {"ok": True, "restored": False, "daemon_killed": False}
    if port:
        res = _api(port, "/api/proxy/stop", "POST", {})
        if res:
            result["restored"] = res.get("restored_to") is not None
            result["restored_to"] = res.get("restored_to")
    # 只杀 CLI 自己起的 daemon；GUI 是用户开的窗口，无权替他关
    pid = _daemon_pid()
    if pid:
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                               capture_output=True, timeout=10)
            else:
                os.kill(pid, 15)
            result["daemon_killed"] = True
        except (OSError, subprocess.SubprocessError) as e:
            result["daemon_kill_error"] = str(e)
        PID_FILE.unlink(missing_ok=True)
    if not port and not pid:
        result["note"] = "没有在跑的实例。若 settings.json 仍是 patch 态，用 restore。"
    _out(result)


def cmd_restore(a) -> None:
    """强制把 settings.json 恢复原状——不依赖任何在跑的进程。

    这是 #3 的救命通道：进程被强杀 / 关机 / macOS Cmd+Q 绕过 Python 退出钩子时，
    settings.json 会被永久留在指向死代理端口的状态，CC 从此不通。
    以前唯一的自愈是「下次启动 GUI」；现在人和 AI 都能一条命令救回来。
    """
    port = _live_instance()
    if port:                                       # 有活实例 → 走正规停止路径
        res = _api(port, "/api/proxy/stop", "POST", {})
        if res is not None:
            _out({"ok": True, "via": "running_app", "restored_to": res.get("restored_to")})
            return
    orphan = settings_guard.check_orphan_backup()   # 无实例 → 读 marker 自己恢复
    if not orphan:
        _out({"ok": True, "via": "marker", "restored": False,
              "note": "没有 patch 态残留（marker 不存在），settings.json 无需恢复。"})
        return
    settings_guard.recover_from_orphan(orphan)
    _out({"ok": True, "via": "marker", "restored": True,
          "restored_to": orphan["recovered_to"], "had_key": orphan["had_key"],
          "was": orphan.get("orphan_base_url")})


def cmd_list(a) -> None:
    lines = _lines(a.date)
    total = len(lines)
    sel = lines[::-1][a.offset:a.offset + a.limit]   # 最新的在前
    items = []
    for ln in sel:
        try:
            items.append(_brief(json.loads(ln)))
        except json.JSONDecodeError:
            continue
    if a.kind:
        items = [i for i in items if i["kind"] == a.kind]
    _out({"ok": True, "date": a.date or time.strftime("%Y-%m-%d", time.localtime()),
          "total": total, "returned": len(items), "items": items})


def cmd_get(a) -> None:
    rec = None
    for ln in _lines(a.date):
        try:
            r = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if r.get("id") == a.id:
            rec = r
            break
    if rec is None and not a.date:                   # 当天没有 → 回落翻历史
        for d in CFG.list_capture_dates():
            for ln in _lines(d["date"]):
                try:
                    r = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                if r.get("id") == a.id:
                    rec = r
                    break
            if rec:
                break
    if rec is None:
        _die("not_found", f"找不到记录 {a.id}")

    body = (rec.get("request") or {}).get("body") or {}
    parts = {
        "all": rec,
        "request": rec.get("request"),
        "response": rec.get("response"),
        "system": body.get("system"),
        "messages": body.get("messages"),
        "tools": [t.get("name") for t in (body.get("tools") or []) if isinstance(t, dict)],
        "meta": {k: v for k, v in rec.items() if k not in ("request", "response")},
    }
    if a.part not in parts:
        _die("bad_part", f"--part 只能是 {list(parts)}")
    data = parts[a.part]
    truncated = False
    if not a.full:
        data, truncated = _shrink(data, a.max_chars)
    _out({"ok": True, "id": a.id, "kind": classifier.classify(rec), "part": a.part,
          "truncated": truncated,
          "hint": ("已按 --max-chars 截断长文本；要完整内容用 --full（当心上下文）" if truncated else None),
          "data": data})


def cmd_grep(a) -> None:
    flags = 0 if a.case else re.IGNORECASE
    try:
        pat = re.compile(re.escape(a.pattern) if a.fixed else a.pattern, flags)
    except re.error as e:
        _die("bad_pattern", f"正则错误：{e}")
    hits = []
    for ln in _lines(a.date):
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError:
            continue
        body = (rec.get("request") or {}).get("body") or {}
        if not isinstance(body, dict):
            body = {}
        fields = {}
        if a.in_ in ("system", "all"):
            fields["system"] = classifier._system_text(body)
        if a.in_ in ("user", "all"):
            fields["user"] = "\n".join(classifier._user_texts(body))
        if a.in_ in ("assistant", "all"):
            fields["assistant"] = "\n".join(
                b.get("text") or "" for b in ((rec.get("response") or {}).get("content_blocks") or [])
                if b.get("type") == "text")
        for where, text in fields.items():
            m = pat.search(text or "")
            if not m:
                continue
            s = max(0, m.start() - 50)
            hits.append({
                "id": rec.get("id"), "ts_start": rec.get("ts_start"),
                "kind": classifier.classify(rec), "where": where,
                "snippet": (text[s:m.end() + 50]).replace("\n", " "),
                "match_count": len(pat.findall(text or "")),
            })
            if len(hits) >= a.limit:
                break
        if len(hits) >= a.limit:
            break
    _out({"ok": True, "pattern": a.pattern, "in": a.in_, "hits": len(hits), "items": hits,
          "note": "只回片段；要看全文用 get <id> --part system|messages"})


def cmd_dag(a) -> None:
    dag = classifier.build_dag(capture_store.list_index(a.date))
    _out({"ok": True, **dag,
          "caveat": "main/subagent 判别正在按真实流量迭代（见 issues），泳道可能把子代理算进主线。"})


def cmd_stats(a) -> None:
    from collections import Counter
    kinds, models, statuses = Counter(), Counter(), Counter()
    tin = tout = tcache = 0
    durs = []
    errors = 0
    n = 0
    for ln in _lines(a.date):
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError:
            continue
        n += 1
        body = (rec.get("request") or {}).get("body") or {}
        resp = rec.get("response") or {}
        kinds[classifier.classify(rec)] += 1
        models[(body if isinstance(body, dict) else {}).get("model") or "?"] += 1
        statuses[str(resp.get("status"))] += 1
        u = _usage(resp)
        tin += (u["input"] or 0)
        tout += (u["output"] or 0)
        tcache += (u["cache_read"] or 0)
        if resp.get("total_ms"):
            durs.append(resp["total_ms"])
        if rec.get("error"):
            errors += 1
    durs.sort()
    date = a.date or time.strftime("%Y-%m-%d", time.localtime())
    f = capture_store.CAPTURES_DIR / f"{date}.jsonl"

    def pct(p):
        return durs[min(int(len(durs) * p), len(durs) - 1)] if durs else None

    _out({"ok": True, "date": date, "records": n,
          "file_size": (f.stat().st_size if f.exists() else 0),
          "kinds": dict(kinds), "models": dict(models), "statuses": dict(statuses),
          "errors": errors, "tokens": {"input": tin, "output": tout, "cache_read": tcache},
          "total_ms": {"p50": pct(0.5), "p95": pct(0.95), "max": (durs[-1] if durs else None)}})


def cmd_clear(a) -> None:
    if a.older_than is not None:
        removed = capture_store.enforce_retention(a.older_than)
        _out({"ok": True, "mode": "older_than", "days": a.older_than, "removed": removed})
        return
    if not a.date:
        _die("bad_args", "要么 --date YYYY-MM-DD，要么 --older-than N")
    try:
        if a.mode == "archive":
            info = capture_store.archive_date(a.date)
            _out({"ok": True, "mode": "archive", "date": a.date, **info})
        else:
            _out({"ok": True, "mode": "purge", "date": a.date,
                  "removed": capture_store.purge_date(a.date)})
    except capture_store.StoreError as e:
        _die(e.code, str(e))


def _serve() -> None:
    """headless 服务（被 daemon 子进程调用）：只起 Flask，不 patch settings——
    patch 由父进程随后 POST /api/proxy/start 触发，保证「改用户 settings.json」这件事
    全项目只有一条代码路径。"""
    CFG.setup_logging()
    import app as flask_app
    port = CFG.find_free_port()
    if not port:
        raise SystemExit("无空闲端口（5051-5100 全占用）")
    flask_app.set_listen_port(port)
    CFG.write_port(port)
    flask_app.app.run(host="127.0.0.1", port=port, debug=False,
                      use_reloader=False, threaded=True)


def main(argv=None) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")   # Windows 控制台默认 GBK，中文/✓ 会炸
    except Exception:
        pass

    p = argparse.ArgumentParser(
        prog="cc-wire-analyzer",
        description="CC Wire Analyzer CLI —— 给 AI agent 用的代理控制与录制解析（输出全为 JSON）。")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("paths", help="数据目录/当天录制/日志/settings.json 的路径（agent 第一步）").set_defaults(fn=cmd_paths)
    sub.add_parser("dates", help="有哪些日期的录制（含条数与体积）").set_defaults(fn=cmd_dates)
    sub.add_parser("status", help="代理是否处于 patch 态、当前 BASE_URL、实例是否在跑").set_defaults(fn=cmd_status)
    sub.add_parser("restore", help="强制恢复 settings.json（进程被强杀/关机后救 CC 用）").set_defaults(fn=cmd_restore)

    pp = sub.add_parser("proxy", help="代理控制")
    psub = pp.add_subparsers(dest="sub", required=True)
    ps = psub.add_parser("start", help="启动代理（无实例则起 headless daemon，不挂住调用方）")
    ps.add_argument("--_serve", action="store_true", help=argparse.SUPPRESS)  # daemon 子进程内部用
    ps.set_defaults(fn=cmd_proxy_start)
    psub.add_parser("stop", help="停止代理并恢复 settings.json").set_defaults(fn=cmd_proxy_stop)
    psub.add_parser("status", help="同顶层 status").set_defaults(fn=cmd_status)

    pl = sub.add_parser("list", help="录制摘要列表（不含 body，最新在前）")
    pl.add_argument("--date"); pl.add_argument("--limit", type=int, default=50)
    pl.add_argument("--offset", type=int, default=0)
    pl.add_argument("--kind", choices=classifier.KIND_ORDER)
    pl.set_defaults(fn=cmd_list)

    pg = sub.add_parser("get", help="取单条记录（默认截断长文本，防炸上下文）")
    pg.add_argument("id"); pg.add_argument("--date")
    pg.add_argument("--part", default="meta",
                    choices=["all", "meta", "request", "response", "system", "messages", "tools"])
    pg.add_argument("--max-chars", dest="max_chars", type=int, default=2000,
                    help="单个字符串字段最多保留多少字符（默认 2000）")
    pg.add_argument("--full", action="store_true", help="不截断（当心：单条可达数 MB）")
    pg.set_defaults(fn=cmd_get)

    pr = sub.add_parser("grep", help="在录制里搜文本，只回 id + 片段")
    pr.add_argument("pattern"); pr.add_argument("--date")
    pr.add_argument("--in", dest="in_", default="all", choices=["system", "user", "assistant", "all"])
    pr.add_argument("--fixed", action="store_true", help="按字面量而非正则")
    pr.add_argument("--case", action="store_true", help="区分大小写")
    pr.add_argument("--limit", type=int, default=20)
    pr.set_defaults(fn=cmd_grep)

    pd = sub.add_parser("dag", help="时序 DAG（泳道/节点/边）")
    pd.add_argument("--date"); pd.set_defaults(fn=cmd_dag)

    pt = sub.add_parser("stats", help="当日聚合：kind/模型/状态/token/耗时分位")
    pt.add_argument("--date"); pt.set_defaults(fn=cmd_stats)

    pc = sub.add_parser("clear", help="清除录制")
    pc.add_argument("--date"); pc.add_argument("--mode", default="purge", choices=["purge", "archive"])
    pc.add_argument("--older-than", dest="older_than", type=int, help="删早于 N 天的全部录制")
    pc.set_defaults(fn=cmd_clear)

    a = p.parse_args(argv)
    if getattr(a, "_serve", False):     # daemon 子进程：进来就是当服务器，不走命令分发
        _serve()
        return
    a.fn(a)


if __name__ == "__main__":
    main()
