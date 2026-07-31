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


def _decode_body(body: bytes, encoding: str) -> tuple[bytes, str | None]:
    """按 content-encoding 解压响应体 → (bytes, 失败原因或 None)。

    转发侧 iter_raw 给的是压缩字节（CC 自解压），录制侧需解压才能正确 decode/解析 SSE
    （审计 260712 #5）。

    260731 起返回失败原因而非只返回原字节：br 事件的实际表现是"解压没成功 → 正文 decode
    失败 → body/usage/content_blocks 一个都不写"，而界面上看不出任何异常，等于**静默丢数据**
    （惯犯 bug ③）。调用方拿到原因后写进 `response.decode_error`，界面如实标出来。
    格式必须支持 CC 声明的全部编码（`Accept-Encoding: gzip, deflate, br, zstd`）——
    这份清单从 CC 的请求头就能确定，不需要等某个上游踩出来（issue 260731）。
    """
    if not encoding:
        return body, None
    try:
        if "gzip" in encoding:
            import gzip
            return gzip.decompress(body), None
        if "deflate" in encoding:
            import zlib
            return zlib.decompress(body), None
        if "br" in encoding:
            try:
                import brotli
                return brotli.decompress(body), None
            except ImportError:
                log.warning("brotli 响应未解压（缺 brotli 包），录制 body 暂为压缩字节")
                return body, "missing_codec:br"
        if "zstd" in encoding:
            try:
                import zstandard
                return zstandard.ZstdDecompressor().decompress(body), None
            except ImportError:
                log.warning("zstd 响应未解压（缺 zstandard 包），录制 body 暂为压缩字节")
                return body, "missing_codec:zstd"
        # CC 声明清单之外的编码：不认识就如实说，别当成未压缩正文往下走
        log.warning("未知 content-encoding=%s，录制 body 保持原字节", encoding)
        return body, f"unknown_encoding:{encoding}"
    except Exception as e:
        log.warning("body 解压失败 encoding=%s: %s", encoding, e)
        return body, f"decompress_failed:{encoding}:{type(e).__name__}"


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
    body_bytes, decode_err = _decode_body(body_bytes, encoding)
    if decode_err:
        # 解压没成功 → 下面的解析必然全空。把原因写进记录，界面才能如实标出来，
        # 不再是"响应莫名其妙没有正文"（issue 260731 G6）。
        resp["decode_error"] = decode_err
    stream_error = None
    if is_sse:
        parsed = _parse_sse(body_bytes.decode("utf-8", errors="replace"))
        resp["stop_reason"] = parsed.get("stop_reason")
        resp["usage"] = parsed.get("usage")
        resp["content_blocks"] = parsed.get("content_blocks")
        if parsed.get("stop_sequence"):
            resp["stop_sequence"] = parsed["stop_sequence"]
        stream_error = parsed.get("stream_error")
    else:
        text = None
        try:
            text = body_bytes.decode("utf-8")
        except UnicodeDecodeError:
            # 解压成功但不是 UTF-8（或压根没解压成功）。同样别静默留空。
            text = None
            resp.setdefault("decode_error", "utf8_decode_failed")
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
    elif stream_error:
        # HTTP 200 但流里报了错。写 error 后 `has_error` 为真，这条才会进失败聚合
        # （diagnose.py 的 `_is_failure` 认 has_error）——这正是 G1 要修的：
        # 此前这类请求被统计成成功。
        rec["error"] = {
            "kind": "stream_error",
            "status": status,
            "body_snippet": (f"{stream_error.get('type') or 'error'}: "
                             f"{stream_error.get('message') or ''}")[:500],
        }
    rec["response"] = resp
    capture_store.append(rec)


