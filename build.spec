# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包脚本：pywebview + Flask 桌面应用
# 用法（项目根目录）：uv run pyinstaller build.spec
# 产出 dist/cc-wire-analyzer.exe（单文件，noconsole）

import os
import sys

from PyInstaller.utils.hooks import collect_submodules

# 版本资源（issue 260808）：让下载到磁盘上的 exe 在「属性 → 详细信息」里直接显示版本号，
# 不必双击打开程序才知道手上是哪一版。**两份 spec 共用 tools/version_res.py**，
# 不各写一份——两份 spec 因"要同时改"分叉过一次（mac spec 漏 brotli）。
sys.path.insert(0, os.path.join(SPECPATH, 'tools'))
from version_res import windows_version_info  # noqa: E402

datas = [
    ('src/templates', 'templates'),   # Flask 模板，app.py 用 sys._MEIPASS/templates 找
    ('src/static', 'static'),         # vendored 前端库（marked/DOMPurify），离线 exe 必须（审计 260712 #3）
    # 给 AI 的用法说明必须随产物走：用户下载到的是单个 exe，仓库 docs/ 一份都不跟着来，
    # 而 serve 模式的消费者正是 AI。/api/ai-guide 从这里读（issue 260801）。
    ('docs/reference/AI_USAGE.md', 'docs'),
]

# pywebview 在 Windows 用 EdgeChromium（WebView2）后端
# 录制侧解压能力覆盖 CC 声明的全部 Accept-Encoding（gzip/deflate/br/zstd，见 issue 260731）。
# brotli / zstandard 是 C 扩展，必须在 hiddenimports 显式带上，否则打包后 import 失败。
hiddenimports = collect_submodules('webview.platforms.edgechromium') + ['brotli', 'zstandard']


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
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,   # --noconsole：不弹黑色控制台窗口
    icon=None,
    # 版本号真源仍是 git tag（CI 打包前生成 src/_version.py）；这里只是把它刻进 PE 资源。
    # 本地无 _version.py 时刻的是 0.0.0/"dev"，一眼能看出不是发行版。
    version=windows_version_info(),
)
