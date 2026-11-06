import json
import pytest
from backend.protocol import E, RelayError, request
from backend.terminology import load_course_corpus
from backend.generated.products.understanding.ast.ast_service_pb2 import TranslateRequest


def write_table(tmp_path, **changes):
    data = dict(hot_words=['音语舞', 'Eurythmy'], zh_en={'音语舞': 'Eurythmy'}, en_zh={'Eurythmy': '音语舞'})
    data.update(changes)
    path = tmp_path / 'terms.json'
    path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return path


@pytest.mark.parametrize('mode', ['auto', 'zh-en', 'en-zh'])
def test_course_terms_serialized_only_in_start(mode):
    corpus = load_course_corpus(mode)
    start = TranslateRequest.FromString(request('class', E.StartSession, mode, corpus=corpus))
    assert dict(start.request.corpus.glossary_list) == corpus['glossary_list']
    assert list(start.request.corpus.hot_words_list) == corpus['hot_words_list']
    glossary = start.request.corpus.glossary_list
    if mode != 'en-zh':
        assert glossary['人智学'] == 'Anthroposophy'
        assert glossary['音语舞'] == 'Eurythmy'
        assert glossary['星智学'] == 'Astrosophy'
        assert glossary['黄道'] == 'Ecliptic' and glossary['黄道带'] == 'Zodiac'
        assert glossary['律动'] == 'Movement'
        assert '现象学观察法' not in glossary and '塑形艺术' not in glossary
    else:
        assert '人智学' not in glossary
    if mode != 'zh-en':
        assert glossary['Eurythmy'] == '音语舞'
        assert glossary['Astrosophy'] == '星智学'
        assert glossary['Astrology'] == '世俗占星'
        assert glossary['I-Organization'] == '自我体'
        assert glossary['Steiner Education'] == '华德福教育'
        assert glossary['Community'] == '社群'
        assert glossary['Form drawing'] == '形线画'
    else:
        assert 'Eurythmy' not in glossary
    assert len(glossary) + len(start.request.corpus.hot_words_list) <= 1000
    audio = b'\x01\x00' * 40
    packet = TranslateRequest.FromString(request('class', E.TaskRequest, audio=audio, corpus=corpus))
    assert packet.source_audio.binary_data == audio
    assert not packet.HasField('request')
    finish = TranslateRequest.FromString(request('class', E.FinishSession, corpus=corpus))
    assert not finish.HasField('request')
    assert not TranslateRequest.FromString(request('probe', E.StartSession)).request.HasField('corpus')


@pytest.mark.parametrize('changes', [
    {'hot_words': 'bad'}, {'hot_words': ['']}, {'hot_words': [42]},
    {'zh_en': []}, {'zh_en': {'音语舞': ''}}, {'zh_en': {' 词': 'word'}},
    {'en_zh': {'音语舞': 'conflict'}}, {'unexpected': True},
])
def test_invalid_table_is_actionable_without_exposing_content(tmp_path, changes):
    path = write_table(tmp_path, **changes)
    with pytest.raises(RelayError) as error:
        load_course_corpus('auto', path)
    assert error.value.code == 'course_terminology' and not error.value.retryable
    assert 'terminology/anthroposophy.json' in error.value.message
    assert 'conflict' not in error.value.message


@pytest.mark.parametrize('content', ['{', '[]', '{"hot_words":[],"zh_en":{},"en_zh":{},"en_zh":{}}', 'x' * (256*1024+1)], ids=['invalid-json', 'wrong-root', 'duplicate-key', 'oversize'])
def test_malformed_duplicate_and_oversize_files(tmp_path, content):
    path = tmp_path / 'terms.json'
    path.write_text(content, encoding='utf-8')
    with pytest.raises(RelayError, match='课程词表'):
        load_course_corpus('auto', path)


def test_missing_file_is_not_silently_ignored(tmp_path):
    with pytest.raises(RelayError, match='课程词表'):
        load_course_corpus('auto', tmp_path / 'missing.json')


def test_total_limit_and_empty_table_opt_out(tmp_path):
    path = write_table(tmp_path, hot_words=['音语舞']*10, zh_en={f'词{i}':f'word{i}' for i in range(998)})
    assert len(load_course_corpus('auto', path)['hot_words_list']) == 1
    path = write_table(tmp_path, zh_en={f'词{i}':f'word{i}' for i in range(999)})
    with pytest.raises(RelayError):
        load_course_corpus('zh-en', path)
    path = write_table(tmp_path, hot_words=[], zh_en={}, en_zh={})
    corpus = load_course_corpus('auto', path)
    assert corpus == dict(hot_words_list=[], glossary_list={})
    start = TranslateRequest.FromString(request('class', E.StartSession, corpus=corpus))
    assert not start.request.corpus.hot_words_list and not start.request.corpus.glossary_list
