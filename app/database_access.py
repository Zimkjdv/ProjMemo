"""Coordinate database requests and restore operations in this single process."""

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import threading


class DatabaseBusyError(RuntimeError):
    pass


class DatabaseAccess:
    def __init__(self):
        self._condition = threading.Condition()
        self._active = 0
        self._restoring = False
        self._unavailable = False

    @contextmanager
    def operation(self):
        # ASGI context also propagates to FastAPI's synchronous route workers.
        if _admitted.get() is self:
            yield
            return
        with self._condition:
            if self._unavailable:
                raise DatabaseBusyError("資料庫需要復原，請保留備份並停止程式後復原。")
            if self._restoring:
                raise DatabaseBusyError("資料還原中，請稍後再試。")
            self._active += 1
        token = _admitted.set(self)
        try:
            yield
        finally:
            _admitted.reset(token)
            with self._condition:
                self._active -= 1
                self._condition.notify_all()

    @contextmanager
    def maintenance(self, *, reuse: bool = False):
        # Only startup migrations explicitly reuse restore's exclusive lease.
        # A second restore, or a normal admitted request, must not acquire it.
        if reuse and _maintenance.get() is self:
            yield
            return
        if _admitted.get() is self:
            raise DatabaseBusyError("資料庫忙碌或需要復原，請先確認還原狀態。")
        with self._condition:
            if self._restoring or self._unavailable:
                raise DatabaseBusyError("資料庫忙碌或需要復原，請先確認還原狀態。")
            self._restoring = True
            self._condition.notify_all()
            if not self._condition.wait_for(lambda: self._active == 0, timeout=10):
                self._restoring = False
                raise DatabaseBusyError("資料庫仍有作業進行中，請稍後再還原。")
        token = _admitted.set(self)
        maintenance_token = _maintenance.set(self)
        try:
            yield
        finally:
            _maintenance.reset(maintenance_token)
            _admitted.reset(token)
            with self._condition:
                self._restoring = False
                self._condition.notify_all()

    def require_recovery(self):
        with self._condition:
            self._unavailable = True

    def accepting_requests(self):
        """Availability must not reuse a caller's admitted maintenance context."""
        with self._condition:
            return not self._restoring and not self._unavailable


_admitted = ContextVar("projmemo_database_operation", default=None)
_maintenance = ContextVar("projmemo_database_maintenance", default=None)
_registry_lock = threading.Lock()
_registry: dict[Path, DatabaseAccess] = {}


def access_for(path: Path) -> DatabaseAccess:
    path = path.resolve()
    with _registry_lock:
        return _registry.setdefault(path, DatabaseAccess())


class DatabaseAccessMiddleware:
    """Keep admitted requests intact; reject new requests during replacement."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        from .db import database_path
        from .i18n import get_language, translate_error
        from starlette.requests import Request
        from starlette.responses import JSONResponse

        path = scope.get("path", "")
        # Restore takes its own exclusive lease. Recovery files stay accessible
        # even if automatic rollback fails and ordinary data access is blocked.
        bypass = (path.startswith("/static/")
                  or path in {"/health/live", "/health/ready"}
                  or path.startswith("/settings/backup/files/")
                  or path == "/settings/backup"
                  or path == "/settings/backup/restore")
        if scope["type"] != "http" or bypass:
            await self.app(scope, receive, send)
            return
        try:
            with access_for(database_path()).operation():
                await self.app(scope, receive, send)
        except DatabaseBusyError as error:
            response = JSONResponse(
                {"detail": translate_error(str(error), get_language(Request(scope)))},
                status_code=503, headers={"Retry-After": "1", "Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
