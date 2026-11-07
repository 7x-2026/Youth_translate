# Build on Windows: uv run --locked --group build python -m scripts.build_windows
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

if sys.platform != 'win32':
    raise SystemExit('Windows executables must be built on Windows.')

root = Path(SPECPATH).parent
sound_data, sound_binaries, sound_imports = collect_all('soundcard')
a = Analysis(
    [str(root / 'desktop_launcher.py')],
    pathex=[str(root)],
    binaries=sound_binaries,
    # Explicit resource allowlist: never collect the project root or .env.
    datas=[
        (str(root / 'frontend/dist'), 'frontend/dist'),
        (str(root / 'terminology/anthroposophy.json'), 'terminology'),
    ] + sound_data,
    hiddenimports=sound_imports + collect_submodules('uvicorn')
        + collect_submodules('websockets') + collect_submodules('backend.generated')
        + ['backend.windows_audio', '_cffi_backend', 'numpy', 'sqlite3', 'tkinter'],
    hookspath=[],
    runtime_hooks=[],
    excludes=['pytest', 'grpc_tools'],
    noarchive=False,
)
for destination, source, kind in a.datas:
    if Path(source).name in ('.env', 'config.env', 'records.sqlite3', 'records.sqlite3-wal', 'records.sqlite3-shm'):
        raise SystemExit('Private configuration and course databases must not be bundled.')

pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='ClassroomInterpreter',
    debug=False,
    strip=False,
    upx=False,
    # Keep real stdout pipes for the audio worker; hide the launcher's console.
    console=True,
    hide_console='hide-early',
)
