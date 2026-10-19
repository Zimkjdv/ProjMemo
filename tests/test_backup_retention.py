"""Explicit retention tests never operate on the user's backups."""

import json
import os
from pathlib import Path
import time

import pytest

from app import backup_retention as retention
from app.backup import create_database_backup, recovery_directory
from app.errors import ApplicationError
from app.main import create_app
from app.services import backups
from tests.client import TestClient
from tests.test_backup_r11 import sources, token_from


def recovery_files(database, count=5):
    directory = recovery_directory(database)
    directory.mkdir(exist_ok=True)
    paths = []
    for index in range(count):
        kind = "restore" if index % 2 else "delete"
        path = directory / f"projmemo-pre-{kind}-20261019-010000-{index:06}.sqlite3"
        create_database_backup(database, path)
        stamp = time.time() - (count - index) * 86400
        os.utime(path, (stamp, stamp))
        paths.append(path)
    return paths


def test_default_and_saving_policy_never_delete_files(sources):
    current, _ = sources
    assert retention.read_policy(current) == retention.DEFAULT_POLICY
    assert not recovery_directory(current).exists()
    paths = recovery_files(current)
    with TestClient(create_app(), follow_redirects=False) as client:
        response = client.post("/settings/backup/retention", data={"mode": "custom", "keep_count": "2", "min_age_days": "0"})
        assert response.status_code == 303
        assert all(path.exists() for path in paths)
        assert retention.read_policy(current) == {"version": 1, "mode": "custom", "keep_count": 2, "min_age_days": 0}
        assert len(retention.cleanup_candidates(current, retention.read_policy(current))) == 3
    assert retention.read_policy(current)["keep_count"] == 2  # Survives app shutdown.


@pytest.mark.parametrize("count,days,expected", [(1, 0, 4), (2, 0, 3), (1, 4, 2), (5, 0, 0), (500, 0, 0)])
def test_newest_count_and_age_protections_are_combined(sources, count, days, expected):
    current, _ = sources
    recovery_files(current)
    assert len(retention.cleanup_candidates(current, retention.normalized_policy("custom", count, days))) == expected


@pytest.mark.parametrize("mode,count,days", [("custom", 0, 0), ("custom", 501, 1), ("custom", 2, -1),
    ("custom", 2, 3651), ("custom", "abc", 0), ("custom", "２", 0), ("custom", "1.0", 0), ("bad", 2, 0)])
def test_invalid_policy_is_rejected_without_changing_files(sources, mode, count, days):
    current, _ = sources
    with pytest.raises(ApplicationError):
        retention.normalized_policy(mode, count, days)
    assert not recovery_directory(current).exists()


def test_preview_cancel_and_confirm_delete_only_listed_files(sources):
    current, _ = sources
    paths = recovery_files(current)
    directory = recovery_directory(current)
    unknown = directory / "manual-backup.sqlite3"
    unknown.write_text("keep", encoding="utf-8")
    migration = directory / "migrations"
    migration.mkdir()
    (migration / "keep.sqlite3").write_text("keep", encoding="utf-8")
    with TestClient(create_app(), follow_redirects=False) as client:
        client.post("/settings/backup/retention", data={"mode": "custom", "keep_count": "2", "min_age_days": "0"})
        response = client.post("/settings/backup/cleanup/preview")
        token = token_from(response, "/settings/backup/cleanup/confirm")
        assert all(path.exists() for path in paths)
        assert unknown.name not in response.text.split('id="cleanup-preview"')[1]
        assert client.post("/settings/backup/preview/cancel", data={"preview_token": token, "kind": "cleanup"}).status_code == 303
        assert all(path.exists() for path in paths)
        token = token_from(client.post("/settings/backup/cleanup/preview"), "/settings/backup/cleanup/confirm")
        data = {"preview_token": token, "confirmation": "DELETE", "acknowledged": "yes"}
        assert client.post("/settings/backup/cleanup/confirm", data={**data, "confirmation": "wrong"}).status_code == 400
        response = client.post("/settings/backup/cleanup/confirm", data=data)
        assert response.status_code == 200 and "已清理 3 份" in response.text
        assert all(not path.exists() for path in paths[:3])
        assert all(path.exists() for path in paths[3:]) and unknown.exists() and (migration / "keep.sqlite3").exists()
        assert client.post("/settings/backup/cleanup/confirm", data=data).status_code == 409


