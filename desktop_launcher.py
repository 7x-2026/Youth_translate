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



PALETTE = dict(bg='#f4f7f2', card='#ffffff', line='#dce5dc', text='#213a31', muted='#63766b', accent='#2c6851')


def prepare_window(root, width, height):
    root.configure(bg=PALETTE['bg'])
    root.resizable(False, False)
    x=max(0, (root.winfo_screenwidth()-width)//2)
    y=max(0, (root.winfo_screenheight()-height)//2)
    root.geometry(f'{width}x{height}+{x}+{y}')


def brand_header(parent, subtitle):
    import tkinter as tk
    p=PALETTE
    frame=tk.Frame(parent, bg=p['bg'])
    frame.pack(fill='x', padx=30, pady=(26,18))
    tk.Label(frame, text='青 衿  /  CLASSROOM', fg=p['accent'], bg=p['bg'], font=('Microsoft YaHei UI',9)).pack(anchor='w')
    tk.Label(frame, text='让语言跟上课堂。', fg=p['text'], bg=p['bg'], font=('Microsoft YaHei UI',23,'bold')).pack(anchor='w', pady=(10,6))
    tk.Label(frame, text=subtitle, fg=p['muted'], bg=p['bg'], font=('Microsoft YaHei UI',10)).pack(anchor='w')


def ui_button(parent, text, command, primary=False):
    import tkinter as tk
    p=PALETTE
    color=p['accent'] if primary else p['card']
    hover='#3f7d63' if primary else '#edf3ec'
    # Keep a real keyboard-accessible Button; the Canvas supplies rounded edges.
    shell=tk.Canvas(parent, bg=parent.cget('bg'), highlightthickness=0, bd=0, cursor='hand2')
    button=tk.Button(shell, text=text, command=command, font=('Microsoft YaHei UI',11,'bold' if primary else 'normal'),
        bg=color, fg=p['bg'] if primary else p['text'], activebackground=hover,
        activeforeground=p['bg'] if primary else p['text'], relief='flat', bd=0,
        cursor='hand2', padx=8, pady=12, highlightthickness=0, takefocus=True)
    shell.configure(height=button.winfo_reqheight()+4)
    item=shell.create_window(0,0,window=button)
    state={'hover':False,'focus':False}
    def draw(_event=None):
        w,h=shell.winfo_width(),shell.winfo_height()
        r=min(14,h/2-1,w/2-1)
        fill=hover if state['hover'] else color
        shell.delete('surface')
        shell.create_polygon(1+r,1,w-1-r,1,w-1,1,w-1,1+r,w-1,h-1-r,w-1,h-1,w-1-r,h-1,1+r,h-1,1,h-1,1,h-1-r,1,1+r,1,1,
            smooth=True,splinesteps=24,fill=fill,outline=p['accent'] if state['focus'] else color if primary else p['line'],width=2 if state['focus'] else 1,tags='surface')
        shell.tag_lower('surface')
        shell.coords(item,w/2,h/2)
        shell.itemconfigure(item,width=max(1,w-2*r-4),height=max(1,h-4))
        button.configure(bg=fill)
    def hovered(value):
        state['hover']=value;draw()
    def focused(value):
        state['focus']=value;draw()
    for widget in (shell,button):
        widget.bind('<Enter>',lambda _e:hovered(True))
        widget.bind('<Leave>',lambda _e:hovered(False))
    button.bind('<FocusIn>',lambda _e:focused(True))
    button.bind('<FocusOut>',lambda _e:focused(False))
    def enter(_event):
        button.invoke();return 'break'
    button.bind('<Return>',enter)
    shell.bind('<ButtonRelease-1>',lambda _e:button.invoke())
    shell.bind('<Configure>',draw)
    return shell


def request_api_key(root):
    import tkinter as tk
    p=PALETTE
    dialog=tk.Toplevel(root)
    dialog.title('青衿学院课堂同传 · 首次设置')
    prepare_window(dialog, 440, 540)
    brand_header(dialog, '首次使用  /  连接你的豆包语音服务')
    body=tk.Frame(dialog, bg=p['bg']);body.pack(fill='both', expand=True, padx=30)
    tk.Label(body, text='豆包语音 API Key', fg=p['text'], bg=p['bg'],font=('Microsoft YaHei UI',11,'bold')).pack(anchor='w', pady=(0,9))
    entry=tk.Entry(body, show='●', bg=p['card'], fg=p['text'], insertbackground=p['accent'], relief='flat', font=('Microsoft YaHei UI',12), highlightthickness=1, highlightbackground=p['line'], highlightcolor=p['accent'])
    entry.pack(fill='x', ipady=10)
    tk.Label(body,text='请使用豆包语音新版控制台的 Key，非火山方舟 ark- Key。\n配置仅保存在本机；翻译需要联网，麦克风授权在浏览器中完成。',justify='left',wraplength=360,fg=p['muted'],bg=p['bg'],font=('Microsoft YaHei UI',9)).pack(anchor='w',pady=(12,6))
    error=tk.StringVar()
    tk.Label(body,textvariable=error,fg='#9b4d1d',bg=p['bg'],font=('Microsoft YaHei UI',9),wraplength=360,justify='left').pack(anchor='w')
    result=[None]
    def submit():
        value=entry.get().strip()
        if not value or value.startswith('ark-') or any(c in value for c in '\r\n\0'):
            error.set('请输入有效的豆包语音 Key，不能使用 ark- Key。');return
        result[0]=value;dialog.destroy()
    ui_button(body,'保存并进入课堂  →',submit,True).pack(fill='x',pady=(12,0))
    dialog.bind('<Return>',lambda _event:submit())
    dialog.protocol('WM_DELETE_WINDOW',dialog.destroy)
    dialog.grab_set();entry.focus_set();root.wait_window(dialog)
    return result[0]


def build_launcher_ui(root, status, open_classroom, close):
    import tkinter as tk
    p=PALETTE
    prepare_window(root, 420, 600)
    brand_header(root, '青衿学院课堂同传  /  中文 ⇄ English')
    card=tk.Frame(root,bg=p['card'],highlightbackground=p['line'],highlightthickness=1)
    card.pack(fill='x',padx=30,pady=(0,16))
    tk.Label(card,text='●  本机课堂服务',fg=p['accent'],bg=p['card'],font=('Microsoft YaHei UI',10,'bold')).pack(anchor='w',padx=18,pady=(16,7))
    tk.Label(card,textvariable=status,fg=p['text'],bg=p['card'],font=('Microsoft YaHei UI',10),wraplength=315,justify='left',height=3,anchor='nw').pack(fill='x',padx=18,pady=(0,12))
    body=tk.Frame(root,bg=p['bg']);body.pack(fill='x',padx=30)
    ui_button(body,'打开课堂  →',open_classroom,True).pack(fill='x')
    tk.Label(body,text='首次使用麦克风\n进入课堂后点击“授权并试音”。\n在浏览器中选择允许，确认电平后再开始课程。',fg=p['muted'],bg=p['bg'],font=('Microsoft YaHei UI',9),justify='left',wraplength=350).pack(anchor='w',pady=(16,18))
    ui_button(body,'退出程序',close).pack(fill='x')
    tk.Label(root,text='本机保存课程文字  ·  不保存录音  ·  翻译依赖网络',fg=p['muted'],bg=p['bg'],font=('Microsoft YaHei UI',8)).pack(side='bottom',pady=14)


def launch():
    import tkinter as tk
    from tkinter import messagebox
    from backend.config import Settings
    from backend.runtime import configuration_path

    root = tk.Tk()
    root.withdraw()
    root.title('青衿学院课堂同传')
    try:
        settings = Settings.load()
        if not settings.api_key or settings.api_key.startswith('ark-') or settings.response_mode == 'unverified':
            while True:
                key = request_api_key(root)
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

    status = tk.StringVar(value='正在启动本机服务，请稍候…')
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

    build_launcher_ui(root, status, lambda: webbrowser.open(url), close)
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
