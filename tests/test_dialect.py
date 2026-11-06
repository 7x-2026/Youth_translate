import asyncio
import base64
import hashlib
import hmac
import json
from dataclasses import replace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend import dialect
from backend.app import create_app
from backend.config import Settings
from backend.dialect import DialectSession, asr_message, asr_url, translation_target
from backend.protocol import RelayError


def configured():
    return Settings(tencent_app_id='12345', tencent_secret_id='test-id',
                    tencent_secret_key='test-secret', tokenhub_api_key='test-token')


def result(index=0, kind=2, text='课堂测试'):
    return dict(code=0, result=dict(index=index, slice_type=kind, voice_text_str=text))


class Cloud:
    def __init__(self, events=()):
        self.responses = asyncio.Queue()
        self.responses.put_nowait(json.dumps(dict(code=0, message='success')))
        self.events, self.frames, self.closed = list(events), [], False
    async def __aenter__(self): return self
    async def __aexit__(self, *_): self.closed = True
    async def recv(self): return await self.responses.get()
    async def send(self, data):
        self.frames.append(data)
        if isinstance(data, bytes) and self.events:
            for event in self.events: self.responses.put_nowait(json.dumps(event))
            self.events = []
        if isinstance(data, str): self.responses.put_nowait(json.dumps(dict(code=0, final=1)))
    def __aiter__(self): return self
    async def __anext__(self): return await self.recv()


async def until(check):
    async with asyncio.timeout(2):
        while not check(): await asyncio.sleep(.005)


def session(cloud, translator=None):
    events, calls = [], []
    async def emit(event): events.append(event)
    async def translate(_settings, text, target):
        calls.append((text, target)); return 'Classroom test.'
    value = DialectSession(configured(), emit, connector=lambda *a, **k: cloud,
                           translator=translator or translate)
    return value, events, calls


def test_asr_signature_percent_encoding_and_fixed_nonpreview_engine():
    url = asr_url(configured(), 'voice-123', now=1700000000, nonce=42)
    parts = urlsplit(url); query = parse_qs(parts.query)
    signature = query.pop('signature')[0]
    canonical = parts.netloc+parts.path+'?'+'&'.join(f'{key}={query[key][0]}' for key in sorted(query))
    expected = base64.b64encode(hmac.new(b'test-secret', canonical.encode(), hashlib.sha1).digest()).decode()
    assert signature == expected and query['engine_model_type'] == ['16k_zh_en']
    assert query['voice_format'] == ['1'] and query['expired'] == ['1700003600']
    assert 'test-secret' not in url and '%3D' in url


@pytest.mark.parametrize('text,target', [('河南口音普通话','英语'),('Hello class','中文'),('中英 mixed','英语')])
def test_auto_direction_requires_no_dialect_selection(text, target):
    assert translation_target(text, 'auto') == target
    assert translation_target(text, 'zh-en') == '英语'
    assert translation_target(text, 'en-zh') == '中文'


@pytest.mark.parametrize('code,retry', [(4002,False),(4003,False),(4004,False),(4008,False),(5000,True),(5001,True)])
def test_asr_errors_are_redacted_and_retry_is_limited(code, retry):
    with pytest.raises(RelayError) as error:
        asr_message(json.dumps(dict(code=code, message='test-secret and private transcript')))
    assert error.value.retryable is retry
    assert 'private' not in error.value.message and 'test-secret' not in error.value.message


@pytest.mark.parametrize('raw', ['bad', '[]', '{}', '{"code":"0"}'])
def test_malformed_provider_messages_stop_cleanly(raw):
    with pytest.raises(RelayError): asr_message(raw)


async def test_missing_configuration_never_connects_or_starts_capture_path():
    calls = []
    async def emit(_): pass
    value = DialectSession(Settings(), emit, connector=lambda *a, **k: calls.append(True))
    value.prepare()
    with pytest.raises(RelayError) as error: await value.start()
    assert error.value.code == 'dialect_not_configured' and calls == [] and value.task is None


