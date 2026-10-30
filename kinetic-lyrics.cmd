@echo off
setlocal
rem The Python packages live in src\; -P keeps the current folder off the import path.
if defined PYTHONPATH (set "PYTHONPATH=%~dp0src;%PYTHONPATH%") else (set "PYTHONPATH=%~dp0src")
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" -P -m pipeline.cli %*
) else (
  python -P -m pipeline.cli %*
)
exit /b %errorlevel%
