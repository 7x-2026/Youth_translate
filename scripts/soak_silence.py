"""Real-time silence soak through production pacing + localhost relay + cloud.

Only generated silence and an explicitly supplied public WAV are sent. No live
microphone/speaker capture, and no credentials, audio or subtitle text in reports.
"""
import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid
import wave
from urllib.request import urlopen
import websockets
from backend.system_audio import paced_audio


class IdleSource:
    def __init__(self):
        self.queue = asyncio.Queue()
    async def read(self):
        return await self.queue.get()


async def soak(seconds, wav_path, port, report_path):
    pcm = b''
    if wav_path:
        with wave.open(str(wav_path), 'rb') as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
                raise ValueError('Public test WAV must be mono PCM16 at 16 kHz')
            if wav.getnframes() > 16000 * 60:
                raise ValueError('Public test WAV must be <= 60 seconds')
            pcm = wav.readframes(wav.getnframes())
    with urlopen(f'http://localhost:{port}/api/health', timeout=5) as response:
        health = json.load(response)
    if not health['ready'] or health['activeSessions']:
        raise RuntimeError('Local relay is not ready or already has a client; no test session started')

    report = dict(startedUtc=datetime.now(timezone.utc).isoformat(), result='running',
                  silenceTargetSeconds=seconds, publicSpeechSeconds=len(pcm)/32000,
                  phases={}, cloudEpochs=[], errors=[], gaps=0, unexpectedSilentSubtitles=0)
    class_id = str(uuid.uuid4())
    phase = 'connecting'
    states = Counter()
    epochs = set()
    ready, paused, stopped = asyncio.Event(), asyncio.Event(), asyncio.Event()
    failure = asyncio.get_running_loop().create_future()
    pump_task = None
    source = None
    latest_epoch = 0
    speech_first_at = None
    speech_started = None

    def save():
        report['cloudEpochs'] = sorted(epochs)
        report['states'] = dict(states)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')

    def check():
        if failure.done():
            raise RuntimeError(failure.result())

    def fail(reason):
        if not failure.done():
            failure.set_result(reason)

    def counters():
        return report['phases'].setdefault(phase, dict(packets=0, bytes=0, maxPacketGapSeconds=0.,
            sourceFinal=0, translationFinal=0, subtitleUpdates=0))

    async with websockets.connect(f'ws://localhost:{port}/ws/translate',
            origin=f'http://localhost:{port}', ping_interval=None, max_size=1024*1024) as ws:
        async def receive():
            nonlocal latest_epoch, speech_first_at
            try:
                async for raw in ws:
                    event = json.loads(raw)
                    if event['type'] == 'status':
                        state = event['state']; states[state] += 1
                        if event.get('gap'): report['gaps'] += 1
                        if state == 'running':
                            latest_epoch = event.get('sessionEpoch', latest_epoch)
                            epochs.add(latest_epoch); ready.set()
                        if state == 'paused': paused.set()
                        if state == 'stopped': stopped.set()
                        if state == 'recovering': fail('unexpected cloud reconnect')
                    elif event['type'] == 'error':
                        report['errors'].append(event.get('code'))
                        fail(f"cloud/relay error: {event.get('code')}")
                    elif event['type'] == 'subtitle' and event.get('text'):
                        counters()['subtitleUpdates'] += 1
                        if phase in ('silence', 'resumed_silence'):
                            report['unexpectedSilentSubtitles'] += 1
                        if speech_started is not None and speech_first_at is None:
                            speech_first_at = time.monotonic()
                        if event.get('isFinal'):
                            key = 'translationFinal' if event['channel'] == 'translation' else 'sourceFinal'
                            counters()[key] += 1
            except Exception as error:
                fail(type(error).__name__)

        async def heartbeat():
            while True:
                await ws.send(json.dumps(dict(type='heartbeat')))
                await asyncio.sleep(10)

        async def wait_event(event, timeout=20):
            started = time.monotonic()
            while not event.is_set():
                check()
                if time.monotonic() - started > timeout:
                    raise TimeoutError(f'{phase}: expected state was not reached')
                await asyncio.sleep(.05)
            check()

        async def pump():
            previous = None
            async for packet, dropped in paced_audio(source):
                check()
                if dropped:
                    report['gaps'] += 1
                if phase in ('silence', 'resumed_silence') and any(packet):
                    raise AssertionError('Non-silent input during silence phase')
                await ws.send(packet)
                now = time.monotonic()
                values = counters()
                values['packets'] += 1; values['bytes'] += len(packet)
                if previous is not None:
                    values['maxPacketGapSeconds'] = max(values['maxPacketGapSeconds'], now-previous)
                previous = now

        async def duration(value, progress=False):
            start = time.monotonic(); next_progress = 30
            while time.monotonic() - start < value:
                check()
                if pump_task is not None and pump_task.done():
                    pump_task.result()
                    raise RuntimeError('audio pump stopped')
                elapsed = time.monotonic() - start
                if progress and elapsed >= next_progress:
                    print(json.dumps(dict(phase=phase, elapsedSeconds=round(elapsed),
                        packets=counters()['packets'], cloudSessions=len(epochs), errors=report['errors'])), flush=True)
                    save(); next_progress += 30
                await asyncio.sleep(min(.2, max(0, value-elapsed)))
            return time.monotonic() - start

        async def stop_pump():
            nonlocal pump_task
            if pump_task:
                pump_task.cancel()
                await asyncio.gather(pump_task, return_exceptions=True)
                pump_task = None

        receiver = asyncio.create_task(receive())
        heartbeat_task = asyncio.create_task(heartbeat())
        try:
            await ws.send(json.dumps(dict(type='start', mode='auto', classId=class_id, sessionEpoch=0)))
            await wait_event(ready)
            phase = 'silence'; source = IdleSource()
            pump_task = asyncio.create_task(pump())
            print(json.dumps(dict(phase=phase, targetSeconds=seconds, cloudEpoch=latest_epoch)), flush=True)
            report['silenceActualSeconds'] = await duration(seconds, progress=True)
            if len(epochs) != 1 or report['gaps']:
                raise AssertionError('Silence did not preserve one uninterrupted cloud session')
            if pcm:
                phase = 'public_speech'; speech_started = time.monotonic()
                for pos in range(0, len(pcm), 2560):
                    check(); source.queue.put_nowait(pcm[pos:pos+2560])
                    await asyncio.sleep(max(0, speech_started+(pos//2560+1)*.08-time.monotonic()))
                await duration(8)
                values = counters()
                report['speechRecovered'] = bool(values['sourceFinal'] and values['translationFinal'])
                report['firstSubtitleAfterSpeechSeconds'] = None if speech_first_at is None else speech_first_at-speech_started
                if not report['speechRecovered']:
                    raise AssertionError('No finalized source and translation after long silence')
                print(json.dumps(dict(phase=phase, recovered=True, sourceFinal=values['sourceFinal'],
                    translationFinal=values['translationFinal'])), flush=True)
            await stop_pump()
            phase = 'paused'; await ws.send(json.dumps(dict(type='pause')))
            await wait_event(paused, 10)
            before = sum(v['packets'] for v in report['phases'].values())
            await duration(10)
            report['pauseStoppedUpload'] = before == sum(v['packets'] for v in report['phases'].values())
            phase = 'resuming'; ready.clear()
            await ws.send(json.dumps(dict(type='resume', mode='auto', classId=class_id, sessionEpoch=latest_epoch)))
            await wait_event(ready)
            phase = 'resumed_silence'; source = IdleSource(); pump_task = asyncio.create_task(pump())
            await duration(5)
            await stop_pump()
            phase = 'finishing'; await ws.send(json.dumps(dict(type='stop')))
            await wait_event(stopped, 10)
            if len(epochs) != 2 or report['errors'] or report['gaps'] or report['unexpectedSilentSubtitles']:
                raise AssertionError('Unexpected recovery, error, gap, or subtitle during silence')
            report['result'] = 'passed'
        except Exception as error:
            report['result'] = 'failed'
            report['failure'] = str(error)
            raise
        finally:
            await stop_pump()
            if not stopped.is_set():
                try:
                    await ws.send(json.dumps(dict(type='stop')))
                    await asyncio.wait_for(stopped.wait(), 7)
                except Exception:
                    pass
            receiver.cancel(); heartbeat_task.cancel()
            await asyncio.gather(receiver, heartbeat_task, return_exceptions=True)
            report['finishedUtc'] = datetime.now(timezone.utc).isoformat()
            save()
            print(json.dumps(dict(result=report['result'], report=str(report_path), errors=report['errors'])), flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=600)
    parser.add_argument('--public-wav', type=Path)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--report', type=Path, default=Path('.local/silence-soak.json'))
    args = parser.parse_args()
    if not 1 <= args.seconds <= 3600:
        parser.error('--seconds must be between 1 and 3600')
    asyncio.run(soak(args.seconds, args.public_wav, args.port, args.report))
