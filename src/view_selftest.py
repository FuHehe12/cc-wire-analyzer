"""API 浏览面自测：`/view` 与 `?format=html`（issue 260825）。

用法：uv run python src/view_selftest.py

**这份自测的第一职责不是证明页面好看，是证明它没碰 AI 那一侧。**
本工具是双模式的（人看 GUI，AI 走 HTTP API），给人加视图最容易犯的错就是顺手改了
公共返回——一个多出来的字段、一次 key 重排，对 AI 消费方就是契约漂移。所以第 [1] 节
拿逐字节比对守这条，别把它简化成"字段还在就行"。

覆盖 issue 里列的六条不变量：
  ① 不带 `?format=html` 时逐字节不变          → [1]
  ② 渲染只发生在 `/api/` 前缀 + GET 上        → [4][5]
  ③ 流式响应绝不进渲染                        → [6]
  ④ 录制内容按不可信渲染（零 innerHTML）      → [3] + 静态扫描 [8]
  ⑤ 内嵌 payload 必须转义 `<`                 → [3]
  ⑥ 超限明说，不静默                          → [7]
另加 [2] 渲染保真（页面里内嵌的就是原 JSON）与 [9] 清单不腐化（url_map 全覆盖）。
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import os                                            # noqa: E402
TMP = Path(tempfile.mkdtemp(prefix="ccwa_view_"))
# **两个都要隔离**：只隔离 CCWA_HOME 会让 settings 那一半仍指向用户真配置
# （260802 实测闯过祸，见开发约定第五节）。这里虽然只读不写，也不留这个口子。
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

FAILED: list[str] = []


def ok(cond, label: str, detail: str = "") -> None:
    print(("  OK   " if cond else "  FAIL ") + label + (("  " + str(detail)) if not cond and detail else ""))
    if not cond:
        FAILED.append(label)


# ===== fixture =====
# 攻击载荷放在**录制正文里**，因为那才是真实威胁面：录的是上游与模型的输出，
# 内容不受我们控制。`</script>` 尤其关键——内嵌 payload 时它是唯一的逃逸口。
EVIL = '</script><img src=x onerror="alert(1)"><script>alert(2)</script>'
DATE = "2026-08-19"


def seed() -> int:
    recs, messages = [], []
    for i in range(4):
        messages = messages + [
            {"role": "user", "content": [{"type": "text", "text": f"第 {i} 个问题 " + EVIL}]},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": f"tu_{i}", "name": "Write",
                 "input": {"file_path": f"/x/{i}.py", "content": "行内容\n" * 400}}]},
        ]
        recs.append({
            "id": f"req_{i:07d}",
            "ts_start": f"{DATE}T10:{i:02d}:00.000",
            "ts_end": f"{DATE}T10:{i:02d}:05.000",
            "method": "POST", "path": "/v1/messages",
            "upstream": "https://api.anthropic.com/v1/messages",
            "request": {
                "headers_safe": {"X-Claude-Code-Session-Id": "s-1", "user-agent": EVIL},
                "body": {"model": "claude-opus-5", "stream": True,
                         "system": [{"type": "text", "text": "You are Claude Code. " + EVIL}],
                         "tools": [{"name": "Write", "description": "写文件",
                                    "input_schema": {"type": "object"}}],
                         "messages": messages, "max_tokens": 32000},
            },
            "response": {"status": 200, "total_ms": 4200, "ttft_ms": 900,
                         "headers_safe": {"content-type": "text/event-stream"},
                         "stop_reason": "end_turn",
                         "usage": {"input_tokens": 1000 + i, "output_tokens": 50},
                         "content_blocks": [{"type": "text", "text": f"回答 {i} " + EVIL}]},
            "error": None,
        })
    p = CS.CAPTURES_DIR / f"{DATE}.jsonl"
    with p.open("w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(recs)


N_RECS = seed()

import app as A                                      # noqa: E402
A.set_listen_port(5199)
C = A.app.test_client()

# 内嵌 payload 的抓取：非贪婪匹配到**第一个** `</script>`。这正是浏览器的解析方式，
# 所以如果正文里漏了一个没转义的 `</script>`，这里抓到的就会是被截断的半截 JSON，
# json.loads 当场失败——[3] 靠的就是这个性质，别改成贪婪匹配。
PAYLOAD_RE = re.compile(r'<script id="payload" type="application/json">(.*?)</script>', re.S)
META_RE = re.compile(r'<script id="meta" type="application/json">(.*?)</script>', re.S)


def page(url: str):
    r = C.get(url)
    return r, r.get_data(as_text=True)


def payload_of(html: str):
    m = PAYLOAD_RE.search(html)
    if not m:
        return None
    return json.loads(m.group(1))


def meta_of(html: str) -> dict:
    m = META_RE.search(html)
    return json.loads(m.group(1)) if m else {}


def tpl_text() -> str:
    return (Path(__file__).resolve().parent / "templates" / "view.html").read_text(encoding="utf-8")


PROBE = [
    f"/api/captures?date={DATE}&limit=50",
    f"/api/stats?date={DATE}",
    f"/api/dag?date={DATE}",
    "/api/about",
    "/api/storage",
    "/api/sources",
    "/api/proxy/status",
    "/api/config",
]


def main() -> None:
    print(f"临时目录：{TMP}  录制 {N_RECS} 条")

    print("\n[1] 不带 format=html：逐字节不变（不变量①，AI 通道零改变）")
    baseline: dict[str, bytes] = {}
    for u in PROBE:
        baseline[u] = C.get(u).get_data()
    for u in PROBE:
        C.get(u + "&format=html" if "?" in u else u + "?format=html")   # 中间插一次渲染请求
    for u in PROBE:
        r = C.get(u)
        ok(r.get_data() == baseline[u], f"{u} 逐字节不变")
        ok(r.content_type.startswith("application/json"), f"{u} content-type 仍是 json", r.content_type)

    print("\n[2] 带 format=html：渲染保真（内嵌的就是原 JSON，不是摘要）")
    for u in PROBE:
        r, html = page(u + ("&" if "?" in u else "?") + "format=html")
        ok(r.content_type.startswith("text/html"), f"{u} 返回 html", r.content_type)
        got = payload_of(html)
        ok(got is not None, f"{u} 页面里有 payload 段")
        if got is not None:
            ok(got == json.loads(baseline[u].decode("utf-8")), f"{u} 内嵌 payload == 原 JSON")
    r, html = page(f"/api/captures?date={DATE}&limit=50&format=html")
    mt = meta_of(html)
    ok(mt.get("url") == f"/api/captures?date={DATE}&limit=50&format=html",
       "工具条如实显示被渲染的 URL（含 format 本身，页面不粉饰自己）", mt.get("url"))
    ok(mt.get("raw") == f"/api/captures?date={DATE}&limit=50",
       "「原始 JSON」链接 = 同一个 URL 去掉 format —— 审计面自己也可被审计", mt.get("raw"))
    ok(mt.get("nbytes") == len(baseline[PROBE[0]]), "页面报出的字节数 = 真实响应体长度", mt.get("nbytes"))

    print("\n[3] 注入：录制正文里的 </script> 必须被转义（不变量⑤）")
    rid = json.loads(baseline[PROBE[0]].decode("utf-8"))["items"][0]["id"]
    r, html = page(f"/api/captures/{rid}?date={DATE}&format=html")
    m = PAYLOAD_RE.search(html)
    ok(m is not None, "详情页有 payload 段")
    if m:
        seg = m.group(1)
        ok("</script>" not in seg, "payload 段内没有裸 </script>（否则浏览器会当场截断）")
        ok("\\u003c" in seg, "`<` 已转义成 \\u003c")
        rec = json.loads(seg)
        sysblk = rec["request"]["body"]["system"][0]["text"]
        ok(EVIL in sysblk, "转义是**等价变换**：JSON.parse 回来原文一字不差")
    ok("<img src=x onerror=" not in html, "攻击载荷没有以可执行形式落进 HTML")

    print("\n[4] 非 GET 不渲染（不变量②）")
    r = C.post("/api/captures/compact?format=html", json={"date": "2099-01-01"})
    ok(r.content_type.startswith("application/json"), "POST 带 format=html 仍返回 json", r.content_type)

    print("\n[5] 非 /api/ 前缀不渲染——代理路径结构上够不着（不变量②）")
    r = C.get("/not-an-api-path?format=html")
    body = r.get_data(as_text=True)
    ok("CC Wire Analyzer" not in body or "id=\"payload\"" not in body,
       "代理兜底路径没有被包成浏览面页面", r.content_type)

    print("\n[6] 流式响应放行（不变量③：get_data 会把 SSE 生成器抽干）")
    # 不真发请求——test_client 会去消费这个永不结束的 SSE。直接拿钩子本人验：
    # 构造一个 streamed Response 走一遍 _view_html，断言它原样返回。
    from flask import Response as FResp
    with A.app.test_request_context("/api/captures/stream?format=html"):
        streamed = FResp((x for x in [b'data: {}\n\n']), content_type="application/json")
        out = A._view_html(streamed)
        ok(out is streamed, "流式响应被原样放行，没有被读取")

    print("\n[7] 超限：不渲染，但必须**明说**（不变量⑥）")
    old = A._VIEW_MAX_BYTES
    try:
        A._VIEW_MAX_BYTES = 200
        r, html = page(f"/api/captures?date={DATE}&limit=50&format=html")
        ok(r.content_type.startswith("text/html"), "超限时仍是 html 页（不是 500）")
        ok(payload_of(html) is None, "超限时 payload 为 null，没有塞半份进去")
        # 页面是 JS 渲染的，静态串里没有 .notice 这个 DOM 产物——能查的是**数据契约**：
        # oversize 带着真实字节数传下去了，模板里也确实有那条分支。DOM 那一层归视觉走查。
        ok(meta_of(html).get("oversize", 0) > 0, "oversize 带着真实字节数传给了页面",
           meta_of(html).get("oversize"))
        ok(meta_of(html).get("maxBytes") == 200, "上限也一并传下去（说明文案要报出它）")
    finally:
        A._VIEW_MAX_BYTES = old
    r, html = page("/api/about?format=html")
    ok(meta_of(html).get("oversize") == 0, "恢复上限后不再报超限")
    # DOM 是 JS 建的，静态串里没有 class="notice" —— 查的是构造那句本身。
    ok('el("div", "notice")' in tpl_text() and 'T("oversizeT")' in tpl_text(),
       "模板里确实有超限说明分支（DOM 落地归视觉走查）")

    print("\n[8] 渲染面的静态护栏（不变量④）")
    tpl = (Path(__file__).resolve().parent / "templates" / "view.html").read_text(encoding="utf-8")
    # 只允许三处 innerHTML：自家文案 lead、DOMPurify 消毒后的 markdown、以及超限说明。
    # 数据一律 textContent —— 多出来的 innerHTML 就是下一个 XSS 入口，宁可在这里挡住。
    hits = re.findall(r"^.*\.innerHTML\s*=.*$", tpl, re.M)
    ok(len(hits) == 3, f"innerHTML 用法恰好 3 处（自家文案 / 消毒后 markdown / 超限说明），实际 {len(hits)}",
       "\n".join(h.strip() for h in hits))
    ok("DOMPurify.sanitize" in tpl, "markdown 分支经 DOMPurify")

    print("\n[9] 说明书渲染 + 清单不腐化")
    r, html = page("/api/ai-guide?format=html")
    ok(r.content_type.startswith("text/html"), "ai-guide 能渲染")
    md = payload_of(html)
    ok(isinstance(md, str) and "CC Wire Analyzer" in md, "markdown 以字符串原文内嵌")
    raw_md = C.get("/api/ai-guide").get_data().decode("utf-8")
    ok(md == raw_md, "渲染页内嵌的说明书 == 原始 markdown，一字不差")

    r, html = page("/view")
    ok(r.content_type.startswith("text/html"), "/view 是 html")
    m = re.search(r'<script id="endpoints" type="application/json">(.*?)</script>', html, re.S)
    ok(m is not None, "/view 带端点清单")
    listed = {e["rule"] for e in json.loads(m.group(1))} if m else set()
    expect = {str(r_.rule) for r_ in A.app.url_map.iter_rules()
              if str(r_.rule).startswith("/api/") and "GET" in (r_.methods or set())}
    # 这条守的是"清单不腐化"：新加端点自动出现，不需要有人记得回来登记。
    ok(listed == expect, f"清单覆盖 url_map 全部 GET /api/*（{len(listed)}/{len(expect)}）",
       f"缺 {sorted(expect - listed)} 多 {sorted(listed - expect)}")
    undocumented = sorted(r_ for r_ in expect if r_ not in A._VIEW_NOTES)
    ok(not undocumented, "每个端点都有一句话说明（没有就补 _VIEW_NOTES）", undocumented)

    print()
    if FAILED:
        print(f"[FAILED] {len(FAILED)} 条：")
        for f in FAILED:
            print("  - " + f)
    else:
        print("[ALL PASSED] API 浏览面自测通过")


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
