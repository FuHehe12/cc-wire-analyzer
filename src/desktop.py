"""pywebview 桌面入口。两种模式（单 exe，260713 合并）：

- 无参 / 双击 → GUI 模式：后台启 Flask + 前台开原生窗口，给人用。
- `serve` 子命令 → headless 模式：起 Flask + 自动启动代理，**不开窗**，给 AI agent 用。
  AI 通过 HTTP API（/api/proxy/*、/api/captures、/api/dag…）控制与查询，数据也可直接读 jsonl。

为什么单 exe 能兼顾（Windows PE 子系统是硬约束）：
  noconsole（console=False）进程永不分配控制台 → 双击不弹黑窗、sys.stdout 是 None。
  所以"AI 要 stdout"和"双击不弹窗"在单个 exe 里互斥。但 AI 其实不需要 stdout——
  app.py 早有一整套 HTTP API，AI 调它们拿结构化 JSON 即可；启停代理（唯一有副作用的动作）
  也走 HTTP。于是 serve 模式只起服务不开窗，绕过 PE 限制，单 exe 覆盖人 + AI 两个场景。

加固：
- 端口动态分配（5051-5100）
- WebView2 缺失友好提示（Windows GUI 模式，不黑屏）
- 日志到 ~/.cc-wire-analyzer/run.log（noconsole 也能查崩溃）
- 退出必恢复 BASE_URL：GUI 模式挂 closing 事件 + finally；serve 模式靠 atexit + signal
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


def _restore_on_close() -> None:
    """窗口 closing 事件回调：恢复 settings.json。幂等，未 patch 时不操作。

    绝不返回 False —— pywebview 把「有 handler 返回 False」当成取消关闭
    （webview/event.py: `return len(false_values) != 0`），那样用户就关不掉窗口了。
    异常也吞掉（pywebview 自己会 log），恢复失败不能演变成关不掉窗。"""
    import logging
    try:
        import settings_guard
        settings_guard._safe_restore()
    except Exception:
        logging.getLogger(__name__).exception("restore on close failed")


def _serve() -> None:
    """headless 服务模式：起 Flask + 自动启动代理，不开窗。给 AI agent 用。

    noconsole 进程没有 stdout/stderr，靠三个文件与外界通信：
      port.txt  —— 选中端口（AI 第一步读这个）
      run.log   —— 日志（崩溃/诊断）
      serve.pid —— 进程号（AI 停止服务用：kill 此 pid；进程退出时 atexit/signal 恢复 settings）

    退出恢复：app.py import 期已 `install_crash_guards()`（atexit + SIGTERM/SIGINT + excepthook）。
    AI 正常 kill（SIGTERM）→ signal handler restore；Windows 上被 TerminateProcess 强杀 →
    atexit 不跑、marker 残留 → 下次任意模式启动时 check_orphan_backup 自愈
    （260713 已加固：陈旧 marker 不覆盖用户自行改的配置）。"""
    import settings_guard
    port = CFG.find_free_port()
    if not port:
        sys.exit(1)
    CFG.write_port(port)
    flask_app.set_listen_port(port)
    try:   # 自动 patch（serve 的目的就是录制，一步到位；与 GUI 的 /api/proxy/start 同一套逻辑）
        settings_guard.snapshot_original()
        settings_guard.backup_file()
        settings_guard.patch_base_url(f"http://127.0.0.1:{port}")
    except Exception:
        sys.exit(1)   # patch 失败 → 退出；crash guards 会尝试清理（未成功 patch 则 restore 是 no-op）
    CFG.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (CFG.CONFIG_DIR / "serve.pid").write_text(str(os.getpid()), encoding="utf-8")
    # 阻塞：Flask 持有主线程。被停止时（SIGTERM/kill）由已注册的 handler 恢复 settings 后退出。
    flask_app.app.run(host="127.0.0.1", port=port, debug=False,
                      use_reloader=False, threaded=True)


def main() -> None:
    # serve 子命令：headless 服务模式（给 AI），见 _serve()。其余（无参/双击）走 GUI。
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        _serve()
        return
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
        win = webview.create_window("CC Wire Analyzer", f"http://127.0.0.1:{port}/",
                                    width=1280, height=840, min_size=(1080, 680))
        # 命脉：恢复不能只押在下面 finally 上（260713 用户实测：Mac 退出后 CC 通信直接断，
        # 要重开软件才靠孤儿自愈修回来 → 说明退出那刻 restore 压根没跑）。
        # macOS 的 Cmd+Q / 红点关窗走 NSApp terminate → C 层 exit()：既不展开 Python 栈、
        # 也不跑 atexit → finally 与三重崩溃保护全部落空，settings.json 永久指向死代理端口。
        # closing 是 pywebview 唯一**同步**派发的关闭事件（window.py:163 `Event(self, True)`），
        # 而 cocoa 的 windowShouldClose_（红点）与 applicationShouldTerminate_（Cmd+Q）
        # 都经 should_close() 触发它 —— 两条 macOS 退出路径全覆盖；winforms 的 FormClosing 同理。
        # 不挂 closed：它是异步派发（后台线程），进程都要没了，跑不跑得完全看运气。
        win.events.closing += _restore_on_close
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
