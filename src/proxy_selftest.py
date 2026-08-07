"""端到端转发测试：mock 上游 + 本软件 app，验证代理完整链路。

不动真 settings.json、不花 token。验证：
  1. CC 请求 → 本地代理 → mock 上游 转发，status/body 透传
  2. SSE 流式聚合 content_blocks 正确
  3. stop_reason / usage 解析正确
  4. headers 脱敏（authorization 不入库原文）
  5. captures 落盘
  6. settings_guard patch/restore 全流程

用法：uv run python src/proxy_selftest.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import httpx
from flask import Flask, Response

# ===== 1. 准备 fake 环境（必须在 import app 前 patch CFG）=====
tmp = Path(tempfile.mkdtemp(prefix="ccwa_e2e_"))
fake_settings = tmp / "settings.json"
fake_settings.write_text(json.dumps({
    "env": {
        # 占位：真正的 mock 上游端口在下面选好后回写（自测不抢固定端口，见 _free_port）
        "ANTHROPIC_BASE_URL": "http://127.0.0.1:0/api/anthropic",
        "ANTHROPIC_AUTH_TOKEN": "fake-token-secret",
    },
    "model": "opus",
}, ensure_ascii=False, indent=2), encoding="utf-8")

import config as CFG  # noqa: E402
CFG.CLAUDE_SETTINGS = fake_settings  # monkeypatch 真路径

import settings_guard  # noqa: E402
settings_guard.BACKUP_DIR = tmp / "backups"
settings_guard._PATCHED_MARKER = tmp / ".patched"   # marker 也重定向到临时目录，避免测试写真文件（审计 260712 #7 配套）

import capture_store  # noqa: E402
capture_store.CAPTURES_DIR = tmp / "captures"

import app as flask_app  # noqa: E402  ← 此处 app 启动时 check_orphan 用 fake 路径

# 重置可能的残留状态
settings_guard._original_base_url = None
settings_guard._patched = False
settings_guard._patched_at = None


# ===== 2. mock 上游（模拟 Anthropic Messages SSE 流）=====
# usage 用**真实的 Anthropic 键名**（input_tokens / output_tokens / cache_read_input_tokens）。
# 260713 前这里写的是短名 {"input":10,"output":2} —— 现实中根本不存在的形状。
# 后果：消费方读短名的键名错位 bug（DAG token 恒空、CLI token 恒 0）在自测里**永远暴露不出来**，
# 因为测试数据自己就是错的。测试数据必须长得像真流量，否则它只是在验证自己的幻觉。
MOCK_SSE = "\n".join([
    'event: message_start',
    'data: {"type":"message_start","message":{"id":"msg_x","usage":{"input_tokens":10,"cache_read_input_tokens":7,"cache_creation_input_tokens":0}}}',
    '',
    'event: content_block_start',
    'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}',
    '',
    'event: content_block_delta',
    'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"你好"}}',
    '',
    'event: content_block_delta',
    'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"世界"}}',
    '',
    'event: content_block_stop',
    'data: {"type":"content_block_stop","index":0}',
    '',
    'event: message_delta',
    'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":2}}',
    '',
    'event: message_stop',
    'data: {"type":"message_stop"}',
    '',
    '',
])

# 非流式 /v1/messages 响应：usage **嵌在 "usage" 里**（不是顶层）——这正是 CC 安全分类器调用的形状。
# 260713 前非 SSE 分支只在顶层找 token 键、且压根不解析 content/stop_reason → 这三样全丢。
MOCK_JSON_MSG = {
    "id": "msg_nonstream", "type": "message", "role": "assistant", "model": "glm-5.2",
    "content": [{"type": "text", "text": "safe"}],
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 551, "output_tokens": 7, "cache_read_input_tokens": 28224},
}

# 流内 error 帧：HTTP 200，错误藏在 SSE 里（上游过载/内部错误的常见形态）。
# CC 的 SDK 对此**抛异常**（bundle v2.1.183 的流迭代器有 `event==="error"` 与 data
# `type==="error"` 两条路径），所以这绝不是"成功的 200"。260731 前我们两条都不认，
# 这类请求被录成成功——失败聚合因此长期漏统计（issue 260731 G1）。
MOCK_SSE_ERROR = "\n".join([
    'event: message_start',
    'data: {"type":"message_start","message":{"id":"msg_e","usage":{"input_tokens":9}}}',
    '',
    'event: error',
    'data: {"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}',
    '',
    '',
])

# compaction 块 + 命中 stop_sequence：CC 声明 beta `context-management-2025-06-27`，
# 实测 3,488/4,652 条请求带 `context_management` 字段——自动压缩是在用的能力（G3）。
# stop_sequence 则是安全分类器截断输出的机制，10 天 200 条响应以它结束却从没记下命中值（G5）。
MOCK_SSE_COMPACT = "\n".join([
    'event: message_start',
    'data: {"type":"message_start","message":{"id":"msg_c","usage":{"input_tokens":12}}}',
    '',
    'event: content_block_start',
    'data: {"type":"content_block_start","index":0,"content_block":{"type":"compaction","content":""}}',
    '',
    'event: content_block_delta',
    'data: {"type":"content_block_delta","index":0,"delta":{"type":"compaction_delta","content":"摘要前半"}}',
    '',
    'event: content_block_delta',
    'data: {"type":"content_block_delta","index":0,"delta":{"type":"compaction_delta","content":"摘要后半"}}',
    '',
    'event: content_block_stop',
    'data: {"type":"content_block_stop","index":0}',
    '',
    # thinking 块的 signature（赋值语义）+ text 块的 citations（追加语义）——两者的累加方式
    # 不同，照 CC 累积器来，别按"看起来应该"写（issue 260731 G2/G4）。
    'event: content_block_start',
    'data: {"type":"content_block_start","index":1,"content_block":{"type":"thinking","thinking":""}}',
    '',
    'event: content_block_delta',
    'data: {"type":"content_block_delta","index":1,"delta":{"type":"thinking_delta","thinking":"想一下"}}',
    '',
    'event: content_block_delta',
    'data: {"type":"content_block_delta","index":1,"delta":{"type":"signature_delta","signature":"sig_abc123"}}',
    '',
    'event: content_block_stop',
    'data: {"type":"content_block_stop","index":1}',
    '',
    'event: content_block_start',
    'data: {"type":"content_block_start","index":2,"content_block":{"type":"text","text":""}}',
    '',
    'event: content_block_delta',
    'data: {"type":"content_block_delta","index":2,"delta":{"type":"text_delta","text":"据此"}}',
    '',
    'event: content_block_delta',
    'data: {"type":"content_block_delta","index":2,"delta":{"type":"citations_delta","citation":{"type":"web_search_result_location","title":"来源A"}}}',
    '',
    'event: content_block_stop',
    'data: {"type":"content_block_stop","index":2}',
    '',
    'event: message_delta',
    'data: {"type":"message_delta","delta":{"stop_reason":"stop_sequence","stop_sequence":"</severity>"},"usage":{"output_tokens":3}}',
    '',
    '',
])

# 260807 运行分析在真实录制里捞到的那条消息（智谱网关 429 限流）。此前它落盘成
# `[1302][�����˻��Ѵﵽ…]` —— 不是显示问题，二进制读索引文件存的就是替换字符。
GBK_ERR_MSG = "[1302] 并发请求数已达上限，请稍后重试"

mock_app = Flask("mock_upstream")


@mock_app.route("/api/anthropic/v1/messages", methods=["POST"])
def _mock_messages():
    from flask import request as _rq
    body = _rq.get_json(silent=True) or {}
    # 带 x-br 头 + 非流式：模拟 DeepSeek 对 security 响应用 brotli 压缩（issue 260731）。
    # 真实上游读 CC 的 Accept-Encoding 协商选 br；这里用显式头触发，绕过协商逻辑更稳。
    if _rq.headers.get("x-br") and not body.get("stream"):
        import brotli
        return Response(
            brotli.compress(json.dumps(MOCK_JSON_MSG).encode("utf-8")),
            status=200, mimetype="application/json",
            headers={"Content-Encoding": "br"})
    # zstd 与 br 是同一批补上的（CC 的 Accept-Encoding 同时声明了两者），但此前只有 br 有
    # 用例——zstd 分支从没被任何测试覆盖过，是 260731 打包冒烟时才第一次真跑到的。
    # 补齐格式清单时，测试也要跟着补齐整份清单，别只测踩出来的那一个。
    if _rq.headers.get("x-zstd") and not body.get("stream"):
        import zstandard
        return Response(
            zstandard.ZstdCompressor().compress(json.dumps(MOCK_JSON_MSG).encode("utf-8")),
            status=200, mimetype="application/json",
            headers={"Content-Encoding": "zstd"})
    # 非 UTF-8 的错误体（260807 P1 的真实形状）。要害是**不声明 charset**——智谱网关就是
    # 这样，Content-Type 里只有 application/json，正文却是 GBK。用显式 headers 而不是
    # mimetype= 来设，避免 Flask 自作主张补上 charset 把用例变成另一种情形。
    if _rq.headers.get("x-gbk-err"):
        payload = json.dumps({"error": {"message": GBK_ERR_MSG}}, ensure_ascii=False)
        return Response(payload.encode("gbk"), status=429,
                        headers={"Content-Type": "application/json"})
    # 同样是 GBK 正文，但上游**谎报成 UTF-8**。这条守的是"别无条件相信声明"。
    if _rq.headers.get("x-gbk-lying"):
        payload = json.dumps({"error": {"message": GBK_ERR_MSG}}, ensure_ascii=False)
        return Response(payload.encode("gbk"), status=429,
                        headers={"Content-Type": "application/json; charset=utf-8"})
    if not body.get("stream"):        # 非流式：返回普通 JSON（安全分类器就走这条）
        return Response(json.dumps(MOCK_JSON_MSG), status=200, mimetype="application/json")
    if _rq.headers.get("x-stream-error"):     # 流内 error 帧（HTTP 仍是 200）
        return Response(MOCK_SSE_ERROR, status=200, mimetype="text/event-stream")
    if _rq.headers.get("x-compaction"):       # compaction 块 + 命中 stop_sequence
        return Response(MOCK_SSE_COMPACT, status=200, mimetype="text/event-stream")
    return Response(MOCK_SSE, status=200, mimetype="text/event-stream")


@mock_app.route("/api/anthropic/v1/messages/count_tokens", methods=["POST"])
def _mock_count():
    return Response(json.dumps({"input_tokens": 42}), status=200, mimetype="application/json")


def _free_port(start: int) -> int:
    """从 start 起找一个空闲端口。自测**不许抢固定端口**（260725）：
    原先写死 5051，被正在跑的 daemon/dev server 占用时，Flask 在后台线程里 bind 失败、
    异常死在那个线程,主流程照常打印「已起」,于是测试请求打到了**别人的实例**上
    ——那个实例的上游是真端点，fake token 换回 401，报错指向「转发失败」这个完全错误的方向，
    还往对方的录制里掺了两条假请求。用 5150+ 也避开工具自己的 5051-5100 区间。"""
    import socket
    for p in range(start, start + 60):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", p))
                return p
        except OSError:
            continue
    raise SystemExit(f"[setup] {start}-{start + 59} 全被占用，找不到空闲端口做自测")


def _start(app_obj, port):
    app_obj.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)


MOCK_PORT = _free_port(5150)
APP_PORT = _free_port(MOCK_PORT + 1)
MOCK_UPSTREAM = f"http://127.0.0.1:{MOCK_PORT}/api/anthropic"
APP_BASE = f"http://127.0.0.1:{APP_PORT}"
# fake settings 的 BASE_URL 要指向本次选中的 mock 端口（不能再写死）
_s = json.loads(fake_settings.read_text(encoding="utf-8"))
_s["env"]["ANTHROPIC_BASE_URL"] = MOCK_UPSTREAM
fake_settings.write_text(json.dumps(_s, ensure_ascii=False, indent=2), encoding="utf-8")

threading.Thread(target=_start, args=(mock_app, MOCK_PORT), daemon=True).start()
flask_app.set_listen_port(APP_PORT)
threading.Thread(target=_start, args=(flask_app.app, APP_PORT), daemon=True).start()

# 探活断言取代 sleep+无条件宣布「已起」——起没起来必须由实际响应说话
for _i in range(50):
    try:
        if httpx.get(f"{APP_BASE}/api/proxy/status", timeout=0.4).status_code == 200:
            break
    except httpx.HTTPError:
        pass
    time.sleep(0.1)
else:
    raise SystemExit(f"[setup] app 在 {APP_PORT} 没起来（/api/proxy/status 探活失败）")
print(f"[setup] mock 上游 :{MOCK_PORT} + 本软件 app :{APP_PORT} 已起（探活通过）✓")


# ===== 3. 启动代理（snapshot + patch）=====
original = settings_guard.snapshot_original()
settings_guard.backup_file()
settings_guard.patch_base_url(APP_BASE)
print(f"[setup] snapshot upstream={original}, patched BASE_URL→本地")
patched = json.loads(fake_settings.read_text(encoding="utf-8"))["env"]["ANTHROPIC_BASE_URL"]
assert patched == APP_BASE, f"patch 没生效: {patched}"
assert json.loads(fake_settings.read_text(encoding="utf-8"))["env"]["ANTHROPIC_AUTH_TOKEN"] == "fake-token-secret"
print("[setup] patch OK，token 未动 ✓")


# ===== 4. 模拟 CC 发请求（流式）=====
print("\n[1] POST /v1/messages（流式）...")
resp = httpx.post(
    APP_BASE + "/v1/messages",
    headers={"content-type": "application/json",
             "authorization": "Bearer fake-token-secret",
             "anthropic-version": "2023-06-01"},
    json={"model": "glm-5.2", "max_tokens": 100,
          "messages": [{"role": "user", "content": "hi"}], "stream": True},
    timeout=30.0,
)
body_text = resp.content.decode("utf-8")  # SSE 无 charset，强制 UTF-8（真实 CC 也用 UTF-8）
print(f"    status={resp.status_code} len(body)={len(body_text)}")
# SSE 原文里 "你好"/"世界" 分在两个 delta event，不是连续子串（连续是聚合后结果）
assert resp.status_code == 200, f"转发失败: {resp.status_code}"
assert "你好" in body_text and "世界" in body_text, f"SSE delta 未透传, len={len(body_text)}"
print(f"    SSE 透传 OK（两个 text_delta 都在）✓")


# ===== 5. 验证录制 + SSE 聚合 =====
caps = capture_store.list_captures()
assert caps["total"] == 1, f"录制数异常: {caps['total']}"
rec = capture_store.get_capture(caps["items"][0]["id"])
print(f"\n[2] 录制 1 条，id={rec['id']}")
print(f"    content_blocks={rec['response']['content_blocks']}")
print(f"    stop_reason={rec['response']['stop_reason']}")
print(f"    usage={rec['response']['usage']}")
print(f"    ttft_ms={rec['response']['ttft_ms']}  total_ms={rec['response']['total_ms']}  chunks={rec['response']['chunks_count']}")
hs = rec["request"]["headers_safe"]
auth = next((v for k, v in hs.items() if k.lower() == "authorization"), None)
print(f"    headers_safe.authorization={auth}")
import classifier  # noqa: E402  （usage 键名归一的单一真源）

assert rec["response"]["content_blocks"] == [{"type": "text", "text": "你好世界"}], "SSE 聚合错误"
assert rec["response"]["stop_reason"] == "end_turn"
un = classifier.usage_norm(rec["response"])
assert un["input"] == 10 and un["output"] == 2 and un["cache_read"] == 7, f"usage 归一错误: {un}"
assert "fake-token-secret" not in json.dumps(rec["request"]["headers_safe"]), "token 未脱敏!"
assert auth is not None and auth != "Bearer fake-token-secret", f"auth 原文入库或未录: {auth}"
print("    SSE 聚合 + usage(真实键名) + 脱敏 ✓")


# ===== 6. 非流式 /v1/messages —— usage 嵌在 "usage" 里，content/stop_reason 也要解析出来 =====
# 这条正是 CC 安全分类器的形状。260713 前：只断言"录到了 2 条"，从不看录到了什么 →
# usage/content_blocks/stop_reason 三样全丢，测试却一路绿灯。
print("\n[3] POST /v1/messages（非流式，usage 嵌套）...")
r2 = httpx.post(
    APP_BASE + "/v1/messages",
    headers={"content-type": "application/json", "authorization": "Bearer fake"},
    json={"model": "glm-5.2", "max_tokens": 100,
          "messages": [{"role": "user", "content": "x"}], "stream": False},
    timeout=10.0,
)
assert r2.status_code == 200
caps2 = capture_store.list_captures()
assert caps2["total"] == 2, f"应录 2 条: {caps2['total']}"
rec2 = capture_store.get_capture(caps2["items"][0]["id"])
r2resp = rec2["response"]
print(f"    usage={r2resp.get('usage')}")
print(f"    stop_reason={r2resp.get('stop_reason')}  content_blocks={r2resp.get('content_blocks')}")
un2 = classifier.usage_norm(r2resp)
assert un2["input"] == 551 and un2["output"] == 7 and un2["cache_read"] == 28224, \
    f"非流式 usage 丢失（嵌套在 j['usage'] 里，旧代码只扫顶层）: {un2}"
assert r2resp.get("stop_reason") == "end_turn", "非流式 stop_reason 丢失（旧代码只在 SSE 分支解析）"
assert r2resp.get("content_blocks") == [{"type": "text", "text": "safe"}], \
    f"非流式 content_blocks 丢失: {r2resp.get('content_blocks')}"
print("    非流式 usage(嵌套) + stop_reason + content_blocks 全解析 ✓")


# ===== 6b. count_tokens（顶层 token 键形状）不能被上面的改动带坏 =====
print("\n[3b] POST /v1/messages/count_tokens（顶层 token 键）...")
r3 = httpx.post(
    APP_BASE + "/v1/messages/count_tokens",
    headers={"content-type": "application/json", "authorization": "Bearer fake"},
    json={"model": "glm-5.2", "messages": [{"role": "user", "content": "x"}]},
    timeout=10.0,
)
assert r3.status_code == 200
caps3 = capture_store.list_captures()
assert caps3["total"] == 3, f"应录 3 条: {caps3['total']}"
rec3 = capture_store.get_capture(caps3["items"][0]["id"])
assert classifier.usage_norm(rec3["response"])["input"] == 42, "count_tokens 顶层形状被带坏了"
print("    count_tokens 顶层 token 键仍正常 ✓")


# ===== 6c. br 压缩的非流式响应 —— 录制侧必须解压出 content/usage（issue 260731）=====
# 转发侧：代理 iter_raw 原样透传压缩字节，测试客户端 httpx（装了 brotli）自动解压。
# 录制侧：_decode_body 解压 br 后解析 content_blocks/usage —— 本次修复的核心路径。
# 修复前这条路径 body/usage/content_blocks 全丢（DeepSeek 对 security 的真实行为）。
print("\n[3c] 非流式 + Content-Encoding: br（DeepSeek 对 security 的行为）...")
r4 = httpx.post(
    APP_BASE + "/v1/messages",
    headers={"content-type": "application/json", "authorization": "Bearer fake",
             "x-br": "1", "accept-encoding": "gzip, deflate, br, zstd"},
    json={"model": "glm-5.2", "max_tokens": 100,
          "messages": [{"role": "user", "content": "x"}], "stream": False},
    timeout=10.0,
)
assert r4.status_code == 200, f"br 转发失败: {r4.status_code}"
fwd = json.loads(r4.content)  # 转发侧客户端收到的应是解压后的明文
assert fwd.get("content") == MOCK_JSON_MSG["content"], f"br 转发侧未解压: {r4.content[:120]}"
caps4 = capture_store.list_captures()
assert caps4["total"] == 4, f"应录 4 条: {caps4['total']}"
rec4 = capture_store.get_capture(caps4["items"][0]["id"])
r4resp = rec4["response"]
print(f"    usage={r4resp.get('usage')} stop={r4resp.get('stop_reason')} blocks={r4resp.get('content_blocks')}")
assert r4resp.get("content_blocks") == [{"type": "text", "text": "safe"}], \
    f"br 录制侧未解压（缺 brotli 包？）: {r4resp.get('content_blocks')}"
assert classifier.usage_norm(r4resp)["input"] == 551, f"br usage 丢失: {classifier.usage_norm(r4resp)}"
print("    br 压缩响应：转发透传 + 录制解压出 content/usage ✓")

# zstd 走同一条路径，断言同形（CC 的 Accept-Encoding 同时声明 br 和 zstd，两条都得测）
print("\n[3c'] 非流式 + Content-Encoding: zstd...")
r4z = httpx.post(
    APP_BASE + "/v1/messages",
    headers={"content-type": "application/json", "authorization": "Bearer fake",
             "x-zstd": "1", "accept-encoding": "gzip, deflate, br, zstd"},
    json={"model": "glm-5.2", "max_tokens": 100,
          "messages": [{"role": "user", "content": "x"}], "stream": False},
    timeout=10.0,
)
assert r4z.status_code == 200, f"zstd 转发失败: {r4z.status_code}"
recz = capture_store.get_capture(capture_store.list_captures()["items"][0]["id"])
rzresp = recz["response"]
assert rzresp.get("content_blocks") == [{"type": "text", "text": "safe"}], \
    f"zstd 录制侧未解压（缺 zstandard 包？）: {rzresp.get('content_blocks')}"
assert not rzresp.get("decode_error"), f"zstd 不该有 decode_error: {rzresp.get('decode_error')}"
assert classifier.usage_norm(rzresp)["input"] == 551, f"zstd usage 丢失: {classifier.usage_norm(rzresp)}"
print("    zstd 压缩响应：录制解压出 content/usage ✓")


# ===== 6d. 流内 error 帧 —— 必须录成失败，不能录成成功的 200（issue 260731 G1）=====
# 这条用例守的是本工具最难堪的一种失真：**把失败录成成功**。HTTP 状态是 200，错误藏在
# SSE 帧里；修复前 _parse_sse 不认 error 事件，rec["error"] 不写，于是失败聚合从来看不见它。
print("\n[3d] 流内 error 帧（HTTP 200，错误在 SSE 里）...")
r5 = httpx.post(
    APP_BASE + "/v1/messages",
    headers={"content-type": "application/json", "authorization": "Bearer fake",
             "x-stream-error": "1"},
    json={"model": "glm-5.2", "max_tokens": 100,
          "messages": [{"role": "user", "content": "x"}], "stream": True},
    timeout=10.0,
)
assert r5.status_code == 200, f"流内 error 场景 HTTP 应仍是 200: {r5.status_code}"
caps5 = capture_store.list_captures()
rec5 = capture_store.get_capture(caps5["items"][0]["id"])
err5 = rec5.get("error") or {}
print(f"    error={err5}")
assert err5.get("kind") == "stream_error", \
    f"流内 error 未被录成失败（这条请求会被统计成成功）: {rec5.get('error')}"
assert "overloaded_error" in (err5.get("body_snippet") or ""), \
    f"错误类型/消息没留下: {err5.get('body_snippet')}"
# 失败聚合必须认它——G1 的要害不是单条记录失真，是失败统计长期偏低。
# 一路验到 diagnose：index_record → has_error → aggregate 的失败组里能查到。
import diagnose                                        # noqa: E402
idx5 = classifier.index_record(rec5)
assert idx5.get("has_error") and idx5.get("err_kind") == "stream_error", \
    f"索引没带上错误，聚合看不到: has_error={idx5.get('has_error')} kind={idx5.get('err_kind')}"
agg5 = diagnose.aggregate([idx5])
assert agg5["failures"] == 1, f"失败聚合仍把流内 error 当成功: {agg5}"
assert agg5["items"][0]["err_kind"] == "stream_error", f"聚合分组键不对: {agg5['items'][0]}"
print(f"    流内 error：录成 stream_error 失败、进失败聚合（failures={agg5['failures']}）✓")


# ===== 6e. compaction 块 + 命中的 stop_sequence（issue 260731 G3/G5）=====
print("\n[3e] compaction 块 + stop_sequence 命中值...")
r6 = httpx.post(
    APP_BASE + "/v1/messages",
    headers={"content-type": "application/json", "authorization": "Bearer fake",
             "x-compaction": "1"},
    json={"model": "glm-5.2", "max_tokens": 100,
          "messages": [{"role": "user", "content": "x"}], "stream": True},
    timeout=10.0,
)
assert r6.status_code == 200
caps6 = capture_store.list_captures()
rec6 = capture_store.get_capture(caps6["items"][0]["id"])
r6resp = rec6["response"]
b6 = r6resp.get("content_blocks") or []
print(f"    blocks={b6} stop_sequence={r6resp.get('stop_sequence')}")
assert b6[0] == {"type": "compaction", "content": "摘要前半摘要后半"}, \
    f"compaction 块未聚合: {b6[:1]}"
assert r6resp.get("stop_sequence") == "</severity>", \
    f"命中的 stop_sequence 没记下: {r6resp.get('stop_sequence')}"
assert rec6.get("error") is None, "compaction 是正常响应，不该被判成失败"
# signature 是**赋值**、citations 是**追加进数组**——两种累加语义都照 CC 累积器（G2/G4）
assert b6[1] == {"type": "thinking", "thinking": "想一下", "signature": "sig_abc123"}, \
    f"signature_delta 未写入 thinking 块: {b6[1] if len(b6) > 1 else None}"
assert b6[2] == {"type": "text", "text": "据此",
                 "citations": [{"type": "web_search_result_location", "title": "来源A"}]}, \
    f"citations_delta 未追加进 text 块: {b6[2] if len(b6) > 2 else None}"
print("    compaction 聚合 + stop_sequence + signature(赋值) + citations(追加) ✓")


# ===== 6e. 非 UTF-8 的错误体 —— 按 charset 解，不能无条件 UTF-8（260807 P1）=====
# 这条守的是**不可逆的数据损坏**：修复前 `body_snippet` 是 `decode("utf-8", errors="replace")`，
# 非 UTF-8 的每个字节当场变 `�`，落盘即丢失、事后无法还原。放在所有 `total ==` 断言之后，
# 免得新增录制打乱既有计数（这份自测的计数是硬编码的）。
print("\n[3f] 上游用 GBK 回错误体（不声明 charset）...")
r7 = httpx.post(
    APP_BASE + "/v1/messages",
    headers={"content-type": "application/json", "authorization": "Bearer fake",
             "x-gbk-err": "1"},
    json={"model": "glm-5.2", "max_tokens": 100,
          "messages": [{"role": "user", "content": "x"}], "stream": True},
    timeout=10.0,
)
assert r7.status_code == 429, f"GBK 错误体转发状态异常: {r7.status_code}"
rec7 = capture_store.get_capture(capture_store.list_captures()["items"][0]["id"])
err7 = rec7["error"]
print(f"    body_snippet={err7['body_snippet'][:60]}")
print(f"    charset_fallback={err7.get('charset_fallback')}")
assert GBK_ERR_MSG in err7["body_snippet"], f"GBK 中文没解对: {err7['body_snippet'][:80]}"
# 最要害的一条：替换字符一旦落盘，信息就永久没了
assert "�" not in err7["body_snippet"], f"落盘仍有替换字符: {err7['body_snippet'][:80]}"
assert err7.get("charset_fallback") == "charset_undeclared:gbk", \
    f"回退标记不对: {err7.get('charset_fallback')}"
print("    GBK 错误体：中文可读 + 无替换字符 + 回退如实标记 ✓")

print("\n[3f'] 上游谎报 charset=utf-8、正文其实是 GBK...")
r8 = httpx.post(
    APP_BASE + "/v1/messages",
    headers={"content-type": "application/json", "authorization": "Bearer fake",
             "x-gbk-lying": "1"},
    json={"model": "glm-5.2", "max_tokens": 100,
          "messages": [{"role": "user", "content": "x"}], "stream": True},
    timeout=10.0,
)
assert r8.status_code == 429, f"谎报 charset 转发状态异常: {r8.status_code}"
err8 = capture_store.get_capture(capture_store.list_captures()["items"][0]["id"])["error"]
print(f"    charset_fallback={err8.get('charset_fallback')}")
assert GBK_ERR_MSG in err8["body_snippet"], f"声明错时没退到 GBK: {err8['body_snippet'][:80]}"
assert err8.get("charset_fallback") == "charset_declared_wrong:utf-8→gbk", \
    f"没标出「声明与实际不符」: {err8.get('charset_fallback')}"
print("    声明不可信时按内容探测 + 标记声明错 ✓")

# 纯单元断言：不走 HTTP，直接钉住解码函数的四条分支语义
import proxy                                          # noqa: E402
print("\n[3f''] _decode_error_body 分支语义...")
_t, _f = proxy._decode_error_body("正常 UTF-8".encode("utf-8"), "application/json")
assert (_t, _f) == ("正常 UTF-8", None), f"UTF-8 正常路径不该打标记: {(_t, _f)}"
_t, _f = proxy._decode_error_body("诚实声明".encode("gbk"), "application/json; charset=gbk")
assert (_t, _f) == ("诚实声明", None), f"上游诚实声明 GBK 时不该打标记: {(_t, _f)}"
# Python 不认识的编码名：不能让 LookupError 冒出来打断录制
_t, _f = proxy._decode_error_body("怪编码名".encode("utf-8"), "application/json; charset=x-weird-9")
assert _t == "怪编码名", f"未知编码名应回退探测而非抛异常: {(_t, _f)}"
# 谁都解不出的字节：latin-1 兜底永不失败，且**字节可从文本还原**（errors="replace" 的反面）
_raw = b"\xff\xfe\x00\x81\xff"
_t, _f = proxy._decode_error_body(_raw, "application/json")
assert _f == "charset_undecodable:latin-1", f"兜底标记不对: {_f}"
assert _t.encode("latin-1") == _raw, "latin-1 兜底必须无损（字节能原样还原）"
print("    四条分支（正常/诚实声明/未知编码名/全解不出）语义正确 ✓")


# ===== 7. 恢复 =====
settings_guard.restore()
restored = json.loads(fake_settings.read_text(encoding="utf-8"))["env"]["ANTHROPIC_BASE_URL"]
print(f"\n[4] restore 后 BASE_URL={restored}")
assert restored == original, f"恢复异常: {restored} != {original}"
print("    恢复 ✓")


# ===== 8. 清理 =====
import shutil
shutil.rmtree(tmp, ignore_errors=True)

print("\n[E2E ALL PASSED] ✓ 代理转发 / SSE 聚合 / usage / 脱敏 / 落盘 / 恢复 全链路验证通过")
