import asyncio
import sqlite3
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import Settings
from backend.records import RecordStore
from backend.session import Session

NOW = datetime.fromisoformat('2026-11-07T10:00:00+08:00')


def subtitle(class_id='course', **changes):
    return dict(type='subtitle', classId=class_id, sessionEpoch=1, channel='translation',
                segmentId='translation-1', revision=1, text='Hello classroom', isFinal=False, **changes)


def test_daily_numbering_resume_and_next_day(tmp_path):
    clock = [NOW]
    store = RecordStore(tmp_path / 'records.sqlite3', clock=lambda: clock[0])
    first = store.save_event(subtitle('first'))
    second = store.save_event(subtitle('second'))
    assert first['name'] == '2026-11-07-001'
    assert second['name'] == '2026-11-07-002'
    clock[0] = NOW.replace(day=8)
    resumed = store.save_event(dict(type='status', classId='first', state='running'))
    assert resumed['name'] == first['name']
    assert store.save_event(subtitle('third'))['name'] == '2026-11-08-001'
    assert store.list_courses()['records'][0]['name'] == '2026-11-08-001'
    store.close()


def test_revisions_final_dedup_and_epoch_identity_survive_reopen(tmp_path):
    path = tmp_path / 'records.sqlite3'
    store = RecordStore(path)
    store.save_event(subtitle())
    store.save_event(dict(subtitle(), text='Final text', revision=3, isFinal=True))
    store.save_event(dict(subtitle(), text='Stale text', revision=2))
    store.save_event(dict(subtitle(), text='Duplicate final', revision=4, isFinal=True))
    store.save_event(dict(subtitle(), sessionEpoch=2, text='New unfinished sentence'))
    store.close()
    reopened = RecordStore(path)
    result = reopened.get_course('course')
    assert [entry['text'] for entry in result['entries']] == ['Final text', 'New unfinished sentence']
    assert [entry['unfinished'] for entry in result['entries']] == [False, True]
    _, text = reopened.export_text('course')
    assert '未定稿' in text and 'Final text' in text and 'Duplicate' not in text
    reopened.close()


def test_concurrent_number_allocation_is_unique(tmp_path):
    stores = [RecordStore(tmp_path / 'records.sqlite3', clock=lambda: NOW) for _ in range(2)]
    # Initialize the schema before competing processes/connections allocate numbers.
    stores[0].list_courses()
    with ThreadPoolExecutor(max_workers=4) as executor:
        names = list(executor.map(lambda n: stores[n % 2].save_event(subtitle(str(n)))['name'], range(12)))
    assert len(set(names)) == 12
    assert sorted(names) == [f'2026-11-07-{i:03d}' for i in range(1, 13)]
    for store in stores:
        store.close()


def test_committed_text_survives_process_exit_without_cleanup(tmp_path):
    path = tmp_path / 'records.sqlite3'
    script = '''
import os,sys
from backend.records import RecordStore
store=RecordStore(sys.argv[1])
store.save_event(dict(type='subtitle',classId='crashed',sessionEpoch=1,
    channel='source',segmentId='one',revision=1,text='saved before crash',isFinal=False))
os._exit(0)
'''
    subprocess.run([sys.executable, '-c', script, str(path)], cwd=Path(__file__).resolve().parents[1], check=True, timeout=10)
    store = RecordStore(path)
    assert store.get_course('crashed')['entries'][0]['text'] == 'saved before crash'
    store.close()


class TextSession(Session):
    """Deterministic relay fixture: no microphone, network or cloud credentials."""
    async def run(self):
        self.epoch += 1
        self.finish = asyncio.Event()
        await self.status('running', 'test session')
        await self.emit(dict(subtitle(self.class_id), sessionEpoch=self.epoch))
        await self.finish.wait()
        await self.emit(dict(subtitle(self.class_id), sessionEpoch=self.epoch, revision=2, text='Final classroom text', isFinal=True))


def test_close_page_then_restart_app_can_list_read_and_export(tmp_path):
    path = tmp_path / 'records.sqlite3'
    class_id = str(uuid.uuid4())
    with TestClient(create_app(Settings(api_key='test-only', response_mode='delta'), session_factory=TextSession,
                               record_store=RecordStore(path, clock=lambda: NOW))) as client:
        with client.websocket_connect('/ws/translate', headers={'origin': 'http://localhost:8765'}) as ws:
            ws.receive_json()
            ws.send_json(dict(type='start', classId=class_id))
            assert ws.receive_json()['record']['name'] == '2026-11-07-001'
            caption = ws.receive_json()
            assert caption['type'] == 'subtitle' and caption['record']['saveState'] == 'saved'
        # The page closes without exporting or explicitly ending the session.
    with TestClient(create_app(Settings(), record_store=RecordStore(path))) as client:
        listed = client.get('/api/records').json()['records']
        assert len(listed) == 1 and listed[0]['state'] == 'interrupted'
        assert listed[0]['name'] == '2026-11-07-001'
        detail = client.get(f'/api/records/{class_id}').json()
        assert detail['entries'][0]['text'] == 'Hello classroom'
        response = client.get(f'/api/records/{class_id}/export')
        assert response.status_code == 200 and response.content.startswith(b'\xef\xbb\xbf')
        assert '2026-11-07-001.txt' in response.headers['content-disposition']
        assert 'Hello classroom' in response.text and '未定稿' in response.text


