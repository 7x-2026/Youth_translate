import struct
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.config import Settings
from backend.audio_diagnostics import AudioDiagnostics


def test_transport_counters_do_not_confuse_received_with_forwarded_audio():
    now=[1.]
    d=AudioDiagnostics(lambda:now[0])
    packet=struct.pack('<h',16384)*1280
    d.receive(packet)
    info=d.snapshot()
    assert info['receivedAudioMs']==80 and info['sentToCloudAudioMs']==0
    assert info['lastInputDbfs']==-6.0 and info['lastSentToCloudAgoMs'] is None
    now[0]=1.2;d.send(packet);now[0]=2.
    info=d.snapshot()
    assert info['sentToCloudAudioMs']==80
    assert info['lastReceivedAgoMs']==1000 and info['lastSentToCloudAgoMs']==800


def test_subtitle_timing_starts_from_forwarded_signal_not_silent_packets():
    now=[0.]
    d=AudioDiagnostics(lambda:now[0]);d.receive(bytes(2560));d.send(bytes(2560))
    assert d.snapshot()['lastInputDbfs'] is None
    assert d.first_sound is None
    now[0]=10.;d.send(struct.pack('<h',1000)*1280)
    now[0]=10.8;d.subtitle('source')
    now[0]=11.;d.subtitle('translation')
    now[0]=12.;d.subtitle('source')
    info=d.snapshot()
    assert info['firstSourceAfterSoundMs']==800
    assert info['firstTranslationAfterSoundMs']==1000
    assert info['lastSourceAgoMs']==0


def test_local_diagnostics_contains_only_metadata_and_releases_closed_session():
    with TestClient(create_app(Settings(api_key='test-only-secret',response_mode='snapshot'))) as client:
        assert client.get('/api/audio-diagnostics').json()==dict(sessions=[])
        with client.websocket_connect('/ws/translate',headers={'origin':'http://localhost:8765'}) as ws:
            ws.receive_json()
            response=client.get('/api/audio-diagnostics')
            info=response.json()['sessions'][0]
            assert info['state']=='idle' and info['receivedAudioMs']==0
            assert 'test-only-secret' not in response.text
            assert 'text' not in info and 'audio' not in info and 'classId' not in info
        assert client.get('/api/audio-diagnostics').json()==dict(sessions=[])