async def test_live_source_final_only_translation_duplicate_filter_and_exact_pcm_tail():
    cloud = Cloud([result(kind=1, text='课堂'), result(), result()])
    value, events, calls = session(cloud)
    await value.start(class_id='class', epoch=3); await until(lambda: value.state=='running')
    pcm = bytes(range(256))*50
    for i in range(0,len(pcm),2560): await value.audio(pcm[i:i+2560])
    await until(lambda: any(e.get('channel')=='translation' for e in events))
    await value.end()
    assert b''.join(frame for frame in cloud.frames if isinstance(frame,bytes)) == pcm
    assert [len(frame) for frame in cloud.frames if isinstance(frame,bytes)] == [6400,6400]
    assert json.loads(cloud.frames[-1]) == dict(type='end')
    assert calls == [('课堂测试','英语')]
    subtitles = [e for e in events if e.get('type')=='subtitle']
    assert [e['channel'] for e in subtitles] == ['source','source','translation']
    assert all(e['classId']=='class' and e['sessionEpoch']==4 for e in subtitles)
    assert cloud.closed and value.state=='stopped'


async def test_short_tail_and_pause_resume_preserve_identity_with_new_epoch():
    clouds = []
    def connect(*a,**k):
        cloud=Cloud(); clouds.append(cloud); return cloud
    async def emit(_): pass
    value=DialectSession(configured(),emit,connector=connect)
    await value.start(class_id='class',epoch=5);await until(lambda:value.state=='running')
    await value.audio(b'\x01\0'*400)
    await value.end()
    assert [len(v) for v in clouds[0].frames if isinstance(v,bytes)]==[800]
    await value.start(class_id='class',epoch=6);await until(lambda:value.state=='running')
    await value.end(pause=True)
    assert value.state=='paused'
    await value.start(resume=True);await until(lambda:value.state=='running')
    assert value.class_id=='class' and value.epoch==8
    await value.end(pause=True)


async def test_pause_cancels_inflight_translation_without_late_emission():
    entered, cancelled = asyncio.Event(), asyncio.Event()
    async def translate(*_):
        entered.set()
        try: await asyncio.Future()
        finally: cancelled.set()
    cloud=Cloud([result()]);value,events,_=session(cloud,translate)
    await value.start();await until(lambda:value.state=='running')
    for _ in range(3):await value.audio(bytes(2560))
    await entered.wait();await value.end(pause=True)
    assert cancelled.is_set() and cloud.closed
    assert not any(e.get('channel')=='translation' for e in events)


async def test_translation_failure_is_not_silent_and_stops_optional_session():
    async def translate(*_): raise RelayError('dialect_translation','test-safe-error')
    value,events,_=session(Cloud([result()]),translate)
    await value.start();await until(lambda:value.state=='running')
    for _ in range(3):await value.audio(bytes(2560))
    await until(lambda:value.state=='error')
    assert not value.wanted and any(e.get('code')=='dialect_translation' for e in events)
    await value.end(immediate=True)


async def test_pending_translations_are_bounded_and_skips_are_reported():
    entered=asyncio.Event()
    async def translate(*_):entered.set();await asyncio.Future()
    value,events,_=session(Cloud([result(index=i) for i in range(12)]),translate)
    await value.start();await until(lambda:value.state=='running')
    for _ in range(3):await value.audio(bytes(2560))
    await entered.wait()
    assert any(e.get('gap') for e in events)
    assert len([e for e in events if e.get('channel')=='source'])==12
    await value.end(pause=True)


def test_tokenhub_request_and_response_without_network(monkeypatch):
    captured={}
    class Connection:
        def __init__(self,host,timeout):captured.update(host=host,timeout=timeout)
        def request(self,method,path,body,headers):captured.update(method=method,path=path,body=json.loads(body),headers=headers)
        def getresponse(self):return self
        status=200
        def read(self,_):return json.dumps(dict(choices=[dict(finish_reason='stop',message=dict(content='Hello.'))])).encode()
        def close(self):captured['closed']=True
    monkeypatch.setattr(dialect.http.client,'HTTPSConnection',Connection)
    assert dialect.translate_sync(configured(),'你好','英语')=='Hello.'
    assert captured['host']=='tokenhub.tencentmaas.com' and captured['body']['model']=='hy-mt2-lite'
    assert captured['headers']['Authorization']=='Bearer test-token' and captured['closed']
    assert 'test-token' not in json.dumps(captured['body'])


def test_health_and_dialect_route_missing_config_are_redacted():
    with TestClient(create_app(Settings())) as client:
        info=client.get('/api/health').json()
        assert info['dialectSupported'] is True and info['dialectConfigured'] is False
        with client.websocket_connect('/ws/translate?engine=dialect',headers={'origin':'http://localhost:8765'}) as ws:
            assert ws.receive_json()['state']=='idle'
            ws.send_json(dict(type='start'))
            assert ws.receive_json()['code']=='dialect_not_configured'
    with TestClient(create_app(configured())) as client:
        response=client.get('/api/health')
        assert response.json()['dialectConfigured'] is True and response.json()['ready'] is False
        assert 'test-secret' not in response.text and 'test-token' not in response.text


