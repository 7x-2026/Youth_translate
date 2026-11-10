import asyncio
from types import SimpleNamespace

import pytest

from backend import session as module
from backend.config import Settings
from backend.protocol import RelayError
from backend.session import Session, MAX_QUEUE_BYTES, next_audio_deadline


def local_session(monkeypatch):
    now=[10.]
    monkeypatch.setattr(module,'time',SimpleNamespace(monotonic=lambda:now[0]))
    events=[]
    async def emit(event):events.append(event)
    session=Session(Settings(),emit)
    session.wanted=True;session.state='running'
    return session,now,events


async def test_short_burst_drops_stale_audio_without_ending_session(monkeypatch):
    session,now,events=local_session(monkeypatch)
    for _ in range(40):await session.audio(bytes(2560))
    assert session.wanted and session.state=='running'
    assert session.audio_diagnostics.rate_dropped_bytes>0
    assert session.queue.bytes<=MAX_QUEUE_BYTES
    assert len([event for event in events if event.get('gap')])==1
    now[0]+=.08
    await session.audio(bytes(2560))
    assert session.queue.bytes==2560


async def test_sustained_extreme_overrun_still_hits_the_hard_limit(monkeypatch):
    session,_,_=local_session(monkeypatch)
    with pytest.raises(RelayError) as error:
        for _ in range(200):await session.audio(bytes(2560))
    assert error.value.code=='rate_limit'
    assert len(session.rate_overruns)<=126 and session.queue.bytes<=MAX_QUEUE_BYTES


async def test_normal_stream_does_not_overrun(monkeypatch):
    session,now,_=local_session(monkeypatch)
    for _ in range(1000):
        now[0]+=.08
        await session.audio(bytes(2560))
        session.queue.clear()
    assert session.audio_diagnostics.rate_dropped_bytes==0
    assert session.wanted


async def test_cloud_sender_spaces_queued_packets_instead_of_bursting():
    times=[]
    async def emit(_):pass
    class Cloud:
        async def send(self,_):times.append(asyncio.get_running_loop().time())
    session=Session(Settings(),emit)
    session.finish.set()
    for _ in range(3):session.queue.push(bytes(2560))
    await session.sender(Cloud(),'test-local-no-cloud')
    assert len(times)==4
    assert times[1]-times[0]>=.07 and times[2]-times[1]>=.07


@pytest.mark.parametrize('duration',[.04,.08])
def test_cloud_clock_does_not_accumulate_small_jitter_over_two_virtual_hours(duration):
    deadline=0.
    count=round(7200/duration)
    for _ in range(count):
        sent_at=deadline+.002
        deadline=next_audio_deadline(deadline,sent_at,duration)
    assert deadline==pytest.approx(7200,abs=1e-6)


def test_cloud_clock_caps_compensation_and_resets_after_long_stall():
    assert next_audio_deadline(1.,1.03,.08)==pytest.approx(1.102)
    assert next_audio_deadline(1.,3.,.08)==pytest.approx(3.08)
