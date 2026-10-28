@echo off
setlocal
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0src\studio.py" %*
) else (
  python "%~dp0src\studio.py" %*
)
exit /b %errorlevel%
