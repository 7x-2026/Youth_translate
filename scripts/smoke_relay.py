"""End-to-end smoke via local relay using a short public 16kHz WAV. Prints counts only.
Usage: .venv/bin/python -m scripts.smoke_relay /tmp/translate-official-test.wav
"""
import argparse
import asyncio
import json
import time
import uuid
import wave
from pathlib import Path
import websockets

async def smoke(path):
    with wave.open(str(path),'rb') as wav:
        if (wav.getnchannels(),wav.getsampwidth(),wav.getframerate())!=(1,2,16000):raise ValueError('requires mono PCM16 16kHz WAV')
        if wav.getnframes()>16000*60:raise ValueError('requires <=60 seconds public test audio')
        pcm=wav.readframes(wav.getnframes())
    sid=str(uuid.uuid4())
    counters={'partial':0,'final':0,'sourceFinal':0,'usage':0,'errors':0,'gap':0}
    epoch=0
    ready=asyncio.Event();done=asyncio.Event()
    actual=[]
    url='ws://localhost:8765/ws/translate'
    async with websockets.connect(url,origin='http://localhost:8765',ping_interval=None,max_size=1024*1024) as ws:
        async def receive():
            nonlocal epoch
            async for wire in ws:
                event=json.loads(wire)
                if event['type']=='status':
                    if event['state']=='running':ready.set();epoch=event['sessionEpoch']
                    if event.get('gap'):counters['gap']+=1
                    if event['state']=='stopped':done.set();return
                elif event['type']=='subtitle':
                    if event['channel']=='translation':counters['final' if event['isFinal'] else 'partial']+=1
                    elif event['isFinal']:counters['sourceFinal']+=1
                    actual.append(event)
                elif event['type']=='usage':
                    counters['usage']+=1
                    if any(i['unit']=='output_audio_tokens' and i['quantity']>0 for i in event['items']):raise AssertionError('unexpected audio usage')
                elif event['type']=='error':
                    counters['errors']+=1
                    raise RuntimeError(f"relay error {event['code']}")
        receiver=asyncio.create_task(receive())
        try:
            await ws.send(json.dumps({'type':'start','mode':'auto','classId':sid,'sessionEpoch':0}))
            await asyncio.wait_for(ready.wait(),15)
            start=time.monotonic()
            for pos in range(0,len(pcm),2560):
                await ws.send(pcm[pos:pos+2560])
                await asyncio.sleep(max(0,start+(pos//2560+1)*.08-time.monotonic()))
            await ws.send(json.dumps({'type':'stop'}))
            await asyncio.wait_for(done.wait(),10)
            await receiver
            if not counters['partial'] or not counters['final'] or not counters['sourceFinal']:raise AssertionError('missing real subtitles')
            print(json.dumps({'result':'ok','classIdMatches':all(e['classId']==sid for e in actual),'epoch':epoch,'counts':counters},ensure_ascii=False))
        finally:
            receiver.cancel();await asyncio.gather(receiver,return_exceptions=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('wav',type=Path)
    args=parser.parse_args()
    asyncio.run(smoke(args.wav))
