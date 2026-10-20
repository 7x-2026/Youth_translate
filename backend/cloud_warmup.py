"""A short-lived authenticated transport. Does not send StartSession or audio."""
import asyncio
from contextlib import asynccontextmanager
from websockets.protocol import State


class CloudWarmup:
    def __init__(self, connect, ttl=5):
        self.connect=connect
        self.ttl=ttl
        self.pending=None
        self.expiry=None

    def prepare(self):
        if self.pending is not None or self.expiry is not None:return
        self.pending=asyncio.create_task(self.open())
        self.expiry=asyncio.create_task(self.expire(self.pending))

    async def open(self):
        context=self.connect()
        return context, await context.__aenter__()

    async def dispose(self, task):
        if not task.done():task.cancel()
        result=(await asyncio.gather(task,return_exceptions=True))[0]
        if isinstance(result,tuple):
            context,_=result
            try:await context.__aexit__(None,None,None)
            except Exception:pass  # Unused transport cleanup cannot block start/stop.

    async def expire(self, task):
        await asyncio.sleep(self.ttl)
        if self.pending is task:
            self.pending=None
            try:await self.dispose(task)
            finally:
                if self.expiry is asyncio.current_task():self.expiry=None

    async def take(self):
        # No await between taking these references: expiration or this caller
        # owns cleanup, never both. Wait for any expiration already closing.
        task,expiry=self.pending,self.expiry
        self.pending=self.expiry=None
        try:
            if task is not None and expiry is not None:
                expiry.cancel()
                await asyncio.gather(expiry,return_exceptions=True)
            elif expiry is not None:
                await asyncio.shield(expiry)
        except asyncio.CancelledError:
            if task is not None:await asyncio.shield(self.dispose(task))
            elif expiry is not None:await asyncio.shield(expiry)
            raise
        return task

    async def close(self):
        task=await self.take()
        if task is not None:await self.dispose(task)

    @asynccontextmanager
    async def connection(self):
        task=await self.take()
        if task is None:
            async with self.connect() as ws:yield ws
            return
        try:
            context,ws=await task
        except asyncio.CancelledError:
            await self.dispose(task)
            raise
        if getattr(ws,'state',State.OPEN)!=State.OPEN:
            # A server may retire an idle socket before its local lease ends.
            # Open a fresh socket directly instead of entering recovery backoff.
            await context.__aexit__(None,None,None)
            async with self.connect() as ws:yield ws
            return
        try:yield ws
        finally:await context.__aexit__(None,None,None)
