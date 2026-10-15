@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0" || exit /b 1

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Local environment is missing. Run setup-local.bat first.
    exit /b 1
)

".venv\Scripts\python.exe" -m app.launcher %*
exit /b %ERRORLEVEL%
