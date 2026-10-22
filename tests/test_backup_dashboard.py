from datetime import datetime, timezone
import json
import os
import sqlite3

import pytest

from app import backup_activity
from app.backup import create_database_backup, recovery_directory
from app.backup_inspection import database_fingerprint, inspect_backup
from app.main import create_app
from app.services import backups
from tests.client import TestClient
from tests.test_backup_r11 import sources, token_from


def test_download_record_is_real_persistent_and_preview_does_not_create_it(sources):
    current, incoming = sources
    before = database_fingerprint(current)
    with TestClient(create_app(), follow_redirects=False) as client:
        assert backup_activity.read_download_activity(current) == {"state": "missing"}
        assert not recovery_directory(current).exists()
        page = client.post('/settings/backup/preview', files={'backup_file': ('fixture.sqlite3', incoming.read_bytes())})
        token_from(page)
        assert backup_activity.read_download_activity(current) == {"state": "missing"}
        assert not recovery_directory(current).exists()
        started = datetime.now(timezone.utc)
        downloaded = client.get('/settings/backup/download')
        assert downloaded.status_code == 200 and downloaded.content.startswith(b'SQLite format 3\0')
        record = backup_activity.read_download_activity(current)
        assert record['state'] == 'recorded'
        assert started <= datetime.fromisoformat(record['iso']) <= datetime.now(timezone.utc)
        assert backups.backup_page_data()['recovery_count'] == 0
        assert database_fingerprint(current) == before
    with TestClient(create_app()) as client:
        assert record['iso'] in client.get('/settings/backup').text


@pytest.mark.parametrize('content', ['{}', 'broken', '{"version":1,"generated_at":"not-a-date"}',
    '{"version":true,"generated_at":"2026-10-22T10:00:00+00:00"}',
    '{"version":1,"generated_at":"2026-10-22T10:00:00"}', 'x' * 1025])
def test_invalid_activity_is_not_presented_as_a_real_backup(sources, content):
    current, _ = sources
    directory = recovery_directory(current); directory.mkdir()
    (directory / 'download-activity.json').write_text(content, encoding='utf-8')
    assert backup_activity.read_download_activity(current) == {'state': 'unavailable'}
    with TestClient(create_app()) as client:
        assert client.get('/settings/backup').status_code == 200


def test_metadata_write_failure_does_not_break_download_or_touch_database(sources, monkeypatch, caplog):
    current, _ = sources
    def fail(*args, **kwargs):
        raise OSError('synthetic failure')
    monkeypatch.setattr(backup_activity.os, 'replace', fail)
    before = current.read_bytes()
    with TestClient(create_app()) as client:
        assert client.get('/settings/backup/download').status_code == 200
    assert current.read_bytes() == before
    assert backup_activity.read_download_activity(current) == {'state': 'missing'}
    assert not list(recovery_directory(current).glob('.download-activity-*'))
    assert 'backup_activity_record_unavailable' in caplog.text


def test_failed_snapshot_does_not_create_a_false_download_record(sources, monkeypatch):
    current, _ = sources
    def fail():
        raise OSError('synthetic snapshot failure')
    monkeypatch.setattr(backups, 'database_snapshot', fail)
    with pytest.raises(OSError):
        backups.download_snapshot()
    assert backup_activity.read_download_activity(current) == {'state': 'missing'}
    assert not recovery_directory(current).exists()


def test_activity_rejects_hard_links_without_modifying_the_target(sources):
    current, _ = sources
    target = current.parent / 'outside.json'
    target.write_text(json.dumps({'version': 1, 'generated_at': '2026-10-22T00:00:00+00:00'}), encoding='utf-8')
    directory = recovery_directory(current); directory.mkdir()
    os.link(target, directory / 'download-activity.json')
    before = target.read_bytes()
    assert backup_activity.read_download_activity(current) == {'state': 'unavailable'}
    backup_activity.record_download_generation(current)
    assert target.read_bytes() == before


