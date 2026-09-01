"""CLI 端到端自测：`uv run python src/cli_selftest.py`

在**临时 CCWA_HOME + 假 settings.json** 里跑真的 daemon / patch / restore ——
绝不碰真实 `~/.claude/settings.json`。这是本项目最危险的一条路径（改用户的 CC 配置），
260713 之前它根本无法自动测：一测就得动真配置，等于拿用户的 CC 当小白鼠。
`config.py` 的 CCWA_HOME / CCWA_CLAUDE_SETTINGS 覆盖就是为此而加。

覆盖：paths / stats / list / get(截断) / grep / dag / proxy start / status / proxy stop /
      restore（含「进程被强杀后救回死端口」）/ clear --older-than（保留天数）
"""
from __future__ import annotations

import datetime
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


def _radar_record(rid: str, *, betas: str, session: str, host: str,
                  blocks: list[dict]) -> dict:
    """造一条给盲区雷达用的记录：beta 头 / 会话 / 上游 host / 响应块都可控。

    雷达的三条语义（未知带 host 归属、beta 关联算提升度、本工具的降级标记单列）此前零覆盖，
    而它们恰恰是最容易悄悄退化的那种逻辑——错了不报错，只是把 AI 引向错误的改进方向。"""
    return {
        "id": rid, "ts_start": "2026-07-13T10:00:00.000", "ts_end": "2026-07-13T10:00:05.000",
        "method": "POST", "path": "v1/messages", "upstream": f"https://{host}/v1/messages",
        "request": {
            "headers_safe": {"anthropic-beta": betas, "X-Claude-Code-Session-Id": session,
                             "user-agent": "claude-cli/2.1.220 (external, cli)"},
            "body": {"model": "glm-5.2", "max_tokens": 32000,
                     "system": [{"type": "text", "text": "You are Claude Code, Anthropic's official CLI for Claude."}],
                     "tools": [{"name": "Read"}],
                     "messages": [{"role": "user", "content": "hi"}]},
        },
        "response": {"status": 200, "ttft_ms": 100, "total_ms": 500,
                     "usage": {"input_tokens": 10, "output_tokens": 5},
                     "stop_reason": "end_turn", "content_blocks": blocks},
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
        # 工具循环中间步（最后一条 user 全是 tool_result）→ turn_start=false，
        # 应当并进前一轮而不是自成一轮（按轮折叠的前提，260802）
        mid = _fake_record("req_ddd4444", "main")
        mid["ts_start"] = "2026-07-12T21:59:10.000"
        mid["request"]["body"]["messages"] = [
            {"role": "user", "content": "帮我查一下泳道判别的问题"},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "Read", "input": {}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}]},
        ]
        f.write(json.dumps(mid, ensure_ascii=False) + "\n")
        # CC 合成的伪 user 消息（建议补全）→ 260902 起判 `self_prompt` 落 aux，**不再开轮**。
        # 真值是 CC 自己的记录：这一族在 jsonl 里没有 promptId、一行都不写（T1 归属对账
        # 31/31 absent）。它带全量工具 + 主线 system 指纹，靠结构位分不出来，只能靠轮首措辞。
        synth = _fake_record("req_eee5555", "main")
        synth["ts_start"] = "2026-07-12T22:05:00.000"
        synth["request"]["body"]["messages"] = [
            {"role": "user", "content": "[SUGGESTION MODE: Suggest what the user might naturally type next]"},
        ]
        f.write(json.dumps(synth, ensure_ascii=False) + "\n")
        # 反例，必须同时守住：后台任务通知**是真轮**——jsonl 给它 promptId（实测 201 行）。
        # 不能按「机器发起的都不算主线」一刀切；它仍判 main、仍开轮，只由 origin 降档成 synthetic。
        notif = _fake_record("req_fff6666", "main")
        notif["ts_start"] = "2026-07-12T22:10:00.000"
        notif["request"]["body"]["messages"] = [
            {"role": "user", "content": "[SYSTEM NOTIFICATION] Background task finished: build ok"},
        ]
        f.write(json.dumps(notif, ensure_ascii=False) + "\n")

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
        check("stats 记录数", o.get("records") == 6, str(o.get("kinds")))
        check("stats token 键名归一", o.get("tokens", {}).get("input") == 24001 * 6,
              f"input={o.get('tokens', {}).get('input')}（6 条 × 24001；SSE 给的是 input_tokens 全名）")
        o = run(env, "list", "--date", "2026-07-12", "--kind", "main")
        check("list --kind 过滤", len(o.get("items", [])) == 4)
        o = run(env, "get", "req_aaa1111", "--date", "2026-07-12", "--part", "system", "--max-chars", "200")
        check("get --part system 截断", o.get("truncated") is True)
        check("get 输出不炸上下文", len(json.dumps(o)) < 4000, f"{len(json.dumps(o))} bytes")
        o = run(env, "get", "req_aaa1111", "--date", "2026-07-12", "--part", "tools")
        check("get --part tools 回工具名", "Agent" in (o.get("data") or []))
        o = run(env, "grep", "security monitor", "--date", "2026-07-12", "--in", "system")
        check("grep 命中", o.get("hits") == 1, f"hits={o.get('hits')}")
        o = run(env, "dag", "--date", "2026-07-12")
        check("dag 出泳道", len(o.get("lanes", [])) >= 1)
        # 轮聚合（260802）：DAG 按轮折叠的全部依据。三条 main（其中一条是工具循环中间步）
        # + 一条 security → 主线两轮，中间步并进前一轮，security 归到它所属的那一轮。
        # 260902：SUGGESTION MODE 那条改判 self_prompt 落 aux、不再开轮；
        # SYSTEM NOTIFICATION 那条仍是主线轮（origin=synthetic）。仍是三轮，但构成变了。
        turns = o.get("turns") or []
        check("dag 出轮", len(turns) == 3, f"turns={len(turns)}")
        t0 = turns[0] if turns else {}
        check("轮卡带用户那轮说的话（不是模型回答）",
              t0.get("user_text") == "帮我查一下泳道判别的问题", repr(t0.get("user_text")))
        check("工具循环中间步并进前一轮，不自成一轮",
              any(t["steps"] == 2 for t in turns), str([t["steps"] for t in turns]))
        check("辅助调用归到所属轮",
              any((t.get("aux") or {}).get("security") for t in turns),
              str([t.get("aux") for t in turns]))
        check("轮带起源分类且合法（user/synthetic/command/partial）",
              all(t.get("origin") in ("user", "synthetic", "command", "partial") for t in turns),
              str([t.get("origin") for t in turns]))
        check("真人消息轮判 user",
              any(t.get("origin") == "user" and t.get("user_text") == "帮我查一下泳道判别的问题"
                  for t in turns),
              str([(t.get("origin"), (t.get("user_text") or "")[:12]) for t in turns]))
        check("CC 自发的一轮（建议补全）判 self_prompt，不开主线轮",
              all("SUGGESTION MODE" not in (t.get("user_text") or "") for t in turns)
              and any(n["kind"] == "self_prompt" and n["lane"] == "aux" for n in o.get("nodes", [])),
              str([(n["kind"], n["lane"]) for n in o.get("nodes", []) if n["kind"] == "self_prompt"]))
        check("后台任务通知仍是主线轮，只降档成 synthetic（不能一刀切）",
              any(t.get("origin") == "synthetic" and "SYSTEM NOTIFICATION" in (t.get("user_text") or "")
                  for t in turns),
              str([(t.get("origin"), (t.get("user_text") or "")[:24]) for t in turns]))
        check("每个主线/子代理节点都有归属轮",
              all(n.get("turn") for n in o.get("nodes", []) if n["kind"] in ("main", "subagent")))

        print("\n[1.5] 盲区雷达（unknowns）")
        UBIQ = "claude-code-20250219"          # 每条都带 → 基线 100%，提升度恒 1，不该被当"来源"
        NEW = "brand-new-feature-2026-08-01"   # 只跟未知一起出现 → 才是真来源
        SID_MAIN, SID_ODD = "sess-main-0001", "sess-odd-0002"
        with (tmp / "captures" / "2026-07-13.jsonl").open("w", encoding="utf-8") as f:
            for i in range(5):                 # 5 条正常记录（无未知）
                f.write(json.dumps(_radar_record(
                    f"req_ok{i}", betas=UBIQ, session=SID_MAIN, host="api.anthropic.com",
                    blocks=[{"type": "text", "text": "fine"}]), ensure_ascii=False) + "\n")
            f.write(json.dumps(_radar_record(   # 1 条带未知块 + 本工具的降级标记
                "req_unk1", betas=f"{UBIQ},{NEW}", session=SID_ODD, host="gw.example.com",
                blocks=[{"type": "weird_block", "payload": "??"},
                        {"type": "tool_use", "name": "Read", "_input_raw": '{"file'}],
            ), ensure_ascii=False) + "\n")
        o = run(env, "unknowns", "--date", "2026-07-13")
        check("雷达只把真未知计入 with_unknowns（降级不算）",
              o.get("totals", {}).get("with_unknowns") == 1 and o["totals"]["degraded"] == 1,
              str(o.get("totals")))
        blk = (o.get("blocks") or [{}])[0]
        check("未知块被报出", blk.get("value") == "weird_block", str(blk.get("value")))
        check("未知带 host 归属（判读第一步：是不是某个网关的形状差异）",
              blk.get("hosts") == {"gw.example.com": 1}, str(blk.get("hosts")))
        check("未知带 cc 版本", blk.get("cc_versions") == {"2.1.220": 1}, str(blk.get("cc_versions")))
        lift_betas = [b["value"] for b in (blk.get("betas") or [])]
        check("beta 关联只留特异的（提升度 ≥1.5）", lift_betas == [NEW], str(blk.get("betas")))
        check("基线 100% 的 beta 不冒充来源", UBIQ not in lift_betas)
        check("本工具的降级标记单列 degraded",
              [d["value"] for d in (o.get("degraded") or [])] == ["tool_use._input_raw"],
              str(o.get("degraded")))
        check("降级标记不混进 block_keys",
              all("_input_raw" not in b["value"] for b in (o.get("block_keys") or [])),
              str([b["value"] for b in (o.get("block_keys") or [])]))
        check("betas.new 认出没见过的扩展",
              [b["value"] for b in o.get("betas", {}).get("new", [])] == [NEW],
              str(o.get("betas", {}).get("new")))
        check("已知 beta 归 known 段",
              UBIQ in [b["value"] for b in o.get("betas", {}).get("known", [])])
        o = run(env, "unknowns", "--date", "2026-07-13", "--exclude-session", SID_ODD)
        check("会话过滤生效（双 CC 审计时排除审计者自身）",
              o.get("totals", {}).get("with_unknowns") == 0 and not o.get("blocks"),
              str(o.get("totals")))
        o = run(env, "stats", "--date", "2026-07-13", "--session", SID_ODD)
        check("stats 也能按会话过滤", o.get("records") == 1, str(o.get("records")))
        o = run(env, "trends", "--span", "1")
        check("trends 走 CLI 不需要服务在跑", o.get("ok") is True and "per_day" in o)

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
        # 「近期」必须**按运行当天现算**，不能写死日期：原先拿固定的 2026-07-12 当近期，
        # 它在 2026-08-11 之后就滑出 30 天窗口，于是这条断言从那天起必然失败——
        # 断言测的不再是保留策略，而是"今天是哪天"（260825 修，与压实改造无关的既有腐化）。
        recent = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        (tmp / "captures" / f"{recent}.jsonl").write_text('{"id":"req_new"}\n', encoding="utf-8")
        (tmp / "captures" / "2026-01-01.jsonl").write_text('{"id":"req_old"}\n', encoding="utf-8")
        o = run(env, "clear", "--older-than", "30")
        check("超期录制被清", "2026-01-01" in o.get("removed", []), str(o.get("removed")))
        check("近期录制没被误删", (tmp / "captures" / f"{recent}.jsonl").exists())
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
