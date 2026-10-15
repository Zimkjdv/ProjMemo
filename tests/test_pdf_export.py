from reportlab.lib.enums import TA_CENTER

from app.pdf_export import _styles
from pathlib import Path

import pytest

from app import pdf_export
from tests.pdf_audit import audit_pdf
from tests.pdf_fixtures import SECRET, pdf_fixture


def test_pdf_center_style_uses_reportlab_alignment_constant() -> None:
    assert _styles("Helvetica")["center"].alignment == TA_CENTER


@pytest.mark.parametrize("kind", ["empty", "mixed", "long-row", "long-title"])
def test_real_pdf_parse_extract_rasterize_and_fit_page(kind):
    data = pdf_fixture(kind)
    content = pdf_export.generate_project_pdf(*data.renderer_args())
    text, pages = audit_pdf(content)
    compact = "".join(text.split())
    for title in ["專案描述", "重要URL", "備註與注意事項", "環境變數說明", "帳號與存取資料", "交接清單"]:
        assert title in compact
    assert SECRET not in text
    if kind == "empty":
        assert "尚未建立備註。" in text
    else:
        assert len(pages) >= 4
        assert data.urls[0]["url"] in compact
        assert "fixture-user" in text and "Checklist-014" in text
        assert "已保存於ProjMemo保管庫（未匯出）" in compact
        assert "資料還原" not in text
    if kind in {"mixed", "long-title"}:
        for number in range(90):
            assert f"CODE-{number:03}" in text
        for number in range(80):
            assert f"TableRow-{number:03}" in text
        assert text.count("Table ID") >= 2  # Actual repeated headers across table pages.
    elif kind == "long-row":
        assert "LONGROW-BEGIN" in text and "LONGROW-END" in text


def test_pdf_embeds_usable_cjk_fonts_and_glyphs():
    from io import BytesIO
    from pypdf import PdfReader
    from reportlab.pdfbase import pdfmetrics

    content = pdf_export.generate_project_pdf(*pdf_fixture("mixed").renderer_args())
    reader = PdfReader(BytesIO(content))
    text = "".join(page.extract_text() for page in reader.pages)
    regular, bold = pdf_export._register_cjk_fonts()
    assert pdf_export._list_bullet(regular) in text  # Embedded Unicode, not Helvetica's DEL alias.
    for font_name in (regular, bold):
        glyphs = pdfmetrics.getFont(font_name).face.charToGlyph
        assert all(ord(char) in glyphs for char in text if not char.isspace())
    fonts = [font.get_object() for page in reader.pages for font in page["/Resources"]["/Font"].values()]
    embedded = [font for font in fonts if "/ToUnicode" in font and "/FontDescriptor" in font]
    assert embedded
    assert all("/FontFile2" in font["/FontDescriptor"] for font in embedded)


@pytest.mark.parametrize("glyphs,expected", [
    ({0x2022: 1, 0x25cf: 2, 45: 3}, "•"),
    ({0x2022: 0, 0x25cf: 2, 45: 3}, "●"),
    ({45: 3}, "-"),
])
def test_list_bullet_requires_an_actual_nonzero_font_glyph(monkeypatch, glyphs, expected):
    from types import SimpleNamespace
    monkeypatch.setattr(pdf_export.pdfmetrics, "getFont", lambda _: SimpleNamespace(face=SimpleNamespace(charToGlyph=glyphs)))
    assert pdf_export._list_bullet("fixture") == expected


@pytest.mark.parametrize("secret", [SECRET, "first\nsecond<&>", "  leading  internal   trailing  "])
def test_real_sensitive_pdf_is_explicit_and_normal_ignores_plaintext(secret):
    data = pdf_fixture("empty")
    account = pdf_fixture().access_accounts[0]
    account["secret_value"] = secret
    data.access_accounts.append(account)
    ordinary = pdf_export.generate_project_pdf(*data.renderer_args())
    sensitive = pdf_export.generate_project_pdf(*data.renderer_args(), include_secrets=True)
    ordinary_text, _ = audit_pdf(ordinary)
    sensitive_text, _ = audit_pdf(sensitive)
    assert secret.strip().splitlines()[0] not in ordinary_text
    assert "敏感資料" not in ordinary_text and "敏感資料" in sensitive_text
    for line in secret.splitlines():
        assert line in sensitive_text


