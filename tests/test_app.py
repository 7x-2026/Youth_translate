import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from backend.app import create_app
from backend.config import Settings

@pytest.fixture
def client():
    with TestClient(create_app(Settings())) as c:yield c

def test_health_redacted(client):
    r=client.get('/api/health').json()
    assert r['status']=='ok' and r['credentialsConfigured'] is False and r['ready'] is False
    assert 'api_key' not in r
    assert r['cloudWarmupSupported'] is True

def test_prepare_control_keeps_unconfigured_session_idle_without_error(client):
    with client.websocket_connect('/ws/translate',headers={'origin':'http://localhost:8765'}) as ws:
        assert ws.receive_json()['state']=='idle'
        ws.send_json({'type':'prepare'})
        ws.send_json({'type':'heartbeat'})
        assert ws.receive_json()['type']=='heartbeat_ack'

@pytest.mark.parametrize('origin',['https://evil.example','http://192.168.1.1:8765',None])
def test_origin_denied(client,origin):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/ws/translate',headers={'origin':origin} if origin else {}):pass

def test_controls_heartbeat_missing_config_and_invalid_json(client):
    with client.websocket_connect('/ws/translate',headers={'origin':'http://localhost:8765'}) as ws:
        assert ws.receive_json()['state']=='idle'
        ws.send_json({'type':'heartbeat'});assert ws.receive_json()['type']=='heartbeat_ack'
        ws.send_text('[]');assert ws.receive_json()['code']=='control'
        ws.send_json({'type':'start'});assert ws.receive_json()['code']=='not_configured'
        ws.send_json({'type':'pause'});assert ws.receive_json()['state']=='paused'

def test_one_local_session_and_audio_limit(client):
    with client.websocket_connect('/ws/translate',headers={'origin':'http://localhost:8765'}) as ws:
        ws.receive_json()
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/ws/translate',headers={'origin':'http://localhost:8765'}):pass
        ws.send_bytes(b'\0'*3000);assert ws.receive_json()['code']=='audio_size'
        with pytest.raises(WebSocketDisconnect):ws.receive_json()

def test_invalid_class_id_type_is_a_control_error(client):
    with client.websocket_connect('/ws/translate',headers={'origin':'http://localhost:8765'}) as ws:
        ws.receive_json();ws.send_json({'type':'start','classId':34})
        assert ws.receive_json()['code']=='control'

def test_ark_key_is_reported_as_wrong_source():
    with TestClient(create_app(Settings(api_key='ark-test-only',response_mode='snapshot'))) as client:
        info=client.get('/api/health').json()
        assert info['credentialsConfigured'] and info['credentialSourceMismatch']
        assert info['ready'] is False
        with client.websocket_connect('/ws/translate',headers={'origin':'http://localhost:8765'}) as ws:
            ws.receive_json();ws.send_json({'type':'start'})
            assert ws.receive_json()['code']=='wrong_key_type'
