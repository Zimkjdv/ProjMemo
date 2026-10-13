from pathlib import Path
from html.parser import HTMLParser

import pytest
from tests.client import TestClient


class IntroHeading(HTMLParser):
    def __init__(self):
        super().__init__()
        self.headings = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag == "h1":
            self.current = {"attrs": dict(attrs), "text": ""}
            self.headings.append(self.current)

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"] += data

    def handle_endtag(self, tag):
        if tag == "h1":
            self.current = None


@pytest.mark.parametrize("language, title, features", [
    ("zh-Hant", "個人專案知識庫", ["重要 URL", "Markdown 備註", "交接清單"]),
    ("en", "PERSONAL PROJECT KNOWLEDGE BASE", ["Important URLs", "Markdown notes", "Handover checklist"]),
])
def test_home_intro_localizes_without_changing_list_controls(tmp_path: Path, monkeypatch, language, title, features):
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(tmp_path / "home.db"))
    from app.main import app

    with TestClient(app, follow_redirects=False) as client:
        client.post("/projects/new", data={"name": "Hero fixture"})
        client.post("/settings/language", data={"language": language})
        response = client.get("/?view=list&page_size=20&q=Hero")
        assert response.status_code == 200
        intro = response.text.split('<section class="hero page-hero dashboard-hero"', 1)[1].split("</section>", 1)[0]
        assert 'aria-labelledby="home-intro-title"' in intro
        heading = IntroHeading()
        heading.feed(intro)
        assert len(heading.headings) == 1
        assert heading.headings[0]["attrs"]["id"] == "home-intro-title"
        assert heading.headings[0]["attrs"]["aria-label"] == title
        assert heading.headings[0]["text"].strip() == title
        assert "專案資訊，清楚有序。" not in intro
        assert "Project information, neatly organized." not in intro
        assert intro.count("<li>") == 3
        assert all(feature in intro for feature in features)
        assert 'href="/projects/new"' in intro
        assert '<table class="project-list">' in response.text
        assert 'value="20" selected' in response.text
        assert 'name="q" value="Hero"' in response.text
        for other_url in ("/settings/backup", "/settings/vault"):
            assert "dashboard-hero" not in client.get(other_url).text
