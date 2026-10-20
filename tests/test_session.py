import asyncio
import pytest
from backend.config import Settings
from backend.session import Session,AudioQueue,MAX_QUEUE_BYTES
from backend.protocol import E,RelayError
from backend.generated.products.understanding.ast.ast_service_pb2 import TranslateRequest,TranslateResponse

class FakeCloud:
    def __init__(self, fail=False, start_ready=True):
        self.frames=[];self.responses=asyncio.Queue();self.fail=fail;self.start_ready=start_ready;self.closed=False
    async def __aenter__(self):return self
    async def __aexit__(self,*args):self.closed=True
    async def send(self,frame):
        r=TranslateRequest.FromString(frame);self.frames.append(r)
        if r.event==E.StartSession and self.start_ready:
            response=TranslateResponse(event=E.SessionStarted)
            if self.fail:response.event=E.SessionFailed;response.response_meta.StatusCode=45000001
            self.responses.put_nowait(response.SerializeToString())
        if r.event==E.FinishSession:
            self.responses.put_nowait(TranslateResponse(event=E.TranslationSubtitleEnd,text='last sentence').SerializeToString())
            self.responses.put_nowait(TranslateResponse(event=E.SessionFinished).SerializeToString())
    async def recv(self):return await self.responses.get()
    def __aiter__(self):return self
    async def __anext__(self):return await self.recv()

async def until(check):
    async with asyncio.timeout(2):
        while not check():await asyncio.sleep(.005)

def setup(cloud):
    events=[]
    async def emit(event):events.append(event)
    session=Session(Settings(api_key='test-only',response_mode='snapshot'),emit,lambda *a,**k:cloud)
    return session,events

async def test_start_idempotent_wait_for_ready_and_tail_finish():
    cloud=FakeCloud();s,events=setup(cloud)
    await s.audio(b'\0'*2560)
    await s.start();await s.start();await until(lambda:s.state=='running')
    assert len([r for r in cloud.frames if r.event==E.StartSession])==1
    await s.audio(b'\0'*2560);await s.audio(b'\0'*80)
    await s.end();await s.audio(b'\0'*2560)
    assert [r.event for r in cloud.frames]==[E.StartSession,E.TaskRequest,E.TaskRequest,E.FinishSession]
    assert any(e.get('text')=='last sentence' and e['isFinal'] for e in events)
    assert s.state=='stopped' and cloud.closed

async def test_pause_during_connect_cancels_and_no_upload():
    cloud=FakeCloud(start_ready=False);s,_=setup(cloud)
    await s.start();await until(lambda:len(cloud.frames)>0);await s.audio(b'\0'*2560);await s.end(pause=True)
    assert s.state=='paused' and cloud.closed and s.queue.bytes==0
    assert len(cloud.frames)==1 and s.task.done()

async def test_fatal_error_never_retries():
    cloud=FakeCloud(fail=True);s,events=setup(cloud)
    await s.start();await until(lambda:s.state=='error')
    assert not s.wanted and len(cloud.frames)==1
    assert any(e.get('retryable') is False for e in events)

async def test_pause_cancels_network_backoff():
    events=[];calls=0
    async def emit(e):events.append(e)
    def connect(*a,**k):
        nonlocal calls;calls+=1;raise OSError('offline')
    s=Session(Settings(api_key='test-only',response_mode='snapshot'),emit,connect)
    await s.start();await until(lambda:s.state=='recovering');await s.end(pause=True)
    await asyncio.sleep(.6);assert calls==1 and not s.wanted

async def test_resume_retains_class_increments_epoch():
    clouds=[]
    def connect(*a,**k):
        cloud=FakeCloud();clouds.append(cloud);return cloud
    async def emit(_):pass
    s=Session(Settings(api_key='test-only',response_mode='snapshot'),emit,connect)
    await s.start(class_id='class',epoch=8);await until(lambda:s.state=='running');await s.end(pause=True)
    await s.start('en-zh',resume=True);await until(lambda:s.state=='running');assert s.class_id=='class' and s.epoch==10
    assert clouds[-1].frames[0].request.source_language=='en';await s.end()

async def test_queue_bound_keeps_newest():
    q=AudioQueue();drops=0
    for i in range(100):drops+=q.push(bytes([i])*2560)
    assert q.bytes<=MAX_QUEUE_BYTES and drops>0
    values=[]
    while not q.items.empty():values.append((await q.get())[0])
    assert values[-1]==99 and values[0]>0

async def test_missing_credentials_and_semantics_no_connection():
    async def emit(_):pass
    for settings in [Settings(),Settings(api_key='test-only')]:
        s=Session(settings,emit)
        with pytest.raises(RelayError):await s.start()
        assert s.task is None

async def test_stop_honors_five_second_finalization_deadline():
    class NeverFinishes(FakeCloud):
        async def send(self, frame):
            r=TranslateRequest.FromString(frame)
            if r.event==E.FinishSession:self.frames.append(r)
            else:await super().send(frame)
    cloud=NeverFinishes();s,events=setup(cloud)
    await s.start();await until(lambda:s.state=='running')
    begin=asyncio.get_running_loop().time();await s.end()
    elapsed=asyncio.get_running_loop().time()-begin
    assert 4.9<=elapsed<6 and cloud.closed and s.state=='stopped'
    assert any('收尾超时' in e.get('detail','') for e in events)

async def test_fresh_start_after_pause_resets_class():
    clouds=[]
    def connect(*a,**k):
        cloud=FakeCloud();clouds.append(cloud);return cloud
    async def emit(_):pass
    s=Session(Settings(api_key='test-only',response_mode='snapshot'),emit,connect)
    await s.start(class_id='first');await until(lambda:s.state=='running');await s.end(pause=True)
    await s.start(class_id='second');await until(lambda:s.state=='running')
    assert s.class_id=='second' and s.epoch==1
    await s.end()

async def test_ark_key_refused_before_upstream_connect():
    attempts=0
    def connector(*_a,**_kw):
        nonlocal attempts; attempts+=1
    async def emit(_):pass
    s=Session(Settings(api_key='ark-example',response_mode='snapshot'),emit,connector)
    with pytest.raises(RelayError) as error:await s.start()
    assert error.value.code=='wrong_key_type' and attempts==0

def test_resource_not_granted_has_actionable_message():
    from backend.session import classify
    from websockets.exceptions import InvalidStatus
    from websockets.http11 import Response
    from websockets.datastructures import Headers
    response=Response(403,'Forbidden',Headers(),b'{"error":"[resource_id=volc.service_type.10053] requested resource not granted"}')
    error=classify(InvalidStatus(response))
    assert error.code=='resource_not_granted' and not error.retryable
    assert '同声传译2.0' in error.message

async def test_prepare_does_not_send_session_or_audio_until_capture_is_ready():
    cloud=FakeCloud();s,events=setup(cloud)
    s.prepare();await until(lambda:s.cloud_warmup.pending.done())
    assert cloud.frames==[] and not s.wanted and s.state=='idle'
    await s.start();await until(lambda:s.state=='running')
    assert [r.event for r in cloud.frames]==[E.StartSession]
    await s.end();assert cloud.closed

async def test_prepare_without_valid_config_never_opens_a_cloud_connection():
    calls=[]
    async def emit(_):pass
    for settings in (Settings(),Settings(api_key='ark-test-only',response_mode='delta'),Settings(api_key='test-only')):
        s=Session(settings,emit,lambda *a,**k:calls.append(True))
        s.prepare();await asyncio.sleep(0);assert s.cloud_warmup.pending is None
        await s.end(immediate=True)
    assert calls==[]
