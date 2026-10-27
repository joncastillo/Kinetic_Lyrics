@echo off
setlocal
if exist "%~dp0kinetic-lyrics\.venv\Scripts\python.exe" (
  "%~dp0kinetic-lyrics\.venv\Scripts\python.exe" "%~dp0kinetic-lyrics\studio.py" %*
) else if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0kinetic-lyrics\studio.py" %*
) else (
  python "%~dp0kinetic-lyrics\studio.py" %*
)
exit /b %errorlevel%
