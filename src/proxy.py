"""透明 MITM 代理：catch-all 转发 + httpx 流式 + SSE 聚合录制。

代理与 UI 共进程共端口：
  - /api/* = UI 后端（app.py 注册）
  - 其余 path = catch-all 透传到上游（settings.json 原始 BASE_URL）

SSE 流式边转发边录制：generator 同时 yield 给 CC、append 到内存 buffer，
请求结束时聚合 SSE chunks 落盘。绝不 buffer 完整响应才返回（破坏流式）。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Iterator
from urllib.parse import urlparse

import httpx
from flask import Response, request, stream_with_context

import capture_store
import settings_guard

log = logging.getLogger(__name__)

# 上游客户端（连接池），首次转发时建
_CLIENT: httpx.Client | None = None

# hop-by-hop / 由 httpx 或 Flask 重算的头，不透传
HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "content-length", "host",
}

SENSITIVE_HEADERS = {
    "authorization", "x-api-key", "anthropic-auth-token", "x-anthropic-api-key",
    "anthropic-authorization", "api-key", "cookie",   # 补充防御覆盖（审计 260712 #8）
}


def _client() -> httpx.Client:
    global _CLIENT
    if _CLIENT is None:
        # read timeout 180s：流式思考链 chunk 间隔通常远小于此；同时作为客户端断开后
        # generator 卡 iter_raw 的恢复上限（审计 260712 #6：根治需 watchdog，此处务实收紧）
        _CLIENT = httpx.Client(timeout=httpx.Timeout(connect=10.0, read=180.0, write=60.0, pool=5.0))
    return _CLIENT


def _redact(headers) -> dict:
    """headers 脱敏 → headers_safe dict。鉴权类一律 <redacted>（审计 260712 #8：
    原 前4后4 切片会泄露 token 末尾明文且落盘 jsonl）。"""
    out = {}
    for k, v in headers.items():
        if k.lower() in SENSITIVE_HEADERS:
            out[k] = "<redacted>"
        else:
            out[k] = v
    return out


def _decode_body(body: bytes, encoding: str) -> bytes:
    """按 content-encoding 解压响应体。转发侧 iter_raw 给的是压缩字节（CC 自解压），
    录制侧需解压才能正确 decode/解析 SSE（审计 260712 #5）。"""
    if not encoding:
        return body
    try:
        if "gzip" in encoding:
            import gzip
            return gzip.decompress(body)
        if "deflate" in encoding:
            import zlib
            return zlib.decompress(body)
        if "br" in encoding:
            try:
                import brotli
                return brotli.decompress(body)
            except ImportError:
                log.warning("brotli 响应未解压（缺 brotli 包），录制 body 暂为压缩字节")
                return body
    except Exception as e:
        log.warning("body 解压失败 encoding=%s: %s", encoding, e)
    return body