def _parse_sse(text: str) -> dict:
    """解析 Anthropic Messages SSE 流 → content_blocks/stop_reason/stop_sequence/usage/stream_error。

    SSE event 间用空行分隔，每 event 含 data: 行（可能多行），可能还有 event: 行给帧名。
    block 按 index 聚合：content_block_start 建 block，content_block_delta 累加，
    input_json_delta 累加字符串、content_block_stop 时 json.loads。

    **覆盖范围以 CC 自己能处理的分支为准**（issue 260731：反编译 bundle v2.1.183 的 SSE 累积器，
    它有几个 case，就是响应形态的完整清单——我们少一个，那种响应就在录制里凭空消失）：

    | CC 的分支 | 这里 |
    |---|---|
    | message_start / content_block_{start,delta,stop} / message_delta | ✅ |
    | error（`event: error` 帧 + data 内 `type=="error"`） | ✅ 260731 补 |
    | text_delta / thinking_delta / input_json_delta | ✅ |
    | compaction_delta / signature_delta / citations_delta | ✅ 260731 补 |
    | message_stop / ping | ➖ 无信息损失，有意不处理 |

    **累加还是赋值，一律照 CC 的累积器来**：text/thinking/input_json/compaction 累加，
    signature 赋值，citations 追加进数组。别按"看起来应该"写。

    ⚠️ 注意 `agent_listing_delta` / `mcp_instructions_delta` / `deferred_tools_delta` 虽然也在
    bundle 里以 `case"..._delta"` 出现，但上下文是 React 渲染层，**不属于 wire 层**，别照着 grep
    结果盲目补。
    """
    blocks: dict[int, dict] = {}
    stop_reason = None
    stop_sequence = None
    usage: dict | None = None
    stream_error = None

    for raw_event in text.split("\n\n"):
        data_lines = []
        event_name = None
        for line in raw_event.split("\n"):
            if line.startswith("data:"):
                data_lines.append(line[5:].strip())
            elif line.startswith("event:"):
                event_name = line[6:].strip()
        if not data_lines:
            continue
        try:
            evt = json.loads("\n".join(data_lines))
        except json.JSONDecodeError:
            continue
        etype = evt.get("type")

        # 流内错误：HTTP 状态是 200，错误藏在 SSE 帧里。CC 的 SDK 有两条抛错路径
        # （bundle v2.1.183 的流迭代器）：`event: error` 帧名，以及 data 的 `type=="error"`
        # ——两条都要认。260731 前一条都不认，`etype` 匹配不上任何分支就跳过，于是这类请求
        # 在录制里是一次**成功的 200**，只是正文莫名空着。后果不止单条记录失真：失败聚合
        # （diagnose.py）的输入里从来没有过流内错误，我们报的失败数一直偏低。
        # 一个观测工具报错误率偏低，比不报更糟。详见 issue 260731 harness 事实对账 G1。
        if event_name == "error" or etype == "error":
            err = evt.get("error") if isinstance(evt.get("error"), dict) else {}
            stream_error = {
                "type": err.get("type") or etype or event_name,
                "message": err.get("message") or "",
            }
            continue

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
            elif dtype == "signature_delta":
                # thinking 块的签名。CC 的累积器是**赋值**不是累加
                # （bundle：`{...r, signature: t.delta.signature}`），照它来。
                # 关系到字节级复原的完整性——这是本项目的立项承诺之一。
                if delta.get("signature"):
                    blk["signature"] = delta["signature"]
            elif dtype == "citations_delta":
                # 引用**追加**进 text 块的 citations 数组
                # （bundle：`citations: [...(r.citations ?? []), t.delta.citation]`）。
                if delta.get("citation") is not None:
                    blk.setdefault("citations", []).append(delta["citation"])
            elif dtype == "compaction_delta":
                # 上下文自动压缩产出的块。CC 声明 beta `context-management-2025-06-27`，
                # 且实测 3,488/4,652 条请求带 `context_management` 字段——这是在用的能力，
                # 不是边角。压缩何时发生、压出了什么，正是 wire 层最该揭示的东西之一。
                blk["type"] = blk.get("type", "compaction")
                blk["content"] = (blk.get("content") or "") + (delta.get("content") or "")
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
            if d.get("stop_sequence"):
                # 命中的是哪个停止序列。安全分类器正是靠 stop_sequences 截断输出的
                # （残缺的 `<severity>N` 就是这么来的，见 classifier.py 的说明），
                # 知道命中哪个序列对解读审查结果直接有用。实测 10 天 200 条响应以
                # stop_sequence 结束，此前一条都没记下命中值。
                stop_sequence = d["stop_sequence"]
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
        "stop_sequence": stop_sequence,
        "usage": usage,
        "stream_error": stream_error,
    }


def _merge_usage(a: dict | None, b: dict) -> dict:
    """合并 usage（message_start 给 input/cache，message_delta 给 output）。"""
    out = dict(a or {})
    for k, v in b.items():
        if v is not None:
            out[k] = v
    return out
