"""Course vocabulary loaded once per explicit start/resume, never per audio packet."""
import json
import os
import tempfile
import threading
from pathlib import Path
from backend.protocol import LANGUAGES, RelayError
from backend.runtime import terminology_path

COURSE_TERMINOLOGY = Path(__file__).resolve().parents[1] / 'terminology' / 'anthroposophy.json'
MAX_ENTRIES = 1000  # AST corpus hot words + glossary combined.
MAX_FILE_BYTES = 256 * 1024
_LOCK = threading.RLock()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


def _term(value):
    return isinstance(value, str) and bool(value.strip()) and value == value.strip()


def _validate(data):
    if not isinstance(data, dict) or set(data) != {'hot_words', 'zh_en', 'en_zh'}:
        raise ValueError('schema')
    if not isinstance(data['hot_words'], list) or not all(_term(word) for word in data['hot_words']):
        raise ValueError('hot words')
    data = dict(data, hot_words=list(dict.fromkeys(data['hot_words'])))
    for name in ('zh_en', 'en_zh'):
        words = data[name]
        if not isinstance(words, dict) or not all(_term(k) and _term(v) for k, v in words.items()):
            raise ValueError('glossary')
    combined = dict(data['zh_en'])
    for source, target in data['en_zh'].items():
        if source in combined and combined[source] != target:
            raise ValueError('ambiguous source')
        combined[source] = target
    if len(data['hot_words']) + len(combined) > MAX_ENTRIES:
        raise ValueError('too many entries')
    return data


def _read(path):
    with Path(path).open('rb') as source:
        raw = source.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError('file too large')
    return _validate(json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_object))


