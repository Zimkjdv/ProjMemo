@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0" || exit /b 1

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: Local environment is missing. Run setup-local.bat first.
    exit /b 1
)

".venv\Scripts\python.exe" -c "import uvicorn; from app.main import app"
if errorlevel 1 (
    echo ERROR: Local dependencies are missing or incompatible. Run setup-local.bat and resolve its errors.
    exit /b 2
)
if not "%~2"=="" goto usage
if /I "%~1"=="--check" (
    echo Local environment is ready. No packages were installed and no database was opened.
    exit /b 0
)
if not "%~1"=="" goto usage

if "%PROJMEMO_PORT%"=="" (
    for /f "delims=" %%P in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$port=8000; do { $client=New-Object Net.Sockets.TcpClient; try { $client.Connect('127.0.0.1',$port); $busy=$true } catch { $busy=$false } finally { $client.Dispose() }; if ($busy) { $port++ } } while ($busy); $port"') do set "PROJMEMO_PORT=%%P"
)

echo Starting ProjMemo on http://127.0.0.1:%PROJMEMO_PORT%/
".venv\Scripts\python.exe" -m uvicorn app.main:app --reload --host 127.0.0.1 --port %PROJMEMO_PORT%
exit /b %ERRORLEVEL%

:usage
echo Usage: run-local.bat [--check]
exit /b 2
