import asyncio
import json
import time
import uuid
from contextlib import suppress
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from backend.config import ROOT, Settings
from backend.protocol import RelayError
from backend.session import Session


def create_app(settings=None, session_factory=Session):
    config = settings or Settings.load()
    app = FastAPI(docs_url=None, redoc_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1', 'testserver'])
    active = set()

    @app.get('/api/health')
    async def health():
        return dict(status='ok', credentialsConfigured=bool(config.api_key), credentialSourceMismatch=config.api_key.startswith('ark-'), protocolInstalled=True, subtitleSemanticsVerified=config.response_mode != 'unverified', ready=bool(config.api_key) and not config.api_key.startswith('ark-') and config.response_mode != 'unverified', activeSessions=len(active))

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
                # Emit to a disconnected browser is unnecessary; cleanup must always finish.
                async def discard(_): pass
                session.emit = discard
                await session.end(immediate=True)
            active.discard(ws)

    dist = ROOT / 'frontend/dist'
    if (dist/'assets').exists(): app.mount('/assets', StaticFiles(directory=dist/'assets'), name='assets')
    @app.get('/')
    async def index():
        if (dist/'index.html').exists(): return FileResponse(dist/'index.html')
        return JSONResponse({'message': '请先运行 cd frontend && npm run build；开发时使用 localhost:5173。'}, status_code=503)
    return app

app = create_app()
