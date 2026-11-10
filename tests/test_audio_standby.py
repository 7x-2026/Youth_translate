"""Single-use Windows preparation must never start capture before user intent."""
import asyncio
import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from backend import system_audio, windows_audio


class IdleWorker:
    def __init__(self):
        self.device_id = None
        self.closed = False
        self.opened = False
    async def outputs(self, standby=False):
        assert standby
        return [dict(id='headphones', label='Headphones', isDefault=True)]
    async def close(self):
        self.closed = True


async def test_concurrent_listing_and_start_share_one_non_recording_worker():
    entered, release = asyncio.Event(), asyncio.Event()
    workers = []
    class SlowWorker(IdleWorker):
        async def outputs(self, standby=False):
            entered.set()
            await release.wait()
            return await super().outputs(standby)
    def factory():
        worker = SlowWorker()
        workers.append(worker)
        return worker
    pool = system_audio.WindowsAudioStandby(factory, ttl=.03)
    try:
        first = asyncio.create_task(pool.outputs())
        await entered.wait()
        second = asyncio.create_task(pool.outputs())
        start = asyncio.create_task(pool.take('selected-device'))
        release.set()
        assert await first == await second
        worker = await start
        assert len(workers) == 1 and worker is workers[0]
        assert worker.device_id == 'selected-device' and not worker.opened
        await asyncio.sleep(.06)
        assert not worker.closed  # Expiry cannot kill a handed-off capture.
        assert await pool.take(None) is None  # Single-use ownership.
    finally:
        await pool.close()
        await workers[0].close()


async def test_unused_worker_expires_and_shutdown_cancels_pending_preparation():
    worker = IdleWorker()
    pool = system_audio.WindowsAudioStandby(lambda: worker, ttl=.01)
    await pool.outputs()
    await asyncio.sleep(.05)
    assert worker.closed and await pool.take(None) is None
    await pool.close()

    entered = asyncio.Event()
    class PendingWorker(IdleWorker):
        async def outputs(self, standby=False):
            entered.set()
            await asyncio.Future()
    worker = PendingWorker()
    pool = system_audio.WindowsAudioStandby(lambda: worker)
    listing = asyncio.create_task(pool.outputs())
    await entered.wait()
    await pool.close()
    with pytest.raises(asyncio.CancelledError):
        await listing
    assert worker.closed and pool.worker is None


async def test_cancelled_request_keeps_preparation_available_and_failure_allows_cold_start():
    release, entered = asyncio.Event(), asyncio.Event()
    class WaitingWorker(IdleWorker):
        async def outputs(self, standby=False):
            entered.set()
            await release.wait()
            return await super().outputs(standby)
    worker = WaitingWorker()
    pool = system_audio.WindowsAudioStandby(lambda: worker)
    listing = asyncio.create_task(pool.outputs())
    await entered.wait()
    listing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await listing
    assert not worker.closed
    release.set()
    assert await pool.take(None) is worker
    await pool.close()
    await worker.close()

    class FailedWorker(IdleWorker):
        async def outputs(self, standby=False):
            raise OSError('test startup failure')
    failed = FailedWorker()
    pool = system_audio.WindowsAudioStandby(lambda: failed)
    pool.schedule()
    await asyncio.sleep(0)
    assert await pool.take(None) is None
    assert failed.closed
    await pool.close()


@pytest.mark.parametrize('command,expected', [
    (b'', None),
    (b'{"device":null}\n', [None]),
    (b'{"device":"chosen-headphones"}\n', ['chosen-headphones']),
    ((json.dumps({'device':'USB 耳机 🎧 "quoted"'})+'\n').encode(), ['USB 耳机 🎧 "quoted"']),
    (b'{"device":""}\n', False),
    (b'{"device":123}\n', False),
    (b'{"device":null,"extra":true}\n', False),
    (b'x'*16385, False),
])
def test_worker_waits_for_one_valid_command_before_opening_capture(monkeypatch, command, expected):
    import sys
    output = io.BytesIO()
    opened = []
    speaker = SimpleNamespace(id='headphones', name='Headphones')
    card = SimpleNamespace(default_speaker=lambda: speaker, all_speakers=lambda: [speaker])
    class Input(io.BytesIO):
        def readline(self, *args):
            assert not opened
            assert json.loads(output.getvalue())[0]['id'] == 'headphones'
            return super().readline(*args)
    monkeypatch.setitem(sys.modules, 'soundcard', card)
    monkeypatch.setitem(sys.modules, 'numpy', SimpleNamespace())
    monkeypatch.setattr(windows_audio, 'sys', SimpleNamespace(
        stdin=SimpleNamespace(buffer=Input(command)), stdout=SimpleNamespace(buffer=output)))
    monkeypatch.setattr(windows_audio, 'capture', lambda _card, _np, _out, device: opened.append(device))
    result = windows_audio.main(['--list-and-wait'])
    assert result == (2 if expected is False else 0)
    assert opened == (expected if isinstance(expected, list) else [])


async def test_prepared_capture_sends_selected_device_without_spawning_again(monkeypatch):
    process = SimpleNamespace(returncode=None, stdin=SimpleNamespace(write=Mock(), drain=AsyncMock()),
        stdout=SimpleNamespace(readline=AsyncMock(return_value=b'{"type":"ready","sampleRate":16000}\n')))
    capture = system_audio.SystemAudio('selected')
    capture.process, capture.prepared = process, True
    capture.spawn = AsyncMock()
    monkeypatch.setattr(system_audio, 'stop_process', AsyncMock())
    assert (await capture.open())['type'] == 'ready'
    assert json.loads(process.stdin.write.call_args.args[0]) == {'device': 'selected'}
    capture.spawn.assert_not_awaited()
    await capture.close()
    assert capture.process is None and not capture.prepared


