"""Shared complete data/policy pipeline for Markdown and PDF exports."""

from dataclasses import dataclass, replace
import sqlite3

from ..db import db_session
from ..errors import ApplicationError
from ..markdown_export import build_markdown
from ..pdf_export import PDFExportError, generate_project_pdf
from ..project_data import ProjectData
from ..runtime import AppRuntime
from ..vault import decrypt_secret
from .projects import load_project_data, project_detail
from .vault import require_vault_key


@dataclass(frozen=True)
class ExportArtifact:
    content: str | bytes
    filename: str
    extension: str
    media_type: str
    sensitive: bool = False


def _sensitive_export_accounts(
    connection: sqlite3.Connection,
    project_id: int,
    key: bytes,
) -> list[dict[str, object]]:
    rows = connection.execute(
        """SELECT id, project_id, label, category, environment, endpoint, database_name,
                  username, role_scope, purpose, owner, secret_reference, secret_ciphertext, secret_nonce
           FROM access_accounts WHERE project_id = ? ORDER BY label COLLATE NOCASE""",
        (project_id,),
    ).fetchall()
    accounts = []
    for row in rows:
        account = {name: row[name] for name in (
            "label", "category", "environment", "endpoint", "database_name", "username",
            "role_scope", "purpose", "owner", "secret_reference",
        )}
        ciphertext, nonce = row["secret_ciphertext"], row["secret_nonce"]
        account["has_secret"] = ciphertext is not None and nonce is not None
        account["secret_value"] = (
            decrypt_secret(
                key,
                int(row["project_id"]),
                int(row["id"]),
                bytes(ciphertext),
                bytes(nonce),
            )
            if ciphertext is not None and nonce is not None else None
        )
        accounts.append(account)
    return accounts


def _render(data: ProjectData, export_format: str, *, sensitive: bool = False) -> ExportArtifact:
    if export_format == "markdown":
        # Keep the original renderer call shapes as well as the rendered bytes.
        content = (build_markdown(*data.renderer_args(), include_secrets=True)
                   if sensitive else build_markdown(*data.renderer_args()))
        extension, media_type = "md", "text/markdown; charset=utf-8"
    else:
        try:
            content = (generate_project_pdf(*data.renderer_args(), include_secrets=True)
                       if sensitive else generate_project_pdf(*data.renderer_args()))
        except PDFExportError as error:
            raise ApplicationError(503, str(error)) from error
        extension, media_type = "pdf", "application/pdf"
    filename = f"{data.project['name']}.{extension}".replace("/", "-").replace("\\", "-")
    return ExportArtifact(content, filename, extension, media_type, sensitive)


def export_project(project_id: int, export_format: str) -> ExportArtifact:
    if export_format not in {"markdown", "pdf"}:
        raise ApplicationError(400, "不支援的匯出格式")
    # Only the metadata projection is loaded, never ciphertext or plaintext.
    return _render(load_project_data(project_id), export_format)


def export_sensitive_project(runtime: AppRuntime, token: str | None, project_id: int,
                             export_format: str, confirm_sensitive_export: bool) -> ExportArtifact:
    if export_format not in {"markdown", "pdf"}:
        raise ApplicationError(400, "不支援的匯出格式")
    if not confirm_sensitive_export:
        raise ApplicationError(400, "請先確認此檔案包含實際密碼")
    key = require_vault_key(runtime, token)
    with db_session() as connection:
        setting = connection.execute("SELECT allow_secret_export FROM app_settings WHERE id = 1").fetchone()
        if setting is None or not setting["allow_secret_export"]:
            raise ApplicationError(403, "尚未在保管庫設定中允許含密碼匯出")
        data = project_detail(connection, project_id)
        accounts = _sensitive_export_accounts(connection, project_id, key)
    return _render(replace(data, access_accounts=accounts), export_format, sensitive=True)
