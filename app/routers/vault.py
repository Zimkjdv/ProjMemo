"""Vault HTML/JSON responses and secure cookies; policy belongs to services."""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from ..errors import ApplicationError
from ..presentation import page_context, templates
from ..runtime import VAULT_COOKIE_NAME, get_runtime
from ..services import vault
from ..web_security import NO_STORE_HEADERS


router = APIRouter()


def vault_page(request: Request, *, error: str = "", status_code: int = 200) -> HTMLResponse:
    configured, allow_export = vault.settings()
    status = vault.vault_status_context(
        get_runtime(request),
        request.cookies.get(VAULT_COOKIE_NAME),
        configured,
        allow_export,
    )
    response = templates.TemplateResponse(request, "vault.html", page_context(
        request, vault_configured=configured, vault_unlocked=status["unlocked"],
        vault_session_status=status, allow_secret_export=allow_export, error=error,
    ), status_code=status_code)
    response.headers.update(
        {"Cache-Control": "no-store", "Pragma": "no-cache", "Referrer-Policy": "same-origin"},
    )
    return response


def vault_session_response(request: Request, key: bytes) -> RedirectResponse:
    token = vault.issue_session(get_runtime(request), key, request.cookies.get(VAULT_COOKIE_NAME))
    response = RedirectResponse(url="/settings/vault", status_code=303)
    response.set_cookie(VAULT_COOKIE_NAME, token, max_age=15 * 60, httponly=True,
                        secure=request.url.scheme == "https", samesite="strict", path="/")
    response.headers.update({"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    return response


@router.get("/settings/vault/status")
def credential_vault_status(request: Request) -> JSONResponse:
    configured, allow_export = vault.settings()
    return JSONResponse(
        vault.vault_status_context(get_runtime(request), request.cookies.get(VAULT_COOKIE_NAME), configured, allow_export),
        headers=NO_STORE_HEADERS,
    )


@router.get("/settings/vault", response_class=HTMLResponse)
def credential_vault_settings(request: Request, error: str = "") -> HTMLResponse:
    return vault_page(request, error=error)


@router.post("/settings/vault/setup")
def setup_credential_vault(
    request: Request,
    master_password: str = Form(...),
    confirm_password: str = Form(...),
) -> Response:
    try:
        key = vault.setup(get_runtime(request), master_password, confirm_password)
    except ApplicationError as error:
        return vault_page(request, error=error.detail, status_code=error.status_code)
    return vault_session_response(request, key)


@router.post("/settings/vault/unlock")
def unlock_credential_vault(request: Request, master_password: str = Form(...)) -> Response:
    try:
        key = vault.unlock(get_runtime(request), master_password)
    except ApplicationError as error:
        return vault_page(request, error=error.detail, status_code=error.status_code)
    return vault_session_response(request, key)


@router.post("/settings/vault/lock")
def lock_credential_vault(request: Request) -> RedirectResponse:
    vault.lock(get_runtime(request), request.cookies.get(VAULT_COOKIE_NAME))
    response = RedirectResponse(url="/settings/vault", status_code=303)
    response.delete_cookie(VAULT_COOKIE_NAME, path="/", samesite="strict")
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/settings/vault/export-policy")
def update_vault_export_policy(
    request: Request,
    allow_secret_export: bool = Form(False),
) -> Response:
    try:
        vault.update_export_policy(
            get_runtime(request),
            request.cookies.get(VAULT_COOKIE_NAME),
            allow_secret_export,
        )
    except ApplicationError as error:
        return vault_page(request, error=error.detail, status_code=error.status_code)
    return RedirectResponse(url="/settings/vault", status_code=303)
