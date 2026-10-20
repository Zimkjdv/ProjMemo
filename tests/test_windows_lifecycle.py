"""Real launcher + OS Ctrl+C. All writes and traffic use disposable fake data."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import asyncio
import json
import os
from pathlib import Path
import queue
import re
import select
import shutil
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import threading
import time

import httpx
import pytest

from app import db, launcher
from app.runtime import AppRuntime
from app.services import accounts, content, projects, vault
from app.vault import decrypt_secret


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows private console and real Ctrl+C")


@pytest.mark.parametrize("failure", [False, True])
def test_launcher_selector_policy_is_scoped_and_restored(failure):
    original = asyncio.get_event_loop_policy()
    try:
        with launcher.server_loop_policy():
            assert isinstance(asyncio.get_event_loop_policy(), asyncio.WindowsSelectorEventLoopPolicy)
            if failure:
                raise RuntimeError("synthetic server failure")
    except RuntimeError:
        assert failure
    assert asyncio.get_event_loop_policy() is original


class Console:
    def __init__(self, database, entry, development, port, workspace=ROOT):
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        self.events = queue.Queue()
        self.output = []
        # The Windows venv redirector itself is an extra console process. Use
        # base Python for the stdlib-only driver, the requested venv for the app.
        self.process = subprocess.Popen([str(Path(sys.base_prefix) / "python.exe"), "-m", "tests.windows_console"],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", startupinfo=startup,
            creationflags=subprocess.CREATE_NEW_CONSOLE, env=os.environ | {"PYTHONUTF8": "1"})
        def collect():
            for line in self.process.stdout:
                try:
                    value = json.loads(line)
                except ValueError:
                    value = {"driver_error": line}
                self.output.append(value)
                self.events.put(value)
        self.reader = threading.Thread(target=collect, daemon=True)
        self.reader.start()
        self.send(dict(database=str(database), python=sys.executable, entry=entry,
                       development=development, port=port, workspace=str(workspace)))

    def send(self, value):
        self.process.stdin.write(json.dumps(value) + "\n")
        self.process.stdin.flush()

    def stop(self):
        self.send({"op": "stop"})
        deadline = time.monotonic() + 8  # Driver enforces the original 5-second stop bound.
        while time.monotonic() < deadline:
            try:
                event = self.events.get(timeout=.1)
            except queue.Empty:
                continue
            if event.get("timeout"):
                pytest.fail(f"Ctrl+C timeout: {event}\n{self.text()}")
            assert "driver_error" not in event, self.text()
            if "exit" in event:
                assert not event.get("already_exited"), self.output
                assert event["exit"] == 0, self.output
                self.process.wait(timeout=5)
                return
        pytest.fail(f"No graceful stop result: {self.output}")

    def close(self):
        if self.process.poll() is None:
            self.send({"op": "abort"})
            self.process.stdin.close()
            self.process.wait(timeout=15)
        self.reader.join(timeout=2)
        self.process.stdout.close()
        if not self.process.stdin.closed:
            self.process.stdin.close()

    def text(self):
        return "".join(event.get("line", event.get("driver_error", "")) for event in self.output)


def ready(url, console):
    deadline = time.monotonic() + 25
    with httpx.Client(trust_env=False, timeout=.5) as client:
        while time.monotonic() < deadline:
            assert console.process.poll() is None, console.text()
            try:
                response = client.get(url + "/health/ready")
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(.05)
    pytest.fail(f"Launcher did not become ready: {console.output}")


def reset_connections(port):
    def reset(number):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2) as stream:
                stream.sendall(b"GET /projects/1 HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: keep-alive\r\n\r\n")
                # Deliberately cancel before completion, not a response-time
                # benchmark for 64 full Markdown pages on a busy workstation.
                if number % 2 and select.select([stream], [], [], .05)[0]:
                    try:
                        stream.recv(128)
                    except ConnectionResetError:
                        # Reset traffic may also be closed by the peer. Server
                        # callback errors/readiness/shutdown are checked separately.
                        pass
                stream.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("HH", 1, 0))
        except OSError as error:
            return type(error).__name__
        return None
    with ThreadPoolExecutor(8) as pool:
        return [error for error in pool.map(reset, range(64)) if error]


def copy_reload_workspace(directory):
    workspace = Path(directory) / "workspace"
    workspace.mkdir()
    shutil.copytree(ROOT / "app", workspace / "app", ignore=shutil.ignore_patterns("__pycache__"))
    for script in ("run-local.bat", "run-dev.bat"):
        shutil.copy2(ROOT / script, workspace / script)
        assert (ROOT / script).read_bytes() == (workspace / script).read_bytes()
    scripts = workspace / ".venv/Scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(sys.executable, scripts / "python.exe")
    shutil.copy2(Path(sys.executable).parent.parent / "pyvenv.cfg", scripts.parent / "pyvenv.cfg")
    return workspace


def reload_and_check_session(workspace, cycle, url, console, password):
    with httpx.Client(trust_env=False, timeout=3) as client:
        page = client.get(url + "/settings/vault")
        csrf = re.search(r'name="csrf-token" content="([^"]+)"', page.text).group(1)
        assert client.post(url + "/settings/vault/unlock", data={"master_password": password},
                           headers={"X-CSRF-Token": csrf, "Origin": url}).status_code == 303
        assert client.get(url + "/settings/vault/status").json()["unlocked"] is True
        old_pids = set(re.findall(r"Started server process \[(\d+)\]", console.text()))
        # Only the private copy is watched/changed, never the live app source.
        (workspace / "app" / f"_lifecycle_probe_{cycle}.py").write_text("# disposable reload probe\n", encoding="utf-8")
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            new_pids = set(re.findall(r"Started server process \[(\d+)\]", console.text()))
            if new_pids - old_pids:
                ready(url, console)
                assert client.get(url + "/settings/vault/status").json()["unlocked"] is False
                return
            time.sleep(.05)
    pytest.fail(f"No real file-watcher reload: {console.text()}")


@pytest.mark.parametrize("development", [False, True], ids=["normal", "dev"])
@pytest.mark.parametrize("entry", ["module", "batch"])
def test_formal_launcher_reset_ctrl_c_restart_and_data_preservation(monkeypatch, entry, development):
    # mkdtemp is scoped to data; never replace the user's .venv, DB or service.
    with tempfile.TemporaryDirectory(prefix="windows-lifecycle-", dir=ROOT / "data") as directory:
        database = Path(directory) / "fixture.db"
        monkeypatch.setenv("PROJMEMO_DB_PATH", str(database))
        db.init_db(database)
        projects.create_project(name="Windows lifecycle synthetic fixture")
        content.add_note(project_id=1, title="Synthetic note", content_markdown="lifecycle fake data\n" * 200)
        runtime = AppRuntime()
        password = "synthetic lifecycle master phrase"
        token = vault.issue_session(runtime, vault.setup(runtime, password, password), None)
        accounts.add_access_account(runtime=runtime, token=token, project_id=1, label="Fake account",
                                    secret_value="synthetic lifecycle account secret")
        before = database.read_bytes()
        workspace = copy_reload_workspace(directory) if development else ROOT
        with closing(launcher.bind_local_socket(0, 0)) as reservation:
            port = reservation.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        for cycle in range(2):
            console = Console(database, entry, development, port, workspace)
            try:
                ready(url, console)
                with httpx.Client(trust_env=False, timeout=3) as client:
                    assert "Windows lifecycle synthetic fixture" in client.get(url + "/").text
                traffic_errors = reset_connections(port)
                ready(url, console)
                if development:
                    reload_and_check_session(workspace, cycle, url, console, password)
                if os.getenv("PROJMEMO_WINDOWS_BROWSER") == "1":
                    browser = subprocess.run(["node", str(ROOT / "tests/browser/launcher-navigation.cjs"), url],
                        cwd=ROOT, env=os.environ, capture_output=True, text=True, encoding="utf-8", timeout=30)
                    assert browser.returncode == 0, browser.stdout + browser.stderr
                console.stop()
            finally:
                console.close()
            output = console.text()
            if traffic_errors:
                pytest.fail(f"Reset traffic failed: {traffic_errors}\n{output}")
            assert not any(event.get("forced_cleanup") for event in console.output), console.output
            assert "Application shutdown complete" in output, output
            assert "Stopping reloader process" in output if development else "Finished server process" in output
            assert not re.search(r"Traceback|WinError|Exception in callback|ERROR:", output), output
            assert database.read_bytes() == before
            with closing(sqlite3.connect(database)) as connection:
                assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
                ciphertext, nonce = connection.execute("SELECT secret_ciphertext, secret_nonce FROM access_accounts WHERE id=1").fetchone()
            key = vault.unlock(AppRuntime(), password)
            assert decrypt_secret(key, 1, 1, ciphertext, nonce) == "synthetic lifecycle account secret"
            # Same address is reusable after a clean stop; no reloader child owns it.
            with closing(launcher.bind_local_socket(port, port)):
                pass
        log = (Path(directory) / "logs/projmemo.log").read_text(encoding="utf-8")
        assert log.count("shutdown_complete") == (4 if development else 2)
        assert password not in log and "synthetic lifecycle account secret" not in log
