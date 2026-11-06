from dataclasses import dataclass, field
from pathlib import Path
import os
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')

@dataclass(frozen=True)
class Settings:
    api_key: str = ''
    resource_id: str = 'volc.service_type.10053'
    ws_url: str = 'wss://openspeech.bytedance.com/api/v4/ast/v2/translate'
    response_mode: str = 'unverified'
    port: int = 8765
    tencent_app_id: str = ''
    tencent_secret_id: str = field(default='', repr=False)
    tencent_secret_key: str = field(default='', repr=False)
    tokenhub_api_key: str = field(default='', repr=False)

    @property
    def dialect_configured(self):
        return self.tencent_app_id.isascii() and self.tencent_app_id.isdigit() and all((self.tencent_secret_id, self.tencent_secret_key, self.tokenhub_api_key))

    @classmethod
    def load(cls):
        value = cls(os.getenv('VOLC_API_KEY', '').strip(), os.getenv('VOLC_RESOURCE_ID', 'volc.service_type.10053'), os.getenv('VOLC_WS_URL', 'wss://openspeech.bytedance.com/api/v4/ast/v2/translate'), os.getenv('VOLC_SUBTITLE_RESPONSE_MODE', 'unverified'), int(os.getenv('PORT', '8765')),
            tencent_app_id=os.getenv('TENCENT_ASR_APP_ID', '').strip(),
            tencent_secret_id=os.getenv('TENCENT_SECRET_ID', '').strip(),
            tencent_secret_key=os.getenv('TENCENT_SECRET_KEY', '').strip(),
            tokenhub_api_key=os.getenv('TOKENHUB_API_KEY', '').strip())
        if value.ws_url != 'wss://openspeech.bytedance.com/api/v4/ast/v2/translate':
            raise ValueError('VOLC_WS_URL must be the official AST WSS endpoint')
        if value.response_mode not in ('unverified', 'delta', 'snapshot'):
            raise ValueError('VOLC_SUBTITLE_RESPONSE_MODE must be unverified, delta or snapshot')
        if os.getenv('HOST', '127.0.0.1') != '127.0.0.1':
            raise ValueError('HOST must remain 127.0.0.1')
        return value

    @property
    def origins(self):
        return {f'http://{host}:{port}' for host in ('localhost', '127.0.0.1') for port in (self.port, 5173)}