class TerminologyStore:
    """Edit one complete table; bundled apps seed their writable table on first save."""
    def __init__(self, builtin_path=None, user_path=None):
        self.builtin_path = Path(builtin_path) if builtin_path is not None else COURSE_TERMINOLOGY
        self.user_path = Path(user_path) if user_path is not None else terminology_path(self.builtin_path)

    def table(self):
        with _LOCK:
            try:
                return _read(self.user_path)
            except FileNotFoundError:
                return _read(self.builtin_path)

    def _snapshot(self, table):
        entries = []
        for name, direction in (('zh_en', 'zh-en'), ('en_zh', 'en-zh')):
            for source, target in table[name].items():
                zh, en = (source, target) if name == 'zh_en' else (target, source)
                entries.append(dict(zh=zh, en=en, direction=direction))
        return dict(entries=entries, hotWordCount=len(table['hot_words']),
                    entryCount=len(table['hot_words']) + len(table['zh_en'] | table['en_zh']),
                    maxEntries=MAX_ENTRIES)

    def snapshot(self):
        return self._snapshot(self.table())

    def add(self, zh, en, direction='both'):
        if (not _term(zh) or not _term(en) or len(zh) > 200 or len(en) > 200
                or direction not in ('both', 'zh-en', 'en-zh')):
            raise RelayError('parameter', '请填写中文词汇和英文译法（各不超过 200 字），并选择翻译方向。')
        with _LOCK:
            table = self.table()
            pairs = []
            if direction in ('both', 'zh-en'):
                pairs.append(('zh_en', zh, en))
            if direction in ('both', 'en-zh'):
                pairs.append(('en_zh', en, zh))
            # Reject the entire addition on conflict, including opposite-direction ambiguity.
            all_words = (table['zh_en'] | table['en_zh'])
            for name, source, target in pairs:
                if source in all_words and all_words[source] != target:
                    raise RelayError('terminology_conflict', f'“{source}”已有译法“{all_words[source]}”，不会覆盖。请检查已有词条或调整翻译方向。')
                table[name][source] = target
            table['hot_words'] = list(dict.fromkeys(table['hot_words'] + [zh, en]))
            try:
                table = _validate(table)
                raw = (json.dumps(table, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
                if len(raw) > MAX_FILE_BYTES:
                    raise ValueError('file too large')
            except ValueError:
                raise RelayError('terminology_limit', '词表容量已达上限；热词和双向术语合计最多 1000 条，词表文件不得超过 256 KiB。') from None
            self._write(raw)
            return self._snapshot(table)

    def _write(self, raw):
        self.user_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.user_path.parent, prefix='.terminology-', delete=False) as output:
                temporary = Path(output.name)
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.user_path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _plan_import(self, items, hot_words):
        if not isinstance(items, list) or len(items) > 1000 or not isinstance(hot_words, list) or len(hot_words) > 1000:
            raise RelayError('parameter', '一次最多导入 1000 行。')
        if not all(_term(word) and len(word) <= 200 for word in hot_words):
            raise RelayError('parameter', '导入热词不可为空或超过 200 字。')
        table = self.table()
        results = []
        counts = dict(added=0, duplicate=0, conflict=0, invalid=0)
        for item in items:
            if not isinstance(item, dict):
                raise RelayError('parameter', '无效词条。')
            zh, en, direction = item.get('zh'), item.get('en'), item.get('direction')
            location = str(item.get('location', ''))[:120]
            result = dict(zh=zh if isinstance(zh, str) else '', en=en if isinstance(en, str) else '',
                          direction=direction if isinstance(direction, str) else '', location=location)
            if (not _term(zh) or not _term(en) or len(zh)>200 or len(en)>200
                    or direction not in ('both','zh-en','en-zh')):
                result.update(status='invalid', detail='需填写中文、英文及有效方向；不导入公式或超过 200 字的词汇。')
            else:
                pairs = []
                if direction in ('both','zh-en'):
                    pairs.append(('zh_en',zh,en))
                if direction in ('both','en-zh'):
                    pairs.append(('en_zh',en,zh))
                current = table['zh_en'] | table['en_zh']
                conflicts = [(source,current[source]) for _,source,target in pairs if source in current and current[source]!=target]
                if conflicts:
                    source,target = conflicts[0]
                    result.update(status='conflict', detail=f'“{source}”已有译法“{target}”，跳过此行。')
                elif all(table[name].get(source)==target for name,source,target in pairs):
                    result.update(status='duplicate', detail='已存在，跳过。')
                else:
                    result.update(status='added', detail='可新增')
                    for name,source,target in pairs:
                        table[name][source] = target
                    table['hot_words'].extend([zh,en])
            counts[result['status']] += 1
            results.append(result)
        table['hot_words'].extend(hot_words)
        try:
            table = _validate(table)
            raw = (json.dumps(table,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
            if len(raw)>MAX_FILE_BYTES:
                raise ValueError('size')
        except ValueError:
            raise RelayError('terminology_limit', '导入后将超过词表容量（1000 条或 256 KiB），请减少词条。') from None
        return table, raw, dict(items=results, hotWords=hot_words, summary=counts)

    def preview_import(self, items, hot_words):
        with _LOCK:
            return self._plan_import(items, hot_words)[2]

    def import_terms(self, items, hot_words):
        with _LOCK:
            table, raw, plan = self._plan_import(items, hot_words)
            if plan['summary']['added'] or hot_words:
                self._write(raw)
            return dict(self._snapshot(table), importSummary=plan['summary'])



def load_course_corpus(mode, path=None):
    """Validate both directions before sending anything; errors never expose file contents."""
    if mode not in LANGUAGES:
        raise RelayError('parameter', '无效翻译方向。')
    try:
        data = TerminologyStore().table() if path is None else _read(path)
        glossary = (data['zh_en'] | data['en_zh']) if mode == 'auto' else data['zh_en' if mode == 'zh-en' else 'en_zh']
        return dict(hot_words_list=data['hot_words'], glossary_list=glossary)
    except (OSError, ValueError, TypeError, RecursionError):
        raise RelayError('course_terminology', '课程词表无法读取或格式无效。请检查当前专业词汇表（源码默认 terminology/anthroposophy.json）：必须包含 hot_words、zh_en、en_zh，词条不可为空或冲突，热词与双向术语合计不得超过 1000 条。修正后重新开始课程。') from None
