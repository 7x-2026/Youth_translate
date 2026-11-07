"""Build and smoke-test a self-contained Windows executable from the repository."""
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command, **options):
    subprocess.run(command, cwd=ROOT, check=True, **options)


def main():
    if sys.platform != 'win32' or platform.machine().lower() not in ('amd64', 'x86_64'):
        raise SystemExit('Build this release with 64-bit Python on Windows x64. See WINDOWS_BUILD.md.')
    npm = shutil.which('npm.cmd')
    if not npm:
        raise SystemExit('Node.js/npm is missing on the build computer. See WINDOWS_BUILD.md.')
    run([npm, '--prefix', 'frontend', 'ci'])
    run([npm, '--prefix', 'frontend', 'run', 'build'])
    run([npm, '--prefix', 'frontend', 'test'])
    run([sys.executable, '-m', 'pytest', '-q'])
    run([
        sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm',
        '--distpath', str(ROOT / 'dist/windows'),
        '--workpath', str(ROOT / '.local/pyinstaller-windows'),
        str(ROOT / 'packaging/windows.spec'),
    ])
    executable = ROOT / 'dist/windows/ClassroomInterpreter.exe'
    for flag in ('--self-test', '--smoke-test'):
        result = subprocess.run([str(executable), flag], cwd=ROOT, check=True,
                                capture_output=True, text=True, timeout=90)
        print(result.stdout.strip(), flush=True)
    print(f'Build complete: {executable}', flush=True)


if __name__ == '__main__':
    main()
