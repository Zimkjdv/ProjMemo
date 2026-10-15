import json
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import urlencode

import pytest
from tests.client import TestClient


class Elements(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.items = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.items.append((tag, dict(attrs)))


@pytest.mark.parametrize('language', ['zh-Hant', 'en'])
def test_list_preferences_use_applied_state_and_clear_links_remain_authoritative(tmp_path, monkeypatch, language):
    monkeypatch.setenv('PROJMEMO_DB_PATH', str(tmp_path / 'list.db'))
    from app.main import app
    with TestClient(app) as client:
        client.post('/settings/language', data={'language': language})
        query = {'q': '</script><script>fixture</script>', 'status': 'handover', 'view': 'list', 'page_size': 20}
        page = client.get('/?' + urlencode(query))
        assert page.status_code == 200
        match = re.search(r'<script type="application/json" id="list-preferences">(.*?)</script>', page.text)
        assert json.loads(match[1]) == query
        assert '</script><script>fixture</script>' not in page.text
        assert 'data-reset-list-preferences' in page.text
        assert 'href="/?view=list&amp;page_size=20&amp;page=1"' in page.text
        assert 'Reset list' in page.text if language == 'en' else '重設列表' in page.text
        assert 'list-preferences.js?v=20261014-r06' in page.text


@pytest.mark.parametrize('language', ['zh-Hant', 'en'])
def test_account_expanders_keep_full_nonsecret_values_and_original_copy_targets(tmp_path, monkeypatch, language):
    monkeypatch.setenv('PROJMEMO_DB_PATH', str(tmp_path / 'values.db'))
    from app.main import app
    endpoint, username = 'host.example.invalid/' + 'long/' * 100, 'fixture-user-' * 50
    with TestClient(app, follow_redirects=False) as client:
        client.post('/settings/language', data={'language': language})
        project = client.post('/projects/new', data={'name': 'R06 fixture'}).headers['location']
        client.post(project + '/accounts', data={'label': 'Long field', 'endpoint': endpoint, 'username': username})
        client.post(project + '/accounts', data={'label': 'Empty field'})
        page = client.get(project)
        items = Elements(page.text).items
        ids = [attrs['id'] for _, attrs in items if 'id' in attrs]
        assert len(ids) == len(set(ids))
        assert sum('data-readable-value' in attrs for _, attrs in items) == 2
        controls = [attrs for tag, attrs in items if tag == 'button' and 'data-expand-value' in attrs]
        assert len(controls) == 2 and all('hidden' in attrs and attrs['aria-expanded'] == 'false' for attrs in controls)
        assert all(attrs['aria-controls'] in ids for attrs in controls)
        assert endpoint in page.text and username in page.text
        assert 'Show full value' in page.text if language == 'en' else '展開完整內容' in page.text
        assert sum(attrs.get('class') == 'section-count' for _, attrs in items) == 5
        assert sum(attrs.get('class') == 'jump-count' for _, attrs in items) == 5
        assert 'project-values.js?v=20261014-r06' in page.text


@pytest.mark.parametrize('language', ['zh-Hant', 'en'])
def test_note_paging_is_progressive_and_keeps_full_export_content(tmp_path, monkeypatch, language):
    monkeypatch.setenv('PROJMEMO_DB_PATH', str(tmp_path / 'pages.db'))
    from app.main import app
    from app.db import db_session
    with TestClient(app, follow_redirects=False) as client:
        client.post('/settings/language', data={'language': language})
        project = client.post('/projects/new', data={'name': 'Many notes'}).headers['location']
        assert 'data-note-pagination' not in client.get(project).text
        with db_session() as connection:
            connection.executemany('INSERT INTO notes (project_id, title, content_markdown) VALUES (?, ?, ?)',
                [(int(project.rsplit('/', 1)[1]), f'Fixture note {i}', 'Fixture content') for i in range(51)])
        page = client.get(project)
        items = Elements(page.text).items
        assert sum(tag == 'article' and 'note-card' in attrs.get('class', '') for tag, attrs in items) == 20
        assert all('hidden' not in attrs for tag, attrs in items if tag == 'article')
        assert any(tag == 'nav' and 'data-note-pagination' in attrs and 'hidden' not in attrs for tag, attrs in items)
        assert 'Notes per page' in page.text if language == 'en' else '每頁備註數量' in page.text
        assert 'server-note-pagination.js?v=20261015-r05-paging' in page.text
        exported = client.get(project + '/export.md').text
        assert all(f'Fixture note {i}' in exported for i in range(51))
