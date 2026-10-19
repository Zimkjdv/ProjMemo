"""Short-lived, browser-bound backup confirmations. No tokens in URLs or logs."""

from contextlib import contextmanager
from dataclasses import dataclass
import logging
from pathlib import Path
import secrets
import threading
import time

from .errors import ApplicationError


@dataclass(frozen=True)
class BackupPlan:
    browser: str
    database: Path
    kind: str
    expires: float
    values: dict
    upload: Path | None = None


class BackupPlans:
    def __init__(self, *, clock=time.monotonic, capacity=4, ttl=600):
        self.clock, self.capacity, self.ttl = clock, capacity, ttl
        self.entries = {}
        self.lock = threading.RLock()
        self.pending_removals = {}

    def _remove_upload(self, plan):
        if plan.upload is not None:
            try:
                plan.upload.unlink(missing_ok=True)
            except OSError:
                with self.lock:
                    if plan.upload not in self.pending_removals:
                        logging.getLogger("projmemo.operations").warning("backup_preview_cleanup_failed")
                    self.pending_removals[plan.upload] = plan
            else:
                with self.lock:
                    self.pending_removals.pop(plan.upload, None)

    def purge_expired(self):
        with self.lock:
            for plan in list(self.pending_removals.values()):
                self._remove_upload(plan)
            for token, plan in list(self.entries.items()):
                if plan.expires <= self.clock():
                    self.entries.pop(token)
                    self._remove_upload(plan)

    def clear(self):
        with self.lock:
            for plan in self.entries.values():
                self._remove_upload(plan)
            self.entries.clear()
            for plan in list(self.pending_removals.values()):
                self._remove_upload(plan)

    def issue(self, browser, database, kind, values, *, upload=None):
        with self.lock:
            self.purge_expired()
            if len(self.entries) + len(self.pending_removals) >= self.capacity:
                raise ApplicationError(503, "備份預覽已滿，請先取消其他預覽，或等待 10 分鐘後重試。")
            token = secrets.token_urlsafe(32)
            self.entries[token] = BackupPlan(browser, database.resolve(), kind,
                                             self.clock() + self.ttl, values, upload)
            return token

    def get(self, token, browser, database, kind):
        with self.lock:
            self.purge_expired()
            plan = self.entries.get(token) if isinstance(token, str) and len(token) <= 100 else None
            if (plan is None or plan.browser != browser or plan.database != database.resolve()
                    or plan.kind != kind):
                raise ApplicationError(409, "預覽已失效或不屬於此瀏覽器，請重新預覽。")
            return plan

    @contextmanager
    def consume(self, token, browser, database, kind):
        # Removal is atomic: concurrent confirmations cannot repeat a restore/delete.
        with self.lock:
            plan = self.get(token, browser, database, kind)
            self.entries.pop(token)
        try:
            yield plan
        finally:
            self._remove_upload(plan)
