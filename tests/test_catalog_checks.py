"""Mutation tests prove the catalog check can fail, without touching real catalogs."""

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts import check_catalogs as checks

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def isolated_app(tmp_path):
    app = tmp_path / "app"
    shutil.copytree(ROOT / "app", app, ignore=shutil.ignore_patterns("__pycache__"))
    return app


def update_json(app, name, change):
    path = app / "locales" / name
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_live_catalog_is_complete_without_accessing_a_database(tmp_path, monkeypatch):
    path = tmp_path / "must-not-exist" / "data.db"
    monkeypatch.setenv("PROJMEMO_DB_PATH", str(path))
    assert checks.check(ROOT / "app") == []
    assert not path.parent.exists()


def test_checker_from_another_directory_and_duplicate_json_key(tmp_path, isolated_app):
    result = subprocess.run([sys.executable, str(ROOT / "scripts/check_catalogs.py")], cwd=tmp_path,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0 and "Catalog check passed" in result.stdout
    (isolated_app / "locales/en.json").write_text('{"key":"first","key":"second"}')
    assert checks.main(["--app-dir", str(isolated_app)]) == 1


def test_new_literal_missing_translation_is_detected(isolated_app):
    (isolated_app / "templates/new.html").write_text("{{ t('全新介面文字') }}", encoding="utf-8")
    assert "missing: 全新介面文字" in checks.check(isolated_app)


def test_python_user_facing_error_and_options_are_covered(isolated_app):
    (isolated_app / "new_error.py").write_text("raise ApplicationError(400, '全新錯誤文字')", encoding="utf-8")
    assert "missing: 全新錯誤文字" in checks.check(isolated_app)
    update_json(isolated_app, "en.json", lambda data: data.pop("維護中"))
    assert "missing: 維護中" in checks.check(isolated_app)


def test_stale_entry_is_reported_and_retention_requires_reason(isolated_app):
    update_json(isolated_app, "en.json", lambda data: data.update({"old-unused": "Old"}))
    assert "unused: old-unused" in checks.check(isolated_app)
    update_json(isolated_app, "catalog-policy.json", lambda data: data["retained_unused"].update({"old-unused": "External compatibility fixture"}))
    assert checks.check(isolated_app) == []
    update_json(isolated_app, "catalog-policy.json", lambda data: data["retained_unused"].update({"old-unused": ""}))
    assert any("invalid/stale retained" in value for value in checks.check(isolated_app))


@pytest.mark.parametrize("translation", ["Missing field", "{other}", "{count:04d}", "{count!r}", "{count", "{count.__class__}", "{count} {count}"])
def test_placeholder_name_format_conversion_braces_and_multiplicity(isolated_app, translation):
    update_json(isolated_app, "en.json", lambda data: data.update({"{count} 個專案": translation}))
    assert any("placeholder mismatch" in value or "invalid format" in value for value in checks.check(isolated_app))


def test_plural_variant_requires_base_and_count(isolated_app):
    update_json(isolated_app, "en.json", lambda data: data.update({"orphan::one": "One"}))
    assert "invalid plural variant: orphan::one" in checks.check(isolated_app)


def test_untranslated_template_text_and_unregistered_dynamic_message(isolated_app):
    (isolated_app / "templates/new.html").write_text("<p>忘了翻譯</p>", encoding="utf-8")
    (isolated_app / "new_error.py").write_text("raise VaultError(f'新的訊息 {value}')", encoding="utf-8")
    problems = checks.check(isolated_app)
    assert any("untranslated template text" in value for value in problems)
    assert any("unregistered dynamic message" in value for value in problems)


def test_removed_dynamic_path_is_not_silently_whitelisted(isolated_app):
    update_json(isolated_app, "catalog-policy.json", lambda data: data["normalized_errors"][0].update({"source": "gone.py"}))
    assert any("stale dynamic declaration" in value for value in checks.check(isolated_app))


def test_format_reordering_and_escaped_braces_are_supported():
    assert checks.placeholders("{first} {{literal}} {last}") == checks.placeholders("{last} {{literal}} {first}")
