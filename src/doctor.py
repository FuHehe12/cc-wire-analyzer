"""配置体检：只读地检查 CC 的配置与本工具状态是否自相矛盾，发现「切一半 / 残留 / 冲突」就报。

为什么要有它（见 issues/open/260718_支持官方订阅录制.md）：用户在「官方订阅 OAuth」与
「第三方端点 + token」之间来回切，每次切一半就会撞上一类难懂的失败——BASE_URL 指第三方却没
token、BASE_URL 指着已经死掉的本地端口、effort 配置两处矛盾导致上游 400。这些都不是本工具的
bug，但**只有本工具处在能看见它们的位置**（它同时读 settings.json、知道自己 patch 没 patch、
还看得见上游的真实响应）。与其一个个去修「切一半」引发的边界 case，不如在用户开代理之前就把
矛盾指出来。

三条铁律（写死在这里，改代码时对照）：

1. **只读。** 本模块不写任何用户文件，也不提供「自动修复」。修配置是用户的决定，
   而「只撤销我们还能证明是自己做的那一笔」是本项目的安全不变量（见 CLAUDE.md）。
2. **宁可漏报不可误报。** 拿不准就降级成 info 或不报。用户看到一个不存在的「问题」，
   比漏掉一个真问题更伤——第二次误报之后，横幅就再也没人看了。
3. **不把用户锁死。** error 级会拦住「启动代理」，但调用方必须留 force 逃生门：
   规则可能错，用户比规则更了解自己的环境。

输出形状（`check()`）：

    {"ok": bool,                       # 无 error 即 True（warning/info 不影响）
     "intent": "subscription" | "third_party" | "unknown",
     "issues": [{"code", "severity", "field", "current_value", "hint"}]}

`hint` 是给 CLI/AI 看的**英文短句**；给人看的三语文案在前端按 code 查表（本模块不做 i18n，
否则同一句话就有两个真源）。
"""
from __future__ import annotations

import json
import logging
import socket
import time
from pathlib import Path
from urllib.parse import urlparse

import config as CFG
import settings_guard

log = logging.getLogger(__name__)

OFFICIAL_HOSTS = ("api.anthropic.com",)
ENV_BASE_URL = "ANTHROPIC_BASE_URL"
ENV_TOKENS = ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY")
ENV_EFFORT = "CLAUDE_CODE_EFFORT_LEVEL"
# 官方端点在 thinking 关闭时拒绝的 effort 档（实测 2026-07，见 issues/open/260725_配置体检实现.md）
EFFORT_REJECTED_BY_OFFICIAL = ("max",)
OAUTH_SOON_SECONDS = 3600


def _credentials_path() -> Path:
    """OAuth 凭据文件。Windows/Linux 在 ~/.claude/.credentials.json；
    macOS 存 Keychain（本模块不读，见下方 _oauth 的 macOS 说明）。
    跟随 CCWA_CLAUDE_SETTINGS 所在目录，这样自测能整套换到临时目录。"""
    return CFG.CLAUDE_SETTINGS.parent / ".credentials.json"


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _is_loopback(url: str) -> bool:
    try:
        return urlparse(url).hostname in ("127.0.0.1", "localhost", "::1")
    except ValueError:
        return False


def _is_official(url: str) -> bool:
    if not url:
        return True          # 无 BASE_URL = CC 直连官方
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return False
    return host in OFFICIAL_HOSTS


def _port_of(url: str) -> int | None:
    try:
        return urlparse(url).port
    except ValueError:
        return None


