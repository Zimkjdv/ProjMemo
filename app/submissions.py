"""Bounded single-worker form replay protection; never stores submitted values."""

import hashlib
import hmac
import secrets
import threading
import time
from urllib.parse import urlencode

from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from fastapi.responses import RedirectResponse

from .database_access import DatabaseBusyError
from .errors import ApplicationError
from .web_security import require_csrf

TTL = 24 * 60 * 60
SECTIONS = {"urls": "important-links", "notes": "project-notes", "checklist": "handover",
            "environment-variables": "environment", "accounts": "access-accounts"}


class SubmissionRegistry:
    def __init__(self, *, clock=time.time, capacity=10000):
        self.clock, self.capacity = clock, capacity
        self.key = secrets.token_bytes(32)
        self.entries = {}
        self.lock = threading.Lock()

    def _sign(self, payload, browser):
        return hmac.new(self.key, (payload + ":" + browser).encode(), hashlib.sha256).hexdigest()

    def issue(self, browser):
        payload = f"{int(self.clock())}.{secrets.token_urlsafe(24)}"
        return payload + "." + self._sign(payload, browser)

    def claim(self, token, browser, path):
        try:
            stamp, nonce, signature = token.split(".")
            issued = int(stamp)
            if len(token) > 160 or not nonce or not 0 <= self.clock() - issued < TTL or not hmac.compare_digest(signature, self._sign(stamp + "." + nonce, browser)):
                raise ValueError
        except (ValueError, AttributeError):
            raise ApplicationError(409, "送出識別已失效，請先確認資料是否已保存，再重新整理。") from None
        with self.lock:
            self.entries = {key: entry for key, entry in self.entries.items() if entry[0] > self.clock()}
            previous = self.entries.get(token)
            if previous:
                if previous[1] != path or previous[2] != "done":
                    raise ApplicationError(409, "此操作處理中或結果待確認，請勿重複新增，稍後重試。")
                return previous[3]
            if len(self.entries) >= self.capacity:
                raise ApplicationError(503, "操作紀錄已滿，請稍後再試；本次未寫入。")
            self.entries[token] = (issued + TTL, path, "pending", "")
        return None

    def finish(self, token, location):
        with self.lock:
            expiration, path, _, _ = self.entries[token]
            self.entries[token] = (expiration, path, "done", location)

    def release(self, token):
        with self.lock:
            self.entries.pop(token, None)


class MutationRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request):
            if request.method != "POST" or request.url.path.endswith("/reveal"):
                return await original(request)
            await require_csrf(request)
            form = await request.form()
            native = "text/html" in request.headers.get("accept", "")
            token = form.get("_submission_token")
            if not native and token is None:
                return await original(request)  # Existing script clients opt in with a token.
            registry = request.app.state.runtime.submissions
            browser = request.state.csrf_token
            location = registry.claim(token, browser, request.url.path)
            if location is not None:
                return RedirectResponse(location, 303, headers={"Cache-Control": "no-store"})
            try:
                response = await original(request)
            except (ApplicationError, RequestValidationError, DatabaseBusyError):
                registry.release(token)  # Services guarantee validation/DB errors roll back.
                raise
            # Unknown exceptions/cancellations remain pending: do not blindly replay a possibly committed write.
            if response.status_code == 303:
                parts = request.url.path.strip("/").split("/")
                section = SECTIONS.get(parts[0]) or (SECTIONS.get(parts[2]) if len(parts) > 2 else "")
                params = {"notice": "saved"}
                view = form.get("_detail_view")
                if view in {"cards", "list"}:
                    params["detail_view"] = view
                location = response.headers["location"] + "?" + urlencode(params) + ("#" + section if section else "")
                response.headers["location"] = location
                response.headers["Cache-Control"] = "no-store"
                registry.finish(token, location)
            return response
        return handle
