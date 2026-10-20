from html.parser import HTMLParser
from pathlib import Path

from tests.client import TestClient


class PageElements(HTMLParser):
    def __init__(self, html: str):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


def test_detail_views_share_forms_and_have_compact_empty_sections(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(tmp_path / "details.db"))
    from app.main import app

    with TestClient(app, follow_redirects=False) as client:
        project_url = client.post("/projects/new", data={"name": "View fixture"}).headers["location"]
        page = client.get(project_url)
        assert page.status_code == 200
        elements = PageElements(page.text).elements
        assert sum("detail-empty" in attrs.get("class", "") for _, attrs in elements) == 5
        assert sum("detail-panel-empty" in attrs.get("class", "") for _, attrs in elements) == 5
        assert not any("breadcrumb" in attrs.get("class", "") for _, attrs in elements)
        assert any(tag == "nav" and attrs.get("aria-label") == "內容導覽" for tag, attrs in elements)
        assert any(tag == "a" and attrs.get("href") == "/" and attrs.get("aria-current") == "page" for tag, attrs in elements)
        assert '>我的專案</a>' in page.text
        ids = [attrs["id"] for _, attrs in elements if "id" in attrs]
        assert len(ids) == len(set(ids))
        # Side-column accounts are immediately after the main-column notes.
        assert ids.index("project-notes") < ids.index("access-accounts") < ids.index("handover") < ids.index("environment")
        assert "環境設定</span>" not in page.text
        assert "empty-inline" not in page.text
        buttons = [attrs for tag, attrs in elements if tag == "button" and "data-detail-view" in attrs]
        assert [attrs["data-detail-view"] for attrs in buttons] == ["cards", "list"]
        assert all(attrs["aria-controls"] == "project-content" for attrs in buttons)
        for suffix in ("urls", "notes", "checklist", "environment-variables", "accounts"):
            assert sum(tag == "form" and attrs.get("action") == f"{project_url}/{suffix}" for tag, attrs in elements) == 1
        assert "只有實際密碼欄位加密" in page.text
        client.post("/settings/language", data={"language": "en", "return_to": project_url})
        english = client.get(project_url)
        assert "Project content view" in english.text
        assert 'aria-label="Content navigation"' in english.text
        assert "Select a section to jump to it" in english.text
        assert "More account details" not in english.text  # No records yet.
        assert "Only password fields are encrypted" in english.text


def test_populated_details_have_column_labels_and_expandable_safe_content(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(tmp_path / "populated.db"))
    from app.main import app

    with TestClient(app, follow_redirects=False) as client:
        project_url = client.post("/projects/new", data={"name": "Populated fixture"}).headers["location"]
        for suffix, data in [
            ("urls", {"title": "Repo", "url": "https://example.invalid/repo", "type": "git"}),
            ("notes", {"title": "Caution", "content_markdown": "**Ready** <script>alert(1)</script>", "priority": "high"}),
            ("checklist", {"title": "Deploy", "category": "deployment"}),
            ("environment-variables", {"key": "DATABASE_URL", "environment": "production", "is_secret": "true"}),
            ("accounts", {"label": "Database", "username": "test-user", "role_scope": "Read only"}),
        ]:
            assert client.post(f"{project_url}/{suffix}", data=data).status_code == 303
        page = client.get(project_url)
        elements = PageElements(page.text).elements
        assert sum("detail-columns " in attrs.get("class", "") for _, attrs in elements) == 5
        assert not any("detail-panel-empty" in attrs.get("class", "") for _, attrs in elements)
        expanders = [attrs for tag, attrs in elements if tag == "details" and "data-expand-in-cards" in attrs]
        assert len(expanders) == 1 and all("open" in attrs for attrs in expanders)
        assert sum(tag == "details" and "data-note-content" in attrs for tag, attrs in elements) == 1
        assert "<script>alert(1)</script>" not in page.text
        assert "<strong>Ready</strong>" in page.text
        assert sum("data-secret-output" in attrs for _, attrs in elements) == 0
        assert sum(tag == "form" and attrs.get("action", "").endswith("/accounts") for tag, attrs in elements) == 1
        client.post("/settings/language", data={"language": "en", "return_to": project_url})
        english = client.get(project_url)
        assert "More account details" in english.text
        assert "URL / note" in english.text
