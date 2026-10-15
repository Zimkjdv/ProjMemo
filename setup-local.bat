@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0" || exit /b 1

if not exist ".venv\Scripts\python.exe" (
    echo Creating the local virtual environment...
    call py -3 -m venv .venv
    if errorlevel 1 goto venv_failed
)
if not exist ".venv\Scripts\python.exe" goto venv_failed

".venv\Scripts\python.exe" -m pip --version
if errorlevel 1 goto pip_failed
".venv\Scripts\python.exe" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto install_failed
".venv\Scripts\python.exe" -c "import uvicorn; from app.main import app"
if errorlevel 1 goto install_failed
echo Setup complete. Use run-local.bat for daily startup.
exit /b 0

:venv_failed
echo ERROR: Could not create .venv. Install Python and its Windows py launcher, then retry.
exit /b 1
:pip_failed
echo ERROR: pip is unavailable in .venv. Repair the virtual environment before retrying setup.
exit /b 2
:install_failed
echo ERROR: Dependency installation or verification failed. The application was not started.
exit /b 3
