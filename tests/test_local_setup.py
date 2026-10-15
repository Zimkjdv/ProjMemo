"""Windows entry points: test failures without installing into the user's venv."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows batch entry points")


def batch(path, *, cwd, env, args="", timeout=30):
    return subprocess.run(f'cmd.exe /d /s /c ""{path}" {args}"', cwd=cwd, env=env,
                          capture_output=True, text=True, errors="replace", timeout=timeout)


def test_daily_check_from_other_directory_is_offline_and_does_not_open_database(tmp_path):
    env = {**os.environ, "PIP_NO_INDEX": "1", "PROJMEMO_DB_PATH": str(tmp_path / "must-not-exist.db")}
    result = batch(ROOT / "run-local.bat", cwd=tmp_path, env=env, args="--check")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Local environment is ready" in result.stdout
    assert not Path(env["PROJMEMO_DB_PATH"]).exists()
    script = (ROOT / "run-local.bat").read_text()
    assert "pip install" not in script and "activate.bat" not in script


def test_missing_environment_has_clear_error_and_never_installs(tmp_path):
    workspace = tmp_path / "workspace with spaces"
    workspace.mkdir()
    path = workspace / "run-local.bat"
    shutil.copyfile(ROOT / path.name, path)
    result = batch(path, cwd=tmp_path, env=os.environ)
    assert result.returncode == 1 and "Run setup-local.bat first" in result.stdout
    assert not (workspace / ".venv").exists()


def test_setup_stops_when_virtual_environment_creation_fails(tmp_path):
    workspace = tmp_path / "setup with spaces"
    workspace.mkdir()
    shutil.copyfile(ROOT / "setup-local.bat", workspace / "setup-local.bat")
    (workspace / "py.bat").write_text("@exit /b 37\n")
    result = batch(workspace / "setup-local.bat", cwd=tmp_path, env=os.environ)
    assert result.returncode == 1 and "Could not create .venv" in result.stdout
    assert "Setup complete" not in result.stdout


def test_setup_stops_on_offline_pip_failure_without_starting_application(tmp_path):
    workspace = tmp_path / "offline setup"
    workspace.mkdir()
    shutil.copyfile(ROOT / "setup-local.bat", workspace / "setup-local.bat")
    (workspace / "requirements.txt").write_text("projmemo-deliberately-missing-fixture==0.0.0\n")
    venv.EnvBuilder(with_pip=True).create(workspace / ".venv")
    env = {**os.environ, "PIP_NO_INDEX": "1", "PIP_CONFIG_FILE": os.devnull,
           "PROJMEMO_DB_PATH": str(workspace / "must-not-exist.db")}
    result = batch(workspace / "setup-local.bat", cwd=tmp_path, env=env, timeout=60)
    assert result.returncode == 3 and "Dependency installation or verification failed" in result.stdout
    assert "Setup complete" not in result.stdout
    assert not Path(env["PROJMEMO_DB_PATH"]).exists()


def test_setup_stops_if_virtual_environment_has_no_pip(tmp_path):
    workspace = tmp_path / "no pip"
    workspace.mkdir()
    shutil.copyfile(ROOT / "setup-local.bat", workspace / "setup-local.bat")
    venv.EnvBuilder(with_pip=False).create(workspace / ".venv")
    result = batch(workspace / "setup-local.bat", cwd=tmp_path, env=os.environ)
    assert result.returncode == 2 and "pip is unavailable" in result.stdout
    assert "Setup complete" not in result.stdout
