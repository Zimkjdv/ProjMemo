from html.parser import HTMLParser
from pathlib import Path

import pytest

from tests.client import TestClient


class Controls(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


@pytest.mark.parametrize('language', ['zh-Hant', 'en'])
def test_detail_polish_retains_heading_and_navigation_counts_and_named_icon_controls(tmp_path: Path, monkeypatch, language):
    monkeypatch.setenv('PROJMEMO_DB_PATH', str(tmp_path / 'polish.db'))
    from app.main import app

    with TestClient(app, follow_redirects=False) as client:
        project = client.post('/projects/new', data={'name': 'Polish fixture'}).headers['location']
        client.post('/settings/language', data={'language': language})
        for suffix, data in [
            ('urls', {'title': 'URL', 'url': 'https://example.invalid/'}),
            ('notes', {'title': 'Note', 'content_markdown': 'Short fixture'}),
            ('checklist', {'title': 'Checklist'}),
            ('environment-variables', {'key': 'FIXTURE_KEY'}),
            ('accounts', {'label': 'Account'}),
        ]:
            assert client.post(f'{project}/{suffix}', data=data).status_code == 303
        page = client.get(project)
        elements = Controls(page.text).elements
        assert sum(attrs.get('class') == 'section-count' for _, attrs in elements) == 5
        assert sum(attrs.get('class') == 'jump-count' for _, attrs in elements) == 5
        assert 'content-navigation-ready' not in page.text  # Both count locations are retained.
        assert '>•••</summary>' not in page.text
        controls = [attrs for tag, attrs in elements if tag == 'summary' and attrs.get('aria-label', '').startswith('Edit or delete' if language == 'en' else '編輯或刪除')]
        assert len(controls) == 5
        assert page.text.count('circle cx="19" cy="12"') == 5
        assert 'project-navigation.js?v=20261014-section-counts' in page.text
        assert 'styles.css?v=20261019-r11' in page.text


@pytest.mark.parametrize('language', ['zh-Hant', 'en'])
def test_selected_language_contract_and_shared_styles_cover_all_desktop_pages(tmp_path: Path, monkeypatch, language):
    monkeypatch.setenv('PROJMEMO_DB_PATH', str(tmp_path / 'pages.db'))
    from app.main import app

    with TestClient(app, follow_redirects=False) as client:
        project = client.post('/projects/new', data={'name': 'Page fixture'}).headers['location']
        client.post('/settings/language', data={'language': language})
        for url in ['/', '/projects/new', project + '/edit', '/settings/vault', '/settings/backup', project]:
            page = client.get(url)
            assert page.status_code == 200
            elements = Controls(page.text).elements
            language_buttons = [attrs for tag, attrs in elements if tag == 'button' and attrs.get('name') == 'language']
            assert len(language_buttons) == 2
            active = [attrs for attrs in language_buttons if attrs.get('aria-pressed') == 'true']
            assert len(active) == 1 and active[0]['value'] == language
            assert active[0]['class'] == 'active'
            assert 'styles.css?v=20261019-r11' in page.text
