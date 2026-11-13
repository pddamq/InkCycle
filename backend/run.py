"""EXE 启动器：后台线程跑 FastAPI（uvicorn），主线程开 pywebview 原生窗口。

打包：见 build_exe.ps1
用法（开发）：python run.py [--browser] [--port N]
"""
import argparse
import os
import socket
import sys
import tempfile
import threading
import time
import traceback
import webbrowser

LOG_PATH = os.path.join(tempfile.gettempdir(), "novelagent.log")


def _ensure_std_streams():
    """窗口模式（--windowed/pythonw）下 sys.stdout/stderr 为 None，
    任何 print 或第三方库写入都会崩溃。重定向到日志文件保证稳定，
    同时保留可诊断的输出。"""
    if sys.stdout is None or sys.stderr is None:
        try:
            logf = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
        except OSError:
            logf = open(os.devnull, "w", encoding="utf-8")
        if sys.stdout is None:
            sys.stdout = logf
        if sys.stderr is None:
            sys.stderr = logf


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_backend(port: int):
    import uvicorn
    from novel_agent.main import app

    config = uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="warning",
        loop="none", http="h11", lifespan="on",
    )
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    deadline = time.time() + 30
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("后端启动超时")
    return server


class _DesktopState:
    allow_close = False
    window = None


def _get_close_action() -> str:
    from novel_agent import db

    action = db.get_config().get("close_action", "ask")
    return action if action in ("ask", "minimize", "exit") else "ask"


def _defer_ui(action):
    """closing 回调运行在 GUI 主线程，不能直接 evaluate_js / minimize（会死锁卡「未响应」）。"""

    def _run():
        time.sleep(0.05)
        try:
            action()
        except Exception:
            traceback.print_exc()

    threading.Thread(target=_run, daemon=True).start()


def _native_close_prompt() -> None:
    """WebView 调 JS 失败时的 Windows 原生兜底。"""
    try:
        import ctypes

        # 4=Yes/No, 32=Question; 6=Yes(最小化), 7=No(退出), 2=Cancel
        choice = ctypes.windll.user32.MessageBoxW(
            0,
            "点击关闭时如何操作？\n\n「是」最小化到任务栏\n「否」退出程序\n「取消」返回",
            "关闭应用",
            0x00000004 | 0x00000020,
        )
        if choice == 6:
            DesktopApi().apply_close_choice("minimize", False)
        elif choice == 7:
            DesktopApi().apply_close_choice("exit", False)
    except Exception:
        traceback.print_exc()


def _show_close_dialog() -> None:
    win = _DesktopState.window
    if not win:
        return
    try:
        # run_js 不等待返回值；且必须在 closing 返回后再调，避免 UI 线程自锁
        win.run_js("window.__showCloseDialog && window.__showCloseDialog()")
    except Exception:
        _native_close_prompt()


class DesktopApi:
    """供前端调用的桌面窗口 API（pywebview js_api）。"""

    def get_close_action(self) -> str:
        return _get_close_action()

    def apply_close_choice(self, action: str, remember: bool) -> None:
        from novel_agent import db

        action = action if action in ("minimize", "exit") else "exit"
        if remember:
            db.set_config_values({"close_action": action})

        def _do():
            win = _DesktopState.window
            if action == "minimize":
                if win:
                    win.minimize()
                return
            _DesktopState.allow_close = True
            if win:
                win.destroy()

        _defer_ui(_do)


def _on_window_closing():
    if _DesktopState.allow_close:
        return True
    action = _get_close_action()
    if action == "exit":
        return True
    if action == "minimize":
        _defer_ui(lambda: _DesktopState.window and _DesktopState.window.minimize())
        return False
    _defer_ui(_show_close_dialog)
    return False


def open_window(url: str) -> bool:
    try:
        import webview  # pywebview

        win = webview.create_window(
            "小说创作 Agent", url, width=1440, height=920, min_size=(1080, 720),
            js_api=DesktopApi(),
        )
        _DesktopState.window = win
        win.events.closing += _on_window_closing
        webview.start()
        return True
    except Exception as e:
        print(f"pywebview 不可用（{e}），退回浏览器模式", file=sys.stderr)
        traceback.print_exc()
        return False


def main():
    _ensure_std_streams()
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", action="store_true", help="直接用系统浏览器打开")
    parser.add_argument("--port", type=int, default=0, help="指定端口（默认自动分配）")
    args, _ = parser.parse_known_args()

    try:
        from novel_agent import db

        db.init_db()
        port = args.port or find_free_port()
        start_backend(port)
        url = f"http://127.0.0.1:{port}"
        print(f"NovelAgent 后端已启动：{url}", flush=True)

        if args.browser:
            webbrowser.open(url)
            print("按回车退出…", flush=True)
            try:
                input()
            except EOFError:
                pass
        else:
            if not open_window(url):
                webbrowser.open(url)
                try:
                    input()
                except EOFError:
                    pass
    except Exception:
        traceback.print_exc()
        # 窗口模式下让用户知道出错了
        try:
            import webview
            webview.create_window("小说创作 Agent - 启动失败",
                                  f"data:text/html;charset=utf-8,<h3>启动失败</h3><pre>{traceback.format_exc()}</pre>")
            webview.start()
        except Exception:
            pass
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
