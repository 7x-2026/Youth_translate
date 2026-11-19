"""Local vocabulary extraction, without formula evaluation or external services."""
import csv
import io
import json
import re
from pathlib import Path
from zipfile import ZipFile

from openpyxl import load_workbook
from backend.terminology import _unique_object, _validate

MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_IMPORT_ROWS = 1000
ALIASES = {
    'zh': {'中文', '中文词汇', '中文术语', '中文名称', '汉语', 'zh', 'chinese', 'chineseterm'},
    'en': {'英文', '英语', '英文译法', '英文术语', '英文名称', 'en', 'english', 'englishterm'},
    'direction': {'方向', '应用方向', '翻译方向', 'direction'},
}


def direction(value):
    text = re.sub(r'\s+', '', str(value or '')).lower().replace('→', '-').replace('->', '-').replace('至', '-').replace('到', '-')
    if text in ('', 'both', 'auto', '双向', '双向中英互译', '中英互译', '中英双向', '中文⇄英文', '中文↔英文'):
        return 'both'
    if text in ('zh-en', '中英', '中译英', '中文-英文', '中文-英语'):
        return 'zh-en'
    if text in ('en-zh', '英中', '英译中', '英文-中文', '英语-中文'):
        return 'en-zh'
    return 'invalid'


def _header(value):
    return re.sub(r'[\s_（）()：:]+', '', str(value or '')).lower()


def _tabular(rows, sheet):
    nonempty = [(n, row) for n, row in rows if any(value not in (None, '') for value in row)]
    header_index = None
    columns = {'zh':0, 'en':1, 'direction':2}
    for index, (_, row) in enumerate(nonempty[:20]):
        found = {key:next((i for i, value in enumerate(row) if _header(value) in aliases), None)
                 for key, aliases in ALIASES.items()}
        if found['zh'] is not None and found['en'] is not None:
            columns = found
            header_index = index
            break
    if header_index is not None:
        nonempty = nonempty[header_index + 1:]
    elif nonempty:
        first = nonempty[0][1]
        if len(first) > 1 and isinstance(first[0], str) and isinstance(first[1], str):
            if not re.search(r'[\u3400-\u9fff]', first[0]) and re.search(r'[\u3400-\u9fff]', first[1]):
                columns['zh'], columns['en'] = 1, 0
    result = []
    for number, row in nonempty:
        def cell(key):
            index = columns[key]
            return row[index] if index is not None and index < len(row) else None
        zh, en = cell('zh'), cell('en')
        # Formulas are read as text and rejected rather than evaluated or imported.
        if not isinstance(zh, str) or zh.startswith('='):
            zh = ''
        if not isinstance(en, str) or en.startswith('='):
            en = ''
        result.append(dict(zh=zh.strip(), en=en.strip(), direction=direction(cell('direction')),
                           location=f'{sheet}第 {number} 行'))
    return result


def parse_vocabulary(raw, filename):
    if not raw or len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError('请选择非空词表文件，最大 2 MiB。')
    suffix = Path(filename).suffix.lower()
    hot_words = []
    try:
        if suffix == '.xlsx':
            with ZipFile(io.BytesIO(raw)) as archive:
                files = archive.infolist()
                if len(files) > 300 or sum(item.file_size for item in files) > 16 * 1024 * 1024:
                    raise ValueError('Excel 文件内容过大，请只保留词表工作表后重试。')
            workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=False, keep_links=False)
            try:
                items = []
                if len(workbook.worksheets) > 20:
                    raise ValueError('工作表过多，请只保留词表工作表后重试。')
                for sheet in workbook.worksheets:
                    sheet.reset_dimensions()
                    rows = []
                    for number, row in enumerate(sheet.iter_rows(max_col=30, values_only=True), 1):
                        if number > 5000:
                            raise ValueError('Excel 工作表行数过多，请只保留词汇内容后重试。')
                        rows.append((number, row))
                    items.extend(_tabular(rows, f'“{sheet.title}”'))
            finally:
                workbook.close()
        elif suffix == '.json':
            data = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_object)
            if isinstance(data, dict) and set(data) == {'hot_words', 'zh_en', 'en_zh'}:
                data = _validate(data)
                hot_words = data['hot_words']
                items = [dict(zh=source if name=='zh_en' else target,
                              en=target if name=='zh_en' else source,
                              direction='zh-en' if name=='zh_en' else 'en-zh', location='JSON')
                         for name in ('zh_en', 'en_zh') for source, target in data[name].items()]
            elif isinstance(data, list):
                items = [dict(zh=row.get('zh', ''), en=row.get('en', ''),
                              direction=direction(row.get('direction')), location=f'第 {i+1} 条')
                         if isinstance(row, dict) else dict(zh='', en='', direction='invalid', location=f'第 {i+1} 条')
                         for i, row in enumerate(data)]
            else:
                raise ValueError('JSON 请使用现有词表格式，或 zh、en、direction 组成的数组。')
        elif suffix in ('.csv', '.tsv', '.txt'):
            try:
                text = raw.decode('utf-8-sig')
            except UnicodeDecodeError:
                text = raw.decode('gb18030')
            delimiter = '\t' if suffix == '.tsv' else None
            if delimiter is None:
                try:
                    delimiter = csv.Sniffer().sniff(text[:8192], delimiters=',\t;').delimiter
                except csv.Error:
                    delimiter = '\t' if '\t' in text else ','
            items = _tabular(list(enumerate(csv.reader(io.StringIO(text), delimiter=delimiter), 1)), '')
        else:
            raise ValueError('请选择 .xlsx、.csv、.tsv、.txt 或 .json 词表。')
        if len(items) > MAX_IMPORT_ROWS:
            raise ValueError('一次最多导入 1000 行，请拆分词表后重试。')
        if not items and not hot_words:
            raise ValueError('未找到词汇，请提供中文、英文两列，可选“方向”列。')
        return dict(items=items, hotWords=hot_words)
    except ValueError:
        raise
    except Exception:
        raise ValueError('无法解析词表，请确认文件未损坏、未加密，并包含中文和英文两列。') from None
