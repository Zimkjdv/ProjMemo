"""Existing workflow tests use real CSRF cookies, without a production bypass."""

from fastapi.testclient import TestClient as RawTestClient

from app.web_security import CSRF_COOKIE, SAFE_METHODS


class TestClient(RawTestClient):
    __test__ = False
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("base_url", "http://127.0.0.1")
        super().__init__(*args, **kwargs)

    def __enter__(self):
        super().__enter__()
        self.get("/")
        return self

    def request(self, method, url, **kwargs):
        if method.upper() not in SAFE_METHODS:
            headers = dict(kwargs.get("headers") or {})
            headers.setdefault("X-CSRF-Token", self.cookies.get(CSRF_COOKIE, ""))
            kwargs["headers"] = headers
        return super().request(method, url, **kwargs)
