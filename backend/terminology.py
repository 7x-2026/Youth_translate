"""Course vocabulary loaded once per explicit start/resume, never per audio packet."""
import json
from pathlib import Path
from backend.protocol import LANGUAGES, RelayError

COURSE_TERMINOLOGY = Path(__file__).resolve().parents[1] / 'terminology' / 'anthroposophy.json'
MAX_ENTRIES = 1000  # AST corpus hot words + glossary combined.
MAX_FILE_BYTES = 256 * 1024


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


def _term(value):
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def load_course_corpus(mode, path=None):
    """Validate both directions before sending anything; errors never expose file contents."""
    if mode not in LANGUAGES:
        raise RelayError('parameter', '无效翻译方向。')
    path = COURSE_TERMINOLOGY if path is None else Path(path)
    try:
        with path.open('rb') as source:
            raw = source.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            raise ValueError('file too large')
        data = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_object)
        if not isinstance(data, dict) or set(data) != {'hot_words', 'zh_en', 'en_zh'}:
            raise ValueError('schema')
        hot_words = data['hot_words']
        if not isinstance(hot_words, list) or not all(_term(word) for word in hot_words):
            raise ValueError('hot words')
        hot_words = list(dict.fromkeys(hot_words))
        for name in ('zh_en', 'en_zh'):
            words = data[name]
            if not isinstance(words, dict) or not all(_term(k) and _term(v) for k, v in words.items()):
                raise ValueError('glossary')
        combined = dict(data['zh_en'])
        for source, target in data['en_zh'].items():
            if source in combined and combined[source] != target:
                raise ValueError('ambiguous source')
            combined[source] = target
        if len(hot_words) + len(combined) > MAX_ENTRIES:
            raise ValueError('too many entries')
        glossary = combined if mode == 'auto' else data['zh_en' if mode == 'zh-en' else 'en_zh']
        return dict(hot_words_list=hot_words, glossary_list=glossary)
    except (OSError, ValueError, TypeError, RecursionError):
        raise RelayError('course_terminology', '课程词表无法读取或格式无效。请检查 terminology/anthroposophy.json：必须包含 hot_words、zh_en、en_zh，词条不可为空或冲突，热词与双向术语合计不得超过 1000 条。修正后重新开始课程。') from None
