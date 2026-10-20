import asyncio
import json
import time
import uuid
import anyio
from contextlib import suppress
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from backend.config import ROOT, Settings
from backend.protocol import RelayError
from backend.session import Session
from backend.system_audio import SystemAudio, paced_audio, supported as system_audio_supported


def create_app(settings=None, session_factory=Session, capture_factory=SystemAudio):
    config = settings or Settings.load()
    app = FastAPI(docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1', 'testserver'])
    active = set()
    capturing = set()
    sessions = set()

    @app.get('/api/health')
    async def health():
        return dict(status='ok', credentialsConfigured=bool(config.api_key), credentialSourceMismatch=config.api_key.startswith('ark-'), protocolInstalled=True, subtitleSemanticsVerified=config.response_mode != 'unverified', ready=bool(config.api_key) and not config.api_key.startswith('ark-') and config.response_mode != 'unverified', activeSessions=len(active), systemAudioSupported=system_audio_supported(), cloudWarmupSupported=True)

    @app.get('/api/audio-diagnostics')
    async def audio_diagnostics():
        return dict(sessions=[dict(state=s.state,mode=s.mode,epoch=s.epoch,
            queuedAudioMs=s.queue.bytes/32,**s.audio_diagnostics.snapshot()) for s in sessions])

    output_lock = asyncio.Lock()
    @app.get('/api/audio-outputs')
    async def audio_outputs():
        if not system_audio_supported():
            return dict(devices=[])
        async with output_lock:
            try:
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
                await capture.close()
                capturing.discard(ws)
                with suppress(RuntimeError, WebSocketDisconnect):
                    await ws.close()

    @app.websocket('/ws/translate')
    async def translate(ws: WebSocket):
        if ws.headers.get('origin') not in config.origins:
            await ws.close(code=1008)
            return
        # Reserve before first await; one local class, no parallel billed sessions.
        if active:
            await ws.close(code=1013)
            return
        active.add(ws)
        session = None
        try:
            await ws.accept()
            send_lock = asyncio.Lock()
            async def emit(event):
                async with send_lock: await asyncio.wait_for(ws.send_json(event), 2)
            session = session_factory(config, emit)
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
            if session:
                sessions.discard(session)
                # Emit to a disconnected browser is unnecessary; cleanup must always finish.
                async def discard(_): pass
                session.emit = discard
                await session.end(immediate=True)
            active.discard(ws)

    dist = ROOT / 'frontend/dist'
    if (dist/'assets').exists(): app.mount('/assets', StaticFiles(directory=dist/'assets'), name='assets')
    @app.get('/')
    async def index():
        if (dist/'index.html').exists(): return FileResponse(dist/'index.html', headers={'Cache-Control': 'no-store'})
        return JSONResponse({'message': '请先运行 cd frontend && npm run build；开发时使用 localhost:5173。'}, status_code=503)
    return app

app = create_app()
