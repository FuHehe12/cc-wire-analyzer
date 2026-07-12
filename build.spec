# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包脚本：pywebview + Flask 桌面应用
# 用法（项目根目录）：uv run pyinstaller build.spec
# 产出 dist/cc-wire-analyzer.exe（单文件，noconsole）

from PyInstaller.utils.hooks import collect_submodules

datas = [
    ('src/templates', 'templates'),   # Flask 模板，app.py 用 sys._MEIPASS/templates 找
    ('src/static', 'static'),         # vendored 前端库（marked/DOMPurify），离线 exe 必须（审计 260712 #3）
]

# pywebview 在 Windows 用 EdgeChromium（WebView2）后端
hiddenimports = collect_submodules('webview.platforms.edgechromium')


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
)
