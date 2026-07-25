"""配置体检自测：每条规则造一份**真形状**的配置走一遍，并验证「该闭嘴时真的闭嘴」。

用法：uv run python src/doctor_selftest.py

为什么 fixture 要「真形状」（CLAUDE.md 教训④）：v0.2.0 一次性放过四个 bug，根因是自测 mock
用了现实中不存在的数据形状，于是测试一路绿灯却什么都没测到。这里的 settings.json 与
.credentials.json 都按真实文件复刻——真实键名（`claudeAiOauth.expiresAt`）、真实单位
（**毫秒**时间戳）、真实字段位置（`effortLevel` 在顶层而 `CLAUDE_CODE_EFFORT_LEVEL` 在 env）。

误报测试和命中测试一样重要：宁可漏报不可误报是本模块的铁律，所以「干净配置零 issue」
「第三方模式下过期 OAuth 不报」「mac 无凭据文件时 OAuth 规则静默跳过」都必须是断言。
"""
from __future__ import annotations

import json
import socket
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

TMP = Path(tempfile.mkdtemp(prefix="ccwa_doctor_"))

import config as CFG  # noqa: E402
CFG.CLAUDE_SETTINGS = TMP / "settings.json"
CFG.CONFIG_DIR = TMP

import settings_guard  # noqa: E402
settings_guard._PATCHED_MARKER = TMP / ".patched"
settings_guard.BACKUP_DIR = TMP / "backups"

import doctor  # noqa: E402

FAILED: list[str] = []
MS = 1000


def write_settings(env: dict | None = None, top: dict | None = None) -> None:
    data = {"model": "opus", "permissions": {"allow": []}}
    data.update(top or {})
    if env is not None:
        data["env"] = env
    CFG.CLAUDE_SETTINGS.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                   encoding="utf-8")


def write_creds(expires_in_seconds: float | None) -> None:
    """真形状的 .credentials.json（毫秒时间戳）。None = 删除文件（模拟 macOS Keychain）。"""
    p = TMP / ".credentials.json"
    if expires_in_seconds is None:
        p.unlink(missing_ok=True)
        return
    p.write_text(json.dumps({"claudeAiOauth": {
        "accessToken": "sk-ant-oat01-" + "x" * 20,
        "refreshToken": "sk-ant-ort01-" + "y" * 20,
        "expiresAt": int((time.time() + expires_in_seconds) * MS),
        "scopes": ["user:inference", "user:profile"],
        "subscriptionType": "max",
    }}, ensure_ascii=False), encoding="utf-8")


def codes(listen_port: int | None = None) -> set[str]:
    return {i["code"] for i in doctor.check(listen_port)["issues"]}


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}  {detail}")
    if not cond:
        FAILED.append(name)


print(f"[setup] 临时目录 {TMP}\n")

# ---- 1. 干净配置：不许报任何东西（误报测试）----
print("[1] 干净的订阅配置 —— 必须零 issue")
write_settings(env={"CLAUDE_CODE_ENABLE_TELEMETRY": "1"})
write_creds(expires_in_seconds=8 * 3600)
r = doctor.check()
check("零 issue", r["issues"] == [], str([i["code"] for i in r["issues"]]))
check("intent=subscription", r["intent"] == "subscription", r["intent"])
check("ok=True", r["ok"] is True)

print("\n[2] 干净的第三方配置 —— 必须零 issue")
write_settings(env={"ANTHROPIC_BASE_URL": "https://example-gateway.com/api/anthropic",
                    "ANTHROPIC_AUTH_TOKEN": "sk-test"})
write_creds(None)                       # 无 OAuth（也覆盖 macOS Keychain 场景）
r = doctor.check()
check("零 issue", r["issues"] == [], str([i["code"] for i in r["issues"]]))
check("intent=third_party", r["intent"] == "third_party", r["intent"])

# ---- 3. half_switch：BASE_URL 指第三方 + 无 token + 有 OAuth ----
print("\n[3] half_switch_to_subscription（切一半）")
write_settings(env={"ANTHROPIC_BASE_URL": "https://example-gateway.com/api/anthropic"})
write_creds(expires_in_seconds=8 * 3600)
check("命中", "half_switch_to_subscription" in codes())
check("是 error", any(i["severity"] == "error" for i in doctor.check()["issues"]))
write_creds(None)
check("无 OAuth 时不报（不猜用户意图）", "half_switch_to_subscription" not in codes())

# ---- 4. dead_port_leftover：loopback + 没人听 ----
print("\n[4] dead_port_leftover（死端口残留）")
write_settings(env={"ANTHROPIC_BASE_URL": "http://127.0.0.1:59998"})
check("命中", "dead_port_leftover" in codes())
# 真起一个 socket 占住端口 → 必须闭嘴（宁可漏报：可能是别的实例/cc-switch）
srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", 59997))
srv.listen(1)
threading.Thread(target=lambda: None, daemon=True).start()
write_settings(env={"ANTHROPIC_BASE_URL": "http://127.0.0.1:59997"})
check("端口有人听 → 不报", "dead_port_leftover" not in codes())
srv.close()

# ---- 5. self_reference_state：指向本实例端口但非 patch 态 ----
print("\n[5] self_reference_state（状态不一致）")
write_settings(env={"ANTHROPIC_BASE_URL": "http://127.0.0.1:5051"})
settings_guard._PATCHED_MARKER.unlink(missing_ok=True)
settings_guard._patched = False
check("命中（listen_port=5051）", "self_reference_state" in codes(listen_port=5051))
check("端口不同则不报（本地 vLLM 等合法上游）",
      "self_reference_state" not in codes(listen_port=5099))

