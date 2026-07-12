"""pywebview 桌面入口：后台启 Flask（动态端口），前台开原生窗口。

加固：
- 端口动态分配（5051-5100）
- WebView2 缺失友好提示（Windows，不黑屏）
- 日志到 ~/.cc-wire-analyzer/run.log（noconsole 也能查崩溃）
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as CFG  # noqa: E402
CFG.setup_logging()
import app as flask_app  # noqa: E402


def _wait_port(port: int, host: str = "127.0.0.1", timeout: float = 20.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def _msg_box(text: str, title: str = "CC Wire Analyzer", style: int = 0x30) -> None:
    """noconsole 崩溃提示（stderr 看不见）。
    Windows 弹 Win32 MessageBox；macOS/Linux 记日志（setup_logging 已写 run.log）。"""
    import logging
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, title, style)
        else:
            logging.getLogger(__name__).error("%s: %s", title, text)
    except Exception:
        pass


def main() -> None:
    port = CFG.find_free_port()
    if not port:
        _msg_box("无空闲端口（5051-5100 全占用）。请关闭占用 5051+ 的程序后重试。", "启动失败", 0x10)
        sys.exit(1)
    CFG.write_port(port)
    flask_app.set_listen_port(port)   # proxy_start 需要 _LISTEN_PORT，否则 no_listen_port（260712 实测发现）

    def _run_server():
        flask_app.app.run(host="127.0.0.1", port=port, debug=False,
                          use_reloader=False, threaded=True)

    srv = threading.Thread(target=_run_server, daemon=True)
    srv.start()
    if not _wait_port(port):
        _msg_box(f"Flask 20s 内未就绪（端口 {port}）。查 ~/.cc-wire-analyzer/run.log。", "启动失败", 0x10)
        sys.exit(1)

    try:
        import webview
        webview.create_window("CC Wire Analyzer", f"http://127.0.0.1:{port}/",
                              width=1280, height=840, min_size=(1080, 680))
        webview.start()
    except Exception as e:
        msg = str(e)
        low = msg.lower()
        if "webview2" in low or "edge chromium" in low or "could not find" in low or "runtime" in low:
            _msg_box(
                "未检测到 WebView2 Runtime（Windows 的渲染内核）。\n\n"
                "请安装 Microsoft Edge WebView2 Runtime：\n"
                "https://developer.microsoft.com/microsoft-edge/webview2/\n\n"
                "错误详情：" + msg,
                "WebView2 缺失", 0x30)
        else:
            _msg_box("启动失败：" + msg, "错误", 0x10)
    finally:
        # 命脉：os._exit(0) 跳过 atexit 钩子，关窗/异常退出前必须手动恢复 BASE_URL，
        # 否则 settings.json 永久指向已死的代理端口 → CC 不可用（审计 260712 #1）。
        # _safe_restore 已 try/except 包裹，未 patch 时幂等返回不操作。
        try:
            import settings_guard
            settings_guard._safe_restore()
        except Exception:
            pass
    os._exit(0)


if __name__ == "__main__":
    main()
