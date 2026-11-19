import json
import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.config import Settings
from backend.protocol import RelayError
from backend.records import RecordStore
from backend.terminology import TerminologyStore, load_course_corpus
from backend.runtime import terminology_path


@pytest.fixture
def store(tmp_path):
    builtin = tmp_path / 'builtin.json'
    builtin.write_text(json.dumps(dict(hot_words=['音语舞'], zh_en={'音语舞':'Eurythmy'},
                                      en_zh={'Eurythmy':'音语舞'})), encoding='utf-8')
    return TerminologyStore(builtin, tmp_path / 'user' / 'terminology.json')


def test_add_preserves_builtin_and_loads_on_next_start(store, monkeypatch):
    import backend.terminology as terminology
    before = store.builtin_path.read_bytes()
    monkeypatch.setattr(terminology, 'COURSE_TERMINOLOGY', store.builtin_path)
    monkeypatch.setattr(terminology, 'terminology_path', lambda *_: store.user_path)
    running_snapshot = load_course_corpus('auto')
    result = store.add('现象学观察法', 'Phenomenological observation')
    assert store.builtin_path.read_bytes() == before
    assert any(row['zh']=='现象学观察法' for row in result['entries'])
    assert json.loads(store.user_path.read_text())['zh_en']['音语舞'] == 'Eurythmy'
    calls=[]
    original_read=terminology._read
    def counted_read(path):
        calls.append(path)
        return original_read(path)
    monkeypatch.setattr(terminology, '_read', counted_read)
    reopened = TerminologyStore(store.builtin_path, store.user_path)
    assert reopened.table()['en_zh']['Phenomenological observation'] == '现象学观察法'
    assert '现象学观察法' not in running_snapshot['glossary_list']
    assert load_course_corpus('zh-en')['glossary_list']['现象学观察法'] == 'Phenomenological observation'
    assert 'Phenomenological observation' not in load_course_corpus('zh-en')['glossary_list']
    assert load_course_corpus('en-zh')['glossary_list']['Phenomenological observation'] == '现象学观察法'
    assert '现象学观察法' in load_course_corpus('auto')['hot_words_list']
    assert calls and all(path==store.user_path for path in calls)


def test_conflicts_never_partially_write_and_duplicates_do_not_grow(store):
    first = store.add('社群', 'Community')
    raw = store.user_path.read_bytes()
    assert store.add('社群', 'Community') == first
    assert store.user_path.read_bytes() == raw
    with pytest.raises(RelayError, match='已有译法'):
        store.add('社区', 'Community')
    assert store.user_path.read_bytes() == raw
    with pytest.raises(RelayError):
        store.add('音语舞', 'Different translation')
    assert store.user_path.read_bytes() == raw
    store.add('社区', 'Community', 'zh-en')
    assert store.table()['en_zh']['Community'] == '社群'


def test_source_mode_edits_existing_table_without_a_second_file(store, monkeypatch):
    import backend.runtime as runtime
    monkeypatch.delattr(runtime.sys, 'frozen', raising=False)
    editable = TerminologyStore(store.builtin_path)
    assert editable.user_path == store.builtin_path
    editable.add('新词', 'New term')
    assert json.loads(store.builtin_path.read_text())['zh_en'] == {'音语舞':'Eurythmy', '新词':'New term'}
    assert not store.user_path.exists()


def test_failure_before_replace_preserves_previous_file(store, monkeypatch):
    store.add('词一', 'One')
    before = store.user_path.read_bytes()
    monkeypatch.setattr(os, 'replace', lambda *args: (_ for _ in ()).throw(OSError('synthetic failure')))
    with pytest.raises(OSError):
        store.add('词二', 'Two')
    assert store.user_path.read_bytes() == before
    assert not list(store.user_path.parent.glob('.terminology-*'))


def test_concurrent_additions_preserved(store):
    def add(n):
        TerminologyStore(store.builtin_path, store.user_path).add(f'词{n}', f'Word {n}')
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(add, range(12)))
    assert len(store.table()['zh_en']) == 13
    assert len(store.table()['en_zh']) == 13


def test_capacity_and_corrupt_custom_file_do_not_get_overwritten(store):
    data = dict(hot_words=[], zh_en={f'词{i}':f'Word{i}' for i in range(1000)}, en_zh={})
    store.user_path.parent.mkdir()
    store.user_path.write_text(json.dumps(data))
    before = store.user_path.read_bytes()
    with pytest.raises(RelayError, match='上限'):
        store.add('更多', 'More')
    assert store.user_path.read_bytes() == before
    store.user_path.write_text('{"hot_words":[],"hot_words":[]}')
    with pytest.raises(ValueError):
        store.add('更多', 'More')
    assert store.user_path.read_text() == '{"hot_words":[],"hot_words":[]}'


def test_packaged_terminology_uses_persistent_user_directory(monkeypatch, tmp_path):
    import backend.runtime as runtime
    monkeypatch.setattr(runtime.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(runtime, 'user_data_directory', lambda: tmp_path / 'persistent')
    assert terminology_path() == tmp_path / 'persistent' / 'terminology.json'


def test_api_validation_origin_and_persistence(store, tmp_path):
    record_store = RecordStore(tmp_path / 'records.sqlite3')
    with TestClient(create_app(Settings(), record_store=record_store, terminology_store=store)) as client:
        response = client.get('/api/terminology')
        assert response.status_code == 200 and response.headers['cache-control']=='no-store'
        assert len(response.json()['entries']) == 2
        data = dict(zh=' 社群 ', en=' Community ', direction='both')
        headers = {'Origin':'http://localhost:8765'}
        assert client.post('/api/terminology', json=data).status_code == 403
        assert client.post('/api/terminology', json=data, headers={'Origin':'https://evil.example'}).status_code==403
        assert client.post('/api/terminology', json=data, headers={**headers,'Sec-Fetch-Site':'cross-site'}).status_code==403
        assert client.get('/api/terminology', headers={'Origin':'https://evil.example'}).status_code==403
        assert client.post('/api/terminology', content='{}', headers=headers).status_code==415
        for body in ('{', '[]', json.dumps(dict(data,unexpected=True)), json.dumps(dict(data,zh=4)), json.dumps(dict(data,en='')), json.dumps(dict(data,direction='bad'))):
            assert client.post('/api/terminology', content=body, headers={**headers,'Content-Type':'application/json'}).status_code==422
        assert client.post('/api/terminology',content='x'*4097,headers={**headers,'Content-Type':'application/json'}).status_code==413
        assert not store.user_path.exists()
        saved=client.post('/api/terminology', json=data, headers=headers)
        assert saved.status_code==200
        assert store.table()['zh_en']['社群']=='Community'
        conflict=client.post('/api/terminology',json=dict(zh='社区',en='Community',direction='both'),headers=headers)
        assert conflict.status_code==409
        assert '社区' not in store.table()['zh_en']
        store.user_path.write_text('{')
        assert client.get('/api/terminology').status_code==503
        assert client.post('/api/terminology',json=data,headers=headers).status_code==503
        assert store.user_path.read_text()=='{'