@pytest.mark.parametrize("change", ["new-file", "policy", "replace-file"])
def test_cleanup_rejects_changed_plan_before_any_delete(sources, change):
    current, _ = sources
    paths = recovery_files(current)
    application = create_app()
    with TestClient(application, follow_redirects=False) as client:
        client.post("/settings/backup/retention", data={"mode": "custom", "keep_count": "2", "min_age_days": "0"})
        token = token_from(client.post("/settings/backup/cleanup/preview"), "/settings/backup/cleanup/confirm")
        if change == "new-file":
            (recovery_directory(current) / "projmemo-pre-restore-20261019-020000-123456.sqlite3").write_text("new", encoding="utf-8")
        elif change == "policy":
            client.post("/settings/backup/retention", data={"mode": "all"})
        else:
            paths[0].write_bytes(b"changed fixture")
        response = client.post("/settings/backup/cleanup/confirm", data={"preview_token": token, "confirmation": "DELETE", "acknowledged": "yes"})
        assert response.status_code == 409
        assert all(path.exists() for path in paths)


def test_all_mode_preview_has_no_delete_form(sources):
    current, _ = sources
    paths = recovery_files(current)
    with TestClient(create_app(), follow_redirects=False) as client:
        response = client.post("/settings/backup/cleanup/preview")
        assert response.status_code == 200
        assert 'action="/settings/backup/cleanup/confirm"' not in response.text
        assert "目前沒有符合條件" in response.text
        assert all(path.exists() for path in paths)


def test_cleanup_is_bounded_and_always_keeps_newest_copy(sources):
    current, _ = sources
    recovery_files(current, count=120)
    candidates = retention.cleanup_candidates(current, retention.normalized_policy("custom", 1, 0))
    assert len(candidates) == 100
    newest = retention.recovery_files(current)[0]
    assert newest not in candidates


@pytest.mark.parametrize("bad", [b"{", b"{}", b"[]", b"x" * 4097,
    b'{"version":1,"mode":"custom","keep_count":true,"min_age_days":0}'])
def test_corrupt_policy_disables_cleanup_but_not_recovery_page(sources, bad):
    current, _ = sources
    paths = recovery_files(current)
    (recovery_directory(current) / "retention-policy.json").write_bytes(bad)
    with TestClient(create_app(), follow_redirects=False) as client:
        assert client.get("/settings/backup").status_code == 200
        assert client.get(f"/settings/backup/files/{paths[0].name}").status_code == 200
        assert client.post("/settings/backup/cleanup/preview").status_code == 503
        assert all(path.exists() for path in paths)


def test_partial_delete_failure_is_reported_without_claiming_all_removed(sources, monkeypatch):
    current, _ = sources
    paths = recovery_files(current)
    policy = retention.normalized_policy("custom", 1, 0)
    candidates = retention.cleanup_candidates(current, policy)
    unlink = Path.unlink
    blocked = candidates[1]["filename"]
    def fail_one(path, *args, **kwargs):
        if path.name == blocked:
            raise PermissionError("R11 simulated download lock")
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", fail_one)
    assert retention.delete_candidates(current, candidates) == {"deleted": 1, "remaining": 3}
    assert sum(path.exists() for path in paths) == 4


def test_policy_replace_failure_keeps_old_settings_and_removes_temp(sources, monkeypatch):
    current, _ = sources
    retention.save_policy(current, retention.DEFAULT_POLICY)
    def fail_replace(*args):
        raise OSError("R11 simulated full disk")
    monkeypatch.setattr(retention.os, "replace", fail_replace)
    with pytest.raises(OSError):
        retention.save_policy(current, retention.normalized_policy("custom", 1, 0))
    assert retention.read_policy(current) == retention.DEFAULT_POLICY
    assert not list(recovery_directory(current).glob(".retention-*"))


def test_corrupt_newest_copy_cannot_cause_last_valid_recovery_point_to_be_deleted(sources):
    current, _ = sources
    paths = recovery_files(current)
    paths[-1].write_bytes(b"R11 deliberately incomplete snapshot")
    with TestClient(create_app(), follow_redirects=False) as client:
        client.post("/settings/backup/retention", data={"mode": "custom", "keep_count": "1", "min_age_days": "0"})
        assert client.post("/settings/backup/cleanup/preview").status_code == 409
        assert all(path.exists() for path in paths)


@pytest.mark.parametrize("link_kind", ["symbolic", "junction"])
def test_linked_recovery_directory_is_rejected_without_accessing_target(sources, monkeypatch, link_kind):
    current, _ = sources
    directory = recovery_directory(current)
    method = "is_symlink" if link_kind == "symbolic" else "is_junction"
    original = getattr(Path, method)
    monkeypatch.setattr(Path, method, lambda path: path == directory or original(path))
    with pytest.raises(ApplicationError):
        retention.safe_directory(current, create=True)
    assert not directory.exists()


def test_policy_survives_database_restore(sources):
    current, incoming = sources
    from tests.test_backup_r11 import preview, restore
    with TestClient(create_app(), follow_redirects=False) as client:
        client.post("/settings/backup/retention", data={"mode": "custom", "keep_count": "3", "min_age_days": "7"})
        token = token_from(preview(client, incoming))
        assert restore(client, token).status_code == 303
        assert retention.read_policy(current)["keep_count"] == 3
        assert retention.read_policy(current)["min_age_days"] == 7
