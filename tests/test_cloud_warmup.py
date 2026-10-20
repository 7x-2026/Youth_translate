import asyncio
import pytest
from backend.cloud_warmup import CloudWarmup
from websockets.protocol import State


class Transport:
    def __init__(self,opening=None,closing=None):
        self.opening=opening;self.closing=closing
        self.entered=asyncio.Event();self.exiting=asyncio.Event()
        self.cancelled=False;self.closed=0
    async def __aenter__(self):
        self.entered.set()
        try:
            if self.opening is not None:await self.opening.wait()
            return self
        except asyncio.CancelledError:
            self.cancelled=True;raise
    async def __aexit__(self,*_):
        self.exiting.set()
        if self.closing is not None:await self.closing.wait()
        self.closed+=1


async def test_prepared_transport_is_reused_and_closed_exactly_once():
    calls=[]
    def connect():
        value=Transport();calls.append(value);return value
    warm=CloudWarmup(connect);warm.prepare();warm.prepare();await asyncio.sleep(0)
    async with warm.connection() as transport:
        assert calls==[transport] and transport.closed==0
    await warm.close()
    assert transport.closed==1 and warm.pending is None and warm.expiry is None


async def test_unused_transport_expires_then_a_start_uses_a_new_connection():
    calls=[]
    def connect():
        value=Transport();calls.append(value);return value
    warm=CloudWarmup(connect,ttl=.01);warm.prepare()
    await asyncio.wait_for(asyncio.create_task(wait_until(lambda:calls and calls[0].closed)),1)
    async with warm.connection() as transport:assert transport is calls[1]
    assert all(t.closed==1 for t in calls)


async def wait_until(check):
    while not check():await asyncio.sleep(.001)


async def test_device_failure_cancels_a_pending_cloud_handshake():
    transport=Transport(opening=asyncio.Event());warm=CloudWarmup(lambda:transport)
    warm.prepare();await transport.entered.wait();await warm.close()
    assert transport.cancelled and warm.pending is None and warm.expiry is None


async def test_start_waits_for_expiration_cleanup_before_opening_another_transport():
    release=asyncio.Event();calls=[]
    def connect():
        value=Transport(closing=release if not calls else None);calls.append(value);return value
    warm=CloudWarmup(connect,ttl=.01);warm.prepare()
    await wait_until(lambda:calls);await calls[0].exiting.wait()
    async def start():
        async with warm.connection():pass
    task=asyncio.create_task(start());await asyncio.sleep(0)
    assert len(calls)==1
    release.set();await task
    assert len(calls)==2 and all(t.closed==1 for t in calls)


async def test_cancel_during_handoff_does_not_orphan_the_warm_connection():
    transport=Transport();warm=CloudWarmup(lambda:transport)
    warm.prepare();await transport.entered.wait()
    async def start():
        async with warm.connection():await asyncio.Future()
    task=asyncio.create_task(start());await asyncio.sleep(0);task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    await warm.close();assert transport.closed==1


async def test_failed_handshake_surfaces_at_start_and_is_not_an_unhandled_background_error():
    class Failing(Transport):
        async def __aenter__(self):raise OSError('network unavailable')
    warm=CloudWarmup(Failing);warm.prepare();await asyncio.sleep(0)
    with pytest.raises(OSError,match='network unavailable'):
        async with warm.connection():pass
    await warm.close()

async def test_server_retired_warm_socket_is_replaced_without_using_it():
    calls=[]
    def connect():
        value=Transport();calls.append(value);return value
    warm=CloudWarmup(connect);warm.prepare();await asyncio.sleep(0)
    calls[0].state=State.CLOSED
    async with warm.connection() as ws:assert ws is calls[1]
    assert all(t.closed==1 for t in calls)

async def test_cancel_while_expiration_is_closing_waits_for_cleanup():
    release=asyncio.Event();transport=Transport(closing=release)
    warm=CloudWarmup(lambda:transport,ttl=.01);warm.prepare()
    await transport.exiting.wait()
    async def start():
        async with warm.connection():pass
    task=asyncio.create_task(start());await asyncio.sleep(0);task.cancel();await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):await task
    assert transport.closed==1
