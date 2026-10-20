"""Vault policy, transactions and session operations without HTTP objects."""

import sqlite3

from ..db import database_path, db_session
from ..database_access import DatabaseBusyError, access_for
from ..backup import create_vault_change_snapshot
from ..errors import ApplicationError
from ..runtime import AppRuntime
from ..vault import (
    InvalidMasterPassword, VaultAlreadyInitialized, VaultError,
    VaultNotInitialized, VaultRateLimited, create_vault, unlock_vault,
    reencrypt_vault, validate_master_password,
)


def current_vault_key(runtime: AppRuntime, token: str | None) -> bytes | None:
    return runtime.vault_sessions.get_key(token)


def require_vault_key(runtime: AppRuntime, token: str | None) -> bytes:
    key = current_vault_key(runtime, token)
    if key is None:
        raise ApplicationError(423, "保管庫已鎖定，請先解鎖")
    return key


def read_vault_settings(connection: sqlite3.Connection) -> tuple[bool, bool]:
    configured = connection.execute("SELECT 1 FROM vault_config WHERE id = 1").fetchone() is not None
    setting = connection.execute("SELECT allow_secret_export FROM app_settings WHERE id = 1").fetchone()
    return configured, bool(setting["allow_secret_export"]) if setting else False


def settings() -> tuple[bool, bool]:
    with db_session() as connection:
        return read_vault_settings(connection)


def vault_status_context(
    runtime: AppRuntime,
    token: str | None,
    configured: bool,
    allow_export: bool,
) -> dict[str, object]:
    return {"configured": configured, "allow_secret_export": allow_export,
            **runtime.vault_sessions.status(token)}


def setup(runtime: AppRuntime, master_password: str, confirm_password: str) -> bytes:
    if master_password != confirm_password:
        raise ApplicationError(400, "兩次輸入的主密碼不一致")
    try:
        with db_session(write=True) as connection:
            key = create_vault(connection, master_password)
    except VaultAlreadyInitialized as error:
        raise ApplicationError(409, "保管庫已設定，請直接解鎖") from error
    except VaultError as error:
        raise ApplicationError(400, str(error)) from error
    runtime.unlock_attempt_limiter.record_success()
    return key


def unlock(runtime: AppRuntime, master_password: str) -> bytes:
    limiter = runtime.unlock_attempt_limiter
    try:
        limiter.check_allowed()
        with db_session() as connection:
            key = unlock_vault(connection, master_password)
    except InvalidMasterPassword as error:
        limiter.record_failure()
        raise ApplicationError(401, "主密碼錯誤，請確認後再試") from error
    except VaultRateLimited as error:
        raise ApplicationError(429, str(error)) from error
    except VaultNotInitialized as error:
        raise ApplicationError(409, "尚未設定保管庫") from error
    except VaultError as error:
        raise ApplicationError(400, str(error)) from error
    limiter.record_success()
    return key


def issue_session(runtime: AppRuntime, key: bytes, old_token: str | None) -> str:
    return runtime.vault_sessions.issue(key, replace_token=old_token)


def lock(runtime: AppRuntime, token: str | None) -> None:
    runtime.vault_sessions.revoke(token)


def update_export_policy(runtime: AppRuntime, token: str | None, allow_secret_export: bool) -> None:
    if allow_secret_export and current_vault_key(runtime, token) is None:
        raise ApplicationError(423, "請先解鎖保管庫，再開啟含密碼匯出")
    with db_session(write=True) as connection:
        configured, _ = read_vault_settings(connection)
        if allow_secret_export and not configured:
            raise ApplicationError(400, "請先設定保管庫，再開啟含密碼匯出")
        connection.execute(
            "UPDATE app_settings SET allow_secret_export = ? WHERE id = 1",
            (int(allow_secret_export),),
        )


def _rotation_authorizer(action, first, second, database, source):
    if action in {sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_SAVEPOINT, sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH}:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def change_master_password(runtime: AppRuntime, current_password: str, new_password: str,
                           confirmation: str, confirmed: bool):
    """Drain old-key requests, snapshot, atomically rotate, then revoke before reopening."""
    if not confirmed:
        raise ApplicationError(400, "請先確認主密碼更換及舊備份注意事項。")
    if new_password != confirmation:
        raise ApplicationError(400, "兩次輸入的新主密碼不一致")
    try:
        validate_master_password(new_password)
        if len(current_password) > 1024:
            raise VaultError("主密碼不可超過 1024 個字元")
        # Validate encoding before backup or changing any encrypted records.
        current_password.encode("utf-8")
        new_password.encode("utf-8")
    except (VaultError, UnicodeError) as error:
        if isinstance(error, VaultError):
            raise ApplicationError(400, str(error)) from None
        raise ApplicationError(400, "主密碼文字格式不正確") from None
    if new_password == current_password:
        raise ApplicationError(400, "新主密碼不可與目前主密碼相同")
    path = database_path()
    access = access_for(path)
    with access.maintenance(vault_change=True):
        snapshot = None
        old_metadata = None
        try:
            runtime.unlock_attempt_limiter.check_allowed()
            with db_session(path, write=True) as connection:
                old_key = unlock_vault(connection, current_password)
                old_metadata = tuple(connection.execute("SELECT * FROM vault_config WHERE id = 1").fetchone())
                snapshot = create_vault_change_snapshot(path)
                connection.set_authorizer(_rotation_authorizer)
                try:
                    reencrypt_vault(connection, old_key, new_password)
                finally:
                    connection.set_authorizer(None)
            # Still under exclusive maintenance: no late unlock/save/export can
            # issue or use an old key between commit and revocation.
            runtime.vault_sessions.clear()
            runtime.unlock_attempt_limiter.record_success()
            return snapshot
        except InvalidMasterPassword:
            runtime.unlock_attempt_limiter.record_failure()
            raise ApplicationError(401, "目前主密碼錯誤，未進行更換") from None
        except VaultNotInitialized:
            raise ApplicationError(409, "尚未設定保管庫") from None
        except VaultRateLimited as error:
            raise ApplicationError(429, str(error)) from None
        except Exception as error:
            if snapshot is not None:
                runtime.vault_sessions.clear()
                # A commit/rollback with an uncertain outcome is not reported as
                # a safe rollback. Fail closed; recovery downloads remain available.
                try:
                    with db_session(path) as check:
                        current = check.execute("SELECT * FROM vault_config WHERE id = 1").fetchone()
                        unchanged = current is not None and tuple(current) == old_metadata
                except Exception:
                    access.require_recovery()
                    raise DatabaseBusyError("資料庫需要復原，請保留備份並停止程式後復原。") from None
                if not unchanged:
                    access.require_recovery()
                    raise DatabaseBusyError("資料庫需要復原，請保留備份並停止程式後復原。") from None
            if isinstance(error, DatabaseBusyError):
                raise
            raise ApplicationError(503, "主密碼更換未完成。請保留復原點，確認資料狀態後再試；如需復原，請前往資料備份。") from None
