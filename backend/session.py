import asyncio
import random
import time
import uuid
from contextlib import suppress
import websockets
from websockets.exceptions import InvalidStatus, ConnectionClosed
from backend.protocol import E, LANGUAGES, RelayError, Normalizer, cloud_error, decode, request
from backend.audio_diagnostics import AudioDiagnostics
from backend.cloud_warmup import CloudWarmup

MAX_QUEUE_BYTES = 48000  # 1.5 s; browser reserves at most 0.5 s.

class AudioQueue:
    def __init__(self):
        self.items = asyncio.Queue()
        self.bytes = 0
    def push(self, packet):
        dropped = 0
        while self.bytes + len(packet) > MAX_QUEUE_BYTES and not self.items.empty():
            old = self.items.get_nowait()
            self.bytes -= len(old)
            dropped += len(old)
        self.items.put_nowait(packet)
        self.bytes += len(packet)
        return dropped
    async def get(self):
        value = await self.items.get()
        self.bytes -= len(value)
        return value
    def clear(self):
        while not self.items.empty(): self.items.get_nowait()
        self.bytes = 0

class Session:
    def __init__(self, settings, emit, connector=websockets.connect):
        self.settings, self.emit, self.connector = settings, emit, connector
        self.class_id = str(uuid.uuid4())
        self.epoch = 0
        self.state = 'idle'
        self.wanted = False
        self.task = None
        self.upstream = None
        self.queue = AudioQueue()
        self.finish = asyncio.Event()
        self.finished = asyncio.Event()
        self.mode = 'auto'
        self.last_gap = 0
        self.tokens, self.token_time = 64000.0, time.monotonic()
        self.usage = []
        self.audio_diagnostics=AudioDiagnostics()
        self.cloud_warmup=CloudWarmup(self.new_connection)

    def new_connection(self):
        return self.connector(self.settings.ws_url, additional_headers={'X-Api-Key': self.settings.api_key, 'X-Api-Resource-Id': self.settings.resource_id, 'X-Api-Connect-Id': str(uuid.uuid4())}, ping_interval=None, open_timeout=10, close_timeout=1, max_size=1024*1024, max_queue=8, write_limit=2560)

    def prepare(self):
        if self.wanted or (self.task and not self.task.done()):return
        if not self.settings.api_key or self.settings.api_key.startswith('ark-') or self.settings.response_mode=='unverified':return
        self.cloud_warmup.prepare()

    async def status(self, state, detail=''):
        self.state = state
        await self.emit(dict(type='status', state=state, detail=detail, classId=self.class_id, sessionEpoch=self.epoch))

    async def start(self, mode='auto', resume=False, class_id=None, epoch=0):
        if self.wanted or (self.task and not self.task.done()): return
        if mode not in LANGUAGES: raise RelayError('parameter', '无效翻译方向。')
        if resume and self.state != 'paused': return
        if not self.settings.api_key: raise RelayError('not_configured', '尚未配置 VOLC_API_KEY。请编辑本机 .env 后重启服务。')
        if self.settings.api_key.startswith('ark-'): raise RelayError('wrong_key_type', '当前是火山方舟 ark- Key；同传接口需要豆包语音新版控制台的 API Key。')
        if self.settings.response_mode == 'unverified': raise RelayError('semantics_unverified', '官方协议已安装；请先运行协议探测，确认音频封装与字幕 Response 语义后配置 .env。')
        if not resume and self.state in ('idle', 'stopped', 'error', 'paused'):
            self.class_id, self.epoch, self.usage = class_id or str(uuid.uuid4()), epoch, []
        self.mode, self.wanted = mode, True
        self.queue.clear()
        self.tokens, self.token_time = 64000.0, time.monotonic()
        self.task = asyncio.create_task(self.run())

    async def gap(self, detail):
        if time.monotonic() - self.last_gap > 1:
            self.last_gap = time.monotonic()
            await self.emit(dict(type='status', state=self.state, detail=detail, gap=True, classId=self.class_id, sessionEpoch=self.epoch))

    async def audio(self, packet):
        if not packet or len(packet) > 2560 or len(packet) % 2:
            raise RelayError('audio_size', '音频包必须是最多 2560 字节的 PCM16 单声道数据。')
        if not self.wanted or self.state not in ('running', 'muted'): return
        now = time.monotonic()
        self.tokens = min(64000, self.tokens + (now-self.token_time)*40000)
        self.token_time = now
        if len(packet) > self.tokens: raise RelayError('rate_limit', '音频上传超过允许速率。')
        self.tokens -= len(packet)
        self.audio_diagnostics.receive(packet)
        if self.queue.push(packet): await self.gap('音频积压：已丢弃最旧的未发送音频，字幕可能存在缺口。')

    async def run(self):
        attempt = 0
        while self.wanted:
            self.epoch += 1
            self.audio_diagnostics=AudioDiagnostics()
            self.finish, self.finished = asyncio.Event(), asyncio.Event()
            normalizer = Normalizer(self.class_id, self.epoch, self.settings.response_mode)
            await self.status('connecting' if attempt == 0 else 'recovering', '正在建立云端会话…')
            try:
                await self.connection(normalizer)
                if self.wanted: raise RelayError('network', '云端连接结束，正在恢复；期间内容可能缺失。', True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if not self.wanted: break
                error = classify(exc)
                await self.emit(dict(type='error', code=error.code, message=error.message, retryable=error.retryable))
                if not error.retryable:
                    self.wanted = False
                    await self.status('error', error.message)
                    break
                attempt = 0 if self.state in ('running', 'muted') else attempt
                await self.status('recovering', '连接中断，正在恢复；未发送音频已清空，字幕可能存在缺口。')
                await self.gap('连接中断，期间内容可能缺失。')
                delay = min(10, .5 * 2**min(attempt, 5)) * random.uniform(.85, 1.15)
                attempt += 1
                await asyncio.sleep(min(delay, 10))
            finally:
                self.upstream = None
                self.queue.clear()

    async def connection(self, normalizer):
        session_id = str(uuid.uuid4())
        # Official Python Demo disables automatic Ping; no fabricated business heartbeat.
        async with self.cloud_warmup.connection() as ws:
            self.upstream = ws
            await ws.send(request(session_id, E.StartSession, self.mode))
            async with asyncio.timeout(15):
                while True:
                    msg = decode(await ws.recv())
                    if msg.event in (E.SessionFailed, E.ConnectionFailed): raise cloud_error(msg)
                    if msg.event == E.SessionStarted: break
            if not self.wanted: return
            await self.status('running', '正在翻译')
            sender = asyncio.create_task(self.sender(ws, session_id))
            receiver = asyncio.create_task(self.receiver(ws, normalizer, session_id))
            try:
                done, _ = await asyncio.wait([sender, receiver], return_when=asyncio.FIRST_COMPLETED)
                for task in done: task.result()
                if self.finish.is_set():
                    await receiver
                else:
                    raise RelayError('network', '云端连接中断。', True)
            finally:
                for task in (sender, receiver): task.cancel()
                await asyncio.gather(sender, receiver, return_exceptions=True)

    async def sender(self, ws, session_id):
        while not self.finish.is_set() or not self.queue.items.empty():
            try: packet = await asyncio.wait_for(self.queue.get(), .08)
            except TimeoutError: continue
            await asyncio.wait_for(ws.send(request(session_id, E.TaskRequest, audio=packet)), 2)
            self.audio_diagnostics.send(packet)
        await ws.send(request(session_id, E.FinishSession))

    async def receiver(self, ws, normalizer, session_id):
        async for data in ws:
            msg = decode(data)
            if msg.response_meta.SessionID and msg.response_meta.SessionID != session_id: continue
            if msg.event in (E.SessionFailed, E.ConnectionFailed, E.SessionCanceled): raise cloud_error(msg)
            if msg.event == E.SessionFinished:
                self.finished.set()
                return
            if msg.event == E.AudioMuted and self.wanted:
                self.audio_diagnostics.cloud_muted_ms=msg.muted_duration_ms
                await self.status('muted', '云端暂未检测到语音；音频输入仍在采集')
            event = normalizer.feed(msg)
            if event:
                if event['text']:self.audio_diagnostics.subtitle(event['channel'])
                if self.state == 'muted' and self.wanted: await self.status('running', '正在翻译')
                await self.emit(event)
            if msg.event == E.UsageResponse:
                # Keep the latest raw billing report only; cumulative semantics unverified.
                billing = msg.response_meta.Billing
                self.usage = [{'unit': item.Unit, 'quantity': item.Quantity} for item in billing.Items]
                await self.emit(dict(type='usage', items=self.usage, durationMs=billing.DurationMsec))
                if any(item['unit'] == 'output_audio_tokens' and item['quantity'] > 0 for item in self.usage):
                    raise RelayError('unexpected_audio_usage', 'S2T 返回了音频输出计量；请核对资源与账单。')
            if msg.data: raise RelayError('unexpected_audio', 'S2T 意外返回音频，请核对接口配置。')

    async def end(self, pause=False, immediate=False):
        self.wanted = False
        await self.cloud_warmup.close()
        if pause or immediate: self.queue.clear()
        if self.task and not self.task.done():
            if self.state in ('running', 'muted') and not immediate:
                await self.status('finishing', '正在接收最后字幕（最多 5 秒）…')
                self.finish.set()
                try: await asyncio.wait_for(asyncio.shield(self.task), 5)
                except TimeoutError:
                    await self.emit(dict(type='status', state='finishing', detail='收尾超时，剩余字幕标为未定稿。'))
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        self.queue.clear()
        await self.status('paused' if pause else 'stopped', '已暂停，音频输入已释放' if pause else '课程已结束')


def classify(exc):
    if isinstance(exc, RelayError): return exc
    if isinstance(exc, InvalidStatus):
        code = exc.response.status_code
        if code == 403 and b'requested resource not granted' in (exc.response.body or b''):
            return RelayError('resource_not_granted', '当前项目未获授予同声传译2.0资源。请在豆包语音控制台的开通管理中核对模型状态。')
        if code in (401, 403):
            return RelayError(f'http_{code}', f'云端鉴权或资源权限失败（HTTP {code}）。请核对豆包语音 API Key、项目和资源状态。')
        return RelayError(f'http_{code}', f'云端握手失败（HTTP {code}），请检查资源权限、余额或额度。', code >= 500)
    if isinstance(exc, (OSError, TimeoutError, ConnectionClosed)):
        return RelayError('network', '网络连接失败，正在自动恢复；期间字幕可能存在缺口。', True)
    return RelayError('protocol', '云端协议或会话发生未知错误，请检查官方协议版本。')
