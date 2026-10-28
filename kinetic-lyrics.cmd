@echo off
setlocal
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0src\kinetic_lyrics.py" %*
) else (
  python "%~dp0src\kinetic_lyrics.py" %*
)
exit /b %errorlevel%
