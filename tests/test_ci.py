"""CI safeguards and deliberately failing formatting/syntax fixtures."""

import os
from pathlib import Path
import re

import pytest
import yaml

from scripts import check_sources

ROOT = Path(__file__).resolve().parents[1]


def test_workflow_is_read_only_pinned_and_windows_gates_linux():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    assert set(workflow["on"]) == {"push", "pull_request", "workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read"}
    jobs = workflow["jobs"]
    assert jobs["windows"]["runs-on"] == "windows-2025"
    assert jobs["linux"]["needs"] == "windows"
    assert jobs["linux"]["env"]["PROJMEMO_CI_CJK_REQUIRED"] == "1"
    for job in jobs.values():
        assert job["timeout-minutes"] <= 20
        uses = [step for step in job["steps"] if "uses" in step]
        assert len(uses) == 3
        assert all(re.fullmatch(r"actions/[a-z-]+@[0-9a-f]{40}", step["uses"]) for step in uses)
        assert uses[0]["with"]["persist-credentials"] is False
        commands = "\n".join(step.get("run", "") for step in job["steps"])
        for expected in ("--require-hashes", "check_catalogs.py", "check_sources.py", "-m pytest", "node --test"):
            assert expected in commands
        assert "--basetemp=data/pytest-ci" in commands
        assert "upload-artifact" not in str(job)
    assert "fonts-wqy-zenhei" in str(jobs["linux"])


@pytest.mark.parametrize("name,text,expected", [
    ("example.py", "pass", "missing final newline"),
    ("example.py", "pass \n", "trailing whitespace"),
    ("example.py", "def broken(\n", "invalid source syntax"),
    ("example.json", '{"x": 1, "x": 2}\n', "invalid source syntax"),
    ("example.json", "[\n", "invalid source syntax"),
    ("example.yml", "item: [\n", "invalid source syntax"),
    ("example.cjs", "const = bad;\n", "invalid JavaScript syntax"),
])
def test_source_checks_reject_real_bad_inputs(tmp_path, name, text, expected):
    directory = tmp_path / "app"
    directory.mkdir()
    (directory / name).write_text(text, encoding="utf-8")
    assert any(expected in problem for problem in check_sources.check(tmp_path))


def test_source_checks_accept_crlf_ignore_data_and_never_execute_scripts(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "app/example.py").write_bytes(b"raise RuntimeError('not executed')\r\n")
    (tmp_path / "app/example.cjs").write_text("throw new Error('not executed');\n")
    (tmp_path / "data/invalid.py").write_text("not valid syntax !!")
    assert check_sources.check(tmp_path) == []


def test_empty_root_and_missing_node_are_errors(tmp_path, monkeypatch):
    assert "no source files found" in check_sources.check(tmp_path)
    (tmp_path / "app").mkdir()
    (tmp_path / "app/example.js").write_text("void 0;\n")
    monkeypatch.setattr(check_sources.shutil, "which", lambda _: None)
    assert "Node.js is required for JavaScript syntax checks" in check_sources.check(tmp_path)


def test_invalid_utf8_source_is_reported(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app/bad.py").write_bytes(b"\xff\xfe")
    assert any("unreadable UTF-8" in problem for problem in check_sources.check(tmp_path))


def test_required_ci_cjk_font_is_real_and_contains_traditional_chinese():
    if os.getenv("PROJMEMO_CI_CJK_REQUIRED") != "1":
        pytest.skip("Explicit CJK environment check runs in the Linux CI job")
    from app import pdf_export
    from reportlab.pdfbase import pdfmetrics

    pdf_export._register_cjk_fonts.cache_clear()
    try:
        regular, bold = pdf_export._register_cjk_fonts()
        for name in (regular, bold):
            glyphs = pdfmetrics.getFont(name).face.charToGlyph
            assert all(ord(character) in glyphs for character in "專案備註交接清單環境設定")
    finally:
        pdf_export._register_cjk_fonts.cache_clear()


def test_missing_cjk_font_has_explicit_failure(monkeypatch):
    from app import pdf_export

    pdf_export._register_cjk_fonts.cache_clear()
    monkeypatch.setattr(pdf_export.Path, "is_file", lambda _: False)
    try:
        with pytest.raises(pdf_export.PDFExportError, match="PROJMEMO_PDF_FONT"):
            pdf_export._register_cjk_fonts()
    finally:
        pdf_export._register_cjk_fonts.cache_clear()
