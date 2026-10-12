from pathlib import Path
import re
from string import Formatter

from fastapi.testclient import TestClient
from jinja2 import Environment, nodes


def test_language_switch_localizes_pages_but_preserves_project_data(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(tmp_path / "languages.db"))
    from app.main import app
    from app.i18n import LANGUAGE_COOKIE

    with TestClient(app, follow_redirects=False) as client:
        default_page = client.get("/")
        assert '<html lang="zh-Hant">' in default_page.text
        assert "個人專案知識庫" in default_page.text
        assert "PERSONAL PROJECT KNOWLEDGE BASE" not in default_page.text
        created = client.post("/projects/new", data={
            "name": "專案名稱", "description": "這是使用者的說明", "owner": "負責人", "tags": "維護中,custom",
        })
        project_url = created.headers["location"]
        assert client.post(f"{project_url}/urls", data={
            "title": "測試連結", "url": "https://example.invalid", "type": "git",
        }).status_code == 303
        next_url = f"{project_url}?source=list#project-notes"
        switched = client.post("/settings/language", data={"language": "en", "return_to": next_url})
        assert switched.status_code == 303
        assert switched.headers["location"] == next_url
        assert client.cookies.get(LANGUAGE_COOKIE) == "en"
        assert "HttpOnly" in switched.headers["set-cookie"]

        detail = client.get(project_url)
        assert '<html lang="en">' in detail.text
        assert "PROJECT OVERVIEW" in detail.text and "REFERENCE" in detail.text and "HANDOVER" in detail.text
        assert "Accounts &amp; access" in detail.text
        assert "In maintenance" in detail.text
        assert "這是使用者的說明" in detail.text
        assert "<h1>專案名稱</h1>" in detail.text
        assert 'class="tag owner-badge">負責人</span>' in detail.text
        assert ">維護中</span>" in detail.text
        assert "Delete this URL?" in detail.text

        for url, expected in [
            ("/", "Showing 1–1 of 1 project"),
            ("/projects/new", "Project details"),
            (f"{project_url}/edit", "Save project"),
            ("/settings/backup", "Download full backup"),
            ("/settings/vault", "Master password"),
        ]:
            page = client.get(url)
            assert page.status_code == 200
            assert '<html lang="en">' in page.text
            assert expected in page.text

        failed_setup = client.post("/settings/vault/setup", data={"master_password": "short", "confirm_password": "short"})
        assert failed_setup.status_code == 400
        assert "at least 16 characters" in failed_setup.text
        failed_restore = client.post("/settings/backup/restore", files={"backup_file": ("invalid.db", b"invalid")})
        assert "not a valid SQLite database backup" in failed_restore.text
        bad_name = client.post("/projects/new", data={"name": " "})
        assert bad_name.json()["detail"] == "Project name cannot be empty"
        invalid_language = client.post("/settings/language", data={"language": "fr"})
        assert invalid_language.status_code == 400
        assert client.cookies.get(LANGUAGE_COOKIE) == "en"

        master_password = "bilingual test master password"
        assert client.post("/settings/vault/setup", data={
            "master_password": master_password, "confirm_password": master_password,
        }).status_code == 303
        vault_token = client.cookies.get("projmemo_vault")
        assert client.post(f"{project_url}/accounts", data={
            "label": "Test account", "username": "demo", "secret_value": "dummy-secret",
        }).status_code == 303
        unlocked_detail = client.get(project_url)
        assert "Show for 15 seconds" in unlocked_detail.text
        assert "dummy-secret" not in unlocked_detail.text

        with TestClient(app) as other_client:
            assert '<html lang="zh-Hant">' in other_client.get("/").text

        client.post("/settings/language", data={"language": "zh-Hant", "return_to": "/?view=list&page_size=20&q=custom"})
        chinese_page = client.get(project_url)
        assert client.cookies.get("projmemo_vault") == vault_token
        assert "顯示 15 秒" in chinese_page.text
        assert '<html lang="zh-Hant">' in chinese_page.text
        assert "REFERENCE" not in chinese_page.text and "HANDOVER" not in chinese_page.text
        client.cookies.set(LANGUAGE_COOKIE, "invalid", domain="testserver.local", path="/")
        assert '<html lang="zh-Hant">' in client.get("/").text


def test_language_return_path_cannot_redirect_off_site(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(tmp_path / "redirects.db"))
    from app.main import app

    with TestClient(app, follow_redirects=False) as client:
        for destination in ["https://example.invalid", "//example.invalid", "///example.invalid", "/\\example.invalid", "/%2fexample.invalid", "//[broken", "/%0d%0aLocation:evil"]:
            response = client.post("/settings/language", data={"language": "en", "return_to": destination})
            assert response.status_code == 303
            assert response.headers["location"] == "/"


def test_translation_catalog_covers_templates_and_preserves_format_fields() -> None:
    from app.i18n import EN_MESSAGES, translate_error

    environment = Environment()
    for path in (Path(__file__).parent.parent / "app" / "templates").glob("*.html"):
        template = environment.parse(path.read_text(encoding="utf-8"))
        for call in template.find_all(nodes.Call):
            if isinstance(call.node, nodes.Name) and call.node.name == "t" and call.args:
                expressions = [call.args[0], *call.args[0].find_all(nodes.Const)]
                for expression in expressions:
                    if isinstance(expression, nodes.Const) and isinstance(expression.value, str):
                        assert expression.value in EN_MESSAGES, (path.name, expression.value)
        for data in template.find_all(nodes.TemplateData):
            assert not re.search(r"[\u3400-\u9fff]", data.data.replace("繁中", "")), (path.name, data.data)

    def fields(message):
        return {field for _, field, _, _ in Formatter().parse(message) if field is not None}

    for source, translated in EN_MESSAGES.items():
        assert fields(source) == fields(translated), source
    assert translate_error("備份檔的「projects」資料表欄位不完整，無法還原。", "en") == "The backup has missing columns in the 'projects' table and cannot be restored."
