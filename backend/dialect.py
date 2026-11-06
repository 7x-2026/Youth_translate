"""Optional Tencent ASR + TokenHub translation; no audio capture or persistence."""
import asyncio
import base64
import hashlib
import hmac
import http.client
import json
import secrets
import time
import uuid
from urllib.parse import urlencode

import websockets
from websockets.exceptions import InvalidStatus
from backend.audio_diagnostics import AudioDiagnostics
from backend.protocol import LANGUAGES, RelayError
from backend.session import Session, classify


def asr_url(settings, voice_id, now=None, nonce=None):
    now = int(time.time()) if now is None else now
    params = dict(engine_model_type='16k_zh_en', expired=now+3600,
                  needvad=1, nonce=secrets.randbelow(10**9) if nonce is None else nonce,
                  secretid=settings.tencent_secret_id, timestamp=now,
                  voice_format=1, voice_id=voice_id, filter_empty_result=0,
                  max_speak_time=5000)
    host_path = f'asr.cloud.tencent.com/asr/v2/{settings.tencent_app_id}'
    canonical = host_path+'?'+'&'.join(f'{k}={v}' for k, v in sorted(params.items()))
    signature = base64.b64encode(hmac.new(settings.tencent_secret_key.encode(),
        canonical.encode(), hashlib.sha1).digest()).decode()
    return 'wss://'+host_path+'?'+urlencode({**params, 'signature': signature})


def asr_message(data):
    try:
        value = json.loads(data)
        if not isinstance(value, dict) or type(value.get('code')) is not int:
            raise ValueError()
    except (ValueError, TypeError):
        raise RelayError('dialect_protocol', '方言识别服务返回了无效消息。') from None
    code = value['code']
    if code:
        detail = {4002:'鉴权失败，请核对腾讯云凭证', 4003:'尚未开通实时语音识别',
                  4004:'识别资源包耗尽', 4005:'账户欠费', 4006:'并发额度不足',
                  4008:'音频上传超时'}.get(code, '请核对识别服务状态与参数')
        raise RelayError(f'dialect_asr_{code}', f'方言识别失败（{code}）：{detail}。', code in (5000, 5001))
    return value


def translation_target(text, mode):
    if mode == 'zh-en': return '英语'
    if mode == 'en-zh': return '中文'
    return '英语' if any('\u3400' <= c <= '\u9fff' for c in text) else '中文'


def translate_sync(settings, text, target):
    # Fixed first-party HTTPS endpoint. No redirects, arbitrary URLs or SDK dependency.
    payload = json.dumps(dict(model='hy-mt2-lite', stream=False,
        messages=[dict(role='user', content=f'将以下文本翻译为{target}，只输出译文，不要解释：\n{text}')]),
        ensure_ascii=False).encode()
    connection = http.client.HTTPSConnection('tokenhub.tencentmaas.com', timeout=8)
    try:
        connection.request('POST', '/v1/chat/completions', body=payload,
            headers={'Content-Type':'application/json',
                     'Authorization':'Bearer '+settings.tokenhub_api_key})
        response = connection.getresponse()
        data = response.read(262145)
        if response.status != 200:
            raise RelayError('dialect_translation', f'方言模式翻译请求失败（HTTP {response.status}），请核对 TokenHub 权限、余额与网络。')
        if len(data)>262144: raise ValueError()
        value = json.loads(data)
        choice = value['choices'][0]
        result = choice['message']['content']
        if choice.get('finish_reason') != 'stop' or not isinstance(result, str) or not result.strip():
            raise ValueError()
        return result.strip()
    except RelayError:
        raise
    except (ValueError, KeyError, IndexError, TypeError):
        raise RelayError('dialect_translation', '方言模式翻译返回不完整或格式异常，请重试。') from None
    except (OSError, http.client.HTTPException):
        raise RelayError('dialect_translation', '方言模式翻译连接失败或超时，请检查网络后重试。') from None
    finally:
        connection.close()


async def translate(settings, text, target):
    return await asyncio.to_thread(translate_sync, settings, text, target)


