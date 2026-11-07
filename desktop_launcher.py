"""Windows executable entry point; source-mode server remains `python -m backend`."""
import json
import socket
import sys
import threading
import time
import webbrowser
from tempfile import TemporaryDirectory
from dataclasses import replace
from pathlib import Path


def save_configuration(api_key, path):
    from dotenv import set_key

    key = api_key.strip()
    if not key or key.startswith('ark-') or any(char in key for char in '\r\n\0'):
        raise ValueError('请填写豆包语音控制台的有效 API Key，不能使用火山方舟 ark- Key。')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Use dotenv's quoting, never put the key into a command line or build file.
    set_key(path, 'VOLC_API_KEY', key, encoding='utf-8')
    # This release uses the delta semantics verified in tests/ACCEPTANCE.md.
    set_key(path, 'VOLC_SUBTITLE_RESPONSE_MODE', 'delta', encoding='utf-8')
    return key


def listening_socket(port):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if sys.platform == 'win32':
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(('127.0.0.1', port))
        listener.listen(128)
        listener.setblocking(False)
        return listener
    except BaseException:
        listener.close()
        raise


def server_for(settings, record_store=None):
    import uvicorn
    from backend.app import create_app

    return uvicorn.Server(uvicorn.Config(
        create_app(settings, record_store=record_store), host='127.0.0.1', port=settings.port,
        ws_max_size=4096, ws_max_queue=4, log_level='warning',
        access_log=False, timeout_graceful_shutdown=7,
    ))


def self_test():
    """Validate embedded dependencies/resources without opening UI or cloud sessions."""
    import sqlite3
    import tkinter
    from backend.runtime import ROOT
    from backend.terminology import load_course_corpus
    from backend.records import RecordStore

    index = ROOT / 'frontend/dist/index.html'
    if not index.is_file() or not list((index.parent / 'assets').glob('*.js')):
        raise RuntimeError('Bundled frontend assets are missing')
    for mode in ('auto', 'zh-en', 'en-zh'):
        load_course_corpus(mode)
    with sqlite3.connect(':memory:') as connection:
        connection.execute('SELECT 1').fetchone()
    with TemporaryDirectory(prefix='classroom-self-test-') as directory:
        path = Path(directory) / 'records.sqlite3'
        store = RecordStore(path)
        store.save_event(dict(type='subtitle', classId='self-test', sessionEpoch=1,
            channel='source', segmentId='one', revision=1, text='self-test', isFinal=True))
        store.close()
        reopened = RecordStore(path)
        try:
            if reopened.get_course('self-test')['entries'][0]['text'] != 'self-test':
                raise RuntimeError('Database persistence check failed')
        finally:
            reopened.close()
    if sys.platform == 'win32':
        import soundcard
        import numpy
        import _cffi_backend
    return {'selfTest': 'ok', 'sqlite': sqlite3.sqlite_version, 'tk': tkinter.TkVersion, 'database': 'ok'}


def smoke_test():
    """Exercise the packaged HTTP server; never access microphones or the cloud."""
    import re
    from urllib.request import ProxyHandler, build_opener
    from backend.config import Settings
    from backend.records import RecordStore

    temporary = TemporaryDirectory(prefix='classroom-smoke-test-')
    records = RecordStore(Path(temporary.name) / 'records.sqlite3')
    listener = listening_socket(0)
    port = listener.getsockname()[1]
    server = server_for(Settings(port=port), record_store=records)
    thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 20
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError('Packaged server failed to start')
            time.sleep(.05)
        opener = build_opener(ProxyHandler({}))
        base = f'http://127.0.0.1:{port}'
        with opener.open(base + '/api/health', timeout=5) as response:
            health = json.load(response)
        if health['credentialsConfigured'] or health['activeSessions']:
            raise RuntimeError('Smoke test must not use credentials or cloud sessions')
        with opener.open(base + '/api/records', timeout=5) as response:
            if json.load(response)['records']:
                raise RuntimeError('Smoke test must use an isolated empty database')
        with opener.open(base, timeout=5) as response:
            html = response.read().decode('utf-8')
        assets = re.findall(r'(?:src|href)="(/assets/[^"<>]+)"', html)
        if not assets:
            raise RuntimeError('No frontend resources referenced')
        for asset in assets:
            with opener.open(base + asset, timeout=5) as response:
                if not response.read():
                    raise RuntimeError('Empty frontend resource')
        return {'smokeTest': 'ok', 'assets': len(assets), 'cloudSessions': 0}
    finally:
        server.should_exit = True
        thread.join(12)
        listener.close()
        records.close()
        temporary.cleanup()
        if thread.is_alive():
            raise RuntimeError('Packaged server did not stop')


