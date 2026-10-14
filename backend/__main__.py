import uvicorn
from backend.config import Settings
if __name__ == '__main__':
    settings = Settings.load()
    uvicorn.run('backend.app:app', host='127.0.0.1', port=settings.port, ws_max_size=4096, ws_max_queue=4, log_level='warning', access_log=False)
