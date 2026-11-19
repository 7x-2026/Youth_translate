import io
import json
from zipfile import ZipFile
from xml.sax.saxutils import escape

import pytest
from fastapi.testclient import TestClient
from backend.app import create_app
from backend.config import Settings
from backend.protocol import RelayError
from backend.records import RecordStore
from backend.terminology import TerminologyStore
from backend.terminology_import import parse_vocabulary


def xlsx(rows):
    """Minimal OOXML test fixture; no authored workbook is delivered."""
    output=io.BytesIO()
    with ZipFile(output,'w') as z:
        z.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        z.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="词表" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        content=[]
        for n,row in enumerate(rows,1):
            cells=[]
            for c,value in enumerate(row):
                ref=f'{chr(65+c)}{n}'
                if isinstance(value,str) and value.startswith('='):
                    cells.append(f'<c r="{ref}"><f>{escape(value[1:])}</f><v>cached result</v></c>')
                else:
                    cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
            content.append(f'<row r="{n}">{"".join(cells)}</row>')
        z.writestr('xl/worksheets/sheet1.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+''.join(content)+'</sheetData></worksheet>')
    return output.getvalue()


@pytest.fixture
def store(tmp_path):
    builtin=tmp_path/'builtin.json'
    builtin.write_text(json.dumps(dict(hot_words=['音语舞'],zh_en={'音语舞':'Eurythmy'},en_zh={'Eurythmy':'音语舞'})))
    return TerminologyStore(builtin,tmp_path/'saved.json')


def test_excel_preview_and_commit_preserve_existing_and_report_skips(store):
    raw=xlsx([['课程词表'],['英文','中文','方向'],['Phenomenology','现象学','双向'],
              ['Eurythmy','音语舞','双向'],['Other','音语舞','双向'],['=1+1','公式','双向'],
              ['Unilateral','单向','中译英'],['Phenomenology','现象学','双向']])
    parsed=parse_vocabulary(raw,'词表.xlsx')
    preview=store.preview_import(parsed['items'],parsed['hotWords'])
    assert preview['summary']==dict(added=2,duplicate=2,conflict=1,invalid=1)
    assert not store.user_path.exists()
    result=store.import_terms(parsed['items'],parsed['hotWords'])
    assert result['importSummary']==preview['summary']
    saved=store.table()
    assert saved['zh_en']['音语舞']=='Eurythmy'
    assert saved['en_zh']['Phenomenology']=='现象学'
    assert saved['zh_en']['单向']=='Unilateral' and 'Unilateral' not in saved['en_zh']
    assert '公式' not in saved['zh_en']
    assert store.preview_import(parsed['items'],[])['summary']['added']==0


@pytest.mark.parametrize('name,raw',[
    ('词.csv','英文,中文,方向\nTherapy,疗愈,英译中'.encode('utf-8-sig')),
    ('词.tsv','疗愈\tTherapy\t英文→中文'.encode()),
    ('词.txt','中文\t英文\n疗愈\tTherapy'.encode('gb18030')),
])
def test_text_formats_and_reversed_columns(name,raw):
    item=parse_vocabulary(raw,name)['items'][0]
    assert item['zh']=='疗愈' and item['en']=='Therapy'


def test_existing_json_and_hotwords_are_imported_into_one_file(store):
    parsed=parse_vocabulary(json.dumps(dict(hot_words=['热词'],zh_en={'词':'Term'},en_zh={'Term':'词'})).encode(),'terms.json')
    store.import_terms(parsed['items'],parsed['hotWords'])
    assert store.table()['zh_en']=={'音语舞':'Eurythmy','词':'Term'}
    assert '热词' in store.table()['hot_words']


def test_import_rechecks_conflicts_after_preview_and_failed_write_is_atomic(store,monkeypatch):
    parsed=parse_vocabulary('中文,英文\n新词,New term\n另词,Another'.encode(),'a.csv')
    assert store.preview_import(parsed['items'],[])['summary']['added']==2
    store.add('新词','Changed')
    result=store.import_terms(parsed['items'],[])
    assert result['importSummary']['conflict']==1
    assert store.table()['zh_en']['新词']=='Changed'
    before=store.user_path.read_bytes()
    monkeypatch.setattr(store,'_write',lambda *args: (_ for _ in ()).throw(OSError('synthetic')))
    with pytest.raises(OSError):
        store.import_terms([dict(zh='第三词',en='Third',direction='both')],[])
    assert store.user_path.read_bytes()==before


def test_parse_limits_and_malformed_files():
    for raw,name in [(b'','empty.xlsx'),(b'broken','bad.xlsx'),(b'x'*(2*1024*1024+1),'big.csv'),('中文'.encode(),'bad.xls'),(b'[]','empty.json')]:
        with pytest.raises(ValueError):
            parse_vocabulary(raw,name)
    with pytest.raises(ValueError):
        parse_vocabulary(('中文,英文\n'+'词,Word\n'*1001).encode(),'too-many.csv')


def test_import_api_excel_preview_requires_origin_and_commit_is_separate(store,tmp_path):
    app=create_app(Settings(),record_store=RecordStore(tmp_path/'records.sqlite3'),terminology_store=store)
    headers={'Origin':'http://localhost:8765','Content-Type':'application/octet-stream'}
    raw=xlsx([['中文词汇','英文译法'],['星智学','Astrosophy']])
    with TestClient(app) as client:
        url='/api/terminology/import/preview?filename=terms.xlsx'
        assert client.post(url,content=raw).status_code==403
        assert client.post(url,content=raw,headers={**headers,'Origin':'https://evil.example'}).status_code==403
        assert client.post(url,content=raw,headers={**headers,'Content-Type':'text/plain'}).status_code==415
        response=client.post(url,content=raw,headers=headers)
        assert response.status_code==200,response.text
        plan=response.json()
        assert plan['summary']['added']==1 and not store.user_path.exists()
        result=client.post('/api/terminology/import',json=dict(items=plan['items'],hotWords=plan['hotWords']),headers={'Origin':'http://localhost:8765'})
        assert result.status_code==200
        assert store.table()['en_zh']['Astrosophy']=='星智学'
        assert client.post('/api/terminology/import',json={'wrong':True},headers={'Origin':'http://localhost:8765'}).status_code==422