@pytest.mark.parametrize('url,origin', [('/ws/translate?engine=unknown','http://localhost:8765'),
                                      ('/ws/translate?engine=dialect','https://evil.example')])
def test_optional_route_still_enforces_origin_and_engine(url,origin):
    with TestClient(create_app(Settings())) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(url,headers={'origin':origin}):pass


def test_dialect_route_shares_single_session_reservation():
    with TestClient(create_app(Settings())) as client:
        headers={'origin':'http://localhost:8765'}
        with client.websocket_connect('/ws/translate',headers=headers) as ws:
            ws.receive_json()
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect('/ws/translate?engine=dialect',headers=headers):pass


def test_environment_loading_is_optional_and_secret_fields_are_not_repr(monkeypatch):
    for key,value in dict(TENCENT_ASR_APP_ID='12345',TENCENT_SECRET_ID='test-id',
        TENCENT_SECRET_KEY='test-secret',TOKENHUB_API_KEY='test-token').items():monkeypatch.setenv(key,value)
    value=Settings.load()
    assert value.dialect_configured
    assert 'test-secret' not in repr(value) and 'test-token' not in repr(value)
    assert not replace(value,tencent_app_id='invalid').dialect_configured


def test_optional_route_emits_source_and_translation_then_releases_for_standard():
    clouds=[]
    def factory(settings,emit):
        cloud=Cloud([result()]);clouds.append(cloud)
        async def translate(*_):return 'Classroom test.'
        return DialectSession(settings,emit,connector=lambda *a,**k:cloud,translator=translate)
    with TestClient(create_app(configured(),dialect_session_factory=factory)) as client:
        headers={'origin':'http://localhost:8765'}
        with client.websocket_connect('/ws/translate?engine=dialect',headers=headers) as ws:
            ws.receive_json();ws.send_json(dict(type='start',mode='auto'))
            while ws.receive_json().get('state')!='running':pass
            for _ in range(3):ws.send_bytes(bytes(2560))
            received=[]
            while not any(v.get('channel')=='translation' for v in received):received.append(ws.receive_json())
            assert [v['channel'] for v in received if v.get('type')=='subtitle']==['source','translation']
            ws.send_json(dict(type='pause'))
            while ws.receive_json().get('state')!='paused':pass
        assert clouds[0].closed
        with client.websocket_connect('/ws/translate',headers=headers) as ws:
            assert ws.receive_json()['state']=='idle'
            ws.send_json(dict(type='start'))
            assert ws.receive_json()['code']=='not_configured'


async def test_dialect_pause_during_handshake_releases_without_audio():
    cloud=Cloud();cloud.responses.get_nowait()
    value,events,calls=session(cloud)
    await value.start();await until(lambda:value.upstream is cloud)
    await value.end(pause=True)
    assert cloud.closed and cloud.frames==[] and calls==[]
    assert value.state=='paused' and value.task.done()


async def test_dialect_retry_is_cancelled_on_pause():
    attempts=[]
    def connect(*a,**k):
        attempts.append(True);cloud=Cloud();cloud.responses.get_nowait()
        cloud.responses.put_nowait(json.dumps(dict(code=5000)));return cloud
    async def emit(_):pass
    value=DialectSession(configured(),emit,connector=connect)
    await value.start();await until(lambda:value.state=='recovering')
    await value.end(pause=True);await asyncio.sleep(.6)
    assert len(attempts)==1 and not value.wanted


async def test_dialect_stop_keeps_five_second_deadline_when_asr_never_finishes():
    class NeverFinishes(Cloud):
        async def send(self,data):
            if isinstance(data,str):self.frames.append(data)
            else:await super().send(data)
    cloud=NeverFinishes();value,events,_=session(cloud)
    await value.start();await until(lambda:value.state=='running')
    started=asyncio.get_running_loop().time();await value.end()
    assert 4.9<=asyncio.get_running_loop().time()-started<6
    assert cloud.closed and value.task.done() and value.state=='stopped'
    assert any('收尾超时' in e.get('detail','') for e in events)
