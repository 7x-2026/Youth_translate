import pytest
from backend.protocol import request, decode, Normalizer, RelayError, cloud_error, E
from backend.generated.products.understanding.ast.ast_service_pb2 import TranslateRequest, TranslateResponse

def msg(event,text='',start=0,end=0,sequence=0):
    r=TranslateResponse(event=event,text=text,start_time=start,end_time=end)
    r.response_meta.Sequence=sequence
    return r

def test_official_wire_and_s2t_fields():
    r=TranslateRequest.FromString(request('test',E.StartSession))
    assert r.request.mode=='s2t'
    assert r.request.source_language==r.request.target_language=='zhen'
    assert r.source_audio.format=='wav' and r.source_audio.codec=='raw'
    assert r.source_audio.rate==16000 and r.source_audio.bits==16 and r.source_audio.channel==1
    assert not r.HasField('target_audio')
    packet=TranslateRequest.FromString(request('test',E.TaskRequest,audio=b'\x00\x01'))
    assert packet.source_audio.binary_data==b'\x00\x01' and not packet.source_audio.data

def test_official_protobuf_roundtrip():
    r=msg(E.TranslationSubtitleResponse,'Test',sequence=4)
    assert decode(r.SerializeToString())==r
    with pytest.raises(RelayError):decode('{}')
    with pytest.raises(RelayError):decode(b'\xff')

@pytest.mark.parametrize('mode',['snapshot','delta'])
def test_normalizer_independent_final_duplicate(mode):
    n=Normalizer('class',2,mode)
    assert n.feed(msg(E.TranslationSubtitleStart,start=10))['text']==''
    assert n.feed(msg(E.TranslationSubtitleResponse,'Hello',sequence=1))['text']=='Hello'
    result=n.feed(msg(E.TranslationSubtitleResponse,' class',sequence=2))
    assert result['text']==('Hello class' if mode=='delta' else ' class')
    assert n.feed(msg(E.TranslationSubtitleResponse,' class',sequence=2))['text']==('Hello class class' if mode=='delta' else ' class')
    final=n.feed(msg(E.TranslationSubtitleEnd,'Hello class',10,900))
    assert final['isFinal'] and final['sessionEpoch']==2 and final['text']=='Hello class'
    assert n.feed(msg(E.TranslationSubtitleEnd,'Hello class',10,900)) is None
    assert n.feed(msg(E.SourceSubtitleEnd,'你好',10,700))['channel']=='source'

def test_semantics_must_be_explicit():
    with pytest.raises(RelayError):Normalizer('class',1,'unverified')

@pytest.mark.parametrize('code,retry',[(45000001,False),(45000151,False),(45000081,True),(55000031,True),(401,False),(999,False)])
def test_error_codes(code,retry):
    r=TranslateResponse();r.response_meta.StatusCode=code;r.response_meta.Message='secret original course text'
    e=cloud_error(r);assert e.retryable==retry;assert 'secret' not in e.message

def test_error_status_without_failure_event_is_not_silently_retried():
    r=msg(E.None_ if hasattr(E,'None_') else 0)
    r.response_meta.StatusCode=45000001
    with pytest.raises(RelayError) as error:decode(r.SerializeToString())
    assert error.value.retryable is False