def forward(path: str) -> Response:
    """转发当前 Flask request 到 UPSTREAM/path，流式录 + 转发。"""
    upstream_base = settings_guard.get_original_base_url()
    if not upstream_base:
        return Response(
            json.dumps({"error": "proxy_not_started",
                        "detail": "原 BASE_URL 未 snapshot，请先启动代理"}),
            status=503, mimetype="application/json",
        )
    upstream_base = upstream_base.rstrip("/")

    # 260718 深度防御（Bug C）：upstream 若等于我们自己 patch 进去的本地监听地址，
    # 说明 snapshot 守卫（Bug A）被绕过或 _original_base_url 被污染 —— 转发即无限递归。
    # snapshot 守卫是第一道防线，这里是最后一道。宁可 502 也不递归。
    listen = settings_guard.get_patched_listen()
    if listen and upstream_base == listen.rstrip("/"):
        log.error("拒绝自指转发：upstream=%s == 本代理监听地址（_original_base_url 被污染）",
                  upstream_base)
        return Response(
            json.dumps({"error": "self_reference_upstream",
                        "detail": f"上游地址 {upstream_base} 等于本代理自身监听地址，"
                                  "转发将无限递归。请停止代理，把 settings.json 的 "
                                  "ANTHROPIC_BASE_URL 改回真上游后重启。"}),
            status=502, mimetype="application/json")

    url = f"{upstream_base}/{path}" if path else upstream_base

    req_body = request.get_data()  # bytes
    req_headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}
    upstream_host = urlparse(upstream_base).netloc
    if upstream_host:
        req_headers["Host"] = upstream_host

    rec = capture_store.new_record()
    rec["method"] = request.method
    rec["path"] = "/" + path
    rec["upstream"] = url
    rec["request"]["headers_safe"] = _redact(req_headers)
    try:
        rec["request"]["body"] = json.loads(req_body) if req_body else None
    except (json.JSONDecodeError, UnicodeDecodeError):
        rec["request"]["body"] = None

    t0 = time.time()

    try:
        upstream = _client().send(
            _client().build_request(request.method, url, headers=req_headers, content=req_body),
            stream=True,
        )
    except httpx.ConnectError as e:
        rec["ts_end"] = capture_store._now_iso()
        rec["error"] = {"kind": "connect", "detail": str(e)}
        capture_store.append(rec)
        return Response(json.dumps({"error": "upstream_connect", "detail": str(e)}),
                        status=502, mimetype="application/json")
    except httpx.TimeoutException as e:
        rec["ts_end"] = capture_store._now_iso()
        rec["error"] = {"kind": "timeout", "detail": str(e)}
        capture_store.append(rec)
        return Response(json.dumps({"error": "upstream_timeout", "detail": str(e)}),
                        status=504, mimetype="application/json")
    except httpx.HTTPError as e:
        rec["ts_end"] = capture_store._now_iso()
        rec["error"] = {"kind": "http_error", "detail": str(e)}
        capture_store.append(rec)
        return Response(json.dumps({"error": "upstream_error", "detail": str(e)}),
                        status=502, mimetype="application/json")

    status = upstream.status_code
    resp_headers_raw = [(k, v) for k, v in upstream.headers.items() if k.lower() not in HOP_BY_HOP]
    content_type = upstream.headers.get("content-type", "application/octet-stream")
    is_sse = "text/event-stream" in content_type

    def generate() -> Iterator[bytes]:
        """边转发边录。finally 里聚合 + 落盘（即使客户端断开也录）。"""
        chunks: list[bytes] = []
        chunk_times: list[float] = []
        try:
            for chunk in upstream.iter_raw():
                if chunk:
                    chunks.append(chunk)
                    chunk_times.append(time.time() - t0)
                    yield chunk
        finally:
            try:
                upstream.close()
                _finalize(rec, status, resp_headers_raw, content_type, is_sse,
                          chunks, chunk_times, t0)
            except Exception as e:
                log.error("finalize record failed: %s", e)

    resp = Response(stream_with_context(generate()), status=status, mimetype=content_type)
    for k, v in resp_headers_raw:
        resp.headers[k] = v
    return resp


def _finalize(rec, status, resp_headers_raw, content_type, is_sse,
              chunks, chunk_times, t0):
    """聚合响应 + 落盘。在 generator finally 里调。"""
    rec["ts_end"] = capture_store._now_iso()
    total_ms = int((time.time() - t0) * 1000)
    resp = {
        "status": status,
        "headers_safe": _redact(dict(resp_headers_raw)),
        "total_ms": total_ms,
        "chunks_count": len(chunks),
        # ttft_ms：首 chunk 时间近似（首 chunk 通常是 message_start，近似首字节时间）
        "ttft_ms": int(chunk_times[0] * 1000) if chunk_times else None,
    }
    body_bytes = b"".join(chunks)
    # 录制侧按 content-encoding 解压（转发给 CC 的是压缩字节，录制/解析需解压——审计 260712 #5）
    encoding = "".join(v for k, v in resp_headers_raw if k.lower() == "content-encoding").lower()
    body_bytes = _decode_body(body_bytes, encoding)
    if is_sse:
        parsed = _parse_sse(body_bytes.decode("utf-8", errors="replace"))
        resp["stop_reason"] = parsed.get("stop_reason")
        resp["usage"] = parsed.get("usage")
        resp["content_blocks"] = parsed.get("content_blocks")
    else:
        text = None
        try:
            text = body_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text = None
        if text:
            resp["body_text"] = text[:2000]
            try:
                j = json.loads(text)
            except (json.JSONDecodeError, ValueError):
                j = None
            if isinstance(j, dict):
                # 260713：非流式响应原本只抽顶层 token 键（260712 为 count_tokens 加的，
                # 那种响应恰好是 {"input_tokens": N} 顶层形状）。但普通 /v1/messages 非流式响应
                # 把 usage **嵌在 j["usage"] 里**，顶层扫不到 → usage 整个丢失；
                # 而 stop_reason / content_blocks 更是只在 SSE 分支解析过，非流式一律没有。
                # 后果：CC 的**安全分类器调用就是非流式的** —— 它每个会话都在后台跑、用户看不见、
                # 还实实在在花钱（实测 551 in + 28224 cache_read），成本却被我们自己扔掉，
                # 用户会以为这些调用不花钱。这恰恰是本工具最该揭示的东西。
                nested = j.get("usage")
                u = dict(nested) if isinstance(nested, dict) else {}
                for k in ("input_tokens", "output_tokens",
                          "cache_read_input_tokens", "cache_creation_input_tokens"):
                    if isinstance(j.get(k), (int, float)):
                        u.setdefault(k, j[k])       # 顶层形状（count_tokens）作补充，不覆盖嵌套值
                if u:
                    resp["usage"] = u
                if j.get("stop_reason"):
                    resp["stop_reason"] = j["stop_reason"]
                if isinstance(j.get("content"), list):
                    resp["content_blocks"] = j["content"]   # 已是 Anthropic block 数组，拿来即用
    if status >= 400:
        rec["error"] = {
            "kind": f"upstream_{status // 100}xx",
            "status": status,
            "body_snippet": body_bytes.decode("utf-8", errors="replace")[:500],
        }
    rec["response"] = resp
    capture_store.append(rec)


