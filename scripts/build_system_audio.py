"""Build the local macOS audio-only helper. Does not install drivers or change audio settings."""
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / '.local/system-audio/TranslatorAudio.app'
BINARY = APP / 'Contents/MacOS/TranslatorAudio'


def build(app=APP, arch=None, minimum_version='14.2'):
    if platform.system() != 'Darwin':
        raise RuntimeError('此构建只用于 macOS；Windows 使用 WASAPI，无需编译此程序。')
    if not shutil.which('swiftc'):
        raise RuntimeError('需要 Apple Command Line Tools。安装后运行 python -m scripts.build_system_audio。')
    app = Path(app)
    binary = app / 'Contents/MacOS/TranslatorAudio'
    binary.parent.mkdir(parents=True, exist_ok=True)
    cache = ROOT / '.local/swift-module-cache'
    cache.mkdir(parents=True, exist_ok=True)
    plist = dict(CFBundleIdentifier='com.classroomtranslate.SystemAudio', CFBundleName='课堂同传音频采集',
                 CFBundleExecutable='TranslatorAudio', CFBundlePackageType='APPL', CFBundleVersion='1',
                 LSUIElement=True, LSMinimumSystemVersion=minimum_version,
                 NSAudioCaptureUsageDescription='采集电脑内部的会议或音乐音频以生成翻译字幕，不录制屏幕，不改变声音播放。')
    info = app / 'Contents/Info.plist'
    info.write_bytes(plistlib.dumps(plist))
    target = ['-target', f'{arch}-apple-macosx{minimum_version}'] if arch else []
    subprocess.run(['swiftc', '-O', '-swift-version', '5', '-module-cache-path', str(cache),
                    *target, str(ROOT / 'native/SystemAudio.swift'), '-o', str(binary)], check=True)
    subprocess.run(['codesign', '--force', '--sign', '-', '--identifier', plist['CFBundleIdentifier'], str(app)], check=True)
    return binary


if __name__ == '__main__':
    print(build())
