"""Render real Markdown output; assert literal metadata and unchanged note syntax."""

from contextlib import closing
from html.parser import HTMLParser
import sqlite3

from markdown import markdown
import pytest

from app import markdown_export as renderer
from app.main import create_app
from app.services import exports, projects
from tests.client import TestClient


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.text = []
        self.links = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag == "a":
            self.links.append(dict(attrs)["href"])

    def handle_data(self, value):
        self.text.append(value)


def render_document(source):
    return Document(markdown(source, extensions=["tables", "fenced_code"]))


def fixture_data():
    project = dict(id=1, name="專案 [A] *B* `C` <D> &copy; \\ #測試",
                   status="maintenance", owner="Owner_[A]", tags="tag|a, [b]",
                   description="<script>literal</script>\n- not a list\n1. not numbered")
    urls = [dict(type="git", title="Repo [x](fake) *literal*", note="note\n# not heading",
                 url="https://example.invalid/a(b)c)?q=[x]&copy;=%25&tag=<value>")]
    notes = [dict(title="Note [A] *literal*", category="caution", priority="high",
                  content_markdown="**Real note markup**\n\n```python\nprint('a|b')\n```\n")]
    variables = [dict(key="KEY`A\\|B", environment="local", is_secret=0,
                      description="**not bold** | C:\\tmp\\| <literal>\r\nnext",
                      source_or_owner="Owner|A &copy;"),
                 dict(key="SAFE_KEY", environment="production", is_secret=1,
                      description="do-not-export-secret-description", source_or_owner="Vault reference")]
    checklist = [dict(title="Task [x] *literal*", completed=1, owner="A|B",
                      description="line\n# not heading", note="C:\\tmp\\|A")]
    accounts = [dict(label="Account [A] <literal>", category="database", environment="staging",
                     endpoint="https://host.invalid/a(b)", database_name="DB_*A*", username="user_[A]",
                     role_scope="read|write", purpose="plain `text`", owner="Owner_[A]",
                     has_secret=True, secret_reference="external|vault", secret_value="private-fixture-password")]
    return project, urls, notes, checklist, variables, accounts


def test_special_metadata_renders_literally_without_creating_extra_markup():
    data = fixture_data()
    source = renderer.build_markdown(*data)
    parsed = render_document(source)
    text = "".join(parsed.text)
    for value in (data[0]["name"], data[0]["owner"], data[1][0]["title"], data[2][0]["title"],
                  data[3][0]["title"], data[5][0]["label"], data[5][0]["username"]):
        assert value in text
    assert parsed.tags.count("h1") == 1
    assert parsed.tags.count("h3") == 2
    assert "script" not in parsed.tags and "literal" in text
    assert parsed.tags.count("strong") == 1  # Only the deliberately formatted note.
    assert "ol" not in parsed.tags
    assert "- not a list" in text and "1. not numbered" in text
    assert data[2][0]["content_markdown"] in source
    assert "print('a|b')" in text
    assert "private-fixture-password" not in source
    assert "do-not-export-secret-description" not in source


def test_link_destination_parentheses_angles_entities_and_percent_are_unambiguous():
    data = fixture_data()
    parsed = render_document(renderer.build_markdown(*data))
    assert parsed.links == ["https://example.invalid/a%28b%29c%29?q=[x]&copy;=%25&tag=%3Cvalue%3E"]


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,<b>bad</b>", "https://[broken"])
def test_invalid_legacy_url_is_literal_not_an_active_link(url):
    parsed = render_document(renderer.markdown_link("[literal]", url))
    assert not parsed.links
    assert url in "".join(parsed.text)


def test_table_backslash_pipe_backticks_newlines_and_html_stay_in_four_cells():
    data = fixture_data()
    parsed = render_document(renderer.build_markdown(*data))
    assert parsed.tags.count("td") == 8
    text = "".join(parsed.text)
    assert data[4][0]["key"] in text
    assert data[4][0]["description"].replace("\r\n", " ") in text
    assert data[4][0]["source_or_owner"] in text
    assert "SAFE_KEY" in text
    assert renderer.markdown_key_cell("SAFE_KEY") == "`SAFE_KEY`"


@pytest.mark.parametrize("secret", ["line1\nline2", "```\n# not heading\n```", "````\r\ntext | <a> &\r\n````", "  exact spaces  "])
def test_sensitive_password_fence_preserves_exact_source_and_is_opt_in(secret):
    data = fixture_data()
    data[5][0]["secret_value"] = secret
    ordinary = renderer.build_markdown(*data)
    sensitive = renderer.build_markdown(*data, include_secrets=True)
    assert secret not in ordinary
    assert secret in sensitive
    assert "此匯出檔包含實際密碼" in sensitive
    assert render_document(sensitive).tags.count("h1") == 1


def test_empty_sections_are_readable_and_still_have_all_section_headings():
    source = renderer.build_markdown(fixture_data()[0], [], [], [], [], [])
    parsed = render_document(source)
    assert parsed.tags.count("h2") == 6
    assert "尚未建立 URL" in "".join(parsed.text)


def test_http_ui_markdown_and_pdf_share_complete_raw_metadata_without_mutating_it(tmp_path, monkeypatch):
    path = tmp_path / "export.db"
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(path))
    data = fixture_data()
    captured = []
    monkeypatch.setattr(exports, "generate_project_pdf", lambda *args: captured.append(args) or b"%PDF-projection-fixture")
    with TestClient(create_app()) as client:
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.execute("INSERT INTO projects(id,name,description,owner,tags) VALUES(1,?,?,?,?)",
                               tuple(data[0][key] for key in ("name", "description", "owner", "tags")))
            connection.executemany("INSERT INTO notes(project_id,title,content_markdown) VALUES(1,?,?)",
                                   [(f"Note-{number:03}", "**complete**") for number in range(55)])
        before = projects.load_project_data(1)
        ui = Document(client.get("/projects/1?notes_page_size=10").text)
        exported = client.get("/projects/1/export.md")
        assert exported.status_code == 200
        assert data[0]["name"] in "".join(ui.text)
        assert data[0]["name"] in "".join(render_document(exported.text).text)
        assert "Note-000" in exported.text and "Note-054" in exported.text
        assert client.get("/projects/1/export.pdf").status_code == 200
        assert captured[0][0]["name"] == data[0]["name"]
        assert len(captured[0][2]) == 55  # PDF projection, not a claim of visual PDF QA.
        after = projects.load_project_data(1)
        assert tuple(before.project) == tuple(after.project)
        assert [dict(row) for row in before.notes] == [dict(row) for row in after.notes]
