"""Generate checked-in bindings from unmodified official .proto definitions."""
from pathlib import Path
import subprocess
import sys
root = Path(__file__).resolve().parents[1]
source = root / 'protocol/protos'
out = root / 'backend/generated'
out.mkdir(parents=True, exist_ok=True)
subprocess.run([sys.executable, '-m', 'grpc_tools.protoc', f'-I{source}', f'--python_out={out}', *map(str, sorted(source.rglob('*.proto')))], check=True)
# Package-local imports avoid polluting sys.path with official generic package names.
for path in out.rglob('*_pb2.py'):
    text = path.read_text().replace('from common import ', 'from backend.generated.common import ').replace('from products.understanding.base import ', 'from backend.generated.products.understanding.base import ')
    path.write_text(text)
    for parent in [path.parent, *path.parent.parents]:
        if parent == out.parent: break
        (parent / '__init__.py').touch()
