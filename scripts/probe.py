"""Real-cloud probe for a short, explicitly supplied test WAV. No fake translation.
Run from project root: .venv/bin/python -m scripts.probe short-test.wav
"""
import argparse
import array
import asyncio
import json
import time
import uuid
import wave
from pathlib import Path
import websockets
from backend.config import Settings
from backend.protocol import E, decode, request, cloud_error
from backend.session import classify

async def probe(args):
    settings = Settings.load()
    if not settings.api_key: raise SystemExit('未配置 VOLC_API_KEY；没有发起云端请求。')
    with wave.open(str(args.wav), 'rb') as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
            raise SystemExit('测试文件必须为单声道、16-bit、16kHz WAV。')
        if wav.getnframes() > 16000*60: raise SystemExit('仅接受不超过 60 秒的测试音频；请勿使用完整课堂录音。')
        pcm = wav.readframes(wav.getnframes())
    # pcm matches the browser relay branch; wav matches official Demo's one-time file header.
    gain=getattr(args,'gain',1.)
    if gain!=1:
        if args.container!='pcm':raise ValueError('Gain comparison requires raw PCM')
        samples=array.array('h',pcm)
        samples=array.array('h',(max(-32768,min(32767,round(v*gain))) for v in samples))
        pcm=samples.tobytes()
    payload = args.wav.read_bytes() if args.container == 'wav' else pcm
    sid = str(uuid.uuid4())
    responses = []
    started = time.monotonic()
    timing={'mode':args.mode,'packetMs':args.packet_ms,'gain':gain,'audioSeconds':len(pcm)/32000}
    elapsed=lambda:round((time.monotonic()-started)*1000,1)
    async with websockets.connect(settings.ws_url, additional_headers={'X-Api-Key':settings.api_key,'X-Api-Resource-Id':settings.resource_id,'X-Api-Connect-Id':str(uuid.uuid4())}, ping_interval=None, max_size=1024*1024, open_timeout=10, close_timeout=1) as ws:
        await ws.send(request(sid,E.StartSession,args.mode))
        async with asyncio.timeout(15):
            while True:
                response=decode(await ws.recv())
                if response.event in (E.SessionFailed,E.ConnectionFailed):raise cloud_error(response)
                if response.event==E.SessionStarted:break
        timing['sessionReadyMs']=elapsed()
        async def upload():
            upload_started=time.monotonic();timing['firstPacketMs']=elapsed()
            for index in range(0,len(payload),args.packet_ms*32):
                await ws.send(request(sid,E.TaskRequest,audio=payload[index:index+args.packet_ms*32]))
                if args.container=='pcm' and 'firstSoundPacketMs' not in timing:
                    samples=array.array('h',payload[index:index+args.packet_ms*32])
                    if samples and sum(v*v for v in samples)/len(samples)>10000:
                        timing['firstSoundPacketMs']=elapsed()
                await asyncio.sleep(max(0,upload_started+(index//(args.packet_ms*32)+1)*args.packet_ms/1000-time.monotonic()))
            timing['finishSentMs']=elapsed()
            await ws.send(request(sid,E.FinishSession))
        sender=asyncio.create_task(upload())
        try:
            async with asyncio.timeout(len(pcm)/32000+30):
                async for data in ws:
                    response=decode(data)
                    record={'event':response.event,'elapsedMs':round((time.monotonic()-started)*1000),'sequence':response.response_meta.Sequence,'startMs':response.start_time,'endMs':response.end_time,'text':response.text,'statusCode':response.response_meta.StatusCode}
                    if response.event==E.UsageResponse:record['billing']=[{'unit':i.Unit,'quantity':i.Quantity} for i in response.response_meta.Billing.Items]
                    responses.append(record)
                    if response.text:
                        if response.event in (E.SourceSubtitleResponse,E.SourceSubtitleEnd):timing.setdefault('firstSourceMs',elapsed())
                        if response.event in (E.TranslationSubtitleResponse,E.TranslationSubtitleEnd):timing.setdefault('firstTranslationMs',elapsed())
                    # Test text appears only in terminal on an explicit request, never server logs.
                    print(json.dumps(record if args.show_text else {k:v for k,v in record.items() if k!='text'}|{'textLength':len(response.text)},ensure_ascii=False))
                    if response.event in (E.SessionFailed,E.ConnectionFailed):raise cloud_error(response)
                    if response.event==E.SessionFinished:break
            await sender
        finally:
            sender.cancel();await asyncio.gather(sender,return_exceptions=True)
    onset=timing.get('firstSoundPacketMs',timing['firstPacketMs'])
    for channel in ('Source','Translation'):
        if f'first{channel}Ms' in timing:
            timing[f'first{channel}AfterSoundMs']=round(timing[f'first{channel}Ms']-onset,1)
            timing[f'{channel.lower()}BeforeFinish']=timing[f'first{channel}Ms']<timing['finishSentMs']
    report=getattr(args,'latency_report',None)
    if report:
        report.parent.mkdir(parents=True,exist_ok=True)
        report.write_text(json.dumps(timing,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'latency':timing},ensure_ascii=False))
    if args.save_redacted:
        # Consistent one-to-one character substitution preserves prefixes, equality and delta evidence.
        table={};alphabet=iter(range(0xE000,0xF8FF))
        for record in responses:
            result=[]
            for c in record['text']:
                if not c.isspace() and c not in table: table[c]=chr(next(alphabet))
                result.append(c if c.isspace() else table[c])
            record['text']=''.join(result)
        path=Path('.local/probe-redacted.json');path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({'container':args.container,'packetMs':args.packet_ms,'mode':args.mode,'events':responses},ensure_ascii=False,indent=2))
        print('已将保留相等/前缀关系的脱敏样本写入 .local/probe-redacted.json；不是自动判定语义。')
    print('核对 Response 是增量还是快照、End 完整文本、PCM 封装、时间戳及计量；生产默认仍为未验证。')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wav',type=Path)
    parser.add_argument('--container',choices=['pcm','wav'],default='pcm')
    parser.add_argument('--mode',choices=['auto','zh-en','en-zh'],default='auto')
    parser.add_argument('--packet-ms',type=int,choices=[40,80],default=80)
    parser.add_argument('--gain',type=float,choices=[.25,1.,4.],default=1.,help='Public PCM sample volume comparison, in memory only')
    parser.add_argument('--latency-report',type=Path,help='Save timings only, no transcript or audio')
    parser.add_argument('--show-text',action='store_true',help='显式在终端展示短测试音频的原文/译文')
    parser.add_argument('--save-redacted',action='store_true',help='保存字符替换后的语义对比样本（不含原始文本）')
    try: asyncio.run(probe(parser.parse_args()))
    except KeyboardInterrupt: pass
    except Exception as exc:
        error=classify(exc)
        raise SystemExit(f'探测失败：{error.code} · {error.message}') from None