def test_pause_resume_keeps_course_name_and_final_export(tmp_path):
    store = RecordStore(tmp_path / 'records.sqlite3', clock=lambda: NOW)
    class_id = str(uuid.uuid4())
    with TestClient(create_app(Settings(api_key='test-only', response_mode='delta'), session_factory=TextSession, record_store=store)) as client:
        with client.websocket_connect('/ws/translate', headers={'origin': 'http://localhost:8765'}) as ws:
            ws.receive_json()
            ws.send_json(dict(type='start', classId=class_id))
            ws.receive_json(); ws.receive_json()
            ws.send_json(dict(type='pause'))
            while ws.receive_json().get('state') != 'paused':
                pass
            ws.send_json(dict(type='resume'))
            assert ws.receive_json()['record']['name'] == '2026-11-07-001'
            ws.receive_json()
            ws.send_json(dict(type='stop'))
            while ws.receive_json().get('state') != 'stopped':
                pass
        courses = client.get('/api/records').json()['records']
        assert len(courses) == 1 and courses[0]['state'] == 'ended'
        detail = client.get(f'/api/records/{class_id}').json()
        assert len(detail['entries']) == 2 and all(e['isFinal'] for e in detail['entries'])


def test_storage_failure_is_visible_and_does_not_drop_live_subtitle(tmp_path, monkeypatch):
    store = RecordStore(tmp_path / 'records.sqlite3')
    def fail(*args):
        raise sqlite3.OperationalError('private-path-must-not-be-exposed')
    monkeypatch.setattr(store, 'save_event', fail)
    with TestClient(create_app(Settings(api_key='test-only', response_mode='delta'), session_factory=TextSession, record_store=store)) as client:
        with client.websocket_connect('/ws/translate', headers={'origin': 'http://localhost:8765'}) as ws:
            ws.receive_json(); ws.send_json(dict(type='start'))
            assert ws.receive_json()['record']['saveState'] == 'error'
            caption = ws.receive_json()
            assert caption['type'] == 'subtitle' and caption['text'] == 'Hello classroom'
            assert caption['record']['saveState'] == 'error'
            assert 'private-path' not in str(caption)


@pytest.mark.parametrize('close_page', [True, False])
def test_recovered_storage_marks_missing_history_incomplete(tmp_path, monkeypatch, close_page):
    store = RecordStore(tmp_path / 'records.sqlite3')
    original = store.save_event
    failed = [False]
    def fail_first_caption(event, *args):
        if event.get('type') == 'subtitle' and not failed[0]:
            failed[0] = True
            raise sqlite3.OperationalError('simulated disk failure')
        return original(event, *args)
    monkeypatch.setattr(store, 'save_event', fail_first_caption)
    with TestClient(create_app(Settings(api_key='test-only', response_mode='delta'), session_factory=TextSession, record_store=store)) as client:
        with client.websocket_connect('/ws/translate', headers={'origin': 'http://localhost:8765'}) as ws:
            ws.receive_json(); ws.send_json(dict(type='start'))
            course = ws.receive_json()['record']
            assert ws.receive_json()['record']['saveState'] == 'error'
            if not close_page:
                ws.send_json(dict(type='stop'))
                while ws.receive_json().get('state') != 'stopped':
                    pass
        record = client.get(f"/api/records/{course['id']}").json()['record']
        assert record['incomplete']
        assert '可能不完整' in client.get(f"/api/records/{course['id']}/export").text


def test_records_access_validation_and_pagination(tmp_path):
    store = RecordStore(tmp_path / 'records.sqlite3')
    store.save_event(subtitle('one'))
    store.save_event(subtitle('two'))
    with TestClient(create_app(Settings(), record_store=store)) as client:
        page = client.get('/api/records?limit=1').json()
        assert page['hasMore'] and len(page['records']) == 1
        next_page = client.get('/api/records?limit=1&offset=1').json()
        assert not next_page['hasMore'] and next_page['records'][0]['id'] != page['records'][0]['id']
        assert client.get('/api/records?limit=1000').status_code == 422
        assert client.get('/api/records/missing/export').status_code == 404
        for path in ('/api/records', '/api/records/one', '/api/records/one/export'):
            assert client.get(path, headers={'Origin': 'https://evil.example'}).status_code == 403
            assert client.get(path, headers={'Sec-Fetch-Site': 'cross-site'}).status_code == 403