def launch():
    import tkinter as tk
    from tkinter import messagebox, simpledialog, ttk
    from backend.config import Settings
    from backend.runtime import configuration_path

    root = tk.Tk()
    root.withdraw()
    root.title('青衿学院课堂同传')
    try:
        settings = Settings.load()
        if not settings.api_key or settings.api_key.startswith('ark-') or settings.response_mode == 'unverified':
            while True:
                key = simpledialog.askstring(
                    '首次设置', '请输入豆包语音新版控制台的 API Key：\n设置会保存在这台电脑，翻译需要联网。',
                    show='*', parent=root,
                )
                if key is None:
                    root.destroy()
                    return 0
                try:
                    key = save_configuration(key, configuration_path())
                    settings = replace(settings, api_key=key, response_mode='delta')
                    break
                except ValueError as error:
                    messagebox.showerror('配置未保存', str(error), parent=root)
        listener = listening_socket(settings.port)
        server = server_for(settings)
    except OSError:
        messagebox.showerror('无法启动', '端口被占用或配置无法保存。请关闭已运行的课堂同传，并检查用户目录的写入权限后重试。', parent=root)
        root.destroy()
        return 1
    except Exception:
        messagebox.showerror('无法启动', '配置或程序资源无法读取。请检查配置，或重新获取完整的程序文件。', parent=root)
        root.destroy()
        return 1

    root.geometry('430x190')
    root.resizable(False, False)
    panel = ttk.Frame(root, padding=20)
    panel.pack(fill='both', expand=True)
    status = tk.StringVar(value='正在启动本机服务…')
    ttk.Label(panel, textvariable=status, wraplength=385).pack(anchor='w', pady=(0, 12))
    url = f'http://localhost:{settings.port}'
    opened = False
    stopping = False
    thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    deadline = time.monotonic() + 30

    def close():
        nonlocal stopping
        if not stopping and messagebox.askokcancel('退出课堂同传', '退出将停止翻译。已自动保存的课程可在下次打开后查看和导出。请确认页面没有保存失败提示。', parent=root):
            stopping = True
            status.set('正在关闭本机服务，请稍候…')
            server.should_exit = True

    def poll():
        nonlocal opened, stopping
        if not thread.is_alive():
            listener.close()
            if not stopping:
                messagebox.showerror('服务已停止', '本机服务未能启动或已异常退出，请重新启动程序。', parent=root)
            root.destroy()
            return
        if not server.started and time.monotonic() > deadline:
            stopping = True
            server.should_exit = True
            status.set('启动超时，正在关闭本机服务…')
        if server.started and not opened and not stopping:
            opened = True
            status.set('课堂同传已启动。请在浏览器中使用；退出程序请点击下方按钮。')
            webbrowser.open(url)
        root.after(150, poll)

    ttk.Button(panel, text='打开课堂界面', command=lambda: webbrowser.open(url)).pack(fill='x', pady=4)
    ttk.Button(panel, text='退出程序', command=close).pack(fill='x', pady=4)
    root.protocol('WM_DELETE_WINDOW', close)
    thread.start()
    root.deiconify()
    root.after(100, poll)
    try:
        root.mainloop()
    finally:
        server.should_exit = True
        thread.join(12)
        listener.close()
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    # Dispatch before importing configuration/UI: child stdout carries JSON/PCM.
    if argv[:1] == ['--audio-worker']:
        from backend.windows_audio import main as audio_main
        return audio_main(argv[1:])
    if argv == ['--self-test']:
        print(json.dumps(self_test()))
        return 0
    if argv == ['--smoke-test']:
        print(json.dumps(smoke_test()))
        return 0
    if argv:
        raise SystemExit('Unsupported launcher argument')
    return launch()


if __name__ == '__main__':
    raise SystemExit(main())
