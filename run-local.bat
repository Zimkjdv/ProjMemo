@echo off
setlocal

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    py -3 -m venv .venv
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if "%PROJMEMO_PORT%"=="" (
    for /f "delims=" %%P in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$port=8000; do { $client=New-Object Net.Sockets.TcpClient; try { $client.Connect('127.0.0.1',$port); $busy=$true } catch { $busy=$false } finally { $client.Dispose() }; if ($busy) { $port++ } } while ($busy); $port"') do set "PROJMEMO_PORT=%%P"
)

echo Starting ProjMemo on http://127.0.0.1:%PROJMEMO_PORT%/
python -m uvicorn app.main:app --reload --port %PROJMEMO_PORT%
