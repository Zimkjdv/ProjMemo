"""Vault policy, transactions and session operations without HTTP objects."""

import sqlite3

from ..db import db_session
from ..errors import ApplicationError
from ..runtime import AppRuntime
from ..vault import (
    InvalidMasterPassword, VaultAlreadyInitialized, VaultError,
    VaultNotInitialized, VaultRateLimited, create_vault, unlock_vault,
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
        with db_session() as connection:
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
    with db_session() as connection:
        configured, _ = read_vault_settings(connection)
        if allow_secret_export and not configured:
            raise ApplicationError(400, "請先設定保管庫，再開啟含密碼匯出")
        connection.execute(
            "UPDATE app_settings SET allow_secret_export = ? WHERE id = 1",
            (int(allow_secret_export),),
        )
