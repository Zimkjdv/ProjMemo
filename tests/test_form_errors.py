from contextlib import closing
import sqlite3

import pytest

from app.main import create_app
from tests.client import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(tmp_path / "forms.db"))
    with TestClient(create_app()) as client:
        client.post("/projects/new", data={"name": "Fixture"})
        yield client


@pytest.mark.parametrize("language,message", [("zh-Hant", "請檢查輸入資料"), ("en", "Check your input")])
@pytest.mark.parametrize("path,data", [
    ("/projects/new", {"name": " ", "description": '<script>alert("draft")</script>', "owner": "Team"}),
    ("/projects/1/notes", {"title": "", "content_markdown": "Keep this draft"}),
    ("/projects/1/urls", {"title": "Draft", "url": "invalid", "note": "Keep this draft"}),
    ("/projects/1/checklist", {"title": " ", "description": "Keep this draft"}),
    ("/projects/1/environment-variables", {"key": " ", "description": "Keep this draft"}),
    ("/projects/1/accounts", {"label": "Draft account", "secret_value": "NEVER-ECHO-THIS-SECRET"}),
])
def test_native_errors_recover_original_forms(client, language, message, path, data):
    client.cookies.set("projmemo_language", language)
    response = client.post(path, data=data, headers={"Accept": "text/html"})
    assert response.status_code in {400, 422, 423}
    assert response.headers["content-type"].startswith("text/html")
    assert "no-store" in response.headers["cache-control"]
    assert message in response.text and 'data-recovered-form="true"' in response.text
    assert "NEVER-ECHO-THIS-SECRET" not in response.text
    assert '<script>alert("draft")</script>' not in response.text
    if "Keep this draft" in data.values():
        assert "Keep this draft" in response.text


def test_missing_password_does_not_echo_other_password_in_validation(client):
    response = client.post("/settings/vault/setup", data={"master_password": "DO-NOT-ECHO-THIS-SECRET"},
                           headers={"Accept": "text/html"})
    assert response.status_code == 422
    assert "DO-NOT-ECHO-THIS-SECRET" not in response.text
    assert 'aria-invalid="true"' in response.text
    assert "confirm_password" in response.text


def test_json_errors_remain_json_and_never_serialize_validation_input(client):
    response = client.post("/projects/new", data={"name": " "})
    assert response.status_code == 400
    assert response.json() == {"detail": "專案名稱不可為空白"}
    response = client.post("/settings/vault/setup", data={"master_password": "PRIVATE"})
    assert response.status_code == 422 and "PRIVATE" not in response.text


def test_edit_error_reopens_correct_editor_and_preserves_markup(client):
    client.post("/projects/1/notes", data={"title": "Original", "content_markdown": "Original body"})
    response = client.post("/notes/1/edit", data={"title": " ", "content_markdown": "Draft & <b>literal</b>"},
                           headers={"Accept": "text/html"})
    assert response.status_code == 400
    assert "Draft &amp; &lt;b&gt;literal&lt;/b&gt;" in response.text
    assert 'class="item-actions" open' in response.text
    assert 'aria-invalid="true"' in response.text
    assert "Original body" in client.get("/projects/1").text


def test_cross_origin_errors_are_not_converted_to_draft_pages(client):
    response = client.post("/projects/new", data={"name": " "},
                           headers={"Accept": "text/html", "Origin": "https://evil.invalid"})
    assert response.status_code == 403 and "data-recovered-form" not in response.text
