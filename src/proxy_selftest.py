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
        "ANTHROPIC_BASE_URL": "http://127.0.0.1:5099/api/anthropic",
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
MOCK_SSE = "\n".join([
    'event: message_start',
    'data: {"type":"message_start","message":{"id":"msg_x","usage":{"input":10,"cache_read":0,"cache_creation":0}}}',
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
    'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output":2}}',
    '',
    'event: message_stop',
    'data: {"type":"message_stop"}',
    '',
    '',
])

mock_app = Flask("mock_upstream")


@mock_app.route("/api/anthropic/v1/messages", methods=["POST"])
def _mock_messages():
    return Response(MOCK_SSE, status=200, mimetype="text/event-stream")


@mock_app.route("/api/anthropic/v1/messages/count_tokens", methods=["POST"])
def _mock_count():
    return Response(json.dumps({"input_tokens": 42}), status=200, mimetype="application/json")


def _start(app_obj, port):
    app_obj.run(host="127.0.0.1", port=port, debug=False, use_reloader=False, threaded=True)


threading.Thread(target=_start, args=(mock_app, 5099), daemon=True).start()
flask_app.set_listen_port(5051)
threading.Thread(target=_start, args=(flask_app.app, 5051), daemon=True).start()
time.sleep(2.5)
print("[setup] mock 上游 :5099 + 本软件 app :5051 已起")


# ===== 3. 启动代理（snapshot + patch）=====
original = settings_guard.snapshot_original()
settings_guard.backup_file()
settings_guard.patch_base_url("http://127.0.0.1:5051")
print(f"[setup] snapshot upstream={original}, patched BASE_URL→本地")
patched = json.loads(fake_settings.read_text(encoding="utf-8"))["env"]["ANTHROPIC_BASE_URL"]
assert patched == "http://127.0.0.1:5051", f"patch 没生效: {patched}"
assert json.loads(fake_settings.read_text(encoding="utf-8"))["env"]["ANTHROPIC_AUTH_TOKEN"] == "fake-token-secret"
print("[setup] patch OK，token 未动 ✓")


# ===== 4. 模拟 CC 发请求（流式）=====
print("\n[1] POST /v1/messages（流式）...")
resp = httpx.post(
    "http://127.0.0.1:5051/v1/messages",
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
assert rec["response"]["content_blocks"] == [{"type": "text", "text": "你好世界"}], "SSE 聚合错误"
assert rec["response"]["stop_reason"] == "end_turn"
assert rec["response"]["usage"]["input"] == 10
assert rec["response"]["usage"]["output"] == 2
assert "fake-token-secret" not in json.dumps(rec["request"]["headers_safe"]), "token 未脱敏!"
assert auth is not None and auth != "Bearer fake-token-secret", f"auth 原文入库或未录: {auth}"
print("    SSE 聚合 + usage + 脱敏 ✓")


# ===== 6. 非 SSE 请求（count_tokens）也录到 =====
print("\n[3] POST /v1/messages/count_tokens（非流式）...")
r2 = httpx.post(
    "http://127.0.0.1:5051/v1/messages/count_tokens",
    headers={"content-type": "application/json", "authorization": "Bearer fake"},
    json={"model": "glm-5.2", "messages": [{"role": "user", "content": "x"}]},
    timeout=10.0,
)
print(f"    status={r2.status_code} body={r2.text}")
assert r2.status_code == 200
caps2 = capture_store.list_captures()
assert caps2["total"] == 2, f"应录 2 条: {caps2['total']}"
print("    非 SSE 请求也录到 ✓")


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
