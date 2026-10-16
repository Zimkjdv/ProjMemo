"""The supported Windows/Python lock is complete and test tooling stays opt-in."""

import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

from app import launcher
from scripts import hash_lock

ROOT = Path(__file__).resolve().parents[1]


def pins(name):
    text = (ROOT / name).read_text(encoding="utf-8")
    entries = {}
    for line in text.splitlines():
        if line and not line[0].isspace() and not line.startswith("#"):
            match = re.fullmatch(r"([a-zA-Z0-9_-]+)==([^\s]+) \\", line)
            assert match, line
            entries[match[1].lower().replace("_", "-")] = match[2]
    assert entries
    assert len(re.findall(r"--hash=sha256:[0-9a-f]{64}", text)) >= len(entries)
    return entries


def test_runtime_and_test_locks_are_complete_and_share_identical_runtime_versions():
    runtime = pins("requirements.txt")
    tests = pins("requirements/requirements-test.txt")
    assert "pytest" not in runtime and "httpx" not in runtime
    assert all(tests[name] == version for name, version in runtime.items())
    assert "pytest" in tests and "httpx" in tests
    assert "pip-audit" not in runtime and "pip-tools" not in runtime


def test_only_runtime_install_entry_remains_at_root_and_inputs_resolve_relative_paths():
    names = {"requirements.in", "requirements-test.in", "requirements-test.txt", "requirements-tools.txt"}
    directory = ROOT / "requirements"
    assert {path.name for path in directory.iterdir() if path.is_file()} == names
    assert {path.name for path in ROOT.glob("requirements*") if path.is_file()} == {"requirements.txt"}
    source = directory / "requirements-test.in"
    directives = [line.split(maxsplit=1) for line in source.read_text(encoding="utf-8").splitlines()
                  if line.startswith(("-r ", "-c "))]
    assert directives == [["-r", "requirements.in"], ["-c", "../requirements.txt"]]
    assert (source.parent / directives[0][1]).resolve() == directory / "requirements.in"
    assert (source.parent / directives[1][1]).resolve() == ROOT / "requirements.txt"


@pytest.mark.parametrize("name", ["requirements.in", "requirements-test.in"])
def test_moved_inputs_are_parsed_by_real_pip_from_another_working_directory(tmp_path, name):
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--dry-run", "--no-index", "--no-deps",
         "--no-input", "-r", str(ROOT / "requirements" / name)],
        cwd=tmp_path,
        env={**os.environ, "PIP_CONFIG_FILE": os.devnull, "PIP_DISABLE_PIP_VERSION_CHECK": "1"},
        capture_output=True, text=True, errors="replace", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Would install" not in result.stdout


def test_hash_cli_help_uses_current_lock_destinations():
    result = subprocess.run([sys.executable, str(ROOT / "scripts/hash_lock.py"), "--help"],
                            capture_output=True, text=True, errors="replace", timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
    help_text = " ".join(result.stdout.split())
    assert "requirements.txt (runtime)" in help_text
    assert "requirements/requirements-test.txt (tests)" in help_text


def test_setup_selects_supported_python_and_checks_hashes():
    text = (ROOT / "setup-local.bat").read_text()
    assert "py -3.12 -m venv" in text
    assert "--require-hashes" in text
    assert '-r "%~dp0requirements.txt"' in text
    assert "requirements-test.txt" not in text


def test_launcher_refuses_unsupported_python_before_importing_application(monkeypatch, capsys):
    monkeypatch.setattr(launcher.sys, "version_info", (3, 11))
    monkeypatch.setattr(launcher.importlib, "import_module", lambda _: (_ for _ in ()).throw(AssertionError("must not import")))
    assert launcher.check_dependencies() is False
    assert "Python 3.12 is required" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["", "x>=1", "-r other.txt", "https://example.invalid/wheel.whl", "x==1\nx==2", "x==1; os_name=='nt'"])
def test_hash_generation_rejects_non_flat_or_incomplete_pins(value):
    with pytest.raises(ValueError):
        hash_lock.render(value)


def test_hash_generation_fetches_only_exact_metadata(monkeypatch):
    import io
    import json

    seen = []

    def fake_urlopen(url, *, timeout):
        seen.append(url)
        assert timeout == 30
        name, version = url.split("/")[-3:-1]
        return io.BytesIO(json.dumps({"info": {"name": name, "version": version},
            "urls": [{"packagetype": "bdist_wheel", "digests": {"sha256": "a" * 64}}]}).encode())

    monkeypatch.setattr(hash_lock, "urlopen", fake_urlopen)
    text = hash_lock.render("example==1.0\n")
    assert seen == ["https://pypi.org/pypi/example/1.0/json"]
    assert "example==1.0" in text and "--hash=sha256:" + "a" * 64 in text


@pytest.mark.skipif(sys.platform != "win32", reason="The lock-writing CLI intentionally requires Windows")
def test_failed_metadata_does_not_replace_existing_lock(tmp_path, monkeypatch):
    pins = tmp_path / "pins.txt"
    output = tmp_path / "existing.txt"
    pins.write_text("example==1.0")
    output.write_text("previous valid lock")
    monkeypatch.setattr(hash_lock.sys, "argv", ["hash_lock.py", str(pins), str(output)])
    monkeypatch.setattr(hash_lock, "fetch_hashes", lambda _: (_ for _ in ()).throw(ValueError("bad metadata")))
    with pytest.raises(ValueError):
        hash_lock.main()
    assert output.read_text() == "previous valid lock"