def test_real_missing_font_export_never_falls_back_to_missing_glyphs(monkeypatch):
    pdf_export._register_cjk_fonts.cache_clear()
    monkeypatch.setattr(Path, "is_file", lambda _: False)
    try:
        with pytest.raises(pdf_export.PDFExportError, match="PROJMEMO_PDF_FONT"):
            pdf_export.generate_project_pdf(*pdf_fixture("empty").renderer_args())
    finally:
        pdf_export._register_cjk_fonts.cache_clear()


@pytest.mark.parametrize("language", ["zh-Hant", "en"])
def test_real_http_pdf_complete_projection_and_sensitive_policy(tmp_path, monkeypatch, language):
    from app.db import db_session
    from app.main import create_app
    from app.services import exports
    from tests.client import TestClient

    monkeypatch.setenv("PROJMEMO_DB_PATH", str(tmp_path / "pdf-http.db"))
    with TestClient(create_app(), follow_redirects=False) as client:
        client.cookies.set("projmemo_language", language)
        client.get("/")
        assert client.post("/projects/new", data={"name": "真實 PDF / HTTP fixture"}).status_code == 303
        master = "R08 synthetic PDF master phrase"
        assert client.post("/settings/vault/setup", data={"master_password": master, "confirm_password": master}).status_code == 303
        assert client.post("/projects/1/accounts", data={"label": "Encrypted fixture", "secret_value": SECRET}).status_code == 303
        with db_session(write=True) as connection:
            connection.executemany("INSERT INTO notes (project_id, title, content_markdown) VALUES (1, ?, ?)",
                                   [(f"FullNote-{n:03}", "完整內容，不裁切 UI 分頁。") for n in range(55)])
        # A normal export must never decrypt even while this browser is unlocked.
        original_decrypt = exports.decrypt_secret
        def forbidden_decrypt(*args):
            pytest.fail("Ordinary PDF must not decrypt")
        monkeypatch.setattr(exports, "decrypt_secret", forbidden_decrypt)
        ordinary = client.get("/projects/1/export.pdf")
        assert ordinary.status_code == 200 and ordinary.headers["content-type"] == "application/pdf"
        assert "attachment" in ordinary.headers["content-disposition"]
        text, _ = audit_pdf(ordinary.content)
        assert SECRET not in text
        for number in range(55):
            assert f"FullNote-{number:03}" in text
        monkeypatch.setattr(exports, "decrypt_secret", original_decrypt)
        values = {"export_format": "pdf", "confirm_sensitive_export": "true"}
        assert client.post("/projects/1/export-with-secrets", data=values).status_code == 403
        assert client.post("/settings/vault/export-policy", data={"allow_secret_export": "true"}).status_code == 303
        assert client.post("/projects/1/export-with-secrets", data={"export_format": "pdf"}).status_code == 400
        sensitive = client.post("/projects/1/export-with-secrets", data=values)
        assert sensitive.status_code == 200
        assert "no-store" in sensitive.headers["cache-control"]
        sensitive_text, _ = audit_pdf(sensitive.content)
        assert SECRET in sensitive_text and "敏感資料" in sensitive_text
        assert client.post("/settings/vault/lock").status_code == 303
        assert client.post("/projects/1/export-with-secrets", data=values).status_code == 423
        pdf_export._register_cjk_fonts.cache_clear()
        with monkeypatch.context() as missing_font:
            missing_font.setattr(Path, "is_file", lambda _: False)
            failed = client.get("/projects/1/export.pdf")
            assert failed.status_code == 503 and "PROJMEMO_PDF_FONT" in failed.text
            assert SECRET not in failed.text
        pdf_export._register_cjk_fonts.cache_clear()
