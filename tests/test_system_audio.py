import asyncio
import io
import json
import sys
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from backend.app import create_app
from backend.config import Settings
from backend.protocol import RelayError
from backend import system_audio
from backend.windows_audio import capture as capture_windows


class FakeCapture:
    def __init__(self, device_id=None):
        self.closed = threading.Event()
        self.device_id = device_id
    async def open(self):
        return dict(type='ready', label='test-native', sampleRate=16000)
    async def read(self):
        await asyncio.sleep(.01)
        return b'\0' * 320
    async def close(self):
        self.closed.set()


@pytest.mark.parametrize('origin', [None, 'https://evil.example', 'http://192.168.1.1:8765'])
def test_system_audio_rejects_foreign_origins_before_capture(origin):
    calls = []
    with TestClient(create_app(Settings(), capture_factory=lambda **_: calls.append(True))) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/ws/system-audio', headers={'origin': origin} if origin else {}):
                pass
    assert calls == []


def test_system_audio_stream_single_capture_disconnect_cleanup_and_resume():
    captures = []
    def factory(**options):
        value = FakeCapture(**options)
        captures.append(value)
        return value
    with TestClient(create_app(Settings(), capture_factory=factory)) as client:
        headers = {'origin': 'http://localhost:8765'}
        with client.websocket_connect('/ws/system-audio?device=headphones', headers=headers) as ws:
            assert ws.receive_json()['label'] == 'test-native'
            assert captures[0].device_id == 'headphones'
            ws.send_text('heartbeat')
            assert ws.receive_bytes() == b'\0' * 2560
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect('/ws/system-audio', headers=headers):
                    pass
            ws.send_text('stop')
            with pytest.raises(WebSocketDisconnect):
                while True:
                    ws.receive_bytes()
        assert captures[0].closed.wait(1)
        with client.websocket_connect('/ws/system-audio', headers=headers) as ws:
            assert ws.receive_json()['type'] == 'ready'
        assert captures[1].closed.wait(1)


def test_system_audio_permission_failure_is_actionable_and_releases_slot():
    capture = FakeCapture()
    async def denied():
        raise RelayError('permission', 'allow audio recording')
    capture.open = denied
    with TestClient(create_app(Settings(), capture_factory=lambda **_: capture)) as client:
        with client.websocket_connect('/ws/system-audio', headers={'origin': 'http://localhost:8765'}) as ws:
            assert ws.receive_json() == dict(type='error', message='allow audio recording')
        assert capture.closed.wait(1)


def test_system_audio_close_during_permission_prompt_cancels_startup():
    capture = FakeCapture()
    entered = threading.Event()
    async def waiting():
        entered.set()
        await asyncio.Future()
    capture.open = waiting
    with TestClient(create_app(Settings(), capture_factory=lambda **_: capture)) as client:
        with client.websocket_connect('/ws/system-audio', headers={'origin': 'http://localhost:8765'}):
            assert entered.wait(1)
        assert capture.closed.wait(1)


class Process:
    def __init__(self, header=b'{"type":"ready","sampleRate":16000,"label":"native"}\n'):
        self.stdout = SimpleNamespace(readline=AsyncMock(return_value=header), read=AsyncMock(return_value=b'pcm'))
        self.returncode = None
        self.terminated = False
    def terminate(self):
        self.terminated = True
        self.returncode = 0
    async def wait(self):
        return self.returncode


async def test_windows_worker_launch_has_no_cloud_credentials_and_closes(monkeypatch):
    process = Process()
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(system_audio, 'sys', SimpleNamespace(platform='win32', executable=sys.executable))
    monkeypatch.setattr(system_audio.asyncio, 'create_subprocess_exec', spawn)
    monkeypatch.setenv('VOLC_API_KEY', 'test-only')
    capture = system_audio.SystemAudio()
    assert (await capture.open())['sampleRate'] == 16000
    assert spawn.call_args.args[-1] == 'backend.windows_audio'
    assert 'VOLC_API_KEY' not in spawn.call_args.kwargs['env']
    assert await capture.read() == b'pcm'
    await capture.close()
    assert process.terminated and capture.process is None


