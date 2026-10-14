from pathlib import Path
from dotenv import dotenv_values
import pytest

def test_frontend_bundle_does_not_contain_server_credential():
    root=Path(__file__).resolve().parents[1]
    dist=root/'frontend/dist'
    if not dist.exists():pytest.skip('先构建前端，再运行产物检查')
    key=dotenv_values(root/'.env').get('VOLC_API_KEY','')
    assert not dotenv_values(root/'.env.example').get('VOLC_API_KEY',''), '配置样例必须保持无真实密钥'
    for path in dist.rglob('*'):
        if path.is_file():
            content=path.read_bytes()
            assert b'X-Api-Key' not in content, '云端鉴权不应打包到前端'
            if key and len(key)>=8:assert key.encode() not in content, '前端构建产物含服务端凭证'
