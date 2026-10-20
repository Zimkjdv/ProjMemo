"""Private hidden-console driver for Windows lifecycle tests, never app runtime.

The parent creates a NEW console for this helper. CTRL_C_EVENT is broadcast
only within that console, never attached to a user's existing console/service.
"""

import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading


_output_lock = threading.Lock()


def emit(value):
    with _output_lock:
        print(json.dumps(value), flush=True)


def main():
    if sys.platform != "win32":
        raise RuntimeError("Windows console test helper only")
    request = json.loads(sys.stdin.readline())
    database = Path(request["database"]).resolve()
    root = Path(__file__).resolve().parents[1]
    workspace = Path(request.get("workspace", str(root))).resolve()
    if workspace != root and (workspace != database.parent / "workspace" or not workspace.is_dir()):
        raise ValueError("Only an isolated workspace copy is allowed")
    python = Path(request["python"]).resolve()
    if (not python.is_relative_to(root) or python.name.lower() != "python.exe"
            or not python.is_file()):
        raise ValueError("Only the project's existing Python runtime is allowed")
    if not database.is_relative_to(root / "data") or database.name != "fixture.db":
        raise ValueError("Only an isolated workspace data fixture is allowed")
    entry = request["entry"]
    development = request["development"]
    port = int(request["port"])
    if entry not in {"module", "batch"} or not isinstance(development, bool) or not 1 <= port <= 65535:
        raise ValueError("Invalid test entry")
    env = os.environ | {"PROJMEMO_DB_PATH": str(database), "PYTHONUTF8": "1",
                        "PIP_NO_INDEX": "1", "PYTHONDONTWRITEBYTECODE": "1"}
    if workspace != root:
        # A copied venv redirector + config uses the existing dependencies read
        # only; no install, junction, or writes to the user's original .venv.
        env["PYTHONPATH"] = str(python.parent.parent / "Lib" / "site-packages")
        env["PYTHONNOUSERSITE"] = "1"
    # Clear inheritance before spawning; the child must receive genuine Ctrl+C.
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    members = (ctypes.c_ulong * 64)()
    count = kernel.GetConsoleProcessList(members, len(members))
    if count != 1 or members[0] != os.getpid():
        raise RuntimeError("Refuse Ctrl+C outside the driver's private console")
    if not kernel.SetConsoleCtrlHandler(None, False):
        raise ctypes.WinError(ctypes.get_last_error())
    command = [str(python), "-m", "app.launcher", "--port", str(port), "--port-end", str(port)]
    if development:
        command.append("--dev")
    if entry == "batch":
        script = workspace / ("run-dev.bat" if development else "run-local.bat")
        command = f'cmd.exe /d /s /c ""{script}" --port {port} --port-end {port}"'
    process = subprocess.Popen(command, cwd=workspace, env=env, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    # Handle Ctrl+C without the inheritable Windows IGNORE_CTRL_C attribute:
    # later reload workers must not inherit an ignore flag through a launcher.
    signal.signal(signal.SIGINT, lambda number, frame: None)
    def collect():
        for line in process.stdout:
            emit({"line": line})
    reader = threading.Thread(target=collect, daemon=True)
    reader.start()
    emit({"started": process.pid})
    try:
        for line in sys.stdin:
            command = json.loads(line)
            if command["op"] == "stop":
                if process.poll() is not None:
                    emit({"exit": process.returncode, "already_exited": True})
                    break
                # This is an OS console event, not terminate()/kill()/SIGTERM.
                if not kernel.GenerateConsoleCtrlEvent(0, 0):
                    raise ctypes.WinError(ctypes.get_last_error())
                # cmd.exe may ask whether to terminate a batch job. N lets its
                # normal exit/errorlevel code run after the Python child stops.
                try:
                    process.stdin.write("N\n")
                    process.stdin.flush()
                except (OSError, ValueError):
                    pass
                try:
                    code = process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    count = kernel.GetConsoleProcessList(members, len(members))
                    emit({"timeout": True, "private_members": list(members)[:min(count, len(members))]})
                else:
                    reader.join(timeout=1)
                    emit({"exit": code})
                    break
            elif command["op"] == "abort":
                break
            else:
                raise ValueError("Invalid command")
    finally:
        if process.poll() is None:
            # Failure cleanup only, precisely the process tree created above.
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                           capture_output=True, timeout=10)
            process.wait(timeout=5)
            emit({"forced_cleanup": True})
        reader.join(timeout=2)
        process.stdout.close()
        process.stdin.close()


if __name__ == "__main__":
    main()
