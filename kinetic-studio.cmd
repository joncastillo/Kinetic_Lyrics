@echo off
setlocal
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0studio.py" %*
) else (
  python "%~dp0studio.py" %*
)
exit /b %errorlevel%
