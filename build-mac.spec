# -*- mode: python ; coding: utf-8 -*-
# macOS 打包脚本：pywebview WebKit（pyobjc）后端 → cc-wire-analyzer.app
# 用法（macOS 构建机）：
#   uv sync --extra mac          # 装 pyobjc（macOS 后端）
#   uv run pyinstaller build-mac.spec --noconfirm --clean
# 产出 dist/cc-wire-analyzer.app
#
# 命名（260730）：与 Windows 侧统一为 kebab-case（原 CCWireAnalyzer.app）。这样两平台的
# serve 命令能写成同一套：cc-wire-analyzer.exe serve /
# cc-wire-analyzer.app/Contents/MacOS/cc-wire-analyzer serve。
#
# 注意：本开发环境为 Windows，此 spec 未在 macOS 实测——macOS 打包靠 GitHub Actions
# macos runner（.github/workflows/release.yml）+ 用户 macOS 验证。

import os
import sys

from PyInstaller.utils.hooks import collect_submodules

# 版本资源（issue 260808）：Finder「显示简介」里的版本号来自 Info.plist 的
# CFBundleShortVersionString——不设就是空的，跟 Windows 属性页没有「文件版本」是同一个病。
# **与 build.spec 共用 tools/version_res.py**，两份 spec 不各写一份（分叉过一次）。
sys.path.insert(0, os.path.join(SPECPATH, 'tools'))
# 只取 mac 那半边：`windows_version_info` 会 import `PyInstaller.utils.win32.versioninfo`，
# 而它在非 Windows 上 import 就炸（compat 里 win32api 只在 is_win 下定义）。
# version_res 把这个 import 放在函数体内，所以模块本身在 macOS 上是安全的。
from version_res import mac_info_plist, runtime_metadata  # noqa: E402

datas = [
    ('src/templates', 'templates'),   # Flask 模板
    ('src/static', 'static'),         # vendored marked/DOMPurify + 打包字体（Inter/JetBrains Mono/Noto Sans SC）
    ('docs/reference/AI_USAGE.md', 'docs'),     # /api/ai-guide 的正文，必须随产物走（issue 260801）
] + runtime_metadata()  # Flask/Werkzeug 的 dist-info（与 build.spec 同源，见 version_res.runtime_metadata）

# pywebview 在 macOS 用 WebKit（pyobjc）后端。
# brotli / zstandard 与 build.spec 对齐（260801 发现两个 spec 分叉）：CC 声明
# `Accept-Encoding: gzip, deflate, br, zstd`，缺 brotli 时非流式响应（安全分类器正是非流式）
# 的 body/usage/content_blocks 会整段丢失——v0.4.3 修的正是这个盲区，而 mac spec 没跟上，
# 等于 macOS 产物仍带着已修掉的 bug。两个 spec 的 hiddenimports 必须同步改。
hiddenimports = collect_submodules('webview.platforms.cocoa') + ['brotli', 'zstandard']


a = Analysis(
    ['src/desktop.py'],
    pathex=['src'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='cc-wire-analyzer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,            # macOS 上 upx 常致签名/运行问题，关
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    icon=None,
)

app = BUNDLE(
    exe,
    name='cc-wire-analyzer.app',
    icon=None,
    bundle_identifier=None,
    # Finder「显示简介」的版本号（issue 260808）。版本真源仍是 git tag，见 tools/version_res.py。
    info_plist=mac_info_plist(),
)
