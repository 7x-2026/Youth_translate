"""Audio-only native capture, streamed to the same-origin browser. Never saves audio."""
import asyncio
import json
import os
import platform
import subprocess
import sys
import time
from contextlib import suppress
from backend.config import ROOT
from backend.protocol import RelayError


class PCMFrames:
    """Bounded PCM16 jitter buffer. An idle output still has a silent timeline."""
    def __init__(self, packet_bytes=2560, max_bytes=16000):
        self.packet_bytes = packet_bytes
        self.max_bytes = max_bytes
        self.pending = bytearray()
        self.dropped = 0

    def push(self, data):
        self.pending.extend(data)
        self.trim(self.max_bytes)

    def trim(self, limit):
        excess = max(0, len(self.pending) - limit)
        # Drop whole samples, retaining alignment even if an IPC read split one.
        count = (excess + 1) // 2 * 2
        if count:
            del self.pending[:count]
            self.dropped += count

    def frame(self):
        size = min(self.packet_bytes, len(self.pending) // 2 * 2)
        packet = bytes(self.pending[:size]) + bytes(self.packet_bytes - size)
        del self.pending[:size]
        dropped, self.dropped = self.dropped, 0
        return packet, dropped


async def paced_audio(capture, clock=time.monotonic, sleep=asyncio.sleep):
    """Send 80 ms frames during OS output inactivity, without masking worker exit.

    Core Audio/WASAPI may stop delivering buffers when nothing is playing. Fill
    that part of the timeline with PCM silence; do not send a fake control ping
    to the cloud or wait until it times out. Real audio resumes on the next frame.
    """
    frames = PCMFrames()
    async def collect():
        while True:
            data = await capture.read()
            if not data:
                raise RelayError('system_audio_ended', '内部音频采集进程已退出，请检查权限或重新连接设备后继续。')
            frames.push(data)

    reader = asyncio.create_task(collect())
    deadline = clock() + .08
    try:
        while True:
            await sleep(max(0, deadline - clock()))
            if reader.done():
                reader.result()
            now = clock()
            if now - deadline >= .16:
                # A stalled consumer must not burst old audio to catch up.
                frames.trim(frames.packet_bytes)
                deadline = now
            deadline += .08
            yield frames.frame()
    finally:
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)


def supported():
    if sys.platform == 'win32':
        return True
    if sys.platform == 'darwin':
        version = tuple(int(x) for x in platform.mac_ver()[0].split('.')[:2])
        return version >= (14, 2)
    return False


async def stop_process(process):
    if process is None:
        return
    if process.returncode is None:
        with suppress(ProcessLookupError):
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), 2)
        except TimeoutError:
            with suppress(ProcessLookupError):
                process.kill()
            await asyncio.wait_for(process.wait(), 2)
    # Drain the pipes before disposing the loop, including cancellation during
    # startup. Waiting for the process alone doesn't release Proactor transports.
    with suppress(TimeoutError, OSError):
        await asyncio.wait_for(process.communicate(), 2)