def _port_alive(port: int) -> bool:
    """本机该端口有没有人在听。用于区分「死端口残留」与「另一个实例/别的代理」——
    这个区别决定了报 error 还是闭嘴，所以必须实测，不能靠猜。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.25)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False


def _oauth() -> dict:
    """OAuth 凭据摘要：{present, expires_at_ms}。

    macOS 把凭据放 Keychain，文件不存在是**正常**的 → present=False 时所有 OAuth 规则
    静默跳过，绝不报「找不到凭据」（那对 mac 用户就是纯误报）。"""
    data = _read_json(_credentials_path())
    blob = data.get("claudeAiOauth") or data.get("claude.ai_oauth") or {}
    if not isinstance(blob, dict) or not blob:
        return {"present": False, "expires_at_ms": None}
    exp = blob.get("expiresAt")
    return {"present": True, "expires_at_ms": exp if isinstance(exp, (int, float)) else None}


def _effective_base_url(env: dict) -> tuple[str, bool]:
    """(用于判定的上游地址, 是否处于本工具 patch 态)。

    patch 期间 settings.json 里的 BASE_URL 就是我们自己的 loopback 地址——此时必须穿透看
    marker 里记的原始上游，否则代理一开，「意图」判定和官方端点相关的规则就全部误报。

    patch 态**以 marker 文件为准**，不能用 `is_patched()`/`get_patched_listen()`：
    那两个只反映本进程的模块状态，而 `cli.py doctor` 是独立进程跑体检，在那里它们永远是空的
    → 代理明明开着，体检却把 loopback BASE_URL 当残留报 error（260725 自测抓到）。"""
    raw = (env.get(ENV_BASE_URL) or "").rstrip("/")
    marker = settings_guard.read_marker() or {}
    listen = (marker.get("listen") or settings_guard.get_patched_listen() or "").rstrip("/")
    if listen and raw and raw == listen:
        original = marker.get("original") or settings_guard.get_original_base_url()
        return (original or settings_guard.DEFAULT_UPSTREAM), True
    return raw, False


def _intent(env: dict, base_url: str, oauth: dict) -> str:
    """从配置组合反推用户**打算**用哪种认证方式。

    「上游是官方 + 没有任何 token」就足以判定订阅意图——**不要求**凭据文件存在：
    macOS 把 OAuth 放 Keychain，文件永远读不到，若拿它当必要条件，mac 上正常的订阅配置
    会被判成 unknown（260725）。凭据文件只是补充证据，不是判定前提。"""
    has_token = any(env.get(k) for k in ENV_TOKENS) or bool(env.get("apiKeyHelper"))
    if _is_official(base_url) and not has_token:
        return "subscription"
    if has_token and not _is_official(base_url) and not _is_loopback(base_url):
        return "third_party"
    return "unknown"


def check(listen_port: int | None = None) -> dict:
    """跑一遍全部规则。单条规则出错只跳过它，不能让整个体检挂掉
    （体检本身崩了会顶到 UI 上，比它要报的问题更吓人）。"""
    settings = _read_json(CFG.CLAUDE_SETTINGS)
    env = settings.get("env") if isinstance(settings.get("env"), dict) else {}
    oauth = _oauth()
    base_url, patched = _effective_base_url(env)
    intent = _intent(env, base_url, oauth)
    ctx = {"settings": settings, "env": env, "oauth": oauth, "raw_base_url":
           env.get(ENV_BASE_URL) or "", "base_url": base_url, "patched": patched,
           "intent": intent, "listen_port": listen_port}

    issues: list[dict] = []
    for rule in (_r_half_switch, _r_dead_port, _r_self_reference, _r_oauth_expired,
                 _r_effort_conflict, _r_effort_max, _r_oauth_soon, _r_token_overrides_oauth):
        try:
            found = rule(ctx)
        except Exception:                      # noqa: BLE001 —— 规则出错不许拖垮体检
            log.exception("体检规则 %s 执行失败（已跳过）", getattr(rule, "__name__", "?"))
            continue
        if found:
            issues.append(found)
    return {"ok": not any(i["severity"] == "error" for i in issues),
            "intent": intent, "patched": patched, "issues": issues}


def _issue(code: str, severity: str, field: str, value, hint: str) -> dict:
    return {"code": code, "severity": severity, "field": field,
            "current_value": value, "hint": hint}


# ===== 规则（每条一个函数，返回 issue 或 None）=====

def _r_half_switch(ctx: dict) -> dict | None:
    """切一半：BASE_URL 指第三方，却没给 token，而 OAuth 凭据是有的。
    CC 会拿 OAuth bearer 打第三方端点 → 被拒。"""
    raw, env = ctx["raw_base_url"], ctx["env"]
    if not raw or _is_official(raw) or _is_loopback(raw):
        return None
    if any(env.get(k) for k in ENV_TOKENS) or env.get("apiKeyHelper"):
        return None
    if not ctx["oauth"]["present"]:
        return None       # 没 OAuth 也没 token：不知道用户打算怎么认证，不猜
    return _issue("half_switch_to_subscription", "error", f"env.{ENV_BASE_URL}", raw,
                  "BASE_URL points at a third-party endpoint but no auth token is set; "
                  "CC will send its subscription OAuth bearer there and be rejected. "
                  "Either remove BASE_URL (use the subscription) or add a token.")


def _r_dead_port(ctx: dict) -> dict | None:
    """BASE_URL 指着一个本机端口，而那个端口没人听 → CC 直接连不上。
    典型来源：本工具（或别的代理）被强杀，patch 没恢复。"""
    raw = ctx["raw_base_url"]
    if not raw or not _is_loopback(raw) or ctx["patched"]:
        return None
    port = _port_of(raw)
    if port is None or _port_alive(port):
        return None       # 有人在听 → 可能是另一个实例或 cc-switch，闭嘴（宁可漏报）
    return _issue("dead_port_leftover", "error", f"env.{ENV_BASE_URL}", raw,
                  "BASE_URL points at a local port with nothing listening — CC cannot "
                  "connect at all. Restore the real upstream, or start the proxy.")


def _r_self_reference(ctx: dict) -> dict | None:
    """BASE_URL 指向**本实例的**监听端口，但我们并不在 patch 态：
    状态不一致（上次退出残留 / marker 被清但文件没恢复）。转发会自指递归，
    proxy.py 有守卫拦着，但根因在配置里。"""
    raw, port_self = ctx["raw_base_url"], ctx["listen_port"]
    if not raw or not port_self or ctx["patched"]:
        return None
    if not _is_loopback(raw) or _port_of(raw) != port_self:
        return None
    return _issue("self_reference_state", "error", f"env.{ENV_BASE_URL}", raw,
                  "BASE_URL points at this tool's own port while the tool is not in "
                  "patched state (leftover from a previous exit). Stop, then start again.")


def _r_oauth_expired(ctx: dict) -> dict | None:
    """OAuth 过期且当前就靠订阅认证 → 请求会 401。
    只在意图是订阅时报：第三方模式下过期的 OAuth 完全无害。"""
    oauth = ctx["oauth"]
    if not oauth["present"] or oauth["expires_at_ms"] is None:
        return None
    if ctx["intent"] != "subscription":
        return None
    if oauth["expires_at_ms"] > time.time() * 1000:
        return None
    return _issue("oauth_expired", "error", "credentials.claudeAiOauth.expiresAt",
                  int(oauth["expires_at_ms"]),
                  "Subscription OAuth credentials have expired; requests will 401. "
                  "Run `claude login`.")


def _r_effort_conflict(ctx: dict) -> dict | None:
    """顶层 effortLevel 与 env CLAUDE_CODE_EFFORT_LEVEL 矛盾。env 优先，顶层那个不生效
    —— 用户以为自己设的是 low，实际跑的是 env 里那个。"""
    top = ctx["settings"].get("effortLevel")
    envv = ctx["env"].get(ENV_EFFORT)
    if not top or not envv or str(top).lower() == str(envv).lower():
        return None
    return _issue("effort_level_conflict", "warning", f"effortLevel / env.{ENV_EFFORT}",
                  f"{top} / {envv}",
                  f"Top-level effortLevel ({top}) conflicts with env {ENV_EFFORT} ({envv}); "
                  "the env value wins, so the top-level one has no effect.")


def _r_effort_max(ctx: dict) -> dict | None:
    """生效 effort = max + 官方端点 → thinking 关闭的请求被 400 拒。

    实测铁证（260725 真实录制）：会话标题生成请求返回
      "output_config.effort 'max' is not supported when thinking is disabled on this model"
    标题功能就此静默失效，CC 界面不会说。第三方端点不受影响，所以**必须**先确认上游是官方。"""
    envv = ctx["env"].get(ENV_EFFORT) or ctx["settings"].get("effortLevel")
    if not envv or str(envv).lower() not in EFFORT_REJECTED_BY_OFFICIAL:
        return None
    if not _is_official(ctx["base_url"]):
        return None
    return _issue("effort_max_rejected_upstream", "warning", f"env.{ENV_EFFORT}", envv,
                  "effort 'max' against the official endpoint makes thinking-disabled "
                  "requests (session title generation, etc.) fail with HTTP 400 — the "
                  "feature silently stops working. Use 'high' or below.")


def _r_oauth_soon(ctx: dict) -> dict | None:
    oauth = ctx["oauth"]
    if not oauth["present"] or oauth["expires_at_ms"] is None:
        return None
    if ctx["intent"] != "subscription":
        return None
    left = oauth["expires_at_ms"] / 1000 - time.time()
    if left <= 0 or left > OAUTH_SOON_SECONDS:
        return None
    return _issue("oauth_expiring_soon", "info", "credentials.claudeAiOauth.expiresAt",
                  int(oauth["expires_at_ms"]),
                  f"Subscription OAuth expires in about {int(left // 60)} minutes.")


def _r_token_overrides_oauth(ctx: dict) -> dict | None:
    """有 OAuth 又有 token：token 优先，订阅静默不生效。
    **只报 info** —— 这很可能正是用户想要的（就是要用第三方），报重了就是误报。"""
    env = ctx["env"]
    key = next((k for k in ENV_TOKENS if env.get(k)), None)
    if not key or not ctx["oauth"]["present"]:
        return None
    return _issue("token_overrides_oauth", "info", f"env.{key}", "<set>",
                  f"{key} takes precedence over your Claude subscription, so the "
                  "subscription login is not being used.")