# ---- 6. patch 态穿透：代理开着时不许满屏误报 ----
print("\n[6] patch 态穿透（代理运行期间不误报）")
write_settings(env={"ANTHROPIC_BASE_URL": "http://127.0.0.1:5051"})
write_creds(expires_in_seconds=8 * 3600)     # 场景是「订阅 + 代理开着」，凭据要在场
settings_guard._write_marker("https://api.anthropic.com", "http://127.0.0.1:5051", False)
settings_guard._patched = True
settings_guard._original_base_url = "https://api.anthropic.com"
r = doctor.check(listen_port=5051)
check("patched=True", r["patched"] is True)
check("不报 self_reference", "self_reference_state" not in {i["code"] for i in r["issues"]})
check("不报 dead_port", "dead_port_leftover" not in {i["code"] for i in r["issues"]})
check("意图穿透看真上游 → subscription", r["intent"] == "subscription", r["intent"])
settings_guard._PATCHED_MARKER.unlink(missing_ok=True)
settings_guard._patched = False
settings_guard._original_base_url = None

# ---- 7. oauth_expired / expiring_soon ----
print("\n[7] OAuth 过期与即将过期")
write_settings(env={})
write_creds(expires_in_seconds=-60)
check("过期 → oauth_expired", "oauth_expired" in codes())
write_creds(expires_in_seconds=20 * 60)
c = codes()
check("20 分钟内 → oauth_expiring_soon", "oauth_expiring_soon" in c)
check("即将过期不算 error", "oauth_expired" not in c)
# 第三方模式下过期 OAuth 无害 → 不许报（误报测试）
write_settings(env={"ANTHROPIC_BASE_URL": "https://example-gateway.com/api/anthropic",
                    "ANTHROPIC_AUTH_TOKEN": "sk-test"})
write_creds(expires_in_seconds=-60)
check("第三方模式下过期 OAuth 不报", "oauth_expired" not in codes())
check("但提示 token 盖住订阅（info）", "token_overrides_oauth" in codes())
# macOS：凭据在 Keychain，文件不存在 → OAuth 规则静默跳过
write_settings(env={})
write_creds(None)
c = codes()
check("无凭据文件时 OAuth 规则静默跳过（macOS）",
      not {"oauth_expired", "oauth_expiring_soon"} & c, str(c))

# ---- 8. effort 两条规则（实测驱动）----
print("\n[8] effort 冲突与 max 被官方端点拒绝")
write_settings(env={"CLAUDE_CODE_EFFORT_LEVEL": "max"}, top={"effortLevel": "low"})
write_creds(expires_in_seconds=8 * 3600)
c = codes()
check("两处矛盾 → effort_level_conflict", "effort_level_conflict" in c)
check("max + 官方端点 → effort_max_rejected_upstream", "effort_max_rejected_upstream" in c)
write_settings(env={"CLAUDE_CODE_EFFORT_LEVEL": "high"}, top={"effortLevel": "high"})
check("一致且非 max → 两条都不报",
      not {"effort_level_conflict", "effort_max_rejected_upstream"} & codes())
# 第三方端点不受该 400 影响 → 不许报（否则对第三方用户是纯误报）
write_settings(env={"ANTHROPIC_BASE_URL": "https://example-gateway.com/api/anthropic",
                    "ANTHROPIC_AUTH_TOKEN": "sk-test", "CLAUDE_CODE_EFFORT_LEVEL": "max"})
check("第三方端点 + max → 不报", "effort_max_rejected_upstream" not in codes())

# ---- 9. 坏文件不许让体检崩 ----
print("\n[9] 健壮性")
CFG.CLAUDE_SETTINGS.write_text("{ this is not json", encoding="utf-8")
r = doctor.check()
check("settings.json 损坏 → 体检仍返回结构", isinstance(r.get("issues"), list))
(TMP / ".credentials.json").write_text("not json either", encoding="utf-8")
r = doctor.check()
check("credentials 损坏 → 不崩", isinstance(r.get("issues"), list))
CFG.CLAUDE_SETTINGS.unlink(missing_ok=True)
r = doctor.check()
check("settings.json 不存在 → 不崩", isinstance(r.get("issues"), list))

# ---- 10. 只读保证 ----
print("\n[10] 只读保证（体检绝不改用户文件）")
write_settings(env={"ANTHROPIC_BASE_URL": "http://127.0.0.1:59998",
                    "CLAUDE_CODE_EFFORT_LEVEL": "max"}, top={"effortLevel": "low"})
write_creds(expires_in_seconds=-60)
before = (CFG.CLAUDE_SETTINGS.read_bytes(), (TMP / ".credentials.json").read_bytes())
for _ in range(3):
    doctor.check(listen_port=5051)
after = (CFG.CLAUDE_SETTINGS.read_bytes(), (TMP / ".credentials.json").read_bytes())
check("settings.json 字节未变", before[0] == after[0])
check("credentials.json 字节未变", before[1] == after[1])

print("\n" + "=" * 46)
if FAILED:
    print(f"[FAILED] {len(FAILED)} 项：{FAILED}")
else:
    print("[ALL PASSED] 配置体检全部规则 + 误报/健壮性/只读 验证通过")