class DialectSession(Session):
    """Reuse bounded audio queue/stop deadline; isolate the optional cloud path."""
    def __init__(self, settings, emit, connector=websockets.connect, translator=translate):
        super().__init__(settings, emit, connector)
        self.translator = translator

    def prepare(self):
        pass  # Never warm either vendor before an explicit, configured start.

    async def start(self, mode='auto', resume=False, class_id=None, epoch=0):
        if self.wanted or (self.task and not self.task.done()): return
        if mode not in LANGUAGES: raise RelayError('parameter', '无效翻译方向。')
        if resume and self.state != 'paused': return
        if not self.settings.dialect_configured:
            raise RelayError('dialect_not_configured', '方言模式尚未配置腾讯云 ASR 与 TokenHub 凭证，请参照用户指南配置后重启服务。')
        if not resume:
            self.class_id, self.epoch = class_id or str(uuid.uuid4()), epoch
        self.mode, self.wanted = mode, True
        self.queue.clear()
        self.tokens, self.token_time = 64000.0, time.monotonic()
        self.task = asyncio.create_task(self.run())

    async def run(self):
        attempt = 0
        while self.wanted:
            self.epoch += 1
            self.audio_diagnostics = AudioDiagnostics()
            self.finish, self.finished = asyncio.Event(), asyncio.Event()
            await self.status('connecting' if not attempt else 'recovering', '正在连接方言识别服务…')
            try:
                await self.connection()
                if self.wanted: raise RelayError('network', '方言识别连接结束，正在恢复。', True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if isinstance(exc, InvalidStatus):
                    status = exc.response.status_code
                    error = RelayError('dialect_handshake', f'方言识别握手失败（HTTP {status}），请核对腾讯云 ASR 权限与网络。', status>=500)
                else:
                    error = classify(exc)
                if not self.wanted: break
                await self.emit(dict(type='error', code=error.code, message=error.message, retryable=error.retryable))
                if not error.retryable:
                    self.wanted = False
                    await self.status('error', error.message)
                    break
                if self.state == 'running': attempt = 0
                await self.status('recovering', '方言识别连接中断，正在恢复；未发送音频已清空。')
                await self.gap('方言识别连接中断，期间内容可能缺失。')
                self.queue.clear()
                await asyncio.sleep(min(10, .5*2**min(attempt, 5)))
                attempt += 1
            finally:
                self.upstream = None
                self.queue.clear()

    async def connection(self):
        jobs = asyncio.Queue(maxsize=4)
        url = asr_url(self.settings, str(uuid.uuid4()))
        async with self.connector(url, ping_interval=None, open_timeout=10, close_timeout=1,
                                  max_size=262144, max_queue=8, write_limit=6400) as ws:
            self.upstream = ws
            ready = asr_message(await asyncio.wait_for(ws.recv(), 10))
            if ready.get('result') or ready.get('final'):
                raise RelayError('dialect_protocol', '方言识别握手响应异常。')
            if not self.wanted: return
            await self.status('running', '方言模式：正在识别，按句翻译')
            tasks = [asyncio.create_task(self.sender(ws)),
                     asyncio.create_task(self.receiver(ws, jobs)),
                     asyncio.create_task(self.translation_worker(jobs))]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done: task.result()
                if self.finish.is_set():
                    await tasks[0]
                    await tasks[1]
                    # Surface worker errors while waiting for outstanding translations.
                    joined = asyncio.create_task(jobs.join())
                    try:
                        complete, _ = await asyncio.wait([joined, tasks[2]], return_when=asyncio.FIRST_COMPLETED)
                        for task in complete: task.result()
                    finally:
                        joined.cancel()
                        await asyncio.gather(joined, return_exceptions=True)
                else:
                    raise RelayError('network', '方言识别连接中断。', True)
            finally:
                for task in tasks: task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    async def sender(self, ws):
        pending = bytearray()
        while not self.finish.is_set() or not self.queue.items.empty():
            try: packet = await asyncio.wait_for(self.queue.get(), .08)
            except TimeoutError: continue
            pending.extend(packet)
            while len(pending)>=6400:
                frame = bytes(pending[:6400]); del pending[:6400]
                await asyncio.wait_for(ws.send(frame), 2)
                self.audio_diagnostics.send(frame)
        if pending:
            frame = bytes(pending)
            await asyncio.wait_for(ws.send(frame), 2)
            self.audio_diagnostics.send(frame)
        await ws.send(json.dumps(dict(type='end')))

    async def receiver(self, ws, jobs):
        last_final, revision = -1, 0
        async for raw in ws:
            if not (self.wanted or self.finish.is_set()): return
            data = asr_message(raw)
            result = data.get('result')
            if result is not None:
                if not isinstance(result, dict): raise RelayError('dialect_protocol', '方言识别结果格式异常。')
                index, kind, text = result.get('index'), result.get('slice_type'), result.get('voice_text_str')
                if type(index) is not int or index<0 or kind not in (0, 1, 2) or not isinstance(text, str) or len(text)>8000:
                    raise RelayError('dialect_protocol', '方言识别结果格式异常。')
                if index>last_final and text.strip():
                    revision += 1
                    event = dict(type='subtitle', classId=self.class_id, sessionEpoch=self.epoch,
                        segmentId=f'asr-{index}', channel='source', revision=revision, text=text, isFinal=kind==2)
                    self.audio_diagnostics.subtitle('source')
                    await self.emit(event)
                    if kind==2:
                        last_final = index
                        if jobs.full():
                            jobs.get_nowait(); jobs.task_done()
                            await self.gap('翻译处理积压，已跳过最早的待译句；对应原文仍保留。')
                        jobs.put_nowait(event)
            if data.get('final')==1:
                self.finished.set()
                return

    async def translation_worker(self, jobs):
        while True:
            event = await jobs.get()
            try:
                # Extremely long utterances are explicitly rejected, never silently truncated.
                if len(event['text'])>2000:
                    raise RelayError('dialect_translation_size', '单句文字过长，方言模式未翻译该句；请分句后重试。')
                text = await self.translator(self.settings, event['text'], translation_target(event['text'], self.mode))
                if event['sessionEpoch']==self.epoch and (self.wanted or self.finish.is_set()):
                    self.audio_diagnostics.subtitle('translation')
                    await self.emit({**event, 'channel':'translation', 'text':text})
            finally:
                jobs.task_done()
