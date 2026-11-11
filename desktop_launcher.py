"""Desktop application entry point; source-mode server remains `python -m backend`."""
import errno
import json
import os
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
    # Commit both fields together so a failed save leaves the previous Key usable.
    with TemporaryDirectory(prefix='.classroom-config-', dir=path.parent) as directory:
        staged = Path(directory) / 'config.env'
        staged.touch(mode=0o600)
        if path.exists():
            staged.write_bytes(path.read_bytes())
        # Use dotenv's quoting, never put the key into a command line or build file.
        set_key(staged, 'VOLC_API_KEY', key, encoding='utf-8')
        set_key(staged, 'VOLC_SUBTITLE_RESPONSE_MODE', 'delta', encoding='utf-8')
        os.replace(staged, path)
    return key


def update_api_key(settings, api_key, path):
    key = save_configuration(api_key, path)
    return replace(settings, api_key=key, response_mode='delta')


def listening_socket(port):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if sys.platform == 'win32':
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
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
    for name in ('academy-logo.png','academy-launcher.png','academy.ico'):
        if not (index.parent/'assets'/name).is_file():
            raise RuntimeError('Bundled academy logo is missing')
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
    if sys.platform == 'darwin' and getattr(sys, 'frozen', False):
        from backend.runtime import bundled_audio_binary
        if not bundled_audio_binary().is_file():
            raise RuntimeError('Bundled system audio helper is missing')
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
        result = {'smokeTest': 'ok', 'assets': len(assets), 'cloudSessions': 0}
        if sys.platform in ('win32', 'darwin'):
            # Import checks alone miss failures in the frozen worker's startup
            # environment and timeout. Enumerating devices does not record audio.
            with opener.open(base + '/api/audio-outputs', timeout=45) as response:
                devices = json.load(response)['devices']
            if not isinstance(devices, list):
                raise RuntimeError('Invalid audio output list')
            result['audioOutputs'] = len(devices)
        return result
    finally:
        server.should_exit = True
        thread.join(12)
        listener.close()
        records.close()
        temporary.cleanup()
        if thread.is_alive():
            raise RuntimeError('Packaged server did not stop')



PALETTE = dict(bg='#f5f1e9', card='#fffdf8', line='#e4ded1', text='#303d36', muted='#807f72', accent='#456950')
UI_FONT = 'PingFang SC' if sys.platform == 'darwin' else 'Microsoft YaHei UI'


