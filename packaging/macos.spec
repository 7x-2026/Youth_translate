# Build with: uv run --locked --group build python -m scripts.build_macos
import platform
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

if sys.platform != 'darwin':
    raise SystemExit('macOS applications must be built on macOS.')

root = Path(SPECPATH).parent
a = Analysis(
    [str(root / 'desktop_launcher.py')],
    pathex=[str(root)],
    binaries=[],
    # Resource allowlist: never include the source tree, .env, or user data.
    datas=[
        (str(root / 'frontend/dist'), 'frontend/dist'),
        (str(root / 'terminology/anthroposophy.json'), 'terminology'),
    ],
    hiddenimports=collect_submodules('uvicorn') + collect_submodules('websockets')
        + collect_submodules('backend.generated') + ['sqlite3', 'tkinter'],
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
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='ClassroomInterpreter',
    debug=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch=platform.machine(),
)
collection = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='ClassroomInterpreter')
app = BUNDLE(
    collection,
    name='ClassroomInterpreter.app',
    icon=str(root / '.local/academy.icns'),
    bundle_identifier='com.classroomtranslate.Interpreter',
    info_plist={
        'CFBundleDisplayName': '青衿课堂同传',
        'CFBundleShortVersionString': '0.1.1',
        'CFBundleVersion': '2',
        'LSMinimumSystemVersion': '14.2',
        'NSHighResolutionCapable': True,
        'NSAudioCaptureUsageDescription': '采集所选扬声器或耳机的内部音频以生成翻译字幕，不录屏、不保存音频。',
        'NSMicrophoneUsageDescription': '课堂同传的麦克风输入由浏览器在您授权后采集，用于实时字幕。',
    },
)