async def test_invalid_worker_header_does_not_leave_capture_running(monkeypatch):
    process = Process(b'bad header\n')
    monkeypatch.setattr(system_audio, 'sys', SimpleNamespace(platform='win32', executable=sys.executable))
    monkeypatch.setattr(system_audio.asyncio, 'create_subprocess_exec', AsyncMock(return_value=process))
    capture = system_audio.SystemAudio()
    with pytest.raises(RelayError):
        await capture.open()
    assert process.terminated and capture.process is None


async def test_output_listing_preserves_hardware_names_and_sorts_default_first(monkeypatch):
    devices = [dict(id='speaker', label='MacBook Pro扬声器', isDefault=False),
               dict(id='headphones', label='EDIFIER W830NB', isDefault=True)]
    process = Process()
    process.returncode = 0
    process.communicate = AsyncMock(return_value=(json.dumps(devices).encode(), b''))
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(system_audio, 'sys', SimpleNamespace(platform='win32', executable=sys.executable))
    monkeypatch.setattr(system_audio.asyncio, 'create_subprocess_exec', spawn)
    capture = system_audio.SystemAudio()
    assert [d['label'] for d in await capture.outputs()] == ['EDIFIER W830NB', 'MacBook Pro扬声器']
    assert spawn.call_args.args[-1] == '--list'
    assert capture.process is None


async def test_selected_output_id_is_forwarded_to_native_worker(monkeypatch):
    process = Process()
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(system_audio, 'sys', SimpleNamespace(platform='win32', executable=sys.executable))
    monkeypatch.setattr(system_audio.asyncio, 'create_subprocess_exec', spawn)
    capture = system_audio.SystemAudio(device_id='headphones')
    await capture.open()
    assert spawn.call_args.args[-2:] == ('--device', 'headphones')
    await capture.close()


def test_windows_uses_default_output_loopback_all_channels_and_shared_mode():
    calls = []
    class Recorder:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def record(self, **options):
            calls.append(options)
            raise RuntimeError('test complete')
    def recorder(**options):
        calls.append(options)
        return Recorder()
    def get_microphone(**options):
        calls.append(options)
        return SimpleNamespace(recorder=recorder)
    library = SimpleNamespace(default_speaker=lambda: SimpleNamespace(id='headphones', name='Headphones'), get_microphone=get_microphone)
    output = io.BytesIO()
    with pytest.raises(RuntimeError, match='test complete'):
        capture_windows(library, None, output)
    assert calls == [dict(id='headphones', include_loopback=True),
        dict(samplerate=16000, channels=None, blocksize=1280, exclusive_mode=False), dict(numframes=640)]
    assert json.loads(output.getvalue())['label'] == 'Headphones'

def test_worker_environment_filter_is_case_insensitive_and_excludes_secrets():
    import os

    keep = {
        'PATH', 'HOME', 'TMPDIR', 'TMP', 'TEMP', 'SystemRoot', 'WINDIR',
        'COMSPEC', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'LANG',
    }
    keep_folded = {name.casefold() for name in keep}

    source = {
        'SYSTEMROOT': r'C:\WINDOWS',
        'PATH': r'C:\WINDOWS\System32',
        'VOLC_API_KEY': 'must-not-be-passed',
    }

    environment = {
        key: value
        for key, value in source.items()
        if key.casefold() in keep_folded
    }
    environment['PYTHONIOENCODING'] = 'utf-8'

    assert environment['SYSTEMROOT'] == r'C:\WINDOWS'
    assert environment['PATH'] == r'C:\WINDOWS\System32'
    assert environment['PYTHONIOENCODING'] == 'utf-8'
    assert 'VOLC_API_KEY' not in environment