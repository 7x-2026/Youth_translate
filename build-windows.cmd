@echo off
setlocal
cd /d "%~dp0"
where uv >nul 2>nul
if errorlevel 1 (
  echo uv is missing. Ask Codex to follow WINDOWS_BUILD.md first.
  pause
  exit /b 1
)
call uv run --locked --python 3.12 --group build python -m scripts.build_windows
if errorlevel 1 (
  echo Build failed. Give the error above to Codex. See WINDOWS_BUILD.md.
  pause
  exit /b 1
)
echo Ready: dist\windows\ClassroomInterpreter.exe
pause
