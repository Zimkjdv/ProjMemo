"""R12 read-only editing and configurable exports, using synthetic data only."""

from contextlib import closing
from itertools import combinations
import sqlite3

import pytest

from app import options as schema_options
from app.db import init_db
from app.errors import ApplicationError
from app.export_options import DOCUMENT_EN, ExportOptions, SECTION_IDS
from app.main import create_app
from app.markdown_editor import editor_templates, validate_preview
from app.markdown_export import build_markdown
from app.pdf_export import generate_project_pdf
from app.presentation import preview_document
from app.runtime import AppRuntime
from app.services import accounts, exports, projects, vault
from tests.client import TestClient
from tests.pdf_audit import audit_pdf
from tests.pdf_fixtures import SECRET, pdf_fixture


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "r12.db"
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(path))
    init_db(path)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("INSERT INTO projects (id, name, description) VALUES (1, 'R12 fixture', '原文 unchanged')")
        connection.execute("INSERT INTO notes (project_id, title, content_markdown) VALUES (1, 'Saved note', 'saved')")
    with TestClient(create_app()) as browser:
        yield browser, path


@pytest.mark.parametrize("language,sections", [("fr", ("notes",)), ("en", ()), ("en", ("other",)),
                                               ("en", ("notes", "notes"))])
def test_invalid_document_choices(language, sections):
    with pytest.raises(ApplicationError):
        ExportOptions(language, sections)


def test_preview_core_has_no_active_markup_and_enforces_unicode_limit():
    source = ('# Heading\n\n**Bold**\n\n[link](https://example.invalid)\n\n'
              '<script>alert(1)</script><img src=x onerror=alert(1)><svg><foreignObject>bad</foreignObject></svg>'
              '\n\n```mermaid\n%%{init: {"securityLevel":"loose"}}%%\ngraph TD; A-->B\n```')
    document = preview_document(validate_preview(source), "en")
    assert "<strong>Bold</strong>" in document and "graph TD" in document
    assert all(item not in document for item in ("<script", "<img", "<svg", "<foreignObject", "href=", "onerror"))
    assert "default-src 'none'" in document
    assert validate_preview("🗒" * 100000) == "🗒" * 100000
    for invalid in ("x" * 100001, "\0"):
        with pytest.raises(ApplicationError):
            validate_preview(invalid)


def test_configured_sensitive_exports_keep_all_guards_and_skip_excluded_accounts(tmp_path, monkeypatch):
    path = tmp_path / "vault-r12.db"
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(path))
    init_db(path)
    project_id = projects.create_project(name="R12 synthetic vault")
    runtime = AppRuntime()
    key = vault.setup(runtime, "test-only-r12-master", "test-only-r12-master")
    token = vault.issue_session(runtime, key, None)
    accounts.add_access_account(runtime=runtime, token=token, project_id=project_id,
        label="Synthetic account", secret_value=SECRET)
    choices = ExportOptions("en", ("accounts",))
    for confirm, session, status in ((False, token, 400), (True, None, 423), (True, token, 403)):
        with pytest.raises(ApplicationError) as result:
            exports.export_sensitive_project(runtime, session, project_id, "markdown", confirm, options=choices)
        assert result.value.status_code == status
    vault.update_export_policy(runtime, token, True)
    exported = exports.export_sensitive_project(runtime, token, project_id, "markdown", True, options=choices)
    assert exported.sensitive and SECRET in exported.content and "actual passwords" in exported.content
    pdf = exports.export_sensitive_project(runtime, token, project_id, "pdf", True, options=choices)
    assert SECRET in audit_pdf(pdf.content)[0]
    def forbidden(*args, **kwargs):
        pytest.fail("Excluded accounts or ordinary exports must not decrypt")
    monkeypatch.setattr(exports, "_sensitive_export_accounts", forbidden)
    monkeypatch.setattr(exports, "decrypt_secret", forbidden)
    assert SECRET not in exports.export_project(project_id, "markdown", options=choices).content
    excluded = ExportOptions("en", ("description",))
    result = exports.export_sensitive_project(runtime, token, project_id, "markdown", True, options=excluded)
    assert SECRET not in result.content and "Synthetic account" not in result.content
    result = exports.export_sensitive_project(runtime, token, project_id, "pdf", True, options=excluded)
    text, _ = audit_pdf(result.content)
    assert "SENSITIVE" in text and "Synthetic account" not in text
    vault.lock(runtime, token)
    with pytest.raises(ApplicationError) as locked:
        exports.export_sensitive_project(runtime, token, project_id, "markdown", True, options=excluded)
    assert locked.value.status_code == 423


def test_all_document_schema_labels_have_english_translations():
    groups = (schema_options.STATUS_OPTIONS, schema_options.URL_TYPES, schema_options.NOTE_CATEGORIES,
              schema_options.PRIORITIES, schema_options.CHECKLIST_CATEGORIES, schema_options.ENVIRONMENTS,
              schema_options.ACCESS_ACCOUNT_CATEGORIES, schema_options.ACCESS_ENVIRONMENTS)
    for group in groups:
        for _, label in group:
            if any("\u3400" <= char <= "\u9fff" for char in label):
                assert label in DOCUMENT_EN


@pytest.mark.parametrize("language", ["zh-Hant", "en"])
def test_all_63_section_combinations_exclude_unselected_content(language):
    data = pdf_fixture("empty")
    headings = ("專案描述", "重要 URL", "Notes & Cautions", "環境變數說明", "帳號與存取資料", "Handover Checklist")
    for size in range(1, 7):
        for selected in combinations(SECTION_IDS, size):
            choices = ExportOptions(language, selected)
            text = build_markdown(*data.renderer_args(), options=choices)
            assert data.project["name"] in text
            for section, heading in zip(SECTION_IDS, headings):
                assert ("## " + choices.label(heading) in text) == (section in selected)


