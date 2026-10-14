from html.parser import HTMLParser
from html import unescape
import json
from pathlib import Path
import re

import pytest

from tests.client import TestClient


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


@pytest.mark.parametrize("language", ["zh-Hant", "en"])
@pytest.mark.parametrize("populated", [False, True])
def test_content_forms_have_safe_cancel_controls_and_bilingual_messages(tmp_path: Path, monkeypatch, language, populated):
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(tmp_path / "content-ui.db"))
    from app.main import app

    with TestClient(app, follow_redirects=False) as client:
        project = client.post("/projects/new", data={"name": "Content fixture"}).headers["location"]
        client.post("/settings/language", data={"language": language})
        if populated:
            for suffix, data in [
                ("urls", {"title": "URL", "url": "https://example.invalid/", "type": "staging"}),
                ("notes", {"title": "Critical", "content_markdown": "Short note", "category": "caution", "priority": "critical"}),
                ("checklist", {"title": "Checklist"}),
                ("environment-variables", {"key": "DEMO_SECRET", "environment": "production"}),
                ("accounts", {"label": "Account"}),
            ]:
                assert client.post(f"{project}/{suffix}", data=data).status_code == 303
        page = client.get(project)
        elements = Elements(page.text).elements
        forms = [attrs for tag, attrs in elements if tag == "form" and "data-content-form" in attrs]
        cancels = [attrs for tag, attrs in elements if tag == "button" and "data-cancel-content" in attrs]
        assert len(forms) == len(cancels) == (10 if populated else 5)
        assert all(attrs["type"] == "button" and "hidden" in attrs for attrs in cancels)
        ids = [attrs["id"] for _, attrs in elements if "id" in attrs]
        assert len(ids) == len(set(ids))
        assert "project-forms.js" in page.text and "project-notes.js" in page.text
        assert page.text.index('id="content-form-messages"') > page.text.index('id="project-content"')
        messages = json.loads(re.search(r'id="content-form-messages">(.*?)</script>', page.text, re.S)[1])
        assert "Discard them and close the form?" in messages["discard"] if language == "en" else "尚有未儲存的修改" in messages["discard"]
        sources = [attrs for tag, attrs in elements if tag == "input" and attrs.get("name") == "source_or_owner"]
        assert len(sources) == (2 if populated else 1)
        assert all(attrs.get("placeholder") for attrs in sources)
        assert "url-kind-staging" in page.text if populated else "url-kind-staging" not in page.text


@pytest.mark.parametrize("language", ["zh-Hant", "en"])
def test_note_summaries_are_plain_safe_text_and_full_markdown_is_not_truncated(tmp_path: Path, monkeypatch, language):
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(tmp_path / "notes-ui.db"))
    from app.main import app

    markdown = "<script>unsafe()</script>\n\n**Readable** & literal\n\n| Name | Value |\n|---|---|\n| Full | Table |\n\n```sh\n  echo '<demo>'\n\tsecond line\n```\n\n" + "Long note paragraph. " * 80
    with TestClient(app, follow_redirects=False) as client:
        project = client.post("/projects/new", data={"name": "Note fixture"}).headers["location"]
        client.post("/settings/language", data={"language": language})
        client.post(f"{project}/notes", data={"title": "Always visible <title>", "content_markdown": markdown, "category": "known_issue", "priority": "high"})
        page = client.get(project)
        elements = Elements(page.text).elements
        notes = [attrs for tag, attrs in elements if tag == "details" and "data-note-content" in attrs]
        assert len(notes) == 1 and "open" in notes[0]  # Full content remains readable without JS.
        summary = re.search(r'<span class="note-preview" data-note-summary>(.*?)</span>', page.text, re.S)[1]
        assert "<table" not in summary and "<code" not in summary and "unsafe()" not in summary
        assert "&lt;demo&gt;" in summary and "Long note paragraph." in summary
        code = unescape(re.search(r'<pre><code>(.*?)</code></pre>', page.text, re.S)[1])
        assert "<table>" in page.text and code == "  echo '<demo>'\n    second line\n"
        assert "Always visible &lt;title&gt;" in page.text
        assert 'class="mini-label note-category"' in page.text
        assert 'class="priority-label priority-high"' in page.text
        assert "Read full note" in page.text if language == "en" else "展開全文" in page.text
