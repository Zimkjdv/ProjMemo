"""Windows-only adapter for the pinned Uvicorn reloader's worker lifecycle.

Keep its file watcher and socket handoff, but use a private spawn Event rather
than a console-wide/invalid-group CTRL_C_EVENT for a file-triggered restart.
No transport/stdlib patches, HTTP shutdown endpoint, or forced worker kills.
"""

from contextlib import contextmanager
import logging
import threading

from uvicorn import Server
from uvicorn._subprocess import get_subprocess
from uvicorn.supervisors import ChangeReload


@contextmanager
def console_stop_handler(stop):
    """Windows control thread can request stop while main waits in a watcher."""
    import ctypes
    from ctypes import wintypes
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.SetConsoleCtrlHandler.argtypes = [callback_type, wintypes.BOOL]
    kernel.SetConsoleCtrlHandler.restype = wintypes.BOOL
    def handle(event):
        if event != 0:  # Only Ctrl+C; do not consume unrelated console events.
            return False
        stop()
        return True
    callback = callback_type(handle)
    if not kernel.SetConsoleCtrlHandler(callback, True):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield
    finally:
        kernel.SetConsoleCtrlHandler(callback, False)


class ReloadServer(Server):
    def __init__(self, config, stop_event):
        super().__init__(config)
        self.stop_event = stop_event

    def run(self, sockets=None):
        def stop_when_requested():
            self.stop_event.wait()
            self.should_exit = True
        # Started inside the spawned worker, never in its parent/pickled state.
        threading.Thread(target=stop_when_requested, daemon=True).start()
        return super().run(sockets=sockets)

    def handle_exit(self, sig, frame):
        # A single console Ctrl+C reaches parent and worker. If the parent's
        # private event wins the race, it must not turn that first Ctrl+C into
        # Uvicorn's *second* Ctrl+C/force-exit and cancel lifespan cleanup.
        if self.stop_event.is_set() and self.should_exit and not self._captured_signals:
            self._captured_signals.append(sig)
            return
        return super().handle_exit(sig, frame)


class WindowsReload(ChangeReload):
    def __init__(self, config, target, sockets, stop_event):
        super().__init__(config, target, sockets)
        self.stop_event = stop_event
        if hasattr(self, "watcher"):
            from watchfiles import watch
            # The synchronous watcher otherwise waits in Rust for up to five
            # seconds before Python can handle a console signal on Windows.
            # Keep notifications/filtering; bound the idle wait, not shutdown.
            self.watcher.close()
            self.watcher = watch(*self.reload_dirs, watch_filter=None, stop_event=self.should_exit,
                                 yield_on_timeout=True, rust_timeout=250)

    def request_stop(self):
        self.should_exit.set()
        self.stop_event.set()

    def run(self):
        self.startup()
        try:
            # Installed after Uvicorn's startup signal handlers, removed on exit.
            # This only consumes this supervisor's event, never sends a signal.
            with console_stop_handler(self.request_stop):
                for changes in self:
                    if changes:
                        logging.getLogger("uvicorn.error").warning("%s detected app changes. Reloading...", self.reloader_name)
                        self.restart()
        finally:
            self.shutdown()

    def restart(self):
        self.stop_event.set()
        self.process.join()  # Old lifespan/transactions must finish before replacement.
        if self.should_exit.is_set():
            return
        self.stop_event.clear()
        if hasattr(self, "mtimes"):  # Preserve the optional StatReload fallback.
            self.mtimes = {}
        self.process = get_subprocess(config=self.config, target=self.target, sockets=self.sockets)
        self.process.start()

    def shutdown(self):
        self.stop_event.set()
        return super().shutdown()
