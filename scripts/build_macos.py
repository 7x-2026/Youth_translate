"""Build, relocate, verify and package a self-contained macOS application."""
import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.build_system_audio import build as build_audio

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.1.1'
PRIVATE_FILES = {'.env', 'config.env', 'records.sqlite3', 'records.sqlite3-wal', 'records.sqlite3-shm'}


def run(command, **options):
    return subprocess.run([str(item) for item in command], cwd=ROOT, check=True, **options)


def verify_application(app, arch):
    """Use only isolated databases, and list devices without recording sound."""
    if any(path.name in PRIVATE_FILES for path in app.rglob('*')):
        raise RuntimeError('Private configuration or course databases found in application')
    executable = app / 'Contents/MacOS/ClassroomInterpreter'
    helper = app / 'Contents/Helpers/TranslatorAudio.app/Contents/MacOS/TranslatorAudio'
    for binary in (executable, helper):
        run(['lipo', '-verify_arch', arch, binary])
    run(['codesign', '--verify', '--deep', '--strict', app])
    # No project directory, cloud credentials or developer Python paths inherited.
    environment = {key: value for key, value in os.environ.items()
                   if key in {'HOME', 'PATH', 'TMPDIR', 'LANG', 'LC_ALL', 'USER', 'LOGNAME'}}
    with TemporaryDirectory(prefix='课堂同传 relocation ', dir=ROOT / '.local') as temporary:
        relocated = Path(temporary) / '独立应用 ClassroomInterpreter.app'
        shutil.copytree(app, relocated, symlinks=True)
        relocated_exe = relocated / 'Contents/MacOS/ClassroomInterpreter'
        results = []
        for flag, field in (('--self-test', 'selfTest'), ('--smoke-test', 'smokeTest')):
            process = subprocess.run([str(relocated_exe), flag], cwd=temporary,
                                     env=environment, capture_output=True, text=True, timeout=120)
            if process.returncode:
                raise RuntimeError(f'Packaged check failed: {flag}\n{process.stdout}\n{process.stderr}')
            result = json.loads(process.stdout)
            if result.get(field) != 'ok':
                raise RuntimeError(f'Packaged check failed: {flag}')
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-checks', action='store_true', help='Reuse already built and tested frontend for a second architecture')
    args = parser.parse_args(argv)
    arch = platform.machine().lower()
    if sys.platform != 'darwin' or arch not in ('arm64', 'x86_64'):
        raise SystemExit('Build with macOS Python 3.12 for arm64 or x86_64. See MACOS_BUILD.md.')
    for tool in ('npm', 'swiftc', 'codesign', 'sips', 'ditto', 'hdiutil', 'lipo'):
        if not shutil.which(tool):
            raise SystemExit(f'Missing build tool: {tool}. See MACOS_BUILD.md.')
    (ROOT / '.local').mkdir(exist_ok=True)
    os.environ.setdefault('PYINSTALLER_CONFIG_DIR', str(ROOT / '.local/pyinstaller-cache'))
    if not args.skip_checks:
        run(['npm', '--prefix', 'frontend', 'ci'])
        run(['npm', '--prefix', 'frontend', 'run', 'build'])
        run(['npm', '--prefix', 'frontend', 'test'])
        run([sys.executable, '-m', 'pytest', '-q'])

    run(['sips', '-s', 'format', 'icns', ROOT / 'frontend/public/assets/academy.ico',
         '--out', ROOT / '.local/academy.icns'], capture_output=True)
    helper_app = ROOT / f'.local/macos-{arch}/TranslatorAudio.app'
    build_audio(app=helper_app, arch=arch)
    destination = ROOT / f'dist/macos-{arch}'
    run([sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm',
         '--distpath', destination, '--workpath', ROOT / f'.local/pyinstaller-macos-{arch}',
         ROOT / 'packaging/macos.spec'])
    app = destination / 'ClassroomInterpreter.app'
    embedded_helper = app / 'Contents/Helpers/TranslatorAudio.app'
    embedded_helper.parent.mkdir(exist_ok=True)
    shutil.copytree(helper_app, embedded_helper, dirs_exist_ok=True, symlinks=True)
    run(['codesign', '--force', '--sign', '-', app])
    results = verify_application(app, arch)

    archive = destination / f'ClassroomInterpreter-macOS-{arch}-{VERSION}.zip'
    archive.unlink(missing_ok=True)
    run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', app, archive])
    image = destination / f'ClassroomInterpreter-macOS-{arch}-{VERSION}.dmg'
    image.unlink(missing_ok=True)
    with TemporaryDirectory(prefix=f'dmg-{arch}-', dir=ROOT / '.local') as temporary:
        staging = Path(temporary)
        shutil.copytree(app, staging / app.name, symlinks=True)
        (staging / 'Applications').symlink_to('/Applications', target_is_directory=True)
        (staging / '安装与使用.txt').write_text(
            '青衿课堂同传 · macOS 14.2 或更新版本\n\n'
            f'本安装包适用于 {"Apple 芯片（M 系列）" if arch == "arm64" else "Intel 芯片"} Mac。\n'
            '请将 ClassroomInterpreter.app 拖到 Applications，再从应用程序中打开。\n'
            '首次填写您自己的豆包语音 API Key，程序会自动打开浏览器中的课堂。\n'
            '以后点击启动器右上角的“更换 API Key”重新填写，保存后刷新课堂网页即可。\n'
            '启动器下方为“开始课堂”和“退出课堂”；结束后点击“退出课堂”。\n\n'
            '当前为本地签名版本，尚未经过 Apple 公证。下载后若系统阻止打开，\n'
            '确认来源后，在系统设置 → 隐私与安全性中选择“仍要打开”。\n'
            '麦克风授权在浏览器完成；内部音频需要允许系统音频录制。\n'
            '配置和新课程保存在 ~/Library/Application Support/ClassroomInterpreter/。\n'
            '源码版的 .env 和历史课程不会自动迁入；更新应用会保留应用版数据。\n'
            '翻译需要联网与已开通服务的 Key，可能产生云端费用。\n', encoding='utf-8')
        run(['hdiutil', 'create', '-volname', f'青衿课堂同传 {VERSION}', '-srcfolder', staging,
             '-format', 'UDZO', '-ov', image])
    checksums = []
    for artifact in (archive, image):
        with artifact.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        checksums.append(f'{digest}  {artifact.name}')
    (destination / 'SHA256SUMS.txt').write_text('\n'.join(checksums) + '\n', encoding='utf-8')
    (destination / 'verification.json').write_text(json.dumps({'architecture': arch, 'checks': results}, indent=2) + '\n', encoding='utf-8')
    print(f'Build complete: {image}', flush=True)


if __name__ == '__main__':
    main()
