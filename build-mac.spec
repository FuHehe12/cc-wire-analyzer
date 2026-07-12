# -*- mode: python ; coding: utf-8 -*-
# macOS 打包脚本：pywebview WebKit（pyobjc）后端 → CCWireAnalyzer.app
# 用法（macOS 构建机）：
#   uv sync --extra mac          # 装 pyobjc（macOS 后端）
#   uv run pyinstaller build-mac.spec --noconfirm --clean
# 产出 dist/CCWireAnalyzer.app
#
# 注意：本开发环境为 Windows，此 spec 未在 macOS 实测——macOS 打包靠 GitHub Actions
# macos runner（.github/workflows/release.yml）+ 用户 macOS 验证。

from PyInstaller.utils.hooks import collect_submodules

datas = [
    ('src/templates', 'templates'),   # Flask 模板
    ('src/static', 'static'),         # vendored marked/DOMPurify + 打包字体（Inter/JetBrains Mono/Noto Sans SC）
]

# pywebview 在 macOS 用 WebKit（pyobjc）后端
hiddenimports = collect_submodules('webview.platforms.cocoa')


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
    name='CCWireAnalyzer',
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
    name='CCWireAnalyzer.app',
    icon=None,
    bundle_identifier=None,
)
