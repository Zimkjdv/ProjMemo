"""Bound SQLite lock waits without retrying application-level writes."""

from pathlib import Path
import sqlite3
from time import monotonic

from .database_access import DatabaseBusyError


SQLITE_LOCK_WAIT_SECONDS = 1.0
DATABASE_BUSY_MESSAGE = "資料庫忙碌，請稍後再試。"


def is_lock_error(error: Exception) -> bool:
    code = getattr(error, "sqlite_errorcode", None)
    return isinstance(code, int) and (code & 0xFF) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}


def copy_database(source_path: Path, destination_path: Path) -> None:
    """Online backup with a bounded continuous BUSY/LOCKED wait.

    SQLite's backup API retries independently of the connection's busy timeout.
    Healthy large copies have no one-second total-runtime limit.
    """
    if source_path.resolve() == destination_path.resolve():
        raise ValueError("來源與備份目的地不可相同。")
    source = destination = None
    busy_since = None
    def progress(status: int, remaining: int, total: int) -> None:
        nonlocal busy_since
        if (status & 0xFF) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
            now = monotonic()
            if busy_since is None:
                busy_since = now
            elif now - busy_since >= SQLITE_LOCK_WAIT_SECONDS:
                raise DatabaseBusyError(DATABASE_BUSY_MESSAGE)
        else:
            busy_since = None
    try:
        source = sqlite3.connect(f"{source_path.resolve().as_uri()}?mode=ro", uri=True,
                                 timeout=SQLITE_LOCK_WAIT_SECONDS)
        destination = sqlite3.connect(destination_path, timeout=SQLITE_LOCK_WAIT_SECONDS)
        source.backup(destination, pages=128, progress=progress, sleep=.01)
    except sqlite3.Error as error:
        if is_lock_error(error):
            raise DatabaseBusyError(DATABASE_BUSY_MESSAGE) from error
        raise
    finally:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()
