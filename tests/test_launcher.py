from contextlib import closing
import os
from pathlib import Path
import queue
import re
import socket
import subprocess
import sys
import threading
import time

import httpx
import pytest

from app import launcher

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("value", ["0", "65536", "bad", "8000 & echo unsafe", "-1"])
def test_invalid_environment_port_is_not_executed(monkeypatch, value):
    monkeypatch.setenv("PROJMEMO_PORT", value)
    with pytest.raises(SystemExit) as error:
        launcher.arguments([])
    assert error.value.code == 2


def test_bounded_range_and_fixed_host_worker(monkeypatch):
    monkeypatch.setenv("PROJMEMO_PORT", "8123")
    args = launcher.arguments([])
    assert (args.port, args.port_end, args.dev) == (8123, 8222, False)
    args = launcher.arguments(["--port", "65535", "--dev"])
    assert (args.port, args.port_end, args.dev) == (65535, 65535, True)
    for invalid in (["--port", "8000", "--port-end", "8100"], ["--port-end", "8122"], ["--host", "0.0.0.0"], ["--workers", "2"]):
        with pytest.raises(SystemExit):
            launcher.arguments(invalid)


def test_bound_socket_stays_exclusive_and_exhaustion_is_clear():
    with closing(launcher.bind_local_socket(0, 0)) as reserved:
        port = reserved.getsockname()[1]
        with closing(socket.socket()) as competitor:
            with pytest.raises(OSError):
                competitor.bind(("127.0.0.1", port))
        with pytest.raises(RuntimeError, match="No available local port"):
            launcher.bind_local_socket(port, port)


def test_normal_mode_passes_same_socket_and_forces_single_worker(monkeypatch):
    import uvicorn

    seen = {}

    class FakeServer:
        started = True

        def __init__(self, config):
            seen["config"] = config

        def run(self, *, sockets):
            seen["sockets"] = sockets

    monkeypatch.setenv("WEB_CONCURRENCY", "8")
    monkeypatch.setattr(uvicorn, "Server", FakeServer)
    with closing(launcher.bind_local_socket(0, 0)) as reserved:
        assert launcher.serve(reserved) == 0
        assert seen["sockets"] == [reserved]
        assert seen["config"].host == "127.0.0.1"
        assert seen["config"].workers == 1
        assert seen["config"].reload is False


def test_dependency_failure_is_clear_without_exception_content(monkeypatch, capsys):
    def fail(_name):
        raise ImportError("fixture-sensitive-value")

    monkeypatch.setattr(launcher.importlib, "import_module", fail)
    assert launcher.check_dependencies() is False
    output = capsys.readouterr().err
    assert "setup-local.bat" in output
    assert "fixture-sensitive-value" not in output


@pytest.mark.skipif(sys.platform != "win32", reason="Windows socket spawn and batch baseline")
@pytest.mark.parametrize("development", [False, True])
def test_real_server_reuses_bound_socket_when_first_port_busy(tmp_path, development):
    with closing(launcher.bind_local_socket(0, 0)) as occupied:
        first = occupied.getsockname()[1]
        if first > 65435:
            pytest.skip("Ephemeral port too close to range boundary")
        env = os.environ | {"PROJMEMO_DB_PATH": str(tmp_path / "fixture.db"), "PROJMEMO_PORT": str(first), "PIP_NO_INDEX": "1"}
        process = subprocess.Popen(
            [sys.executable, "-m", "app.launcher"] + (["--dev"] if development else []),
            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors="replace", creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        lines = queue.Queue()
        output = []

        def collect():
            for line in process.stdout:
                output.append(line)
                lines.put(line)

        reader = threading.Thread(target=collect, daemon=True)
        reader.start()
        try:
            deadline = time.monotonic() + 25
            selected = None
            with httpx.Client(trust_env=False, timeout=0.5) as client:
                while time.monotonic() < deadline:
                    assert process.poll() is None, "".join(output)
                    try:
                        line = lines.get(timeout=0.05)
                        match = re.search(r"http://127\.0\.0\.1:(\d+)/", line)
                        if match:
                            selected = int(match.group(1))
                    except queue.Empty:
                        pass
                    if selected:
                        try:
                            response = client.get(f"http://127.0.0.1:{selected}/")
                            if response.status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                else:
                    pytest.fail("Server did not become ready: " + "".join(output))
            assert first < selected <= first + 99
            assert "ProjMemo" in response.text
            assert (tmp_path / "fixture.db").exists()
        finally:
            if process.poll() is None:
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, timeout=10)
            process.wait(timeout=10)
            reader.join(timeout=2)
            process.stdout.close()
