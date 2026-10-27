@echo off
setlocal
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0kinetic_lyrics.py" %*
) else if exist "%~dp0..\.venv\Scripts\python.exe" (
  "%~dp0..\.venv\Scripts\python.exe" "%~dp0kinetic_lyrics.py" %*
) else (
  python "%~dp0kinetic_lyrics.py" %*
)
exit /b %errorlevel%