def _parse_sse(text: str) -> dict:
    """解析 Anthropic Messages SSE 流 → content_blocks/stop_reason/usage。

    SSE event 间用空行分隔，每 event 含 data: 行（可能多行）。
    block 按 index 聚合：content_block_start 建 block，content_block_delta 累加，
    input_json_delta 累加字符串、content_block_stop 时 json.loads。
    """
    blocks: dict[int, dict] = {}
    stop_reason = None
    usage: dict | None = None

    for raw_event in text.split("\n\n"):
        data_lines = []
        for line in raw_event.split("\n"):
            if line.startswith("data:"):
                data_lines.append(line[5:].strip())
        if not data_lines:
            continue
        try:
            evt = json.loads("\n".join(data_lines))
        except json.JSONDecodeError:
            continue
        etype = evt.get("type")

        if etype == "content_block_start":
            idx = evt.get("index", 0)
            blocks[idx] = dict(evt.get("content_block") or {})
        elif etype == "content_block_delta":
            idx = evt.get("index", 0)
            delta = evt.get("delta") or {}
            blk = blocks.setdefault(idx, {})
            dtype = delta.get("type")
            if dtype == "text_delta":
                blk["type"] = blk.get("type", "text")
                blk["text"] = (blk.get("text") or "") + (delta.get("text") or "")
            elif dtype == "thinking_delta":
                blk["type"] = blk.get("type", "thinking")
                blk["thinking"] = (blk.get("thinking") or "") + (delta.get("thinking") or "")
            elif dtype == "input_json_delta":
                blk["_input_raw"] = (blk.get("_input_raw") or "") + (delta.get("partial_json") or "")
        elif etype == "content_block_stop":
            idx = evt.get("index", 0)
            blk = blocks.get(idx, {})
            if "_input_raw" in blk:
                # 先取局部变量再 loads，失败保留原始串不静默丢（审计 260712 #9）
                raw = blk.pop("_input_raw")
                try:
                    blk["input"] = json.loads(raw)
                except json.JSONDecodeError:
                    blk["input_raw_fallback"] = raw
        elif etype == "message_delta":
            d = evt.get("delta") or {}
            if "stop_reason" in d:
                stop_reason = d["stop_reason"]
            u = evt.get("usage")
            if isinstance(u, dict):
                usage = _merge_usage(usage, u)
        elif etype == "message_start":
            msg = evt.get("message") or {}
            u = msg.get("usage")
            if isinstance(u, dict):
                usage = _merge_usage(usage, u)

    return {
        "content_blocks": [blocks[i] for i in sorted(blocks.keys())],
        "stop_reason": stop_reason,
        "usage": usage,
    }


def _merge_usage(a: dict | None, b: dict) -> dict:
    """合并 usage（message_start 给 input/cache，message_delta 给 output）。"""
    out = dict(a or {})
    for k, v in b.items():
        if v is not None:
            out[k] = v
    return out
