"""Local origin checks and signed, browser-bound double-submit CSRF tokens."""

import hashlib
import hmac
import re
import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from jinja2 import pass_context
from markupsafe import Markup, escape
from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse, Response

from .i18n import get_language, translate_error


CSRF_COOKIE = "projmemo_csrf"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
_SIGNING_KEY = secrets.token_bytes(32)
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}\.[0-9a-f]{64}")
NO_STORE_HEADERS = {
    "Cache-Control": "no-store, private",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def _signature(nonce: str) -> str:
    return hmac.new(_SIGNING_KEY, nonce.encode("ascii"), hashlib.sha256).hexdigest()


def new_csrf_token() -> str:
    nonce = secrets.token_urlsafe(32)
    return f"{nonce}.{_signature(nonce)}"


def valid_csrf_token(value: object) -> bool:
    if not isinstance(value, str) or not _TOKEN_PATTERN.fullmatch(value):
        return False
    nonce, signature = value.split(".")
    return hmac.compare_digest(signature, _signature(nonce))


@pass_context
def csrf_input(context) -> Markup:
    return Markup('<input type="hidden" name="csrf_token" value="{}">').format(
        escape(context["csrf_token"]),
    )


async def require_csrf(request: Request) -> None:
    if request.method in SAFE_METHODS:
        return
    cookie = request.cookies.get(CSRF_COOKIE)
    if not valid_csrf_token(cookie):
        raise HTTPException(403, "頁面驗證已失效，請重新整理後再試。")
    submitted = request.headers.get("X-CSRF-Token")
    if submitted is None:
        # FastAPI reuses its parsed FormData, including multipart uploads.
        form = await request.form()
        values = form.getlist("csrf_token")
        submitted = values[0] if len(values) == 1 else None
    if not valid_csrf_token(submitted) or not hmac.compare_digest(cookie, submitted):
        raise HTTPException(403, "頁面驗證已失效，請重新整理後再試。")


def _origin(url: str) -> tuple[str, str, int] | None:
    try:
        if any(ord(char) <= 32 for char in url) or "\\" in url:
            return None
        parsed = urlsplit(url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None):
            return None
        port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
        if not 1 <= port <= 65535:
            return None
        return parsed.scheme, parsed.hostname.lower(), port
    except ValueError:
        return None


class LocalRequestSecurityMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        headers = Headers(scope=scope)
        hosts = headers.getlist("host")
        host = hosts[0] if len(hosts) == 1 else ""
        expected = _origin(f"{scope['scheme']}://{host}")
        # Reject credentials, paths, untrusted names and malformed authorities.
        if (not re.fullmatch(r"(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?", host, re.I)
                or expected is None or expected[1] not in LOCAL_HOSTS):
            await self._reject(request, 400, "僅允許透過本機網址存取 ProjMemo。", receive, send)
            return

        if request.method not in SAFE_METHODS:
            origins = headers.getlist("origin")
            referers = headers.getlist("referer")
            source = origins[0] if len(origins) == 1 else referers[0] if len(referers) == 1 else None
            try:
                source_url = urlsplit(origins[0]) if origins else None
                origin_has_path = bool(source_url and (source_url.path or source_url.query or source_url.fragment))
            except ValueError:
                origin_has_path = True
            if (len(origins) > 1 or len(referers) > 1
                    or origin_has_path
                    or source is not None and _origin(source) != expected
                    or headers.get("sec-fetch-site") not in {None, "same-origin", "none"}):
                await self._reject(request, 403, "請從同一個 ProjMemo 頁面執行此操作。", receive, send)
                return

        cookie = request.cookies.get(CSRF_COOKIE)
        if request.method not in SAFE_METHODS:
            # Reject requests without a valid browser token before parsing
            # file bodies. Native forms are checked again by require_csrf.
            submitted_header = headers.get("x-csrf-token")
            if (not valid_csrf_token(cookie)
                    or submitted_header is not None and (
                        not valid_csrf_token(submitted_header)
                        or not hmac.compare_digest(cookie, submitted_header))):
                await self._reject(request, 403, "頁面驗證已失效，請重新整理後再試。", receive, send)
                return
        token = cookie if valid_csrf_token(cookie) else new_csrf_token()
        scope.setdefault("state", {})["csrf_token"] = token

        async def protected_send(message):
            if message["type"] == "http.response.start":
                response_headers = MutableHeaders(scope=message)
                response_headers["X-Content-Type-Options"] = "nosniff"
                response_headers["Referrer-Policy"] = "no-referrer"
                response_headers["X-Frame-Options"] = "DENY"
                if response_headers.get("content-type", "").startswith("text/html"):
                    response_headers["Cache-Control"] = "no-store, private"
                    if token != cookie:
                        response = Response()
                        response.set_cookie(CSRF_COOKIE, token, httponly=True, samesite="strict",
                                            secure=scope["scheme"] == "https", path="/")
                        response_headers.append("set-cookie", response.headers["set-cookie"])
            await send(message)

        await self.app(scope, receive, protected_send)

    async def _reject(self, request, status, message, receive, send):
        response = JSONResponse(
            {"detail": translate_error(message, get_language(request))},
            status_code=status, headers=NO_STORE_HEADERS,
        )
        await response(request.scope, receive, send)
