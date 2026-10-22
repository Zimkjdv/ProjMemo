"""Best-effort download-generation metadata, separate from restorable SQLite data."""

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import stat
import tempfile
import threading

from .backup_retention import safe_directory
from .errors import ApplicationError


_lock = threading.Lock()
_filename = "download-activity.json"


def read_download_activity(database: Path) -> dict:
    try:
        path = safe_directory(database) / _filename
        if not path.exists() and not path.is_symlink():
            return {"state": "missing"}
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or path.is_junction() or info.st_nlink != 1 or info.st_size > 1024:
            raise ValueError
        with path.open("r", encoding="utf-8") as stream:
            record = json.loads(stream.read(1025))
        if not isinstance(record, dict) or set(record) != {"version", "generated_at"} or type(record["version"]) is not int or record["version"] != 1:
            raise ValueError
        timestamp = datetime.fromisoformat(record["generated_at"])
        if timestamp.tzinfo is None:
            raise ValueError
        local = timestamp.astimezone()
        return {"state": "recorded", "iso": timestamp.isoformat(), "date": local.strftime("%Y-%m-%d"),
                "time": local.strftime("%H:%M:%S %z")}
    except (OSError, OverflowError, ValueError, TypeError, ApplicationError):
        return {"state": "unavailable"}


def record_download_generation(database: Path) -> None:
    """A generated file is not proof that a browser saved it; never block the download."""
    temporary = None
    try:
        with _lock:
            directory = safe_directory(database, create=True)
            destination = directory / _filename
            if destination.exists() or destination.is_symlink():
                info = destination.lstat()
                if not stat.S_ISREG(info.st_mode) or destination.is_junction() or info.st_nlink != 1:
                    raise ValueError
            descriptor, name = tempfile.mkstemp(prefix=".download-activity-", dir=directory)
            temporary = Path(name)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump({"version": 1, "generated_at": datetime.now(timezone.utc).isoformat()}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
    except (OSError, ValueError, ApplicationError):
        logging.getLogger("projmemo").warning("backup_activity_record_unavailable")
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass  # A best-effort metadata failure must not discard a valid backup.