async def test_dead_prepared_worker_falls_back_to_original_launch(monkeypatch):
    dead = SimpleNamespace(returncode=2)
    live = SimpleNamespace(stdout=SimpleNamespace(readline=AsyncMock(
        return_value=b'{"type":"ready","sampleRate":16000}\n')))
    capture = system_audio.SystemAudio('selected')
    capture.process, capture.prepared = dead, True
    async def spawn(args):
        assert args == ['--device', 'selected']
        capture.process = live
    capture.spawn = AsyncMock(side_effect=spawn)
    stop = AsyncMock()
    monkeypatch.setattr(system_audio, 'stop_process', stop)
    assert (await capture.open())['type'] == 'ready'
    stop.assert_awaited_once_with(dead)
    capture.spawn.assert_awaited_once()
    await capture.close()


def test_app_pause_resume_and_shutdown_release_each_single_use_worker(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from backend import app as app_module
    from backend.config import Settings
    from backend.records import RecordStore
    workers = []
    class CaptureWorker(IdleWorker):
        async def open(self):
            self.opened = True
            return dict(type='ready', sampleRate=16000, label=self.device_id)
        async def read(self):
            await asyncio.sleep(.01)
            return b'\0'*320
    def factory():
        worker = CaptureWorker()
        workers.append(worker)
        return worker
    pool = system_audio.WindowsAudioStandby(factory)
    monkeypatch.setattr(app_module, 'sys', SimpleNamespace(platform='win32'))
    monkeypatch.setattr(app_module, 'WindowsAudioStandby', lambda: pool)
    app = app_module.create_app(Settings(), record_store=RecordStore(tmp_path/'records.sqlite3'))
    with TestClient(app) as client:
        for device in ('first', 'second', 'third'):
            assert client.get('/api/audio-outputs').status_code == 200
            with client.websocket_connect(f'/ws/system-audio?device={device}',
                    headers={'origin':'http://localhost:8765'}) as ws:
                assert ws.receive_json()['label'] == device
                assert ws.receive_bytes() == b'\0'*2560
                ws.send_text('stop')
                with pytest.raises(WebSocketDisconnect):
                    while True:
                        ws.receive_bytes()
    assert pool.closed and all(worker.closed for worker in workers)
    assert sum(worker.opened for worker in workers) == 3


def test_app_cancel_while_preparing_does_not_start_late_capture(monkeypatch, tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from backend import app as app_module
    from backend.config import Settings
    from backend.records import RecordStore
    entered, release = threading.Event(), threading.Event()
    worker = IdleWorker()
    async def wait_for_list(standby=False):
        entered.set()
        while not release.is_set():
            await asyncio.sleep(.005)
        return []
    worker.outputs = wait_for_list
    worker.open = AsyncMock(side_effect=AssertionError('Cancelled capture must not open'))
    pool = system_audio.WindowsAudioStandby(lambda: worker)
    monkeypatch.setattr(app_module, 'sys', SimpleNamespace(platform='win32'))
    monkeypatch.setattr(app_module, 'WindowsAudioStandby', lambda: pool)
    app = app_module.create_app(Settings(), record_store=RecordStore(tmp_path/'records.sqlite3'))
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        listing = executor.submit(client.get, '/api/audio-outputs')
        try:
            assert entered.wait(3)
            with client.websocket_connect('/ws/system-audio', headers={'origin':'http://localhost:8765'}) as ws:
                ws.send_text('stop')
                with pytest.raises(WebSocketDisconnect):
                    ws.receive_json()
        finally:
            release.set()
        assert listing.result(timeout=3).status_code == 200
        worker.open.assert_not_awaited()
    assert worker.closed


async def test_slow_preparation_does_not_hold_up_the_original_capture_path():
    entered, release = asyncio.Event(), asyncio.Event()
    class SlowWorker(IdleWorker):
        async def outputs(self, standby=False):
            entered.set()
            await release.wait()
            return []
    worker = SlowWorker()
    pool = system_audio.WindowsAudioStandby(lambda: worker, wait_timeout=.01)
    listing = asyncio.create_task(pool.outputs())
    try:
        await entered.wait()
        assert await pool.take('selected') is None
        assert not worker.closed and not listing.done()
        release.set()
        await listing
        assert await pool.take('selected') is worker
    finally:
        await pool.close()
        await worker.close()


def test_failed_preparation_keeps_ordinary_listing_and_disables_optional_optimization(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from backend import app as app_module
    from backend.config import Settings
    from backend.records import RecordStore
    calls = []
    class UnsupportedWorker(IdleWorker):
        async def outputs(self, standby=False):
            calls.append('prepare')
            raise OSError('optional mode unavailable')
    pool = system_audio.WindowsAudioStandby(UnsupportedWorker)
    normal = AsyncMock(return_value=[dict(id='normal', label='USB 音箱')])
    monkeypatch.setattr(app_module, 'sys', SimpleNamespace(platform='win32'))
    monkeypatch.setattr(app_module, 'WindowsAudioStandby', lambda: pool)
    monkeypatch.setattr(system_audio.SystemAudio, 'outputs', normal)
    app = app_module.create_app(Settings(), record_store=RecordStore(tmp_path/'records.sqlite3'))
    with TestClient(app) as client:
        for _ in range(2):
            assert client.get('/api/audio-outputs').json()['devices'][0]['id'] == 'normal'
        assert pool.disabled and calls == ['prepare']
        assert normal.await_count == 2