@pytest.mark.parametrize("language", ["zh-Hant", "en"])
def test_selected_content_and_user_strings_are_not_translated(language):
    data = pdf_fixture()
    data.project["name"] = "狀態 / Project name"
    data.project["owner"] = "負責人"
    data.notes[0]["content_markdown"] = "## 狀態\n\n負責人 / original text\n\n```mermaid\ngraph TD; A-->B\n```"
    result = build_markdown(*data.renderer_args(), options=ExportOptions(language, ("notes",)))
    assert "# 狀態 / Project name" in result
    assert data.notes[0]["content_markdown"] in result
    assert data.project["owner"] in result
    assert data.access_accounts[0]["username"] not in result
    assert SECRET not in result


@pytest.mark.parametrize("language", ["zh-Hant", "en"])
def test_configured_pdf_real_cjk_tables_and_selected_sections(tmp_path, language):
    data = pdf_fixture()
    content = generate_project_pdf(*data.renderer_args(), options=ExportOptions(language, SECTION_IDS))
    (tmp_path / language).mkdir()
    text, _ = audit_pdf(content, tmp_path / language)
    assert "CODE-089" in text and "TableRow-079" in text
    assert SECRET not in text
    assert ("Handover checklist" if language == "en" else "交接清單") in text
    minimal = generate_project_pdf(*data.renderer_args(), options=ExportOptions(language, ("description",)))
    minimal_text, _ = audit_pdf(minimal)
    assert "CODE-000" not in minimal_text and "fixture-user" not in minimal_text


def test_preview_is_sanitized_bounded_read_only_and_no_store(client):
    browser, path = client
    before = path.read_bytes()
    content = ('# Title\n\n**Bold**\n\n<script>alert(1)</script><img src="https://example.invalid/x">'
               '<svg onload="alert(1)"></svg><a href="javascript:alert(1)">bad</a>\n\n'
               '[external](https://example.invalid)\n\n```mermaid\ngraph TD; A-->B\n```')
    result = browser.post("/editor/preview", data={"content_markdown": content}, headers={"Accept": "application/json"})
    assert result.status_code == 200
    document = result.json()["document"]
    assert "<strong>Bold</strong>" in document and "graph TD" in document
    assert all(item not in document for item in ("<script", "<img", "<svg", "href=", "onload", "javascript:"))
    assert "default-src 'none'" in document
    assert "no-store" in result.headers["cache-control"]
    native = browser.post("/editor/preview", data={"content_markdown": "## Native preview"})
    assert native.status_code == 200 and "sandbox" in native.headers["content-security-policy"]
    assert browser.post("/editor/preview", data={"content_markdown": ""}).status_code == 200
    for invalid in ("x" * 100001, "bad\x00input"):
        assert browser.post("/editor/preview", data={"content_markdown": invalid}).status_code == 400
    assert path.read_bytes() == before
    assert browser.post("/editor/preview", data={"content_markdown": "valid"}, headers={"X-CSRF-Token": "invalid"}).status_code == 403


def test_native_templates_and_project_fragments(client):
    browser, _ = client
    for language in ("zh-Hant", "en"):
        browser.cookies.set("projmemo_language", language)
        assert len(editor_templates(language)) == 4
        response = browser.get("/editor?template=deployment")
        assert response.status_code == 200 and "formtarget=\"_blank\"" in response.text
        assert "Secret" in response.text and "data-markdown-editor" in response.text
    fragment = browser.get("/projects/1", headers={"X-ProjMemo-Fragment": "notes"})
    assert "data-markdown-editor" in fragment.text
    assert "<script" not in fragment.text


def test_configured_download_and_policies_cannot_be_bypassed(client, monkeypatch):
    browser, _ = client
    assert browser.get("/projects/1/export").status_code == 200
    assert browser.get("/projects/999/export").status_code == 404
    def forbidden(*args, **kwargs):
        pytest.fail("Regular export must not load or decrypt secrets")
    monkeypatch.setattr(exports, "_sensitive_export_accounts", forbidden)
    monkeypatch.setattr(exports, "decrypt_secret", forbidden)
    base = {"export_format": "markdown", "document_language": "en", "sections": ["description"]}
    response = browser.post("/projects/1/export", data=base)
    assert response.status_code == 200 and "## Project description" in response.text
    assert "原文 unchanged" in response.text and "Saved note" not in response.text
    assert "attachment;" in response.headers["content-disposition"]
    assert "no-store" in response.headers["cache-control"]
    assert browser.post("/projects/1/export", data={**base, "sections": []}).status_code == 400
    assert browser.post("/projects/1/export", data={**base, "document_language": "fr"}).status_code == 400
    assert browser.post("/projects/1/export", data={**base, "include_secrets": "true"}).status_code == 400
    assert browser.post("/projects/1/export", data={**base, "include_secrets": "true", "confirm_sensitive_export": "true"}).status_code == 423
    native = browser.post("/projects/1/export", data={**base, "export_format": "pdf", "sections": ["notes"],
        "include_secrets": "true"}, headers={"Accept": "text/html"})
    assert native.status_code == 400
    from app.form_errors import FormDocument
    fields = [node for node in FormDocument(native.text).root.walk() if node.tag == "input"]
    chosen = [node.attrs["value"] for node in fields if node.attrs.get("name") == "sections" and "checked" in node.attrs]
    assert chosen == ["notes"]
    assert all("checked" not in node.attrs for node in fields if node.attrs.get("name") in {
        "include_secrets", "confirm_sensitive_export"})
    assert '<option value="pdf" selected' in native.text and '<option value="en" selected' in native.text