class SystemAudio:
    def __init__(self, device_id=None):
        self.process = None
        self.device_id = device_id
        self.prepared = False

    async def command(self):
        if not supported():
            raise RelayError('system_audio_unsupported', '电脑内部音频需要 Windows 或 macOS 14.2 及以上版本。')
        if sys.platform == 'darwin':
            from scripts.build_system_audio import BINARY
            source = ROOT / 'native/SystemAudio.swift'
            if not BINARY.exists() or BINARY.stat().st_mtime < source.stat().st_mtime:
                builder = await asyncio.create_subprocess_exec(sys.executable, '-m', 'scripts.build_system_audio',
                    cwd=ROOT, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                try:
                    if await asyncio.wait_for(builder.wait(), 90):
                        raise RelayError('system_audio_build', '本机音频组件构建失败。请安装 Apple Command Line Tools，再运行 python -m scripts.build_system_audio。')
                finally:
                    await stop_process(builder)
            command = [str(BINARY)]
        else:
            command = ([sys.executable, '--audio-worker'] if getattr(sys, 'frozen', False)
                       else [sys.executable, '-u', '-m', 'backend.windows_audio'])
        return command

    async def spawn(self, args, interactive=False):
        command = await self.command()
        # The capture worker has no need for any cloud credentials.
        keep = {
            'PATH', 'HOME', 'TMPDIR', 'TMP', 'TEMP', 'SystemRoot', 'WINDIR',
            'COMSPEC', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'LANG',
        }
        if sys.platform == 'win32' and getattr(sys, 'frozen', False):
            # This is a worker of the same onefile executable. Retain the
            # bootloader's context so it reuses the parent's extracted bundle
            # instead of unpacking the EXE again for every device query.
            keep.update({
                '_PYI_ARCHIVE_FILE', '_PYI_APPLICATION_HOME_DIR',
                '_PYI_PARENT_PROCESS_LEVEL', '_PYI_SPLASH_IPC',
            })
        keep_folded = {name.casefold() for name in keep}

        environment = {
            key: value
            for key, value in os.environ.items()
            if key.casefold() in keep_folded
        }
        environment['PYTHONIOENCODING'] = 'utf-8'
        options = {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)} if sys.platform == 'win32' else {}
        self.process = await asyncio.create_subprocess_exec(*command, *args, cwd=ROOT, env=environment, **options,
            stdin=asyncio.subprocess.PIPE if interactive else asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=65536 if interactive else 16000)

    async def outputs(self, standby=False):
        try:
            if standby:
                await self.spawn(['--list-and-wait'], interactive=True)
                data = await asyncio.wait_for(self.process.stdout.readline(), 30)
            else:
                await self.spawn(['--list'])
                data, _ = await asyncio.wait_for(self.process.communicate(), 30)
            # Cold antivirus scans/imports can exceed ten seconds on Windows.
            if self.process.returncode or len(data) > 65536:
                raise ValueError('output device listing failed')
            devices = json.loads(data)
            if not isinstance(devices, list):
                raise ValueError('invalid devices')
            result = sorted([d for d in devices if isinstance(d, dict) and isinstance(d.get('id'), str)
                and isinstance(d.get('label'), str)], key=lambda d: not d.get('isDefault'))
            self.prepared = standby
            return result
        finally:
            if not self.prepared:
                await self.close()

    async def open(self):
        if self.prepared:
            self.prepared = False
            try:
                if self.process.returncode is not None:
                    raise BrokenPipeError('prepared worker exited')
                self.process.stdin.write((json.dumps({'device': self.device_id})+'\n').encode('utf-8'))
                await self.process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                await self.close()
        if self.process is None:
            await self.spawn(['--device', self.device_id] if self.device_id else [])
        try:
            line = await asyncio.wait_for(self.process.stdout.readline(), 90)
            ready = json.loads(line)
            if not isinstance(ready, dict) or ready.get('type') != 'ready' or ready.get('sampleRate') != 16000:
                raise ValueError('invalid readiness')
            return dict(type='ready', sampleRate=16000, label=ready.get('label', '电脑内部音频'))
        except (ValueError, TimeoutError):
            await self.close()
            raise RelayError('system_audio_permission', '内部音频未能启动。macOS 请允许“系统音频录制”权限；Windows 请运行 uv sync --locked 并检查默认声音输出设备。') from None

    async def read(self):
        return await self.process.stdout.read(2560)

    async def close(self):
        self.prepared = False
        await stop_process(self.process)
        self.process = None


class WindowsAudioStandby:
    """One single-use, non-recording worker; owned by one application lifespan."""
    def __init__(self, factory=SystemAudio, ttl=60, wait_timeout=.25):
        self.factory = factory
        self.ttl = ttl
        self.wait_timeout = wait_timeout
        self.worker = None
        self.pending = None
        self.expiry = None
        self.cleanups = set()
        self.closed = False
        self.disabled = False

    def track(self, task):
        self.cleanups.add(task)
        def finished(value):
            self.cleanups.discard(value)
            if not value.cancelled():
                value.exception()  # Background preparation is optional.
        task.add_done_callback(finished)
        return task

    async def outputs(self):
        if self.closed:
            raise RuntimeError('audio preparation is closed')
        if self.pending is None:
            self.pending = self.track(asyncio.create_task(self.load()))
        return await asyncio.shield(self.pending)

    async def load(self):
        worker = self.factory()
        old, self.worker = self.worker, None
        if self.expiry:
            self.expiry.cancel()
            self.expiry = None
        try:
            if old:
                await old.close()
            devices = await worker.outputs(standby=True)
            if self.closed:
                raise asyncio.CancelledError()
            self.worker = worker
            self.expiry = asyncio.get_running_loop().call_later(self.ttl,
                lambda: self.track(asyncio.create_task(self.expire(worker))))
            return devices
        except BaseException:
            self.disabled = True
            await worker.close()
            raise
        finally:
            self.pending = None

    async def expire(self, expected):
        if self.worker is expected:
            self.worker = None
            self.expiry = None
            await expected.close()

    async def take(self, device_id):
        if self.pending is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self.pending), self.wait_timeout)
            except (OSError, ValueError, TimeoutError, RelayError):
                pass  # A cold start remains available after failed preparation.
        worker, self.worker = self.worker, None
        if self.expiry:
            self.expiry.cancel()
            self.expiry = None
        if worker:
            worker.device_id = device_id
        return worker

    def schedule(self):
        if not self.closed and not self.disabled and self.worker is None and self.pending is None:
            self.track(asyncio.create_task(self.outputs()))

    async def close(self):
        self.closed = True
        if self.expiry:
            self.expiry.cancel()
            self.expiry = None
        if self.pending:
            self.pending.cancel()
        if self.cleanups:
            await asyncio.gather(*tuple(self.cleanups), return_exceptions=True)
        worker, self.worker = self.worker, None
        if worker:
            await worker.close()
