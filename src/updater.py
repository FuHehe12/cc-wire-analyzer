"""就地更新：查 → 下载 → 校验 → 替换重启（issue 260808）。

**这是"点一下就换好"，不是"自动升级"。** 区别不是措辞：本工具在录制期间持有用户
`settings.json` 的 patch 态，一个背着用户替换自己二进制、还要重启进程的后台任务，
是这个项目最不该有的东西。所以这里没有定时检查、没有静默安装，每一步都对应一次用户点击；
录制中拒绝替换（**不代劳停止**——停代理要写用户的配置，那不该由"我想升级"顺带触发）。

安全边界见 `docs/reference/开发约定.md` 不变量 10。四条最要紧的：

1. 仓库地址**硬编码**，不接受任何可配置的下载源。这是个无需认证的本机 HTTP 接口，
   一旦下载地址可配置，它就成了"让本机下载并运行任意二进制"的入口。
2. 只走 https，且**逐跳**校验重定向目标的 host——GitHub 的资产下载必然重定向到对象
   存储，只查第一跳等于没查。
3. 有 `SHA256SUMS.txt` 就强制比对；没有（老版本的 release）就**明说没有**并把实测
   SHA-256 摆出来，绝不假装验过了。默默降级比不做更糟（惯犯 bug ③ 的形状）。
4. 先落 `.part`，校验通过才改名——半成品永远不会被当成可执行的更新包。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import config as CFG

log = logging.getLogger(__name__)

# ===== 硬编码的来源（不变量 10 第 1 条：这几个常量不许变成配置项）=====
REPO = "FuHehe12/cc-wire-analyzer"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
SUMS_ASSET = "SHA256SUMS.txt"

# 允许的下载主机（后缀匹配，含子域）。GitHub 的 release 资产 302 到 objects.githubusercontent.com，
# 所以两个域都要在名单里；名单之外的任何一跳都直接中止下载。
ALLOWED_HOST_SUFFIXES = ("github.com", "githubusercontent.com")

UPDATES_DIR = CFG.CONFIG_DIR / "updates"
# 被替换掉的旧 exe 改名成这个后缀留在原地（运行中的文件不能删、但能改名），下次启动清理。
OLD_SUFFIX = ".old"
STAGING_SUFFIX = ".new"

_HTTP_TIMEOUT = 15          # 查 release / 取校验和：小请求
_READ_TIMEOUT = 60          # 下载：单次 read 的上限，整体不设死限（30MB 走代理可能很慢）
_CHUNK = 64 * 1024
_MAX_ASSET_BYTES = 400 * 1024 * 1024   # 资产体积上限，防"下载到天荒地老"

_lock = threading.Lock()
_cancel = threading.Event()
_thread: threading.Thread | None = None

# 单一状态机。phase: idle / checking / downloading / verifying / ready / applying / error
_state: dict = {
    "phase": "idle",
    "latest": None,
    "has_update": False,
    "asset": None,          # {"name","size","url"}
    "downloaded": 0,
    "total": 0,
    "path": None,           # 校验通过后的本地文件
    "sha256": None,
    "sha256_verified": False,
    "error": None,
}


def _set(**kw) -> None:
    with _lock:
        _state.update(kw)


def _snapshot() -> dict:
    with _lock:
        return dict(_state)


# ===== 版本 =====

def _parts(v: str) -> list[int]:
    return [int(n) for n in re.findall(r"\d+", re.split(r"[-+]", str(v), 1)[0])] or [0]


def cmp_version(a: str, b: str) -> int:
    """语义比较，`a` 比 `b` 新则 > 0。预发布后缀不参与比较（与前端 cmpVer 同规则）。"""
    pa, pb = _parts(a), _parts(b)
    for i in range(max(len(pa), len(pb))):
        d = (pa[i] if i < len(pa) else 0) - (pb[i] if i < len(pb) else 0)
        if d:
            return d
    return 0


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def current_exe() -> Path | None:
    """冻结态下正在运行的那个 exe。源码模式返回 None（没有"可替换的产物"这回事）。"""
    return Path(sys.executable).resolve() if is_frozen() else None


# ===== HTTP：每一跳都校验 host =====

def _assert_allowed(url: str) -> None:
    p = urlsplit(url)
    host = (p.hostname or "").lower()
    if p.scheme != "https":
        raise ValueError(f"拒绝非 https 地址：{url[:120]}")
    if not any(host == s or host.endswith("." + s) for s in ALLOWED_HOST_SUFFIXES):
        raise ValueError(f"拒绝名单外的主机：{host}")


class _GuardedRedirect(urllib.request.HTTPRedirectHandler):
    """重定向的**每一跳**都过白名单。

    只校验最初那个 URL 是不够的：GitHub 的 release 资产必然 302 到对象存储，而一个被劫持的
    重定向可以把下载指向任何地方——那正是"下载并执行二进制"这条路径上最危险的一跳。
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _assert_allowed(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener() -> urllib.request.OpenerDirector:
    # ProxyHandler() 不传参 = 用 urllib.getproxies()：Windows 上除环境变量外还会读系统代理
    # 注册表设置。国内用户走 Clash 之类的系统代理时，后端与 WebView2 走的是同一条路——
    # 否则会出现"前端检查更新好使、后端下载永远超时"这种最难判的故障。
    return urllib.request.build_opener(urllib.request.ProxyHandler(), _GuardedRedirect())


def _headers(version: str) -> dict:
    # GitHub API 强制要求 UA。带上版本号纯粹是为了对方日志可读，**不发送任何与用户有关的信息**。
    return {"Accept": "application/vnd.github+json",
            "User-Agent": f"cc-wire-analyzer/{version}"}


def _get_bytes(url: str, version: str, timeout: int = _HTTP_TIMEOUT) -> bytes:
    _assert_allowed(url)
    req = urllib.request.Request(url, headers=_headers(version))
    with _opener().open(req, timeout=timeout) as r:
        return r.read(4 * 1024 * 1024)      # 只用来读 JSON / 校验和文件，有界


# ===== 查更新 =====

def _pick_asset(assets: list[dict]) -> dict | None:
    """挑本平台的资产。**按模式匹配，不按固定文件名**——资产名从 260808 起带版本号
    （`cc-wire-analyzer-v0.4.11-windows.exe`），写死名字下个版本就找不到了。"""
    want_ext, want_tag = (".exe", "windows") if sys.platform == "win32" else (".zip", "macos")
    for a in assets:
        name = (a.get("name") or "").lower()
        if name.endswith(want_ext) and want_tag in name:
            return {"name": a.get("name"), "size": int(a.get("size") or 0),
                    "url": a.get("browser_download_url") or ""}
    return None


def check(version: str) -> dict:
    """查 GitHub 最新 release。**只读**，不写盘、不下载。

    失败不抛给调用方——网络不通是这个功能最常见的结局（GitHub 在很多网络下要走代理），
    返回结构化的 `error` + 手动下载地址，比一个 500 有用。
    """
    _set(phase="checking", error=None)
    try:
        data = json.loads(_get_bytes(API_LATEST, version).decode("utf-8", "replace"))
        latest = (data.get("tag_name") or "").lstrip("vV")
        if not latest:
            raise ValueError("release 没有 tag_name")
        asset = _pick_asset(data.get("assets") or [])
        has = cmp_version(latest, version) > 0
        _set(phase="idle", latest=latest, has_update=has, asset=asset, error=None)
        return {"ok": True, "current": version, "latest": latest, "has_update": has,
                "asset": asset, "releases_url": RELEASES_PAGE,
                "notes_url": data.get("html_url") or RELEASES_PAGE,
                "updates_dir": str(UPDATES_DIR), **_capability(asset)}
    except Exception as e:                      # noqa: BLE001 —— 网络异常形态太多，一律降级
        log.warning("检查更新失败：%s", e)
        _set(phase="idle", error=str(e))
        return {"ok": False, "current": version, "error": str(e),
                "releases_url": RELEASES_PAGE, "updates_dir": str(UPDATES_DIR),
                **_capability(None)}


def _capability(asset: dict | None) -> dict:
    """这台机器上"点一下就换好"能走到哪一步——UI 与 agent 都要据此决定显示什么。

    三种不能就地替换的处境，**分别给出原因**：一句笼统的"不支持"会让用户以为是坏了。
    """
    if not is_frozen():
        return {"can_apply": False, "apply_reason": "source",
                "in_place": False}
    if sys.platform == "win32":
        return {"can_apply": bool(asset), "apply_reason": "" if asset else "no_asset",
                "in_place": True}
    # macOS：只做到"下载 + 校验 + 在 Finder 里指出来"，不就地替换 .app。
    # 维护者在 Windows，替换正在运行的 bundle 还牵扯隔离属性与 Gatekeeper——
    # 没有实测环境就不写会动用户磁盘的代码（开发约定「跨平台」一节）。
    return {"can_apply": bool(asset), "apply_reason": "" if asset else "no_asset",
            "in_place": False}


# ===== 下载 =====

def _sums_map(text: str) -> dict[str, str]:
    """解析 `SHA256SUMS.txt`：`<64位hex>␣␣<文件名>`，文件名可能带 `*` 前缀（二进制模式）。"""
    out = {}
    for line in text.splitlines():
        m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", line)
        if m:
            out[m.group(2)] = m.group(1).lower()
    return out


def _fetch_sums(version: str, tag_assets: list[dict], name: str) -> str | None:
    for a in tag_assets:
        if (a.get("name") or "") == SUMS_ASSET:
            try:
                text = _get_bytes(a.get("browser_download_url") or "", version).decode("utf-8", "replace")
                return _sums_map(text).get(name)
            except Exception as e:              # noqa: BLE001
                log.warning("取校验和失败：%s", e)
                return None
    return None


def _download(version: str, asset: dict, expect_sha: str | None) -> None:
    """后台线程：下载 → 校验 → 改名。任何一步失败都把半成品删掉。"""
    UPDATES_DIR.mkdir(parents=True, exist_ok=True)
    dest = UPDATES_DIR / asset["name"]
    part = dest.with_name(dest.name + ".part")
    try:
        # 开工前把更新目录清空（**包括同名的那一份**）。只留一份、不攒是次要的；
        # 要紧的是：留着同名旧文件时，这一轮下载失败**不会**留下"空目录"，而是留下一个
        # 看起来完好、实际来路不明的 exe 躺在更新目录里等人双击（自测抓到，260808）。
        for stale in UPDATES_DIR.glob("*"):
            if stale.is_file():
                try:
                    stale.unlink()
                except OSError:
                    pass
        _assert_allowed(asset["url"])
        req = urllib.request.Request(asset["url"], headers=_headers(version))
        h = hashlib.sha256()
        got = 0
        with _opener().open(req, timeout=_READ_TIMEOUT) as r:
            total = int(r.headers.get("Content-Length") or asset.get("size") or 0)
            if total > _MAX_ASSET_BYTES:
                raise ValueError(f"资产体积异常（{total} 字节）")
            _set(phase="downloading", total=total, downloaded=0, path=None,
                 sha256=None, sha256_verified=False)
            with open(part, "wb") as f:
                while True:
                    if _cancel.is_set():
                        raise InterruptedError("已取消")
                    chunk = r.read(_CHUNK)
                    if not chunk:
                        break
                    f.write(chunk)
                    h.update(chunk)
                    got += len(chunk)
                    if got > _MAX_ASSET_BYTES:
                        raise ValueError("下载超出体积上限")
                    _set(downloaded=got)
        _set(phase="verifying")
        declared = int(asset.get("size") or 0)
        if declared and got != declared:
            raise ValueError(f"体积不符：期望 {declared}，实得 {got}")
        # 魔数：下到一页 HTML 错误页而不是二进制，是网关/登录墙最常见的表现。
        head = part.read_bytes()[:2] if part.stat().st_size >= 2 else b""
        want_magic = b"MZ" if asset["name"].lower().endswith(".exe") else b"PK"
        if head != want_magic:
            raise ValueError(f"文件头不对（{head!r}）——多半下到了错误页而不是产物")
        digest = h.hexdigest()
        if expect_sha and digest != expect_sha:
            raise ValueError(f"SHA-256 不符：release 声明 {expect_sha[:16]}…，实得 {digest[:16]}…")
        part.replace(dest)                       # 校验通过才改名成正式文件
        _set(phase="ready", path=str(dest), sha256=digest,
             sha256_verified=bool(expect_sha), error=None)
        log.info("更新包就绪：%s（sha256=%s，校验和比对=%s）",
                 dest, digest[:16], bool(expect_sha))
    except Exception as e:                       # noqa: BLE001
        try:
            part.unlink(missing_ok=True)
        except OSError:
            pass
        msg = "已取消" if isinstance(e, InterruptedError) else str(e)
        log.warning("下载更新失败：%s", msg)
        _set(phase="idle" if isinstance(e, InterruptedError) else "error",
             error=None if isinstance(e, InterruptedError) else msg,
             downloaded=0, path=None)


def start_download(version: str) -> dict:
    """启动下载（立即返回，进度走 `/api/update/status`）。"""
    global _thread
    st = _snapshot()
    asset = st.get("asset")
    if not asset:
        return {"ok": False, "error": "还没有可下载的资产，先调 /api/update/check"}
    if st["phase"] in ("downloading", "verifying", "applying"):
        return {"ok": False, "error": f"已有任务在跑（{st['phase']}）"}
    # 校验和在主线程取：它很小，且失败与否要立刻反映到状态里（"有没有校验和"是要展示给用户的事实）
    expect = None
    try:
        data = json.loads(_get_bytes(API_LATEST, version).decode("utf-8", "replace"))
        expect = _fetch_sums(version, data.get("assets") or [], asset["name"])
    except Exception as e:                       # noqa: BLE001
        log.warning("取校验和清单失败（继续下载，届时标注未校验）：%s", e)
    _cancel.clear()
    _thread = threading.Thread(target=_download, args=(version, asset, expect),
                               daemon=True, name="ccwa-update-download")
    _thread.start()
    return {"ok": True, "sha256_expected": bool(expect)}


def cancel() -> dict:
    _cancel.set()
    return {"ok": True}


def status(version: str) -> dict:
    st = _snapshot()
    st.update({"ok": True, "current": version, "releases_url": RELEASES_PAGE,
               "updates_dir": str(UPDATES_DIR), **_capability(st.get("asset"))})
    return st


def open_releases_page() -> dict:
    """在系统浏览器里打开发布页。**没有入参**——地址是本模块硬编码的那一个常量。

    做成端点而不是让前端 `window.open`：webview 里 `window.open` 打不开外部浏览器。
    做成无参而不是"打开某个 URL"：那就成了一个能被任意页面调用的"用系统浏览器打开任意地址"
    的本机接口（不变量 10 第 1 条的同一条理由）。
    """
    import webbrowser
    try:
        if not webbrowser.open(RELEASES_PAGE) and sys.platform == "win32":
            os.startfile(RELEASES_PAGE)          # noqa: S606 —— 常量地址，无用户输入
        return {"ok": True, "url": RELEASES_PAGE}
    except Exception as e:                       # noqa: BLE001
        log.warning("打开发布页失败：%s", e)
        return {"ok": False, "error": str(e), "url": RELEASES_PAGE}


# ===== 替换 =====

def _reveal(path: Path) -> None:
    """在文件管理器里指出这个文件。失败不致命——路径已经告诉用户了。"""
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
    except Exception:                            # noqa: BLE001
        log.warning("打开所在文件夹失败：%s", path)


def swap_in_place(new_file: Path, cur: Path) -> Path:
    """把 `new_file` 换成 `cur`，返回旧文件被改名后的路径。**纯文件操作，可单独测**。

    正在运行的 exe 不能被写、也不能被删，但**可以被改名**——Windows 就地更新靠的就是这条。
    三步的顺序是为了让每一步失败时都能全身而退：

      1. 复制到同目录的 `<name>.new`  ← 还没动过任何在用的文件；无写权限就在这里失败
      2. `os.replace(cur, cur+.old)`  ← 同目录、原子
      3. `os.replace(staging, cur)`   ← 同目录、原子；失败就把 .old 换回去

    第 1 步必须落在**同一个目录**：更新包下在 `~/.cc-wire-analyzer/`，而 exe 可能在另一个盘，
    跨卷的 `os.replace` 直接 EXDEV，而跨卷的 move 是"复制+删除"、不原子。
    """
    staging = cur.with_name(cur.name + STAGING_SUFFIX)
    old = cur.with_name(cur.name + OLD_SUFFIX)
    staging.unlink(missing_ok=True)
    try:
        old.unlink(missing_ok=True)              # 上一次更新留下的，能删就删
    except OSError:
        pass
    shutil.copy2(new_file, staging)
    try:
        os.replace(cur, old)
    except OSError:
        staging.unlink(missing_ok=True)
        raise
    try:
        os.replace(staging, cur)
    except OSError:
        os.replace(old, cur)                     # 回滚：原封不动地放回去
        staging.unlink(missing_ok=True)
        raise
    return old


def cleanup_leftovers() -> int:
    """启动时清掉上次更新留下的 `*.old` / `*.new`。删不掉就下次再说，绝不报错。"""
    cur = current_exe()
    if not cur:
        return 0
    n = 0
    for p in (cur.with_name(cur.name + OLD_SUFFIX), cur.with_name(cur.name + STAGING_SUFFIX)):
        try:
            if p.exists():
                p.unlink()
                n += 1
        except OSError:
            log.info("残留文件暂时删不掉（多半仍被占用），下次启动再试：%s", p)
    return n


def preflight(is_recording: bool) -> tuple[bool, str]:
    """替换前的三道门。返回 `(能不能替换, 原因码)`，原因码由前端翻译成三语。"""
    st = _snapshot()
    if st["phase"] != "ready" or not st.get("path"):
        return False, "not_ready"
    if not is_frozen():
        return False, "source"          # 源码模式：该 git pull，不该覆盖文件
    if is_recording:
        # **不代劳停止**：停代理会写用户的 settings.json，是有副作用的动作，
        # 不该由"我想升级"这个意图顺带触发（同不变量 8「不提供自动修复」的思路）。
        return False, "recording"
    if not Path(st["path"]).exists():
        return False, "file_gone"
    return True, ""


def apply(is_recording: bool, on_exit) -> dict:
    """执行替换。Windows 就地换 + 重启；macOS 解压后指路，不动 `.app`。

    `on_exit` 由调用方给（`app.py` 传一个"恢复 settings 然后退出"的回调）——
    退出这件事的正确做法属于进程生命周期，不该在这个模块里各写一份。
    """
    ok, why = preflight(is_recording)
    if not ok:
        return {"ok": False, "reason": why}
    st = _snapshot()
    src = Path(st["path"])
    if sys.platform != "win32":
        # macOS：解压出 .app 并在 Finder 里指出来。**有意不就地替换**，见 _capability。
        try:
            out = UPDATES_DIR / "extracted"
            shutil.rmtree(out, ignore_errors=True)
            shutil.unpack_archive(str(src), str(out))
            app = next((p for p in out.glob("*.app")), out)
            _reveal(app)
            return {"ok": True, "in_place": False, "path": str(app), "restart": False}
        except Exception as e:                   # noqa: BLE001
            log.warning("解压更新包失败：%s", e)
            return {"ok": False, "reason": "unpack_failed", "error": str(e),
                    "path": str(src)}
    cur = current_exe()
    assert cur is not None                        # preflight 已确认冻结态
    _set(phase="applying")
    try:
        old = swap_in_place(src, cur)
    except OSError as e:
        # 最常见：装在 Program Files 之类没有写权限的地方。回落成"下好了，你自己换"——
        # 这时把文件夹打开，比只给一句错误有用。
        log.warning("就地替换失败（%s）：%s", cur, e)
        _set(phase="ready", error=str(e))
        _reveal(src)
        return {"ok": False, "reason": "not_writable", "error": str(e), "path": str(src)}
    log.info("已替换产物：%s（旧版留在 %s，下次启动清理）", cur, old.name)
    _set(phase="idle", has_update=False, path=None, latest=None, asset=None)
    threading.Timer(1.0, _relaunch, args=(cur, on_exit)).start()
    return {"ok": True, "in_place": True, "restart": True, "path": str(cur)}


def _relaunch(exe: Path, on_exit) -> None:
    """拉起新版本，然后让本进程走**正常退出路径**（先恢复 settings.json 再退）。

    延迟 1 秒是为了让 `/api/update/apply` 的响应先回到界面——否则用户只看到窗口消失，
    分不清是"更新中"还是"崩了"。
    """
    argv = [str(exe)] + [a for a in sys.argv[1:] if a not in ("--update-applied",)]
    try:
        kwargs = {}
        if sys.platform == "win32":
            # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP：新实例不做本进程的子进程，
            # 我们退出时不会连带它。
            kwargs["creationflags"] = 0x00000008 | 0x00000200
        subprocess.Popen(argv, close_fds=True, **kwargs)
    except Exception as e:                        # noqa: BLE001
        log.error("新版本拉起失败（旧版已被改名，用户需手动启动 %s）：%s", exe, e)
    on_exit()


def self_check() -> list[tuple[str, bool]]:
    """给 `update_selftest.py` 用的纯函数抽查（不联网）。"""
    checks = [
        ("版本比较：新 > 旧", cmp_version("0.5.0", "0.4.11") > 0),
        ("版本比较：0.4.11 > 0.4.9（不是字符串序）", cmp_version("0.4.11", "0.4.9") > 0),
        ("版本比较：相等", cmp_version("0.4.9", "0.4.9") == 0),
        ("版本比较：预发布后缀不参与", cmp_version("0.5.0-rc1", "0.5.0") == 0),
    ]
    return checks
