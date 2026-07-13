# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包脚本：CLI（给 AI agent 用的 headless 入口）
# 用法（项目根目录）：uv run pyinstaller build-cli.spec
# 产出 dist/cc-wire-analyzer-cli(.exe)
#
# 为什么必须单独出一个二进制，而不是给 GUI exe 加子命令：
# Windows 的 GUI exe 是 `console=False`（--noconsole，否则双击会弹黑窗口），
# 而 **noconsole 的进程没有 stdout** —— `cc-wire-analyzer-windows.exe paths` 什么都打不出来，
# AI 拿不到任何返回。所以 CLI 必须是 console=True 的独立二进制。
# macOS 没有这个二分（stdout 一直在），但一并出裸二进制，省得让用户去 .app 里掏路径。

datas = [
    ('src/templates', 'templates'),   # daemon 模式会起 Flask（虽然 headless，模板路径要在）
    ('src/static', 'static'),
]

a = Analysis(
    ['src/cli.py'],
    pathex=['src'],
    binaries=[],
    datas=datas,
    hiddenimports=[],     # 不需要 webview：CLI 从不开窗口
    hookspath=[],
    runtime_hooks=[],
    excludes=['webview'],
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
    name='cc-wire-analyzer-cli',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,   # ←←← 命脉：有 stdout，AI 才拿得到 JSON
    icon=None,
)
