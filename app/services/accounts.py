"""Account metadata and encrypted secrets; plaintext never enters page queries."""

from ..db import db_session
from ..errors import ApplicationError
from ..validation import normalize_fields
from ..runtime import AppRuntime
from ..vault import VaultError, decrypt_secret, encrypt_secret
from .projects import get_project, touch_project
from .vault import current_vault_key, require_vault_key


def add_access_account(
    *,
    runtime: AppRuntime,
    token: str | None,
    project_id: int,
    label: str,
    category: str = 'website',
    environment: str = 'test',
    endpoint: str = '',
    database_name: str = '',
    username: str = '',
    role_scope: str = '',
    purpose: str = '',
    owner: str = '',
    secret_reference: str = '',
    secret_value: str = '',
) -> int:
    label, category, environment, endpoint, database_name, username, role_scope, purpose, owner, secret_reference, secret_value = normalize_fields("account", locals())
    key = current_vault_key(runtime, token) if secret_value else None
    if secret_value and key is None:
        raise ApplicationError(status_code=423, detail="請先解鎖保管庫再保存實際密碼")

    with db_session(write=True) as connection:
        get_project(connection, project_id)
        cursor = connection.execute(
            """
            INSERT INTO access_accounts
                (project_id, label, category, environment, endpoint, database_name,
                 username, role_scope, purpose, owner, secret_reference)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (project_id, label.strip(), category, environment, endpoint.strip(),
             database_name.strip(), username.strip(), role_scope.strip(), purpose.strip(),
             owner.strip(), secret_reference.strip()),
        )
        account_id = int(cursor.lastrowid)
        if secret_value and key is not None:
            ciphertext, nonce = encrypt_secret(key, project_id, account_id, secret_value)
            connection.execute(
                "UPDATE access_accounts SET secret_ciphertext = ?, secret_nonce = ? WHERE id = ?",
                (ciphertext, nonce, account_id),
            )
        touch_project(connection, project_id)
    return int(project_id)


def update_access_account(
    *,
    runtime: AppRuntime,
    token: str | None,
    account_id: int,
    label: str,
    category: str = 'website',
    environment: str = 'test',
    endpoint: str = '',
    database_name: str = '',
    username: str = '',
    role_scope: str = '',
    purpose: str = '',
    owner: str = '',
    secret_reference: str = '',
    secret_value: str = '',
    delete_secret: bool = False,
) -> int:
    label, category, environment, endpoint, database_name, username, role_scope, purpose, owner, secret_reference, secret_value = normalize_fields("account", locals())
    if delete_secret and secret_value:
        raise ApplicationError(status_code=400, detail="不能同時刪除並更新密碼")
    key = current_vault_key(runtime, token) if secret_value else None
    if secret_value and key is None:
        raise ApplicationError(status_code=423, detail="請先解鎖保管庫再更新實際密碼")

    with db_session(write=True) as connection:
        item = connection.execute(
            "SELECT project_id FROM access_accounts WHERE id = ?", (account_id,)
        ).fetchone()
        if item is None:
            raise ApplicationError(status_code=404, detail="找不到此帳號資料")
        project_id = int(item["project_id"])
        connection.execute(
            """
            UPDATE access_accounts
            SET label = ?, category = ?, environment = ?, endpoint = ?, database_name = ?,
                username = ?, role_scope = ?, purpose = ?, owner = ?, secret_reference = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (label.strip(), category, environment, endpoint.strip(), database_name.strip(),
             username.strip(), role_scope.strip(), purpose.strip(), owner.strip(),
             secret_reference.strip(), account_id),
        )
        if delete_secret:
            connection.execute(
                "UPDATE access_accounts SET secret_ciphertext = NULL, secret_nonce = NULL WHERE id = ?",
                (account_id,),
            )
        elif secret_value and key is not None:
            ciphertext, nonce = encrypt_secret(key, project_id, account_id, secret_value)
            connection.execute(
                "UPDATE access_accounts SET secret_ciphertext = ?, secret_nonce = ? WHERE id = ?",
                (ciphertext, nonce, account_id),
            )
        touch_project(connection, project_id)
    return int(project_id)


def delete_access_account(*, account_id: int) -> int:
    with db_session(write=True) as connection:
        item = connection.execute(
            "SELECT project_id FROM access_accounts WHERE id = ?", (account_id,)
        ).fetchone()
        if item is None:
            raise ApplicationError(status_code=404, detail="找不到此帳號資料")
        project_id = int(item["project_id"])
        connection.execute("DELETE FROM access_accounts WHERE id = ?", (account_id,))
        touch_project(connection, project_id)
    return int(project_id)


def reveal_secret(runtime: AppRuntime, token: str | None, account_id: int) -> str:
    key = require_vault_key(runtime, token)
    with db_session() as connection:
        item = connection.execute(
            """
            SELECT project_id, secret_ciphertext, secret_nonce
            FROM access_accounts WHERE id = ?
            """,
            (account_id,),
        ).fetchone()
    if item is None:
        raise ApplicationError(status_code=404, detail="找不到此帳號資料")
    if item["secret_ciphertext"] is None or item["secret_nonce"] is None:
        raise ApplicationError(status_code=404, detail="此帳號沒有保存密碼")
    try:
        secret_value = decrypt_secret(
            key,
            int(item["project_id"]),
            account_id,
            bytes(item["secret_ciphertext"]),
            bytes(item["secret_nonce"]),
        )
    except VaultError as error:
        raise ApplicationError(status_code=500, detail=str(error)) from error
    if current_vault_key(runtime, token) is None:
        raise ApplicationError(status_code=423, detail="保管庫已鎖定，請先解鎖")
    return secret_value
