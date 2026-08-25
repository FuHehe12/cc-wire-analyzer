"""LLM 输入上限配置自测（issue 260825_LLM输入上限可配置）。

用法：uv run python src/llm_selftest.py

背景：translate/AI 解读/差异解读的输入上限与分析对话的上下文上限原先是 app.py 里写死的
20,000 字符。截断一直**有自陈**（260801），但砍在哪一刀用户定不了——实测单条 system prompt
40K+ 常见，被砍一半的翻译/解读本身就是失真的结论。本测守三件事：

  ① 老配置升级零变化：没有新键的 config.json 合并后行为与默认完全一致
  ② 配置真的改变刀口：SSE 的 input_truncated 事件带的是**配置值**而不是常量
  ③ 防呆夹取：这是花钱的旋钮，0/负数/天文数字不许穿透到截断逻辑

单位是**字符**（用户拍板）：客户端算不出 token，截断提示报的也是字符，配置项与提示同单位。

LLM 不真调：没有配 key 的环境里请求会在截断事件之后立刻 error——正好，我们要断言的
就是截断事件本身，error 事件是预期终止符，不是失败。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import os                                            # noqa: E402
TMP = Path(tempfile.mkdtemp(prefix="ccwa_llm_"))
# 双隔离（260802 教训）：只隔离 CCWA_HOME 会让 settings 一半仍指用户真配置
os.environ["CCWA_HOME"] = str(TMP)
os.environ["CCWA_CLAUDE_SETTINGS"] = str(TMP / "fake_settings.json")
(TMP / "fake_settings.json").write_text(
    json.dumps({"env": {"ANTHROPIC_BASE_URL": "https://fake.example.invalid"}}),
    encoding="utf-8")

import config as CFG                                 # noqa: E402
CFG.CONFIG_DIR = TMP

import capture_store as CS                           # noqa: E402
CS.CAPTURES_DIR = TMP / "captures"
CS.ARCHIVES_DIR = TMP / "archives"
CS.SOURCES_DIR = TMP / "sources"
CS.CAPTURES_DIR.mkdir(parents=True, exist_ok=True)

import snapshot_store as SS                          # noqa: E402
SS.SNAPSHOTS_DIR = TMP / "snapshots"
SS._INDEX_FILE = SS.SNAPSHOTS_DIR / "index.jsonl"

FAILED: list[str] = []


def ok(cond, label: str, detail: str = "") -> None:
    print(("  OK   " if cond else "  FAIL ") + label + (("  " + str(detail)) if not cond and detail else ""))
    if not cond:
        FAILED.append(label)


def sse_events(resp) -> list[dict]:
    """把 SSE 响应拆成事件对象。"""
    out = []
    for line in resp.get_data(as_text=True).splitlines():
        if line.startswith("data: "):
            try:
                out.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return out


def make_prompt_snapshot(text: str) -> str:
    """真形状的提示词快照（system[2] 位置放长文本，走 _resolve_origin 的 system 路径）。"""
    rec = {
        "id": "req_llm001", "ts_start": "2026-08-25T10:00:00.000", "ts_end": "2026-08-25T10:00:05.000",
        "method": "POST", "path": "/v1/messages",
        "upstream": "https://api.anthropic.com/v1/messages",
        "request": {"headers_safe": {}, "body": {
            "model": "claude-opus-5", "stream": True,
            "system": [{"type": "text", "text": "billing header"},
                       {"type": "text", "text": "identity line"},
                       {"type": "text", "text": text}],
            "messages": [], "tools": []}},
        "response": {"status": 200, "content_blocks": [], "usage": {}},
        "error": None,
    }
    return SS.create_prompt(rec, {"kind": "system", "index": 2})["sid"]


def main() -> None:
    print(f"临时目录：{TMP}")
    import app as A                                   # noqa: E402
    C = A.app.test_client()

    print("\n[1] 老配置升级零变化（不带新键的 config.json 合并出默认值）")
    CFG.CONFIG_FILE.write_text(json.dumps({"ui_lang": "zh", "translate": {"max_tokens": 8192}}),
                               encoding="utf-8")
    cfg = CFG.get_config()
    ok(cfg["translate"]["input_max_chars"] == 20000, "缺键 → 默认 20000")
    ok(cfg["translate"]["chat_context_max_chars"] == 20000, "缺键 → 默认 20000")
    ok(A._llm_input_max() == 20000 and A._chat_ctx_max() == 20000, "app 侧读到默认")
    ok(cfg["translate"]["max_tokens"] == 8192, "既有键不受影响")

    print("\n[2] 配置改变刀口：input_truncated 事件带配置值")
    CFG.set_config({"translate": {"input_max_chars": 5000}})
    r = C.post("/api/translate", json={"text": "字" * 8000})
    evs = sse_events(r)
    cut = next((e for e in evs if "input_truncated" in e), None)
    ok(cut is not None, "超配置值 → 有截断事件")
    ok(cut and cut["input_truncated"] == 5000, "事件里是配置值 5000（不是常量 20000）", cut)
    ok(cut and cut["orig"] == 8000, "事件里原文长度 8000", cut)
    # 同样的 8000 字在默认 20K 下不该有截断事件
    CFG.set_config({"translate": {"input_max_chars": 20000}})
    r = C.post("/api/explain", json={"text": "字" * 8000})
    evs = sse_events(r)
    ok(not any("input_truncated" in e for e in evs), "默认 20K 下 8000 字不截断")
    # AI 解读走同一把刀（同一函数，换端点验证接线没漏）
    CFG.set_config({"translate": {"input_max_chars": 6000}})
    r = C.post("/api/explain", json={"text": "字" * 7000})
    cut = next((e for e in sse_events(r) if "input_truncated" in e), None)
    ok(cut and cut["input_truncated"] == 6000, "/api/explain 同一把刀", cut)

    print("\n[3] 分析对话上下文：配置改变且 level1 预算跟随")
    sid = make_prompt_snapshot("规则库正文。" * 12000)      # ≈ 72,000 字符
    CFG.set_config({"translate": {"chat_context_max_chars": 20000}})
    r = C.post("/api/analyze/chat", json={"sid": sid, "question": "这份提示词讲什么？"})
    cut = next((e for e in sse_events(r) if "input_truncated" in e), None)
    ok(cut is not None and cut["input_truncated"] == 20000, "默认 20K：72K 上下文被截", cut)
    CFG.set_config({"translate": {"chat_context_max_chars": 100000}})
    r = C.post("/api/analyze/chat", json={"sid": sid, "question": "这份提示词讲什么？"})
    evs = sse_events(r)
    ok(not any("input_truncated" in e for e in evs), "调到 100K：72K 上下文不再被截")
    # 录制快照的 level1 预算 = m - CHAT_SOURCES_MAX，配置要传导进去（不能只改截断判断）
    with A.app.test_request_context():
        m = A._chat_ctx_max()
        ok(m == 100000, "config 100K 生效")
        ok(A.CHAT_CONTEXT_MAX == 20000, "常量仍是默认值（只作 fallback，不被改写）")

    print("\n[4] 防呆夹取（花钱的旋钮，读写两侧都夹）")
    CFG.set_config({"translate": {"input_max_chars": 0, "chat_context_max_chars": -5}})
    cfg = CFG.get_config()
    ok(cfg["translate"]["input_max_chars"] == 1000, "0 → 夹到下限 1000", cfg["translate"])
    ok(cfg["translate"]["chat_context_max_chars"] == 1000, "负数 → 夹到下限 1000")
    CFG.set_config({"translate": {"input_max_chars": 999_999_999}})
    ok(CFG.get_config()["translate"]["input_max_chars"] == 2_000_000, "天文数字 → 夹到 2,000,000")
    # 手改坏的 config.json（绕过 set_config 直接写文件）读回来也要被夹
    CFG.CONFIG_FILE.write_text(
        json.dumps({"translate": {"input_max_chars": 3}}), encoding="utf-8")
    ok(CFG.get_config()["translate"]["input_max_chars"] == 1000, "手改坏文件，读侧同样夹住")

    print("\n[5] 设置页接线（load/save 的字段名与后端一致）")
    cfg = CFG.set_config({"translate": {"input_max_chars": 30000, "chat_context_max_chars": 40000}})
    r = C.get("/api/config")
    tr = r.get_json()["translate"]
    ok(tr["input_max_chars"] == 30000 and tr["chat_context_max_chars"] == 40000,
       "/api/config 回读两个新键", tr)
    html = (Path(__file__).resolve().parent / "templates" / "index.html").read_text(encoding="utf-8")
    for field in ("cfgTransInputMax", "cfgChatCtxMax"):
        ok(f'id="{field}"' in html, f"设置卡有 {field} 输入框")
    ok("input_max_chars: parseInt" in html and "chat_context_max_chars: parseInt" in html,
       "saveConfig 收集两个新键")

    print()
    if FAILED:
        print(f"[FAILED] {len(FAILED)} 条：")
        for f in FAILED:
            print("  - " + f)
    else:
        print("[ALL PASSED] LLM 输入上限配置自测通过")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        FAILED.append("自测自身崩溃")
    finally:
        import shutil
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if FAILED else 0)
