"""settings.json 配置守卫：备份 / 原子改写 / 恢复 + 崩溃保护。

最关键的安全模块——本软件要改用户的 ~/.claude/settings.json，
必须做到：**只动 BASE_URL 一字段、原子写、三重崩溃保护、启动扫孤儿备份**。

恢复策略：用"改回原值"不用"整文件回滚"——代理期间用户/CC 可能改了别的字段，
整文件回滚会丢那些改动（与 cc-switch 等配置工具共存的关键）。

self-test：`uv run python src/settings_guard.py --self-test`，用临时文件验证全流程，
不动真 settings.json。
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import signal
import sys
import threading
import time
from pathlib import Path

import config as CFG

log = logging.getLogger(__name__)

ENV_KEY = "ANTHROPIC_BASE_URL"
# CC 无 ANTHROPIC_BASE_URL 时直连的官方默认端点。用户 settings.json 没设该键
# （直连官方，开源用户占多数）时，代理 fallback 到抓这个端点（260712 修复）。
DEFAULT_UPSTREAM = "https://api.anthropic.com"
BACKUP_DIR = CFG.CONFIG_DIR / "backups"
MAX_BACKUPS = 5
# patch 态 marker 文件：patch 时写（含 original_url），restore 时删。
# orphan 检测看 marker 是否残留（=上次 patch 后进程被强杀没正常 restore），
# 不靠 url 子串猜，避免误判用户合法的本地端点（审计 260712 #7）。
# 模块级变量便于 self_test 临时重定向到临时目录。
_PATCHED_MARKER = CFG.CONFIG_DIR / ".patched"

# ===== 模块状态 =====
_original_base_url: str | None = None   # snapshot 记录（恢复值 + 上游转发目标）
_original_had_key: bool = True          # settings.json 原本是否有 BASE_URL 键；
                                        # False=原本直连官方，restore 时删键而非写回（260712）
_patched: bool = False                  # 当前是否处于 patch 态
_patched_listen: str | None = None      # patch 后的本地监听地址
_patched_at: str | None = None          # patch 起始时间（ISO，供 UI 显示 started_at）
_guards_installed: bool = False
_external_change: dict | None = None    # 外部接管检测结果（cc-switch 等改了 BASE_URL），
                                        # 重新 patch（重新接管）时清空
# watcher 线程与 Flask 线程会并发进 patch/restore/外部检测，改状态前必须持锁
_LOCK = threading.RLock()


class SettingsGuardError(Exception):
    pass


# ===== 内部工具 =====

def _read_settings(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write(path: Path, data: dict) -> None:
    """原子写：写临时文件 + os.replace 覆盖（Windows 同卷原子）。保序 dumps。

    保留原文件的行尾符与末尾换行风格——否则 Windows text mode 会把 json.dumps 的
    \\n 隐式转成 \\r\\n，把整个文件行尾符从 LF 改成 CRLF（改动全部行、污染 git diff）。
    只想动 BASE_URL 一字段，行尾符必须原样（260712 修复）。"""
    newline, trailing = "\n", ""
    try:
        raw = path.read_bytes()
        if b"\r\n" in raw:
            newline = "\r\n"        # 原文件 CRLF → 输出 CRLF
        if raw.endswith(b"\n"):
            trailing = "\n"         # 原文件有末尾换行 → 保留
    except OSError:
        pass                        # 新文件（首次写）→ 默认 LF 无末尾换行
    text = json.dumps(data, ensure_ascii=False, indent=2) + trailing
    tmp = path.with_suffix(path.suffix + ".tmp")
    # newline="\n" 禁止转换（LF 原样）；newline="\r\n" 把 \n 转成 CRLF
    tmp.write_text(text, encoding="utf-8", newline=newline)
    os.replace(tmp, path)


def _patch_base_url_to(path: Path, target: str) -> None:
    """把 path 的 env.ANTHROPIC_BASE_URL 改成 target，其他字段值与顺序不动。
    settings.json 无 env 字段时创建 env={}（开源用户可能连 env 都没有，260712）。"""
    data = _read_settings(path)
    env = data.get("env")
    if not isinstance(env, dict):
        env = {}
        data["env"] = env
    env[ENV_KEY] = target
    _atomic_write(path, data)


def _remove_base_url(path: Path) -> None:
    """删除 env.ANTHROPIC_BASE_URL（原本无该键时的 restore：回到直连官方原状，不留污染）。"""
    data = _read_settings(path)
    env = data.get("env")
    if isinstance(env, dict) and ENV_KEY in env:
        del env[ENV_KEY]
        _atomic_write(path, data)


def _read_base_url(path: Path) -> str | None:
    try:
        data = _read_settings(path)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return data.get("env", {}).get(ENV_KEY)


def _is_local_proxy_url(url: str) -> bool:
    return "127.0.0.1" in url or "localhost" in url


def _write_marker(original: str, listen: str, had_key: bool) -> None:
    """写 patch 态 marker（含原 BASE_URL + 原本是否有该键，供崩溃后恢复）。"""
    CFG.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _PATCHED_MARKER.write_text(json.dumps({
        "original": original,
        "listen": listen,
        "had_key": had_key,
        "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
    }, ensure_ascii=False), encoding="utf-8")


def _clear_marker() -> None:
    """删 patch 态 marker（正常 restore 后调）。"""
    try:
        _PATCHED_MARKER.unlink()
    except FileNotFoundError:
        pass
    except OSError as e:
        log.warning("clear marker failed: %s", e)


# ===== 公开 API =====

def snapshot_original(path: Path | None = None) -> str:
    """启动代理时调。读 settings.json 的 env.BASE_URL 记内存。
    返回上游转发目标（= 恢复值）。

    无该键时不再报错——CC 直连官方端点，fallback 到抓 DEFAULT_UPSTREAM，
    记 _original_had_key=False（restore 时删键回到直连原状，260712 修复）。"""
    global _original_base_url, _original_had_key
    p = path or CFG.CLAUDE_SETTINGS
    url = _read_base_url(p)
    if url:
        _original_base_url = url
        _original_had_key = True
    else:
        _original_base_url = DEFAULT_UPSTREAM
        _original_had_key = False
    log.info("snapshot original BASE_URL=%s (had_key=%s)", _original_base_url, _original_had_key)
    return _original_base_url


def backup_file(path: Path | None = None) -> Path:
    """整文件拷到 backups/settings.json.<ts>。留最近 MAX_BACKUPS 份。"""
    p = path or CFG.CLAUDE_SETTINGS
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    now = time.time()
    ts = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    ms = int((now % 1) * 1000)   # 毫秒，避免同秒多次启动覆盖
    dst = BACKUP_DIR / f"settings.json.{ts}.{ms:03d}"
    dst.write_bytes(p.read_bytes())
    # 清理超量备份（按名字排序，留最后 MAX_BACKUPS 份）
    backups = sorted(BACKUP_DIR.glob("settings.json.*"))
    for old in backups[:-MAX_BACKUPS]:
        try:
            old.unlink()
        except OSError:
            pass
    log.info("backup → %s", dst)
    return dst


def patch_base_url(local_listen: str, path: Path | None = None) -> None:
    """原子改写 env.ANTHROPIC_BASE_URL = local_listen，其他不动。标记 _patched + 写 marker。"""
    global _patched, _patched_listen, _patched_at, _external_change
    with _LOCK:
        p = path or CFG.CLAUDE_SETTINGS
        _patch_base_url_to(p, local_listen)
        _patched = True
        _patched_listen = local_listen
        _patched_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        _external_change = None   # 重新接管：上一次的外部改动记录随之翻篇
        if _original_base_url:
            _write_marker(_original_base_url, local_listen, _original_had_key)
        log.info("patched BASE_URL → %s", local_listen)


def restore(path: Path | None = None) -> bool:
    """恢复 settings.json 到 patch 前原状。返回是否实际执行。
    幂等：未 patch 时返回 False，重复调用安全。
    原本有 BASE_URL 键 → 写回原值；原本无 → 删键（回到直连官方原状，260712）。

    260713 新增守卫：只撤销**我们还能证明是自己做的**那一笔。若当前 BASE_URL 已不是我们
    patch 进去的那个地址（代理运行期间用户用 cc-switch 换了上游 / 手改了配置），那是用户的
    新意图，无权拿旧快照覆盖它 —— 只清内部状态与 marker，不动文件。"""
    global _patched, _patched_listen, _patched_at
    with _LOCK:
        if not _patched:
            return False
        p = path or CFG.CLAUDE_SETTINGS
        current = _read_base_url(p)
        if _patched_listen and current != _patched_listen:
            log.warning("跳过恢复：当前 BASE_URL=%s ≠ 我们 patch 的 %s（用户已自行改动）",
                        current, _patched_listen)
            _patched = False
            _patched_listen = None
            _patched_at = None
            _clear_marker()
            return False
        try:
            if _original_had_key:
                _patch_base_url_to(p, _original_base_url)
                log.info("restored BASE_URL → %s", _original_base_url)
            else:
                _remove_base_url(p)
                log.info("restored: removed BASE_URL key (原本直连官方)")
        finally:
            _patched = False
            _patched_listen = None
            _patched_at = None
            _clear_marker()  # 正常恢复，清 patch 态 marker（审计 260712 #7）
        return True


def check_orphan_backup(path: Path | None = None) -> dict | None:
    """启动时调。看 patch 态 marker 是否残留（=上次 patch 后进程被强杀、没正常 restore），
    marker 记的 original_url 即恢复目标。

    marker 与 URL 两个条件**都要满足**才认（260713 修复）：marker 证明「我们 patch 过」，
    URL 证明「而且 settings.json 现在还是我们那份」。260712 那次改成只信 marker，
    把 URL 检查整个丢了（`_is_local_proxy_url` 就此成了零调用的死代码）——后果是陈 marker
    会拿过期信息覆盖用户之后自己设的 BASE_URL，`had_key=False` 的陈 marker 更会**直接删掉**
    用户刚用 cc-switch 设好的键。真实可触发链见 issues/260713_孤儿恢复会覆盖用户新配置.md。

    陈 marker（当前值不是我们写进去的那个）→ 只清 marker，绝不碰 settings.json。"""
    p = path or CFG.CLAUDE_SETTINGS
    if not _PATCHED_MARKER.exists():
        return None
    try:
        info = json.loads(_PATCHED_MARKER.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    original = info.get("original")
    if not original:
        return None

    current = _read_base_url(p)
    listen = info.get("listen")
    # 精确比对优先（marker 记着当初 patch 进去的确切地址）；老 marker 无 listen 时退回本地端点判断。
    ours = bool(current) and (current == listen if listen else _is_local_proxy_url(current))
    if not ours:
        log.warning("陈旧 marker：当前 BASE_URL=%s 不是我们 patch 的 %s → 只清 marker，不动 settings.json",
                    current, listen)
        _clear_marker()
        return None

    return {
        "marker_file": str(_PATCHED_MARKER),
        "orphan_base_url": current,
        "recovered_to": original,
        "had_key": info.get("had_key", True),  # 老 marker 无此字段则按有键（保守写回）
    }


def recover_from_orphan(orphan_info: dict, path: Path | None = None) -> None:
    """启动扫到孤儿时调。据 marker 记的 had_key 恢复原状：
    原本有键→写回原值；原本无键→删键。不设 _patched（这是恢复，不是新 patch）。清 marker。"""
    global _original_base_url, _original_had_key
    p = path or CFG.CLAUDE_SETTINGS
    had_key = orphan_info.get("had_key", True)
    if had_key:
        _patch_base_url_to(p, orphan_info["recovered_to"])
        log.info("orphan recovered → %s", orphan_info["recovered_to"])
    else:
        _remove_base_url(p)
        log.info("orphan recovered: removed BASE_URL key (原本直连官方)")
    _original_base_url = orphan_info["recovered_to"]
    _original_had_key = had_key
    _clear_marker()


def backups_count() -> int:
    """当前备份数（供 UI 显示）。"""
    try:
        return len(list(BACKUP_DIR.glob("settings.json.*")))
    except OSError:
        return 0


def is_patched() -> bool:
    return _patched


def get_original_base_url() -> str | None:
    return _original_base_url


def patched_at() -> str | None:
    return _patched_at


def check_external_change(path: Path | None = None) -> dict | None:
    """patch 态下检测 settings.json 是否被外部改动（cc-switch 切换 / 手改）。

    当前 BASE_URL ≠ 我们 patch 进去的地址 → 外部已接管：CC 在直连新上游，代理已被绕过。
    此时**只降旗**——清 _patched 态与 marker、记录 _external_change 供 UI/AI 呈现，
    **绝不碰 settings.json**（与 restore 守卫同一原则：只撤销能证明是自己做的那一笔；
    新值是用户的新意图）。重新接管 = 用户显式再走一次 proxy/start（snapshot 自然收编新上游）。

    返回 None（未变/未 patch）或 _external_change 信息。watcher 线程周期调用。"""
    global _patched, _patched_listen, _patched_at, _external_change
    with _LOCK:
        if not _patched:
            return None
        p = path or CFG.CLAUDE_SETTINGS
        try:
            current = _read_settings(p).get("env", {}).get(ENV_KEY)
        except FileNotFoundError:
            current = None            # 文件没了：等效键被删，按外部改动处理
        except json.JSONDecodeError:
            return None               # 外部工具非原子写入的半截文件：本轮不判，下轮再看
        if current == _patched_listen:
            return None
        _external_change = {
            "at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "current": current,                    # 外部设的新上游（None=键被删）
            "was_listen": _patched_listen,         # 我们 patch 进去的本地地址
            "original": _original_base_url,        # 我们启动时记的旧上游
        }
        log.warning("检测到 settings.json 被外部修改：BASE_URL=%s ≠ 我们 patch 的 %s"
                    "（cc-switch 切换/手改）→ 代理已被绕过，降旗断开，不碰文件",
                    current, _patched_listen)
        _patched = False
        _patched_listen = None
        _patched_at = None
        _clear_marker()
        return _external_change


def get_external_change() -> dict | None:
    return _external_change


# ===== 崩溃保护（三重）=====

def _safe_restore(*args, **kwargs) -> None:
    """try/except 包裹 restore，恢复失败只记日志，不二次抛异常。"""
    try:
        restore()
    except Exception as e:
        log.error("safe_restore failed: %s", e)


def _signal_handler(signum, frame):
    log.warning("signal %s received, restoring", signum)
    _safe_restore()
    sys.exit(0)


def _excepthook(exc_type, exc, tb):
    import traceback
    log.error("Unhandled %s: %s",
              exc_type.__name__,
              "".join(traceback.format_exception(exc_type, exc, tb)))
    _safe_restore()
    sys.__excepthook__(exc_type, exc, tb)


def _atexit_restore() -> None:
    """atexit 钩子：显式记一行退出事件再恢复——让 run.log 能回答「这次进程怎么结束的」。
    强杀(TerminateProcess)/断电到不了这里，靠「启动横幅 + 无退出行 + 下次 orphan」组合反推。"""
    log.info("exit: atexit fired（解释器正常收尾）")
    _safe_restore()


def install_crash_guards() -> None:
    """注册 atexit + SIGTERM/SIGINT + sys.excepthook 三重恢复。仅注册一次。"""
    global _guards_installed
    if _guards_installed:
        return
    atexit.register(_atexit_restore)
    try:
        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)
    except (ValueError, OSError) as e:
        # Windows 主线程外不能设 signal；atexit + excepthook 仍兜底
        log.warning("signal handler 注册失败（无碍）: %s", e)
    sys.excepthook = _excepthook
    _guards_installed = True
    log.info("crash guards installed")


# ===== self-test（临时文件，不动真 settings.json）=====

def self_test() -> None:
    import tempfile
    import shutil
    tmpdir = Path(tempfile.mkdtemp(prefix="ccwa_test_"))
    fake = tmpdir / "settings.json"
    fake.write_text(json.dumps({
        "env": {
            "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
            "ANTHROPIC_AUTH_TOKEN": "fake-token-should-never-change",
            "ANTHROPIC_DEFAULT_OPUS_MODEL": "glm-5.2[1M]",
        },
        "model": "opus",
        "permissions": {"defaultMode": "auto"},
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    global BACKUP_DIR, _PATCHED_MARKER, _original_base_url, _patched, _patched_listen, _original_had_key
    old_backup_dir = BACKUP_DIR
    old_marker = _PATCHED_MARKER
    BACKUP_DIR = tmpdir / "backups"
    _PATCHED_MARKER = tmpdir / ".patched"   # marker 重定向到临时目录，不碰真实位置
    _original_base_url = None
    _patched = False
    _patched_listen = None

    print(f"[setup] fake settings: {fake}")
    print(f"[setup] 原始:\n{fake.read_text(encoding='utf-8')}\n")

    try:
        # 1. snapshot
        orig = snapshot_original(fake)
        assert orig == "https://api.anthropic.com", f"snapshot: {orig}"
        print(f"[1] snapshot OK: {orig}")

        # 2. backup
        bkp = backup_file(fake)
        assert bkp.exists()
        print(f"[2] backup OK: {bkp.name}")

        # 3. patch + 其他字段不动
        patch_base_url("http://127.0.0.1:5051", fake)
        data = _read_settings(fake)
        assert data["env"][ENV_KEY] == "http://127.0.0.1:5051"
        assert data["env"]["ANTHROPIC_AUTH_TOKEN"] == "fake-token-should-never-change", "token 被改!"
        assert data["env"]["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "glm-5.2[1M]", "模型映射被改!"
        assert data["model"] == "opus"
        assert data["permissions"]["defaultMode"] == "auto"
        print(f"[3] patch OK: BASE_URL→本地，token/模型映射/permissions 未动 ✓")

        # 4. orphan 检测 + 恢复（marker 机制：patch 写了 marker，模拟崩溃没 restore）
        orphan = check_orphan_backup(fake)
        assert orphan is not None, "orphan(marker) 未检出残留"
        assert orphan["recovered_to"] == "https://api.anthropic.com"
        print(f"[4] orphan(marker) 检出 → 恢复到 {orphan['recovered_to']}")
        _patched = False  # 模拟崩溃后进程重启、_patched 复位、marker 仍残留
        recover_from_orphan(orphan, fake)
        assert _read_base_url(fake) == "https://api.anthropic.com"
        assert not _PATCHED_MARKER.exists(), "recover 后 marker 应清除"
        print(f"[4] recover OK + marker 清除 ✓")

        # 5. restore 幂等
        patch_base_url("http://127.0.0.1:5051", fake)
        assert restore(fake) is True
        assert restore(fake) is False, "二次 restore 应返回 False"
        assert _read_base_url(fake) == "https://api.anthropic.com"
        print(f"[5] restore 幂等 OK")

        # 6. backup 留最近 MAX_BACKUPS
        for _ in range(MAX_BACKUPS + 2):
            backup_file(fake)
        n = len(list(BACKUP_DIR.glob("settings.json.*")))
        assert n == MAX_BACKUPS, f"备份未裁剪: {n}"
        print(f"[6] backup 裁剪 OK: 留 {n} 份 (max={MAX_BACKUPS})")

        # 7. 无 BASE_URL 场景（直连官方，260712 修复）：snapshot fallback + restore 删键
        nobase = tmpdir / "settings_nobase.json"
        nobase.write_text(json.dumps({
            "env": {"ANTHROPIC_AUTH_TOKEN": "tok", "OTEL_LOGS_EXPORTER": "otlp"},
            "permissions": {"defaultMode": "auto"},
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        _patched = False
        orig7 = snapshot_original(nobase)
        assert orig7 == DEFAULT_UPSTREAM, f"无 BASE_URL 应 fallback 官方: {orig7}"
        assert _original_had_key is False, "had_key 应为 False"
        patch_base_url("http://127.0.0.1:5051", nobase)
        d7 = _read_settings(nobase)
        assert d7["env"][ENV_KEY] == "http://127.0.0.1:5051", "patch 应新增本地 BASE_URL"
        assert d7["env"]["ANTHROPIC_AUTH_TOKEN"] == "tok", "token 被动!"
        assert restore(nobase) is True
        d7b = _read_settings(nobase)
        assert ENV_KEY not in d7b["env"], "restore 应删除 BASE_URL 键（回到直连官方原状）"
        assert d7b["env"]["ANTHROPIC_AUTH_TOKEN"] == "tok", "删键误伤其他字段!"
        assert d7b["permissions"]["defaultMode"] == "auto"
        print(f"[7] 无 BASE_URL 场景 OK: fallback 官方 → patch 新增 → restore 删键，其他字段无损 ✓")

        # 8. 无 env 字段场景：patch 创建 env，restore 后 BASE_URL 键不残留
        noenv = tmpdir / "settings_noenv.json"
        noenv.write_text(json.dumps({"model": "opus"}, ensure_ascii=False, indent=2), encoding="utf-8")
        _patched = False
        snapshot_original(noenv)
        patch_base_url("http://127.0.0.1:5051", noenv)
        d8 = _read_settings(noenv)
        assert d8["env"][ENV_KEY] == "http://127.0.0.1:5051", "无 env 应创建并写入"
        assert restore(noenv) is True
        assert ENV_KEY not in _read_settings(noenv).get("env", {}), "restore 后不应残留 BASE_URL"
        print(f"[8] 无 env 字段场景 OK: patch 创建 env → restore 清键 ✓")

        # 9. 陈旧 marker（had_key=False）+ 用户之后自己设了 BASE_URL → 绝不能删他的键（260713）
        #    这是真实可触发的破坏链：直连官方的用户起代理 → 被强杀 → 自己用 cc-switch 切到智谱
        #    → 再开本软件 → 旧代码会把刚设好的键删掉。
        stale = tmpdir / "settings_stale.json"
        stale.write_text(json.dumps({
            "env": {"ANTHROPIC_BASE_URL": "https://open.bigmodel.cn/api/anthropic",
                    "ANTHROPIC_AUTH_TOKEN": "tok"},
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        _PATCHED_MARKER.write_text(json.dumps({      # 模拟强杀留下的 marker（当时没有键）
            "original": DEFAULT_UPSTREAM, "listen": "http://127.0.0.1:5051",
            "had_key": False, "at": "2026-07-13T00:00:00"}), encoding="utf-8")
        assert check_orphan_backup(stale) is None, "陈旧 marker 不该被当成孤儿"
        d9 = _read_settings(stale)
        assert d9["env"][ENV_KEY] == "https://open.bigmodel.cn/api/anthropic", "用户的 BASE_URL 被删了!"
        assert not _PATCHED_MARKER.exists(), "陈旧 marker 应被清掉"
        print(f"[9] 陈旧 marker(had_key=False) + 用户已设新 BASE_URL → 不删键、只清 marker ✓")

        # 10. 陈旧 marker（had_key=True）+ 用户已换别的上游 → 不得用旧值覆盖
        stale.write_text(json.dumps({
            "env": {"ANTHROPIC_BASE_URL": "https://new-provider.example.com"},
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        _PATCHED_MARKER.write_text(json.dumps({
            "original": "https://old-provider.example.com", "listen": "http://127.0.0.1:5051",
            "had_key": True, "at": "2026-07-13T00:00:00"}), encoding="utf-8")
        assert check_orphan_backup(stale) is None
        assert _read_base_url(stale) == "https://new-provider.example.com", "用户的新上游被旧值覆盖了!"
        print(f"[10] 陈旧 marker(had_key=True) + 用户已换上游 → 不覆盖 ✓")

        # 11. 真孤儿（当前值 == marker 记的 listen）→ 照常恢复（回归：别把安全网收得连正事都不干了）
        real = tmpdir / "settings_orphan.json"
        real.write_text(json.dumps({
            "env": {"ANTHROPIC_BASE_URL": "http://127.0.0.1:5051"},
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        _PATCHED_MARKER.write_text(json.dumps({
            "original": "https://open.bigmodel.cn/api/anthropic", "listen": "http://127.0.0.1:5051",
            "had_key": True, "at": "2026-07-13T00:00:00"}), encoding="utf-8")
        o11 = check_orphan_backup(real)
        assert o11 is not None, "真孤儿没被检出！"
        recover_from_orphan(o11, real)
        assert _read_base_url(real) == "https://open.bigmodel.cn/api/anthropic"
        assert not _PATCHED_MARKER.exists()
        print(f"[11] 真孤儿(current == marker.listen) → 正常恢复 ✓")

        # 12. 代理运行期间用户换了上游 → restore 不得覆盖他的新选择
        live = tmpdir / "settings_live.json"
        live.write_text(json.dumps({"env": {"ANTHROPIC_BASE_URL": "https://a.example.com"}},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
        _patched = False
        snapshot_original(live)
        patch_base_url("http://127.0.0.1:5051", live)
        _patch_base_url_to(live, "https://user-switched.example.com")   # 模拟 cc-switch 中途切换
        assert restore(live) is False, "用户中途改了 BASE_URL，restore 不该动它"
        assert _read_base_url(live) == "https://user-switched.example.com", "用户的新上游被覆盖了!"
        assert not _PATCHED_MARKER.exists()
        print(f"[12] 代理运行期间用户换上游 → restore 跳过、不覆盖 ✓")

        print("\n[ALL PASSED] ✓")
    finally:
        BACKUP_DIR = old_backup_dir
        _PATCHED_MARKER = old_marker
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    # Windows 控制台默认 GBK，强制 UTF-8 避免 ✓ 等字符 UnicodeEncodeError
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    CFG.setup_logging()
    if "--self-test" in sys.argv:
        self_test()
    else:
        print("用法: python settings_guard.py --self-test")