def prepare_window(root, width, height):
    root.configure(bg=PALETTE['bg'])
    root.resizable(False, False)
    x=max(0, (root.winfo_screenwidth()-width)//2)
    y=max(0, (root.winfo_screenheight()-height)//2)
    root.geometry(f'{width}x{height}+{x}+{y}')
    from backend.runtime import ROOT
    icon = ROOT/'frontend/dist/assets/academy.ico'
    if sys.platform == 'win32' and icon.is_file():
        root.iconbitmap(str(icon))


def brand_header(parent, subtitle):
    import tkinter as tk
    from backend.runtime import ROOT
    p=PALETTE
    frame=tk.Frame(parent, bg=p['bg'])
    frame.pack(fill='x', padx=32, pady=(20,20))
    logo_path=ROOT/'frontend/dist/assets/academy-launcher.png'
    if logo_path.is_file():
        logo=tk.PhotoImage(file=str(logo_path))
        label=tk.Label(frame, image=logo, bg=p['bg'], bd=0)
        label.image=logo
        label.pack(pady=(0,10))
    tk.Label(frame, text='课堂同传', fg=p['text'], bg=p['bg'], font=(UI_FONT,22)).pack(pady=(0,9))
    tk.Label(frame, text=subtitle, fg=p['muted'], bg=p['bg'], font=(UI_FONT,10)).pack()


def mac_button(parent, text, command, primary=False, compact=False):
    """Rounded controls drawn consistently across Aqua light and dark modes."""
    import tkinter as tk
    from tkinter import font as tkfont

    face = tkfont.Font(family=UI_FONT, size=9 if compact else 12,
                       weight='bold' if primary else 'normal')
    shell = tk.Canvas(parent, bg=parent.cget('bg'), bd=0, highlightthickness=0,
        width=face.measure(text) + (28 if compact else 40), height=30 if compact else 48,
        takefocus=True, cursor='hand2')
    shell.button_font = face
    state = dict(hover=False, pressed=False, focus=False)

    def rounded(x, y, right, bottom, radius, **options):
        fill, outline = options['fill'], options.get('outline', '')
        shell.create_rectangle(x+radius,y,right-radius,bottom,fill=fill,outline='')
        shell.create_rectangle(x,y+radius,right,bottom-radius,fill=fill,outline='')
        corners = ((x,y,x+radius*2,y+radius*2,90),
                   (right-radius*2,y,right,y+radius*2,0),
                   (right-radius*2,bottom-radius*2,right,bottom,270),
                   (x,bottom-radius*2,x+radius*2,bottom,180))
        for left, top, end, low, start in corners:
            shell.create_arc(left,top,end,low,start=start,extent=90,fill=fill,outline='',style='pieslice')
        if outline:
            width = options.get('width', 1)
            for points in ((x+radius,y,right-radius,y),(right,y+radius,right,bottom-radius),
                           (x+radius,bottom,right-radius,bottom),(x,y+radius,x,bottom-radius)):
                shell.create_line(*points,fill=outline,width=width)
            for left, top, end, low, start in corners:
                shell.create_arc(left,top,end,low,start=start,extent=90,outline=outline,width=width,style='arc')

    def draw(_event=None):
        width, height = shell.winfo_width(), shell.winfo_height()
        if width < 8 or height < 8:
            return
        shell.delete('all')
        radius = 8 if compact else 11
        if primary:
            fill = '#005FCC' if state['pressed'] else '#006FE6' if state['hover'] else '#007AFF'
            foreground, border = '#FFFFFF', fill
        else:
            fill = '#E8E8ED' if state['pressed'] else '#F5F5F7' if state['hover'] else '#FFFFFF'
            foreground = '#007AFF' if compact else '#1D1D1F'
            border = '#C5C5CA' if state['hover'] else '#D2D2D7'
        if state['focus']:
            rounded(1,1,width-1,height-1,radius+1,fill='#BFDEFF',outline='')
        rounded(3,3,width-3,height-3,radius,fill=fill,outline=border,width=1)
        shell.create_text(width/2,height/2,text=text,font=face,fill=foreground)

    def update(**changes):
        state.update(changes)
        draw()

    def press(_event):
        shell.focus_set()
        update(pressed=True)
        return 'break'

    def release(event):
        activate = state['pressed'] and 0 <= event.x < shell.winfo_width() and 0 <= event.y < shell.winfo_height()
        update(pressed=False)
        if activate:
            command()
        return 'break'

    def keyboard_activate(_event):
        update(pressed=False)
        command()
        return 'break'

    def space_release(event):
        if state['pressed']:
            return keyboard_activate(event)
        return 'break'

    shell.bind('<Configure>',draw)
    shell.bind('<Enter>',lambda _event: update(hover=True))
    shell.bind('<Leave>',lambda _event: update(hover=False,pressed=False))
    shell.bind('<FocusIn>',lambda _event: update(focus=True))
    shell.bind('<FocusOut>',lambda _event: update(focus=False,pressed=False))
    shell.bind('<ButtonPress-1>',press)
    shell.bind('<ButtonRelease-1>',release)
    shell.bind('<Return>',keyboard_activate)
    shell.bind('<KeyPress-space>',lambda _event: update(pressed=True) or 'break')
    shell.bind('<KeyRelease-space>',space_release)
    return shell


def ui_button(parent, text, command, primary=False):
    if sys.platform == 'darwin':
        return mac_button(parent, text, command, primary)
    import tkinter as tk
    p=PALETTE
    color=p['accent'] if primary else p['card']
    hover='#3f7d63' if primary else '#edf3ec'
    # Keep a real keyboard-accessible Button; the Canvas supplies rounded edges.
    shell=tk.Canvas(parent, bg=parent.cget('bg'), highlightthickness=0, bd=0, cursor='hand2')
    foreground = p['text'] if sys.platform == 'darwin' or not primary else p['bg']
    button=tk.Button(shell, text=text, command=command, font=(UI_FONT,11,'bold' if primary else 'normal'),
        bg=color, fg=foreground, activebackground=hover,
        activeforeground=foreground, relief='flat', bd=0,
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


def request_api_key(root, *, changing=False, save=None):
    import tkinter as tk
    p=PALETTE
    dialog=tk.Toplevel(root)
    title = '更换 API Key' if changing else '首次设置'
    dialog.title(f'青衿学院课堂同传 · {title}')
    prepare_window(dialog, 440, 700 if changing else 650)
    brand_header(dialog, title)
    body=tk.Frame(dialog, bg=p['bg']);body.pack(fill='both', expand=True, padx=30)
    tk.Label(body, text='豆包语音 API Key', fg=p['text'], bg=p['bg'],font=(UI_FONT,11,'bold')).pack(anchor='w', pady=(0,9))
    entry=tk.Entry(body, show='●', bg=p['card'], fg=p['text'], insertbackground=p['accent'], relief='flat', font=(UI_FONT,12), highlightthickness=1, highlightbackground=p['line'], highlightcolor=p['accent'])
    entry.pack(fill='x', ipady=10)
    instructions = ('请填写新的豆包语音 API Key，非火山方舟 ark- Key。\n'
        '保存后自动重启本机服务，当前翻译会中断，历史课程保留。请刷新课堂网页后继续。'
        if changing else '请使用豆包语音新版控制台的 Key，非火山方舟 ark- Key。\n'
        '配置仅保存在本机；翻译需要联网，麦克风授权在浏览器中完成。')
    tk.Label(body,text=instructions,justify='left',wraplength=360,fg=p['muted'],bg=p['bg'],font=(UI_FONT,9)).pack(anchor='w',pady=(12,6))
    error=tk.StringVar()
    tk.Label(body,textvariable=error,fg='#9b4d1d',bg=p['bg'],font=(UI_FONT,9),wraplength=360,justify='left').pack(anchor='w')
    result=[None]
    def submit():
        value=entry.get().strip()
        if not value or value.startswith('ark-') or any(c in value for c in '\r\n\0'):
            error.set('请输入有效的豆包语音 Key，不能使用 ark- Key。');return
        if save is not None:
            try:
                save(value)
            except (OSError, ValueError):
                error.set('保存失败，请检查本机配置目录的写入权限后重试。原来的 Key 未更改。')
                return
        result[0]=value;dialog.destroy()
    ui_button(body,'保存并应用' if changing else '保存并进入课堂',submit,True).pack(fill='x',pady=(12,0))
    if changing:
        ui_button(body,'取消',dialog.destroy).pack(fill='x',pady=(10,0))
    dialog.bind('<Return>',lambda _event:submit())
    dialog.protocol('WM_DELETE_WINDOW',dialog.destroy)
    dialog.grab_set();entry.focus_set();root.wait_window(dialog)
    return result[0]


def build_launcher_ui(root, status, open_classroom, close, change_key):
    import tkinter as tk
    p=PALETTE
    prepare_window(root, 420, 640)
    brand_header(root, '中文与英文，实时字幕')
    card=tk.Frame(root,bg=p['card'],highlightbackground=p['line'],highlightthickness=1)
    card.pack(fill='x',padx=30,pady=(0,16))
    tk.Label(card,text='●  本机课堂服务',fg=p['accent'],bg=p['card'],font=(UI_FONT,10,'bold')).pack(anchor='w',padx=18,pady=(16,7))
    tk.Label(card,textvariable=status,fg=p['text'],bg=p['card'],font=(UI_FONT,10),wraplength=315,justify='left',height=3,anchor='nw').pack(fill='x',padx=18,pady=(0,12))
    body=tk.Frame(root,bg=p['bg']);body.pack(fill='x',padx=30)
    ui_button(body,'开始课堂',open_classroom,True).pack(fill='x')
    ui_button(body,'退出课堂',close).pack(fill='x',pady=(12,0))
    key_button = (mac_button(root,'更换 API Key',change_key,compact=True)
        if sys.platform == 'darwin' else tk.Button(root,text='更换 API Key',command=change_key,font=(UI_FONT,9),
            fg=p['text'],bg=p['bg'],activeforeground=p['text'],relief='flat',bd=0,
            highlightthickness=0,padx=8,pady=4,takefocus=True,cursor='hand2'))
    key_button.place(relx=1.0,x=-18,y=12,anchor='ne')
    if sys.platform != 'darwin':
        key_button.bind('<Return>',lambda _event: change_key() or 'break')
    tk.Label(root,text='本机保存课程文字  ·  不保存录音  ·  翻译依赖网络',fg=p['muted'],bg=p['bg'],font=(UI_FONT,8)).pack(side='bottom',pady=14)


def launch():
    import tkinter as tk
    from tkinter import messagebox
    from backend.config import Settings
    from backend.runtime import configuration_path

    root = tk.Tk()
    root.withdraw()
    root.title('青衿学院课堂同传')

    def save_key(value):
        nonlocal settings
        settings = update_api_key(settings, value, configuration_path())

    listener = None
    try:
        settings = Settings.load()
        if not settings.api_key or settings.api_key.startswith('ark-') or settings.response_mode == 'unverified':
            key = request_api_key(root, save=save_key)
            if key is None:
                root.destroy()
                return 0
        listener = listening_socket(settings.port)
        server = server_for(settings)
    except OSError as error:
        if listener is not None:
            listener.close()
        detail = ('本机端口已被占用。请先退出已打开的课堂同传，再重新启动。'
                  if error.errno == errno.EADDRINUSE else '本机服务无法启动，请检查本机权限或重新安装完整应用后重试。')
        messagebox.showerror('无法启动', detail, parent=root)
        root.destroy()
        return 1
    except Exception:
        if listener is not None:
            listener.close()
        messagebox.showerror('无法启动', '配置或程序资源无法读取。请检查配置，或重新获取完整的程序文件。', parent=root)
        root.destroy()
        return 1

    status = tk.StringVar(value='正在启动本机服务，请稍候…')
    url = f'http://localhost:{settings.port}'
    opened = False
    stopping = False
    restarting = False
    key_changed = False
    thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    deadline = time.monotonic() + 30

    def close():
        nonlocal stopping
        if not stopping and messagebox.askokcancel('退出课堂同传', '退出将停止翻译。已自动保存的课程可在下次打开后查看和导出。请确认页面没有保存失败提示。', parent=root):
            stopping = True
            status.set('正在关闭本机服务，请稍候…')
            server.should_exit = True

    def change_key():
        nonlocal restarting, key_changed
        if stopping or restarting or not server.started:
            return
        key = request_api_key(root, changing=True, save=save_key)
        if key is None or stopping:
            return
        restarting = True
        key_changed = True
        status.set('API Key 已保存，正在重启本机服务，请稍候…')
        server.should_exit = True

    def poll():
        nonlocal opened, stopping, restarting, listener, server, thread, deadline
        if not thread.is_alive():
            listener.close()
            if restarting and not stopping:
                try:
                    listener = listening_socket(settings.port)
                    server = server_for(settings)
                except Exception:
                    listener.close()
                    messagebox.showerror('服务未能重启', '新 API Key 已保存，但本机服务未能重启。请退出后重新打开课堂同传。', parent=root)
                    root.destroy()
                    return
                thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
                deadline = time.monotonic() + 30
                opened = False
                restarting = False
                thread.start()
            else:
                if not stopping:
                    messagebox.showerror('服务已停止', '本机服务未能启动或已异常退出，请重新启动程序。', parent=root)
                root.destroy()
                return
        if not restarting and not server.started and time.monotonic() > deadline:
            stopping = True
            server.should_exit = True
            status.set('启动超时，正在关闭本机服务…')
        if server.started and not opened and not stopping and not restarting:
            opened = True
            if key_changed:
                status.set('API Key 已更换并生效。请刷新课堂网页后继续；历史课程已保留。')
            else:
                status.set('课堂同传已启动。请在浏览器中使用；结束后请点击“退出课堂”。')
                webbrowser.open(url)
        root.after(150, poll)

    build_launcher_ui(root, status, lambda: webbrowser.open(url), close, change_key)
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
