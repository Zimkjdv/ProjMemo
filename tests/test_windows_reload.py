"""Worker replacement ordering; real Windows console cases are separate."""

from types import SimpleNamespace
import ctypes
import signal
import threading
import time

import pytest
from uvicorn import Config, Server

from app import windows_reload


@pytest.mark.parametrize("failure", [False, True])
def test_native_console_handler_only_consumes_ctrl_c_and_is_unregistered(monkeypatch, failure):
    calls, stopped = [], []
    class Register:
        def __call__(self, callback, add):
            calls.append((callback, add))
            return True
    register = Register()
    monkeypatch.setattr(ctypes, "WINFUNCTYPE", lambda *types: lambda callback: callback, raising=False)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: SimpleNamespace(SetConsoleCtrlHandler=register), raising=False)
    try:
        with windows_reload.console_stop_handler(lambda: stopped.append(True)):
            callback = calls[0][0]
            assert calls == [(callback, True)]
            assert callback(1) is False and stopped == []
            assert callback(0) is True and stopped == [True]
            if failure:
                raise RuntimeError("synthetic watcher failure")
    except RuntimeError:
        assert failure
    assert calls == [(callback, True), (callback, False)]


def test_windows_watcher_uses_short_idle_wait_without_changing_shutdown_timeout(monkeypatch):
    import watchfiles
    actions = []
    event = threading.Event()
    def initialize(self, config, target, sockets):
        self.reload_dirs = ["synthetic app directory"]
        self.should_exit = event
        self.watcher = SimpleNamespace(close=lambda: actions.append("close-unused-generator"))
    def watch(*paths, **options):
        assert paths == ("synthetic app directory",)
        assert options == dict(watch_filter=None, stop_event=event, yield_on_timeout=True, rust_timeout=250)
        actions.append("bounded-watch")
        return "replacement generator"
    monkeypatch.setattr(windows_reload.ChangeReload, "__init__", initialize)
    monkeypatch.setattr(watchfiles, "watch", watch)
    reloader = windows_reload.WindowsReload(object(), object(), [], threading.Event())
    assert reloader.watcher == "replacement generator"
    assert actions == ["close-unused-generator", "bounded-watch"]


@pytest.mark.parametrize("stopping", [False, True])
def test_private_event_stops_old_worker_before_any_replacement(monkeypatch, stopping):
    actions = []
    stopped = threading.Event()
    reloader = object.__new__(windows_reload.WindowsReload)
    reloader.stop_event = SimpleNamespace(set=lambda: actions.append("signal"), clear=lambda: actions.append("clear"))
    reloader.process = SimpleNamespace(join=lambda: actions.append("join"))
    reloader.should_exit = stopped
    reloader.config, reloader.target, reloader.sockets = object(), object(), [object()]
    reloader.mtimes = {"old": 1}
    replacement = SimpleNamespace(start=lambda: actions.append("start"))
    def create(**values):
        assert values == dict(config=reloader.config, target=reloader.target, sockets=reloader.sockets)
        assert actions == ["signal", "join", "clear"]
        assert reloader.mtimes == {}
        actions.append("create")
        return replacement
    monkeypatch.setattr(windows_reload, "get_subprocess", create)
    if stopping:
        stopped.set()
    reloader.restart()
    assert actions == (["signal", "join"] if stopping else ["signal", "join", "clear", "create", "start"])


def test_shutdown_notifies_worker_before_parent_joins(monkeypatch):
    actions = []
    reloader = object.__new__(windows_reload.WindowsReload)
    reloader.stop_event = SimpleNamespace(set=lambda: actions.append("signal"))
    monkeypatch.setattr(windows_reload.ChangeReload, "shutdown", lambda self: actions.append("parent"))
    reloader.shutdown()
    assert actions == ["signal", "parent"]


def test_console_stop_requests_watcher_and_worker_without_broadcast():
    reloader = object.__new__(windows_reload.WindowsReload)
    reloader.should_exit = threading.Event()
    reloader.stop_event = threading.Event()
    reloader.request_stop()
    assert reloader.should_exit.is_set() and reloader.stop_event.is_set()


def test_worker_runs_normal_server_shutdown_after_private_event(monkeypatch):
    event = threading.Event()
    server = windows_reload.ReloadServer(Config("app.main:app", log_config=None), event)
    assert not server.should_exit
    sockets = [object()]
    def run(self, sockets=None):
        assert self is server and sockets == expected_sockets
        event.set()
        deadline = time.monotonic() + 1
        while not self.should_exit and time.monotonic() < deadline:
            time.sleep(.001)
        assert self.should_exit
        return "normal lifespan path"
    expected_sockets = sockets
    monkeypatch.setattr(Server, "run", run)
    assert server.run(sockets=sockets) == "normal lifespan path"


def test_parent_event_and_first_ctrl_c_do_not_force_cancel_lifespan():
    event = threading.Event()
    server = windows_reload.ReloadServer(Config("app.main:app", log_config=None), event)
    event.set()
    server.should_exit = True  # Parent's event was delivered first.
    server.handle_exit(signal.SIGINT, None)
    assert server.should_exit and not server.force_exit
    assert server._captured_signals == [signal.SIGINT]
    server.handle_exit(signal.SIGINT, None)
    assert server.force_exit  # A genuine second Ctrl+C keeps its old meaning.
