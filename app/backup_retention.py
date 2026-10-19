"""Explicit, previewed recovery-file cleanup; never scheduled or run at startup."""

from datetime import datetime
import json
import os
from pathlib import Path
import stat
import tempfile
import time

from .backup import BackupValidationError, is_recovery_backup_filename, recovery_directory, validate_backup
from .errors import ApplicationError


DEFAULT_POLICY = {"version": 1, "mode": "all", "keep_count": 10, "min_age_days": 30}
MAX_CLEANUP_FILES = 100


def safe_directory(database, *, create=False):
    directory = recovery_directory(database)
    if directory.is_symlink() or directory.is_junction():
        raise ApplicationError(400, "復原點目錄不可使用連結，請先檢查備份位置。")
    if create:
        directory.mkdir(parents=True, exist_ok=True)
    return directory


def normalized_policy(mode, keep_count, min_age_days):
    if mode == "all":
        return dict(DEFAULT_POLICY)
    if mode != "custom":
        raise ApplicationError(400, "請選擇有效的復原點保留策略。")
    values = (str(keep_count), str(min_age_days))
    if (any(not value.isascii() or not value.isdigit() or len(value) > 4 for value in values)
            or not 1 <= int(values[0]) <= 500 or not 0 <= int(values[1]) <= 3650):
        raise ApplicationError(400, "至少保留 1 至 500 份；最短保留天數為 0 至 3650，0 表示不限天數。")
    return {"version": 1, "mode": mode, "keep_count": int(values[0]), "min_age_days": int(values[1])}


def read_policy(database):
    path = safe_directory(database) / "retention-policy.json"
    if path.is_symlink() or path.is_junction():
        raise ApplicationError(503, "保留策略無法讀取，已停止清理；請保留復原點並檢查設定檔。")
    try:
        if not path.exists():
            return dict(DEFAULT_POLICY)
        if path.stat().st_size > 4096:
            raise ValueError
        policy = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(policy, dict) or set(policy) != set(DEFAULT_POLICY)
                or type(policy["version"]) is not int or policy["version"] != 1
                or type(policy["keep_count"]) is not int or type(policy["min_age_days"]) is not int):
            raise ValueError
        expected = normalized_policy(policy["mode"], policy["keep_count"], policy["min_age_days"])
        if policy != expected:
            raise ValueError
        return policy
    except (OSError, ValueError, TypeError, ApplicationError):
        raise ApplicationError(503, "保留策略無法讀取，已停止清理；請保留復原點並檢查設定檔。") from None


def save_policy(database, policy):
    directory = safe_directory(database, create=True)
    destination = directory / "retention-policy.json"
    if destination.is_symlink() or destination.is_junction():
        raise ApplicationError(400, "復原點目錄不可使用連結，請先檢查備份位置。")
    descriptor, filename = tempfile.mkstemp(prefix=".retention-", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(policy, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(filename, destination)
    finally:
        Path(filename).unlink(missing_ok=True)


def recovery_files(database):
    directory = safe_directory(database)
    records = []
    if not directory.exists():
        return records
    for path in directory.iterdir():
        if not is_recovery_backup_filename(path.name):
            continue
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or path.is_junction() or info.st_nlink != 1:
            continue
        records.append({"filename": path.name, "size": info.st_size, "mtime_ns": info.st_mtime_ns,
                        "identity": (info.st_dev, info.st_ino),
                        "created_at": datetime.fromtimestamp(info.st_mtime).strftime("%Y-%m-%d %H:%M:%S")})
        if len(records) > 2000:
            raise ApplicationError(400, "復原點超過 2000 份，請先備份並以離線方式整理。")
    return sorted(records, key=lambda item: (item["mtime_ns"], item["filename"]), reverse=True)


def cleanup_candidates(database, policy, *, now=None):
    files = recovery_files(database)
    if policy["mode"] == "all":
        return []
    cutoff = (time.time() if now is None else now) - policy["min_age_days"] * 86400
    # Both protections apply: keep the newest N AND anything younger than D days.
    return [item for item in files[policy["keep_count"]:]
            if item["mtime_ns"] / 1e9 <= cutoff][:MAX_CLEANUP_FILES]


def verify_retained_copy(database, candidates):
    if not candidates:
        return
    removed = {item["filename"] for item in candidates}
    for item in recovery_files(database):
        if item["filename"] not in removed:
            try:
                validate_backup(safe_directory(database) / item["filename"])
                return
            except BackupValidationError:
                continue
    raise ApplicationError(409, "保留範圍內沒有通過驗證的復原點，請先建立並保存有效備份。")


def delete_candidates(database, candidates):
    # Caller owns exclusive database maintenance. Validate ALL paths before any unlink.
    current = {item["filename"]: item for item in recovery_files(database)}
    if any(current.get(item["filename"]) != item for item in candidates):
        raise ApplicationError(409, "復原點已變更，本次未清理，請重新預覽。")
    deleted = 0
    for item in candidates:
        try:
            (safe_directory(database) / item["filename"]).unlink()
        except OSError:
            return {"deleted": deleted, "remaining": len(candidates) - deleted}
        deleted += 1
    return {"deleted": deleted, "remaining": 0}
