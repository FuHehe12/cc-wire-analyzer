"""pywebview 桌面入口。三种调用（单 exe，260713 合并 GUI/serve，260801 加 help）：

- 无参 / 双击 → GUI 模式：后台启 Flask + 前台开原生窗口，给人用。
- `serve` 子命令 → headless 模式：起 Flask + 自动启动代理，**不开窗**，给 AI agent 用。
  AI 通过 HTTP API（/api/proxy/*、/api/captures、/api/dag…）控制与查询，数据也可直接读 jsonl。
- `--help` / `--ai-guide` → 打印用法说明后退出，**不开窗**（见 _emit_help）。

为什么主通道是 HTTP：app.py 早有一整套 HTTP API，结构化 JSON、不用 shell 转义、
GUI 与 AI 共用同一份实现；启停代理（唯一有副作用的动作）也走 HTTP。

⚠️ noconsole 的准确含义（260801 实测纠正，本文件此前写错过）：
  console=False 的进程**永不分配控制台**，所以**双击运行**时没有可写的 stdout。
  但这不等于"打不出任何东西"——被 shell 以**管道或重定向**启动时（agent 调命令的标准姿势）
  fd 1 是有效句柄，os.write(1, …) 照样能写。原来那句"CLI 子命令什么都打印不出来"是错的，
  它让 --help 这条最自然的入口空了三周（别人机器上的 AI 试 --help 只会看到弹出一个窗口）。

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
        logging.getLogger(__name__).info("exit: window closing（用户关窗）")
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
    import logging
    port = CFG.find_free_port()
    if not port:
        sys.exit(1)
    CFG.write_port(port)
    flask_app.set_listen_port(port)
    flask_app.set_run_mode("serve")   # 无窗模式尤其需要被看见——设置页实例总览的主要对象（260809）
    logging.getLogger(__name__).info(
        "=== started mode=serve pid=%s version=%s port=%s ===",
        os.getpid(), flask_app.VERSION, port)
    try:   # 自动 patch（serve 的目的就是录制，一步到位）。**与 GUI 的 /api/proxy/start 调同一个
           # 函数**——260807 之前这里是抄过去的三行，新增的上游历史采集只加进了路由那份，
           # serve 模式的历史于是永远是空的。声称"同一套逻辑"就得真的是同一个函数。
        flask_app.begin_recording(port)
    except Exception as e:
        # 260807：patch 失败**不再退出**，服务照常起，只是没在录。
        #
        # 起因是一条真实且很难自己走出去的死路：BASE_URL 被固化成了本机代理地址（录制期间
        # 切换工具保存 profile 所致）→ snapshot 的自指守卫拒绝 patch（拿它当上游会无限递归）
        # → serve 进程直接 exit(1) → 而修复这个病的端点（`/api/settings/upstream-restore`）
        # **正好在这个进程里**。于是 AI 侧一个能自救的路径都没有，只能人去手改 settings.json。
        # 起着不录，比退出后什么都做不了强得多：status 会如实显示 running=false，
        # 修复端点可用，修完调一次 /api/proxy/start 就开始录。
        logging.getLogger(__name__).warning(
            "自动 patch 失败（%s）——服务继续运行但未在录制。"
            "若是 BASE_URL 被固化成本机地址，调 GET /api/settings/upstream-history 看 "
            "current.needs_fix，再 POST /api/settings/upstream-restore 修复，然后 "
            "POST /api/proxy/start 开始录制。", e)
    CFG.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    (CFG.CONFIG_DIR / "serve.pid").write_text(str(os.getpid()), encoding="utf-8")
    # 阻塞：Flask 持有主线程。被停止时（SIGTERM/kill）由已注册的 handler 恢复 settings 后退出。
    flask_app.app.run(host="127.0.0.1", port=port, debug=False,
                      use_reloader=False, threaded=True)


# AI 打开一个陌生二进制的第一反应就是 `--help`。此前这些参数会被当成"不是 serve"→ **弹出 GUI 窗口**，
# 对一个正在跑命令的 agent 来说是最糟的结果（窗口冒出来、命令不返回、什么都没学到）。
_HELP_ARGS = {"-h", "--help", "help", "/?", "-?", "--ai-guide", "guide", "--version", "-v"}


def _emit_help() -> None:
    """打印用法并退出，绝不开窗、绝不弹模态框（模态框会把 agent 的命令挂住）。

    noconsole 进程的 `sys.stdout` 通常是 None，但**标准句柄被重定向时**（agent 的 shell 用管道
    收集输出、或用户 `> out.txt`）fd 1 依然有效——所以先试 os.write(1)，能打就打。
    无论能不能打，都把完整说明落到数据目录的 ai-guide.md：那是一条即使 stdout 不可用也能
    被读到的路径（前提是知道它在哪，所以这条路径本身要出现在能打出来的那份文本里）。
    """
    import app as flask_app  # 说明书正文与 /api/ai-guide 同一份，别再抄第二份
    guide = flask_app._ai_guide_body()
    text = (
        "CC Wire Analyzer " + flask_app.VERSION + "\n"
        "本机 MITM 代理，透明录制 Claude Code ↔ 上游的全部 HTTP 流量。\n\n"
        "用法：\n"
        "  cc-wire-analyzer            打开图形界面（双击同此），给人用\n"
        "  cc-wire-analyzer serve      只起 HTTP 服务 + 代理、不开窗，给 AI agent 用\n"
        "  cc-wire-analyzer --help     打印本说明\n\n"
        "给 AI agent：起 serve 之后，**完整用法说明在 http://127.0.0.1:<port>/api/ai-guide**\n"
        "（端口写在 " + str(CFG.CONFIG_DIR / "port.txt") + "，从 5051 起挑空闲口，别照抄 5051）。\n"
        "同一份说明也落在 " + str(CFG.CONFIG_DIR / "ai-guide.md") + "。\n\n"
        "--- 完整说明 ---\n\n" + guide
    )
    try:
        CFG.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        (CFG.CONFIG_DIR / "ai-guide.md").write_text(text, encoding="utf-8")
    except OSError:
        pass          # 落盘失败不能连"打印"这件事都一起失败
    data = text.encode("utf-8", "replace")
    if sys.stdout is not None:
        try:
            sys.stdout.buffer.write(data)
            sys.stdout.flush()
            return
        except Exception:
            pass
    try:
        os.write(1, data)      # stdout 被重定向/管道接走时，fd 1 有效而 sys.stdout 可能是 None
    except OSError:
        pass                   # 真的无处可打（双击运行）——文件已经落好了，静默退出


def main() -> None:
    # serve 子命令：headless 服务模式（给 AI），见 _serve()。其余（无参/双击）走 GUI。
    arg1 = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg1 == "serve":
        _serve()
        return
    if arg1.lower() in _HELP_ARGS:
        _emit_help()
        return
    port = CFG.find_free_port()
    if not port:
        _msg_box("无空闲端口（5051-5100 全占用）。请关闭占用 5051+ 的程序后重试。", "启动失败", 0x10)
        sys.exit(1)
    CFG.write_port(port)
    flask_app.set_listen_port(port)   # proxy_start 需要 _LISTEN_PORT，否则 no_listen_port（260712 实测发现）
    flask_app.set_run_mode("gui")     # 设置页「运行中的实例」据此区分 GUI / serve（260809）
    import logging
    logging.getLogger(__name__).info(
        "=== started mode=gui pid=%s version=%s port=%s ===",
        os.getpid(), flask_app.VERSION, port)

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
            import logging
            import settings_guard
            settings_guard._safe_restore()
            # os._exit 跳过 atexit → 这里是 GUI 正常退出唯一的收尾记录点。
            # run.log 里见此行 = 干净退出；启动横幅后无任何 exit 行 = 强杀/断电。
            logging.getLogger(__name__).info("=== exit: gui shutdown pid=%s ===", os.getpid())
            logging.shutdown()   # os._exit 不冲缓冲，显式 flush 才能保证这行落盘
        except Exception:
            pass
    os._exit(0)


if __name__ == "__main__":
    main()
