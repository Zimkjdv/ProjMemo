"""Local storage preflight and bounded, allowlisted operational diagnostics."""

from contextlib import contextmanager
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import uuid

from .database_access import DatabaseBusyError, access_for
from .db import MigrationError, configured_database_path
from .migrations import SCHEMA_VERSION

MIN_FREE_BYTES = 64 * 1024 * 1024
STORAGE_CODES = {"DATA_PATH_INVALID", "DATA_SPACE_LOW", "DATA_DIRECTORY_UNWRITABLE"}


class StorageProblem(RuntimeError):
    def __init__(self, code):
        self.code = code if code in STORAGE_CODES else "STORAGE_ERROR"
        super().__init__(self.code)


class SafeLogFailure:
    def handleError(self, record):
        # Standard logging's error fallback prints exception context and paths.
        try:
            sys.stderr.write("ProjMemo log write failed [LOG_WRITE_FAILED]; check local storage.\n")
        except OSError:
            pass


class SafeRotatingHandler(SafeLogFailure, RotatingFileHandler):
    pass


class SafeConsoleHandler(SafeLogFailure, logging.StreamHandler):
    pass


def prepare_storage():
    """Probe only a private temporary file; never write into the existing DB."""
    path = configured_database_path().resolve()
    probe = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not path.is_file():
            raise StorageProblem("DATA_PATH_INVALID")
        if shutil.disk_usage(path.parent).free < MIN_FREE_BYTES:
            raise StorageProblem("DATA_SPACE_LOW")
        if path.exists():
            with path.open("rb+"):
                pass
        descriptor, filename = tempfile.mkstemp(prefix=".projmemo-write-probe-", dir=path.parent)
        probe = Path(filename)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(b"ProjMemo storage probe\n")
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        raise StorageProblem("DATA_DIRECTORY_UNWRITABLE") from None
    finally:
        if probe is not None:
            try:
                probe.unlink(missing_ok=True)
            except OSError:
                raise StorageProblem("DATA_DIRECTORY_UNWRITABLE") from None
    return path


@contextmanager
def operational_log(path):
    """Each application owns its handlers and releases Windows file handles."""
    logger = logging.Logger("projmemo.operations", level=logging.INFO)
    handlers = []
    try:
        directory = path.parent / "logs"
        directory.mkdir(parents=True, exist_ok=True)
        handlers.append(SafeRotatingHandler(directory / "projmemo.log", maxBytes=1024 * 1024,
                                            backupCount=3, encoding="utf-8"))
        handlers.append(SafeConsoleHandler())
        for handler in handlers:
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            logger.addHandler(handler)
        yield logger
    finally:
        for handler in handlers:
            logger.removeHandler(handler)
            handler.close()


def error_category(error):
    # Never use str(error), exception arguments, class names, or traceback locals.
    if isinstance(error, StorageProblem):
        return error.code
    if isinstance(error, MigrationError):
        return "DATABASE_INIT_FAILED" if error.recovered else "DATABASE_RECOVERY_REQUIRED"
    if isinstance(error, sqlite3.Error):
        return "DATABASE_ERROR"
    if isinstance(error, OSError):
        return "STORAGE_ERROR"
    return "INTERNAL_ERROR"


def database_ready():
    """Read-only, cheap availability check; not an integrity test or write test."""
    try:
        path = configured_database_path().resolve()
        if not path.is_file() or shutil.disk_usage(path.parent).free < MIN_FREE_BYTES:
            return False
        access = access_for(path)
        if not access.accepting_requests():
            return False
        with access.operation():
            connection = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=0.2)
            try:
                if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                    return False
                connection.execute("SELECT 1 FROM sqlite_schema LIMIT 1").fetchone()
            finally:
                connection.close()
        return True
    except (OSError, sqlite3.Error, DatabaseBusyError):
        return False


class SafeDiagnosticsMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        from starlette.datastructures import MutableHeaders
        from starlette.requests import Request
        from starlette.responses import JSONResponse
        from .i18n import get_language, translate_error
        from .web_security import NO_STORE_HEADERS

        request_id = uuid.uuid4().hex  # Never trust a caller-supplied correlation value.
        started = False
        status = None
        category = None
        state = getattr(scope.get("app"), "state", None)
        logger = getattr(state, "operations_logger", None) or logging.getLogger("projmemo.operations")

        async def tracked_send(message):
            nonlocal started, status
            if message["type"] == "http.response.start":
                started = True
                status = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        except Exception as error:
            category = error_category(error)
            if started:
                # Let the server close a failed stream, but only with a sanitized
                # exception. Do not send a second response or log the original.
                raise RuntimeError("ProjMemo response stream failed; consult the safe request log") from None
            status = 503 if category in {"DATABASE_ERROR", "STORAGE_ERROR"} else 500
            detail = "服務暫時無法處理此操作，請確認資料目錄、磁碟空間與備份；保留追蹤碼供查核。"
            response = JSONResponse({"detail": translate_error(detail, get_language(Request(scope))),
                                     "request_id": request_id}, status_code=status, headers=NO_STORE_HEADERS)
            try:
                await response(scope, receive, tracked_send)
            except Exception:
                raise RuntimeError("ProjMemo error response failed; consult the safe request log") from None
        finally:
            if category or (status is not None and status >= 500):
                method = scope.get("method", "")
                method = method if method in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"} else "OTHER"
                route = getattr(scope.get("route"), "path", None) or "unmatched"
                logger.error("request_failed id=%s method=%s route=%s status=%s category=%s",
                             request_id, method, route, status or 500, category or "HANDLED_ERROR")
