import json
import threading
import time
from types import SimpleNamespace
from urllib.request import ProxyHandler, build_opener

import pytest
from dotenv import dotenv_values

import desktop_launcher
from backend.config import Settings
from backend.records import RecordStore


@pytest.mark.parametrize('cancel', [False, True])
def test_launcher_applies_new_key_only_after_save_and_old_service_exit(tmp_path, monkeypatch, cancel):
    servers, listeners, actions, browser_calls = [], [], {}, []
    config_path = tmp_path / 'config.env'
    desktop_launcher.save_configuration('previous-test-key', config_path)

    class Status:
        def __init__(self, value): self.value = value
        def set(self, value): self.value = value

    class Root:
        def withdraw(self): pass
        def title(self, value): pass
        def protocol(self, *args): pass
        def deiconify(self): pass
        def after(self, delay, callback): actions['poll'] = callback
        def destroy(self): actions['destroyed'] = True
        def mainloop(self):
            actions['poll']()
            assert browser_calls == ['http://localhost:8765']
            actions['change_key']()
            actions['poll']()
            if cancel:
                assert len(servers) == 1
                assert not servers[0].should_exit
                assert dotenv_values(config_path)['VOLC_API_KEY'] == 'previous-test-key'
            else:
                assert len(servers) == 2
                assert servers[0].should_exit and listeners[0].closed
                assert servers[1].settings.api_key == 'replacement-test-key'
                assert dotenv_values(config_path)['VOLC_API_KEY'] == 'replacement-test-key'
                assert '已更换并生效' in actions['status'].value
                assert len(browser_calls) == 1  # Refresh the existing page, without duplicate course tabs.
            actions['close']()
            actions['poll']()
            assert actions['destroyed']

    class Thread:
        def __init__(self, target, **kwargs): self.server = target.__self__
        def start(self): self.server.started = True
        def is_alive(self): return self.server.started and not self.server.should_exit
        def join(self, timeout): assert self.server.should_exit

    class Server:
        started = False
        should_exit = False
        def run(self): pass

    def listener(port):
        assert not listeners or listeners[-1].closed
        item = SimpleNamespace(closed=False)
        item.close = lambda: setattr(item, 'closed', True)
        listeners.append(item)
        return item

    def server(settings):
        item = Server()
        item.settings = settings
        servers.append(item)
        return item

    def build(root, status, open_classroom, close, change_key):
        actions.update(status=status, close=close, change_key=change_key)

    def dialog(root, *, changing, save):
        assert changing
        if cancel: return None
        save('replacement-test-key')
        return 'replacement-test-key'

    def unexpected_error(*args, **kwargs):
        pytest.fail(f'Unexpected launcher error: {args[0]}')

    monkeypatch.setitem(__import__('sys').modules, 'tkinter', SimpleNamespace(Tk=Root, StringVar=Status,
        messagebox=SimpleNamespace(askokcancel=lambda *args, **kwargs: True, showerror=unexpected_error)))
    monkeypatch.setattr(Settings, 'load', classmethod(lambda cls: Settings(api_key='previous-test-key', response_mode='delta')))
    monkeypatch.setattr('backend.runtime.configuration_path', lambda: config_path)
    monkeypatch.setattr(desktop_launcher, 'listening_socket', listener)
    monkeypatch.setattr(desktop_launcher, 'server_for', server)
    monkeypatch.setattr(desktop_launcher.threading, 'Thread', Thread)
    monkeypatch.setattr(desktop_launcher, 'request_api_key', dialog)
    monkeypatch.setattr(desktop_launcher, 'build_launcher_ui', build)
    monkeypatch.setattr(desktop_launcher.webbrowser, 'open', lambda url: browser_calls.append(url))
    assert desktop_launcher.launch() == 0
    assert all(item.closed for item in listeners)


def test_real_http_service_restarts_on_same_port_with_new_key_and_saved_courses(tmp_path):
    path = tmp_path / 'records.sqlite3'
    initial = RecordStore(path)
    initial.save_event(dict(type='subtitle', classId='saved-course', sessionEpoch=1,
        channel='source', segmentId='one', revision=1, text='saved course fixture', isFinal=True))
    initial.close()
    port = 0
    opener = build_opener(ProxyHandler({}))
    for key in ('', 'replacement-test-key'):
        listener = desktop_launcher.listening_socket(port)
        port = listener.getsockname()[1]
        records = RecordStore(path)
        server = desktop_launcher.server_for(Settings(api_key=key, response_mode='delta', port=port), record_store=records)
        thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                assert thread.is_alive() and time.monotonic() < deadline
                time.sleep(.01)
            with opener.open(f'http://127.0.0.1:{port}/api/health', timeout=5) as response:
                health = json.load(response)
            assert health['credentialsConfigured'] == bool(key)
            assert health['activeSessions'] == 0
            with opener.open(f'http://127.0.0.1:{port}/api/records/saved-course', timeout=5) as response:
                assert json.load(response)['entries'][0]['text'] == 'saved course fixture'
        finally:
            server.should_exit = True
            thread.join(10)
            listener.close()
            records.close()
        assert not thread.is_alive()
