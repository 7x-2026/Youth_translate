import asyncio
import pytest
from backend.protocol import RelayError
from backend.system_audio import PCMFrames, paced_audio


class Clock:
    now = 0.
    def time(self): return self.now
    async def sleep(self, delay):
        self.now += delay
        await asyncio.sleep(0)


class Capture:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.cancelled = False
    async def read(self):
        try:
            return await self.queue.get()
        except asyncio.CancelledError:
            self.cancelled = True
            raise


async def test_ten_minutes_without_os_buffers_preserves_timeline_then_resumes_real_audio():
    clock, capture = Clock(), Capture()
    stream = paced_audio(capture, clock.time, clock.sleep)
    silence = bytes(2560)
    for _ in range(7500):
        packet, dropped = await anext(stream)
        assert packet == silence and dropped == 0
    assert clock.now == pytest.approx(600)
    # A voice/music block arriving after the long pause is delivered exactly once.
    audio = b'\x00\x40' * 1280
    capture.queue.put_nowait(audio)
    assert await anext(stream) == (audio, 0)
    assert await anext(stream) == (silence, 0)
    await stream.aclose()
    assert capture.cancelled


def test_partial_pcm_samples_remain_aligned_across_silent_ticks():
    frames = PCMFrames(packet_bytes=8)
    frames.push(b'\x01')
    assert frames.frame() == (bytes(8), 0)
    frames.push(b'\x02\x03\x04')
    assert frames.frame() == (b'\x01\x02\x03\x04' + bytes(4), 0)
    assert frames.frame() == (bytes(8), 0)


def test_jitter_buffer_is_bounded_and_drops_whole_old_samples():
    frames = PCMFrames(packet_bytes=4, max_bytes=8)
    frames.push(bytes(range(11)))
    assert len(frames.pending) <= 8
    assert frames.frame() == (bytes(range(4, 8)), 4)
    frames.push(b'\x0b')
    assert frames.frame() == (bytes(range(8, 12)), 0)


async def test_stalled_consumer_skips_stale_audio_and_never_bursts_to_catch_up():
    clock, capture = Clock(), Capture()
    stream = paced_audio(capture, clock.time, clock.sleep)
    await anext(stream)
    capture.queue.put_nowait(b'\x01\0'*1280 + b'\x02\0'*1280 + b'\x03\0'*1280)
    clock.now += 2
    assert await anext(stream) == (b'\x03\0'*1280, 5120)
    resumed_at = clock.now
    assert await anext(stream) == (bytes(2560), 0)
    assert clock.now - resumed_at == pytest.approx(.08)
    await stream.aclose()


async def test_worker_exit_stops_instead_of_filling_silence_forever():
    clock, capture = Clock(), Capture()
    stream = paced_audio(capture, clock.time, clock.sleep)
    capture.queue.put_nowait(b'')
    with pytest.raises(RelayError, match='进程已退出'):
        await anext(stream)


async def test_worker_failure_propagates_even_during_silence():
    clock = Clock()
    class Broken:
        async def read(self): raise OSError('device disconnected')
    stream = paced_audio(Broken(), clock.time, clock.sleep)
    with pytest.raises(OSError, match='device disconnected'):
        await anext(stream)