def test_activity_survives_database_restore_and_does_not_add_recovery_points(sources):
    current, incoming = sources
    with TestClient(create_app(), follow_redirects=False) as client:
        assert client.get('/settings/backup/download').status_code == 200
        record = backup_activity.read_download_activity(current)
        assert client.post('/settings/backup/restore', files={'backup_file': ('fixture.sqlite3', incoming.read_bytes())}).status_code == 303
        assert backup_activity.read_download_activity(current) == record


def test_hard_linked_recovery_is_neither_listed_nor_previewed(sources):
    current, incoming = sources
    directory = recovery_directory(current); directory.mkdir()
    name = 'projmemo-pre-restore-20261022-010000-000001.sqlite3'
    os.link(incoming, directory / name)
    with TestClient(create_app(), follow_redirects=False) as client:
        assert backups.backup_page_data()['recovery_count'] == 0
        assert client.post(f'/settings/backup/files/{name}/preview').status_code == 404


def test_counts_include_all_recovery_points_not_just_the_ten_displayed(sources):
    current, _ = sources
    directory = recovery_directory(current); directory.mkdir()
    for number in range(12):
        create_database_backup(current, directory / f'projmemo-pre-restore-20261022-010000-{number:06d}.sqlite3')
    with TestClient(create_app()):
        page = backups.backup_page_data()
        assert page['recovery_count'] == 12 and len(page['recovery_backups']) == 10


def test_recovery_preview_requires_confirmation_and_keeps_original_snapshot(sources):
    current, incoming = sources
    directory = recovery_directory(current); directory.mkdir()
    snapshot = directory / 'projmemo-pre-restore-20261022-010000-000001.sqlite3'
    create_database_backup(incoming, snapshot)
    original_snapshot = snapshot.read_bytes()
    original_db = database_fingerprint(current)
    app = create_app()
    with TestClient(app, follow_redirects=False) as client:
        response = client.post(f'/settings/backup/files/{snapshot.name}/preview')
        token = token_from(response)
        assert database_fingerprint(current) == original_db and snapshot.read_bytes() == original_snapshot
        assert len(list(directory.glob('*.sqlite3'))) == 1
        assert client.post('/settings/backup/restore/confirm', data={'preview_token': token}).status_code == 400
        assert database_fingerprint(current) == original_db
        assert client.post('/settings/backup/restore/confirm', data={
            'preview_token': token, 'confirmation': 'RESTORE', 'acknowledged': 'yes'}).status_code == 303
        assert snapshot.read_bytes() == original_snapshot
        with sqlite3.connect(current) as connection:
            assert connection.execute('SELECT name FROM projects').fetchone()[0] == 'Incoming fixture'


def test_unlisted_recovery_preview_and_corrupt_snapshot_are_rejected(sources):
    current, _ = sources
    directory = recovery_directory(current); directory.mkdir()
    unknown = directory / 'manual.sqlite3'; create_database_backup(current, unknown)
    invalid = directory / 'projmemo-pre-restore-20261022-010000-000001.sqlite3'; invalid.write_bytes(b'invalid')
    before = database_fingerprint(current)
    with TestClient(create_app(), follow_redirects=False) as client:
        assert client.post('/settings/backup/files/manual.sqlite3/preview').status_code == 404
        assert client.post(f'/settings/backup/files/{invalid.name}/preview').status_code == 400
        assert database_fingerprint(current) == before


def test_latest_update_is_compared_without_mutating_the_backup(sources):
    current, incoming = sources
    with sqlite3.connect(current) as connection:
        connection.execute("UPDATE projects SET updated_at='2026-10-22 09:00:00'")
    with sqlite3.connect(incoming) as connection:
        connection.execute("UPDATE projects SET updated_at='2026-10-01 08:00:00'")
    before = incoming.read_bytes()
    assert inspect_backup(incoming)['latest_project_update'] == '2026-10-01 08:00:00'
    assert incoming.read_bytes() == before
    with TestClient(create_app(), follow_redirects=False) as client:
        response = client.post('/settings/backup/preview', files={'backup_file': ('fixture.sqlite3', before)})
        assert '2026-10-22 09:00:00' in response.text and '2026-10-01 08:00:00' in response.text
