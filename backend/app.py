import asyncio
import json
import sqlite3
import sys
import time
import uuid
import anyio
from contextlib import asynccontextmanager, suppress
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from backend.config import ROOT, Settings
from backend.protocol import RelayError
from backend.session import Session
from backend.dialect import DialectSession
from backend.system_audio import SystemAudio, WindowsAudioStandby, paced_audio, supported as system_audio_supported
from backend.records import RecordStore, STATES
from backend.runtime import records_path


def create_app(settings=None, session_factory=Session, capture_factory=SystemAudio, dialect_session_factory=DialectSession, record_store=None):
    config = settings or Settings.load()
    records = record_store if record_store is not None else RecordStore(records_path())
    standby = WindowsAudioStandby() if sys.platform == 'win32' and capture_factory is SystemAudio else None
    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            try:
                if standby:
                    await standby.close()
            finally:
                await anyio.to_thread.run_sync(records.close)
    app = FastAPI(docs_url=None, redoc_url=None, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1', 'testserver'])
    active = set()
    capturing = set()
    sessions = set()

    def normalize_record(record):
        if record['state'] == 'recording' and not any(s.class_id == record['id'] for s in sessions):
            record['state'] = 'interrupted'

    def check_record_request(request):
        origin = request.headers.get('origin')
        if (origin and origin not in config.origins) or request.headers.get('sec-fetch-site') == 'cross-site':
            raise HTTPException(403, '课程记录仅供本机课堂页面读取。')

    async def read_records(request, function, *args):
        check_record_request(request)
        try:
            return await anyio.to_thread.run_sync(function, *args)
        except (OSError, sqlite3.Error):
            raise HTTPException(503, '无法读取本地课程记录，请检查磁盘空间及数据目录权限。') from None

    @app.get('/api/records')
    async def list_records(request: Request, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
        result = await read_records(request, records.list_courses, limit, offset)
        for record in result['records']:
            normalize_record(record)
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})

    @app.get('/api/records/{class_id}')
    async def get_record(class_id: str, request: Request):
        result = await read_records(request, records.get_course, class_id)
        if result is None:
            raise HTTPException(404, '课程记录不存在。')
        normalize_record(result['record'])
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})

    @app.get('/api/records/{class_id}/export')
    async def export_record(class_id: str, request: Request):
        result = await read_records(request, records.export_text, class_id)
        if result is None:
            raise HTTPException(404, '课程记录不存在。')
        name, text = result
        return Response('\ufeff' + text, media_type='text/plain; charset=utf-8', headers={
            'Content-Disposition': f'attachment; filename="{name}.txt"', 'Cache-Control': 'no-store',
        })

    @app.get('/api/health')
    async def health():
        return dict(status='ok', credentialsConfigured=bool(config.api_key), credentialSourceMismatch=config.api_key.startswith('ark-'), protocolInstalled=True, subtitleSemanticsVerified=config.response_mode != 'unverified', ready=bool(config.api_key) and not config.api_key.startswith('ark-') and config.response_mode != 'unverified', activeSessions=len(active), systemAudioSupported=system_audio_supported(), cloudWarmupSupported=True, recordsSupported=True, dialectConfigured=bool(config.dialect_configured), dialectSupported=True)

    @app.get('/api/audio-diagnostics')
    async def audio_diagnostics():
        return dict(sessions=[dict(state=s.state,mode=s.mode,epoch=s.epoch,
            queuedAudioMs=s.queue.bytes/32,**s.audio_diagnostics.snapshot()) for s in sessions])

    output_lock = asyncio.Lock()
    @app.get('/api/audio-outputs')
    async def audio_outputs():
        if not system_audio_supported():
            return dict(devices=[])
        try:
            if standby and not standby.disabled:
                try:
                    return dict(devices=await standby.outputs())
                except (OSError, ValueError, TimeoutError, RelayError):
                    pass  # Keep ordinary device enumeration on incompatible machines.
            async with output_lock:
                return dict(devices=await SystemAudio().outputs())
        except (OSError, ValueError, TimeoutError, RelayError):
            return JSONResponse(dict(devices=[], message='无法读取扬声器 / 耳机名称，请检查本机音频组件与依赖。'), status_code=503)

    @app.websocket('/ws/system-audio')
    async def system_audio(ws: WebSocket):
        if ws.headers.get('origin') not in config.origins:
            await ws.close(code=1008)
            return
        if capturing:
            await ws.close(code=1013)
            return
        capturing.add(ws)
        device_id = ws.query_params.get('device')
        if device_id is not None and (not device_id or len(device_id) > 2048):
            capturing.discard(ws)
            await ws.close(code=1008)
            return
        capture = capture_factory(device_id=device_id)
        tasks = []
        try:
            await ws.accept()
            async def stream():
                nonlocal capture
                if standby:
                    prepared = await standby.take(device_id)
                    if prepared:
                        capture = prepared
                await ws.send_json(await capture.open())
                async for packet, dropped in paced_audio(capture):
                    if dropped:
                        await asyncio.wait_for(ws.send_json(dict(type='gap', message='本机音频处理积压，已跳过旧音频；字幕可能存在缺口。')), 1)
                    await asyncio.wait_for(ws.send_bytes(packet), 1)
            async def monitor():
                # Detect closed tabs/paused capture even while the OS permission prompt is open.
                while True:
                    value = await asyncio.wait_for(ws.receive(), 30)
                    if value['type'] == 'websocket.disconnect':
                        return
                    if value.get('text') == 'stop':
                        return
                    if value.get('text') != 'heartbeat':
                        raise RelayError('control', '无效的音频采集控制消息。')
            tasks = [asyncio.create_task(stream()), asyncio.create_task(monitor())]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except RelayError as error:
            with suppress(RuntimeError, WebSocketDisconnect):
                await ws.send_json(dict(type='error', message=error.message))
        except OSError:
            with suppress(RuntimeError, WebSocketDisconnect):
                await ws.send_json(dict(type='error', message='无法启动本机音频组件，请检查依赖安装和系统音频权限。'))
        except (TimeoutError, RuntimeError, WebSocketDisconnect, asyncio.CancelledError):
            pass
        finally:
            # Closing a tab or shutting down the ASGI task must not orphan an OS tap.
            with anyio.CancelScope(shield=True):
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                try:
                    await capture.close()
                finally:
                    capturing.discard(ws)
                    if standby:
                        standby.schedule()
                    with suppress(RuntimeError, WebSocketDisconnect):
                        await ws.close()

    @app.websocket('/ws/translate')
    async def translate(ws: WebSocket):
        engine = ws.query_params.get('engine', 'standard')
        if engine not in ('standard', 'dialect'):
            await ws.close(code=1008)
            return
        if ws.headers.get('origin') not in config.origins:
            await ws.close(code=1008)
            return
        # Reserve before first await; one local class, no parallel billed sessions.
        if active:
            await ws.close(code=1013)
            return
        active.add(ws)
        session = None
        disconnected = False
        last_record = None
        failed_records = set()
        try:
            await ws.accept()
            send_lock = asyncio.Lock()
            async def emit(event):
                nonlocal last_record
                async with send_lock:
                    payload = event
                    save = event.get('type') == 'subtitle' or (not disconnected and event.get('type') == 'status' and event.get('state') in STATES)
                    if save:
                        class_id = event.get('classId')
                        try:
                            record = await anyio.to_thread.run_sync(records.save_event, event, session.mode, engine, class_id in failed_records)
                            if record is not None:
                                last_record = record
                                meta = dict(record, saveState='error' if record['incomplete'] else 'saved')
                                if record['incomplete']:
                                    meta['detail'] = '本次课程曾有保存失败，记录可能不完整；请保留页面并导出 TXT。'
                                payload = dict(event, record=meta)
                        except (OSError, sqlite3.Error):
                            failed_records.add(class_id)
                            previous = last_record if last_record and last_record['id'] == class_id else {}
                            meta = dict(previous, id=class_id, saveState='error',
                                        detail='自动保存失败，请检查磁盘空间及权限，并在关闭页面前导出 TXT。')
                            payload = dict(event, record=meta)
                    if not disconnected:
                        await asyncio.wait_for(ws.send_json(payload), 2)
            session = (dialect_session_factory if engine == 'dialect' else session_factory)(config, emit)
            sessions.add(session)
            await session.status('idle', '本机服务已连接')
            last_heartbeat = time.monotonic()
            control_times = []
            while True:
                timeout = max(.01, 30 - (time.monotonic()-last_heartbeat))
                data = await asyncio.wait_for(ws.receive(), timeout)
                if data['type'] == 'websocket.disconnect': break
                try:
                    if data.get('bytes') is not None:
                        await session.audio(data['bytes'])
                        continue
                    raw = data.get('text', '')
                    if len(raw.encode()) > 4096: raise RelayError('control_size', '控制消息过大。')
                    now = time.monotonic()
                    control_times = [t for t in control_times if now-t < 1]
                    control_times.append(now)
                    if len(control_times) > 20: raise RelayError('rate_limit', '控制消息过于频繁。')
                    control = json.loads(raw)
                    if not isinstance(control, dict): raise ValueError()
                    kind = control.get('type')
                    if kind == 'heartbeat':
                        last_heartbeat = time.monotonic()
                        await emit(dict(type='heartbeat_ack'))
                    elif kind == 'prepare':
                        session.prepare()
                    elif kind in ('start', 'resume'):
                        class_id = control.get('classId')
                        if class_id is not None:
                            if not isinstance(class_id, str): raise ValueError()
                            uuid.UUID(class_id)
                        epoch = control.get('sessionEpoch', 0)
                        if type(epoch) is not int or not 0 <= epoch < 1000000: raise ValueError()
                        await session.start(control.get('mode', 'auto'), resume=kind == 'resume', class_id=class_id, epoch=epoch)
                    elif kind in ('pause', 'stop'):
                        await session.end(pause=kind == 'pause')
                    else: raise RelayError('control', '不支持的控制消息。')
                except (ValueError, TypeError):
                    await emit(dict(type='error', code='control', message='控制消息格式错误。', retryable=False))
                except RelayError as error:
                    await emit(dict(type='error', code=error.code, message=error.message, retryable=error.retryable))
                    if error.code in ('rate_limit', 'control_size', 'audio_size'):
                        await ws.close(code=1008)
                        break
        except (WebSocketDisconnect, TimeoutError, RuntimeError):
            pass
        finally:
            disconnected = True
            with anyio.CancelScope(shield=True):
                try:
                    if session:
                        sessions.discard(session)
                        # Keep persisting received text during cleanup; skip socket sends.
                        await session.end(immediate=True)
                        if last_record:
                            with suppress(OSError, sqlite3.Error):
                                await anyio.to_thread.run_sync(records.interrupt, last_record['id'], last_record['id'] in failed_records)
                finally:
                    active.discard(ws)

    dist = ROOT / 'frontend/dist'
    if (dist/'assets').exists(): app.mount('/assets', StaticFiles(directory=dist/'assets'), name='assets')
    @app.get('/')
    async def index():
        if (dist/'index.html').exists(): return FileResponse(dist/'index.html', headers={'Cache-Control': 'no-store'})
        return JSONResponse({'message': '请先运行 cd frontend && npm run build；开发时使用 localhost:5173。'}, status_code=503)
    return app

app = create_app()
