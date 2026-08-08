"""平台原生版本资源：让**不打开程序**也能看到版本号（issue 260808）。

此前版本号只活在运行期（`/api/about`、`--help`），下载到磁盘上的 exe 属性页里
「文件版本」一栏是空的 —— 想知道手上这个是哪一版，唯一办法是双击打开它。而对一个
会 patch `settings.json` 的工具来说，"打开"不是零成本动作。

**两份 spec 共用这一份，而不是各写一份再对账**：`build.spec` 与 `build-mac.spec` 已经
因为"两份要同时改"分叉过一次（mac spec 没跟上 `brotli`，macOS 产物整段丢非流式响应）。
共享模块让分叉在结构上不可能发生 —— 比事后加检查更彻底，符合本项目那句
「给腐化开的药方如果需要人工定期同步，它自己就是下一处腐化」。

版本号的唯一真源仍是 git tag：CI 打包前从 tag 生成 `src/_version.py`，这里只读它。
**本文件绝不写死任何真实版本号**（开发约定第九节）。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 开发机上没有 `_version.py`（CI 生成物，仓库排除）。回落成 0.0.0 + 字符串 "dev"：
# 一个明显不是发行版的值，比"看起来像正式版本号的假数字"安全得多。
DEV_VERSION = "dev"


def read_version() -> str:
    """读 `src/_version.py` 的 `VERSION`。没有就返回 `"dev"`。

    不 import 它：spec 在 PyInstaller 进程里执行，`src/` 不在 sys.path 上，而为了读一个
    字符串去改 sys.path 会把构建脚本和运行时的模块解析搅在一起。
    """
    try:
        text = (ROOT / "src" / "_version.py").read_text(encoding="utf-8")
    except OSError:
        return DEV_VERSION
    m = re.search(r'^VERSION\s*=\s*["\']([^"\']+)["\']', text, re.M)
    return m.group(1).strip() if m else DEV_VERSION


def version_tuple(version: str) -> tuple[int, int, int, int]:
    """`"0.4.11"` → `(0, 4, 11, 0)`。Windows 版本资源只接受四个整数。

    预发布后缀（`0.5.0-rc1` / `0.0.0-dev`）在这里被丢掉 —— 四元组塞不下它。
    完整字符串照原样进 `FileVersion` / `ProductVersion` 字段，属性页显示的是那一份，
    所以后缀不会丢失，只是不参与"数字版本"的比较。
    """
    nums = re.findall(r"\d+", re.split(r"[-+]", version, 1)[0])
    parts = [int(n) for n in nums[:4]]
    parts += [0] * (4 - len(parts))
    return tuple(parts)  # type: ignore[return-value]


def windows_version_info(version: str | None = None):
    """构造 Windows VERSIONINFO 资源，直接传给 `EXE(version=...)`。

    PyInstaller 6.x 的 `EXE` 接受 `VSVersionInfo` 实例本身（building/api.py:618），
    不必先把它序列化成文本文件再让它 eval 回来 —— 少一个中间产物，也少一处能对不上的地方。
    非 Windows 平台上 PyInstaller 会忽略这个参数（api.py:485），所以调用方不必自己判平台。
    """
    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo,
        VarStruct, VSVersionInfo)

    v = version or read_version()
    t = version_tuple(v)
    return VSVersionInfo(
        ffi=FixedFileInfo(filevers=t, prodvers=t,
                          mask=0x3F, flags=0x0,
                          OS=0x40004,      # VOS_NT_WINDOWS32
                          fileType=0x1,    # VFT_APP
                          subtype=0x0, date=(0, 0)),
        kids=[
            # 040904B0 = en-US + Unicode(1200)。产物是三语界面，但版本资源的语言标记
            # 只影响属性页按哪个语言分组取字符串，用 en-US 一套即可（Windows 找不到
            # 用户语言的那一套时就显示这一套）。
            StringFileInfo([StringTable("040904B0", [
                StringStruct("CompanyName", "cc-wire-analyzer contributors"),
                StringStruct("FileDescription",
                             "CC Wire Analyzer - local MITM proxy for Claude Code traffic"),
                StringStruct("FileVersion", v),
                StringStruct("InternalName", "cc-wire-analyzer"),
                StringStruct("LegalCopyright",
                             "Copyright (c) 2026 cc-wire-analyzer contributors. MIT License."),
                StringStruct("OriginalFilename", "cc-wire-analyzer.exe"),
                StringStruct("ProductName", "CC Wire Analyzer"),
                StringStruct("ProductVersion", v),
            ])]),
            VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
        ])


def mac_info_plist(version: str | None = None) -> dict:
    """macOS `.app` 的 Info.plist 版本字段 —— Finder「显示简介」读的就是这两个。

    `LSUIElement=False` 等其余键交给 PyInstaller 的默认值，这里只管版本，
    免得顺手改掉窗口行为却没人在 macOS 上验证（维护者在 Windows）。
    """
    v = version or read_version()
    return {
        "CFBundleShortVersionString": v,   # Finder 简介里的「版本」
        "CFBundleVersion": v,              # 构建号，本项目与版本同值（唯一真源是 tag）
        "CFBundleName": "CC Wire Analyzer",
        "NSHumanReadableCopyright":
            "Copyright (c) 2026 cc-wire-analyzer contributors. MIT License.",
    }


if __name__ == "__main__":   # 手查：uv run python tools/version_res.py
    v = read_version()
    print(f"version={v!r}  tuple={version_tuple(v)}")
    print(f"mac plist={mac_info_plist(v)}")
