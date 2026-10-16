"""The manual acceptance helper stays isolated and never stores real secrets."""

from html.parser import HTMLParser
from pathlib import Path

import pytest

from tests.client import TestClient
from tests.desktop_fixture import ClipboardFixture, COPY_CODE, COPY_ENDPOINT, COPY_URL, COPY_USERNAME, seed


class CodeText(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.blocks, self.inside = [], False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "pre":
            self.blocks.append("")
            self.inside = True

    def handle_endtag(self, tag):
        if tag == "pre":
            self.inside = False

    def handle_data(self, data):
        if self.inside:
            self.blocks[-1] += data


@pytest.mark.parametrize("mode", ["normal", "denied", "unavailable"])
def test_desktop_fixture_profiles_and_explicit_failure_modes(tmp_path, monkeypatch, mode):
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(tmp_path / "fixture.db"))
    from app.db import db_session
    from app.main import create_app

    app = create_app()
    target = app if mode == "normal" else ClipboardFixture(app, mode)
    with TestClient(target) as client:
        projects = seed(app.state.runtime)
        assert projects == {"empty": 1, "mixed": 2, "large": 3}
        empty = client.get("/projects/1").text
        mixed = client.get("/projects/2").text
        assert 'class="detail-empty"' in empty
        assert COPY_ENDPOINT in mixed and COPY_USERNAME in mixed
        assert COPY_URL.replace("&", "&amp;") in mixed
        assert 'data-copy-target="url-value-' in mixed
        assert COPY_CODE in CodeText(mixed).blocks
        if mode == "normal":
            assert "data-desktop-clipboard-fixture" not in mixed
            assert "Object.defineProperty(navigator" not in mixed
        else:
            assert f'data-desktop-clipboard-fixture="{mode}"' in mixed
            assert ("Promise.reject" in mixed) == (mode == "denied")
        with db_session() as connection:
            assert connection.execute("SELECT COUNT(*) FROM notes WHERE project_id=3").fetchone()[0] == 250
            assert connection.execute("SELECT COUNT(*) FROM access_accounts WHERE project_id=3").fetchone()[0] == 30
            assert connection.execute("SELECT COUNT(*) FROM access_accounts WHERE secret_ciphertext IS NOT NULL").fetchone()[0] == 0
            assert COPY_CODE in connection.execute(
                "SELECT content_markdown FROM notes WHERE project_id=2 ORDER BY id DESC LIMIT 1"
            ).fetchone()[0]
        assert client.get("/health/ready").status_code == 200


def test_desktop_fixture_rejects_implicit_mode_and_has_no_formal_db_or_host_option():
    with pytest.raises(ValueError):
        ClipboardFixture(None, "normal")
    from tests.desktop_fixture import main
    with pytest.raises(SystemExit) as error:
        main(["--db", "formal.db"])
    assert error.value.code == 2
    source = (Path(__file__).parent / "desktop_fixture.py").read_text(encoding="utf-8")
    assert source.index('os.environ["PROJMEMO_DB_PATH"] =') < source.index("from app.db import init_db")
    assert 'reserved.bind(("127.0.0.1", 0))' in source
