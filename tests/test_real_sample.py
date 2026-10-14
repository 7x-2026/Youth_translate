"""Real AST S2T events from the official Demo's public short WAV, text substituted."""
import json
from pathlib import Path
from collections import defaultdict
from backend.generated.products.understanding.ast.ast_service_pb2 import TranslateResponse
from backend.protocol import E, Normalizer

SAMPLE=json.loads((Path(__file__).parent/'fixtures/ast_real_redacted.json').read_text())

def test_live_sample_fragment_semantics_and_finalization():
    n=Normalizer('live-probe',1,'delta')
    groups=defaultdict(lambda:{'parts':[],'final':None})
    outputs=[]
    for item in SAMPLE['events']:
        event=item['event'];seq=item['sequence']
        message=TranslateResponse(event=event,text=item['text'],start_time=item['startMs'],end_time=item['endMs'])
        message.response_meta.Sequence=seq
        result=n.feed(message)
        if result:outputs.append(result)
        if event in (E.SourceSubtitleResponse,E.TranslationSubtitleResponse):groups[(event,seq)]['parts'].append(item['text'])
        if event in (E.SourceSubtitleEnd,E.TranslationSubtitleEnd):groups[(event-1,seq)]['final']=item['text']
    assert len(groups)==16
    assert all(len(g['parts'])>=2 and ''.join(g['parts'])==g['final'] for g in groups.values())
    assert sum(e['isFinal'] for e in outputs)==16
    assert sum(e['channel']=='translation' and not e['isFinal'] and bool(e['text']) for e in outputs)>8
    assert any(e['event']==E.SessionFinished for e in SAMPLE['events'])
    assert all(item['quantity']==0 for event in SAMPLE['events'] for item in event.get('billing',[]) if item['unit']=='output_audio_tokens')

def test_repeated_sequence_is_not_a_duplicate_frame():
    n=Normalizer('class',1,'delta')
    def m(event,text):
        value=TranslateResponse(event=event,text=text);value.response_meta.Sequence=4
        return value
    n.feed(m(E.TranslationSubtitleStart,''))
    assert n.feed(m(E.TranslationSubtitleResponse,'ha'))['text']=='ha'
    assert n.feed(m(E.TranslationSubtitleResponse,'ha'))['text']=='haha'
    assert n.feed(m(E.TranslationSubtitleEnd,'haha'))['text']=='haha'
