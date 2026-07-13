"""CLI 端到端自测：`uv run python src/cli_selftest.py`

在**临时 CCWA_HOME + 假 settings.json** 里跑真的 daemon / patch / restore ——
绝不碰真实 `~/.claude/settings.json`。这是本项目最危险的一条路径（改用户的 CC 配置），
260713 之前它根本无法自动测：一测就得动真配置，等于拿用户的 CC 当小白鼠。
`config.py` 的 CCWA_HOME / CCWA_CLAUDE_SETTINGS 覆盖就是为此而加。

覆盖：paths / stats / list / get(截断) / grep / dag / proxy start / status / proxy stop /
      restore（含「进程被强杀后救回死端口」）/ clear --older-than（保留天数）
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CLI = str(Path(__file__).resolve().parent / "cli.py")
ORIG_UPSTREAM = "https://fake-upstream.example.com"
FAILED: list[str] = []


def _fake_record(rid: str, kind: str) -> dict:
    """造一条形似真实抓包的记录（system 三块 + 计费头 + session_id，见 tools/lane_probe.py）。"""
    if kind == "main":
        system = [
            {"type": "text", "text": "x-anthropic-billing-header: cc_version=2.1.207.238; cc_entrypoint=cli;"},
            {"type": "text", "text": "You are Claude Code, Anthropic's official CLI for Claude."},
            {"type": "text", "text": "You are an interactive agent that helps users with software engineering tasks. " * 20},
        ]
        tools = [{"name": n} for n in ("Read", "Edit", "Bash", "Agent", "Grep")]
    else:   # security 分类器
        system = [
            {"type": "text", "text": "x-anthropic-billing-header: cc_version=2.1.207.238; cc_entrypoint=cli;"},
            {"type": "text", "text": "You are a security monitor for autonomous agents."},
        ]
        tools = []
    return {
        "id": rid, "ts_start": "2026-07-12T21:57:03.318", "ts_end": "2026-07-12T21:58:07.912",
        "method": "POST", "path": "v1/messages", "upstream": ORIG_UPSTREAM,
        "request": {
            "headers_safe": {"Authorization": "<redacted>",
                             "X-Claude-Code-Session-Id": "1a60f3bf-8f40-456a-8d53-72cd1c5612d1"},
            "body": {
                "model": "glm-5.2", "max_tokens": 32000, "system": system, "tools": tools,
                "metadata": {"user_id": json.dumps({"session_id": "1a60f3bf-8f40-456a-8d53-72cd1c5612d1"})},
                "messages": [{"role": "user", "content": "帮我查一下泳道判别的问题"}],
            },
        },
        "response": {
            "status": 200, "ttft_ms": 554, "total_ms": 63400,
            # 关键：SSE 聚合出来的是 Anthropic 全名（input_tokens），不是短名——
            # 260713 之前 CLI 读短名，token 统计恒为 0
            "usage": {"input_tokens": 24001, "output_tokens": 3155, "cache_read_input_tokens": 212800},
            "stop_reason": "tool_use",
            "content_blocks": [{"type": "text", "text": "好的，我先读一下 classifier。"}],
        },
        "error": None,
    }


def run(env, *args, expect_ok=True) -> dict:
    r = subprocess.run([sys.executable, CLI, *args], env=env, capture_output=True,
                       text=True, encoding="utf-8")
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError:
        FAILED.append(f"{args}: 非 JSON 输出 — {r.stdout[:120]} {r.stderr[:200]}")
        return {}
    if expect_ok and not out.get("ok"):
        FAILED.append(f"{args}: ok=false — {out.get('error')}")
    return out


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}  {detail}")
    if not cond:
        FAILED.append(name)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    tmp = Path(tempfile.mkdtemp(prefix="ccwa_cli_"))
    (tmp / "captures").mkdir()
    settings = tmp / "settings.json"
    settings.write_text(json.dumps({
        "env": {"ANTHROPIC_BASE_URL": ORIG_UPSTREAM, "ANTHROPIC_AUTH_TOKEN": "must-not-change"},
        "model": "opus", "permissions": {"defaultMode": "auto"},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    with (tmp / "captures" / "2026-07-12.jsonl").open("w", encoding="utf-8") as f:
        for rid, kind in (("req_aaa1111", "main"), ("req_bbb2222", "security"),
                          ("req_ccc3333", "main")):
            f.write(json.dumps(_fake_record(rid, kind), ensure_ascii=False) + "\n")

    env = {**os.environ, "CCWA_HOME": str(tmp), "CCWA_CLAUDE_SETTINGS": str(settings)}

    def base_url():
        return json.loads(settings.read_text(encoding="utf-8"))["env"].get("ANTHROPIC_BASE_URL")

    def token_intact():
        return json.loads(settings.read_text(encoding="utf-8"))["env"]["ANTHROPIC_AUTH_TOKEN"] == "must-not-change"

    print(f"[setup] 临时 CCWA_HOME = {tmp}\n")
    try:
        print("[1] 只读查询")
        o = run(env, "paths")
        check("paths 走 CCWA_HOME", str(tmp) in o.get("captures_dir", ""))
        o = run(env, "stats", "--date", "2026-07-12")
        check("stats 记录数", o.get("records") == 3, str(o.get("kinds")))
        check("stats token 键名归一", o.get("tokens", {}).get("input") == 24001 * 3,
              f"input={o.get('tokens', {}).get('input')}（3 条 × 24001；SSE 给的是 input_tokens 全名）")
        o = run(env, "list", "--date", "2026-07-12", "--kind", "main")
        check("list --kind 过滤", len(o.get("items", [])) == 2)
        o = run(env, "get", "req_aaa1111", "--date", "2026-07-12", "--part", "system", "--max-chars", "200")
        check("get --part system 截断", o.get("truncated") is True)
        check("get 输出不炸上下文", len(json.dumps(o)) < 4000, f"{len(json.dumps(o))} bytes")
        o = run(env, "get", "req_aaa1111", "--date", "2026-07-12", "--part", "tools")
        check("get --part tools 回工具名", "Agent" in (o.get("data") or []))
        o = run(env, "grep", "security monitor", "--date", "2026-07-12", "--in", "system")
        check("grep 命中", o.get("hits") == 1, f"hits={o.get('hits')}")
        o = run(env, "dag", "--date", "2026-07-12")
        check("dag 出泳道", len(o.get("lanes", [])) >= 1)

        print("\n[2] proxy start —— 真起 daemon + 真 patch（假 settings）")
        o = run(env, "proxy", "start")
        port = o.get("port")
        check("start ok", o.get("ok") is True, f"port={port}")
        check("BASE_URL 被 patch 到本地", base_url() == f"http://127.0.0.1:{port}", str(base_url()))
        check("只动 BASE_URL 一字段", token_intact())
        check("marker 已写", (tmp / ".patched").exists())
        o = run(env, "status")
        check("status 报 patch 态 + 实例在跑",
              o.get("patched") is True and o.get("app_running") is True and bool(o.get("daemon_pid")))
        check("status 说得出恢复目标", o.get("would_restore_to") == ORIG_UPSTREAM)

        print("\n[3] proxy stop —— 恢复 + 收掉 daemon")
        o = run(env, "proxy", "stop")
        check("stop 报已恢复", o.get("restored") is True, f"→ {o.get('restored_to')}")
        check("daemon 被收掉", o.get("daemon_killed") is True)
        check("BASE_URL 复原", base_url() == ORIG_UPSTREAM)
        check("marker 已清", not (tmp / ".patched").exists())

        print("\n[4] restore —— 进程被强杀留下死端口，人和 AI 都能一条命令救回")
        o = run(env, "restore")
        check("无残留时是 no-op", o.get("restored") is False)
        settings.write_text(json.dumps({      # 模拟：patch 完就被 taskkill / Cmd+Q
            "env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:59999",
                    "ANTHROPIC_AUTH_TOKEN": "must-not-change"},
            "model": "opus", "permissions": {"defaultMode": "auto"},
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        (tmp / ".patched").write_text(json.dumps({
            "original": ORIG_UPSTREAM, "listen": "http://127.0.0.1:59999",
            "had_key": True, "at": "2026-07-13T10:00:00"}), encoding="utf-8")
        o = run(env, "restore")
        check("restore 救回死端口", o.get("restored") is True,
              f"{o.get('was')} → {o.get('restored_to')}")
        check("BASE_URL 复原", base_url() == ORIG_UPSTREAM)
        check("其他字段无损", token_intact())

        print("\n[5] 保留天数（原死配置）")
        (tmp / "captures" / "2026-01-01.jsonl").write_text('{"id":"req_old"}\n', encoding="utf-8")
        o = run(env, "clear", "--older-than", "30")
        check("超期录制被清", "2026-01-01" in o.get("removed", []), str(o.get("removed")))
        check("近期录制没被误删", (tmp / "captures" / "2026-07-12.jsonl").exists())
    finally:
        run(env, "proxy", "stop", expect_ok=False)   # 兜底：别把 daemon 留在后台
        time.sleep(0.5)
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 46)
    if FAILED:
        print(f"[FAILED] {len(FAILED)} 项")
        for f in FAILED:
            print("  [x]", f)
        raise SystemExit(1)
    print("[ALL PASSED] CLI 全链路（含 patch/restore 危险路径）验证通过")


if __name__ == "__main__":
    main()
