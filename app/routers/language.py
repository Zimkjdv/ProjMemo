"""Language preference HTTP cookie and safe local redirect."""

from urllib.parse import unquote, urlsplit
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from ..i18n import LANGUAGE_COOKIE, LANGUAGES

router = APIRouter()


@router.post("/settings/language")
def change_language(
    request: Request,
    language: str = Form(...),
    return_to: str = Form("/"),
) -> RedirectResponse:
    if language not in LANGUAGES:
        raise HTTPException(status_code=400, detail="不支援的介面語言")
    try:
        destination = urlsplit(return_to)
    except ValueError:
        return_to = "/"
        destination = urlsplit(return_to)
    decoded_path = unquote(destination.path)
    if (
        not return_to.startswith("/")
        or destination.scheme
        or destination.netloc
        or unquote(return_to).startswith("//")
        or decoded_path.startswith("//")
        or "\\" in decoded_path
        or any(ord(character) < 32 for character in unquote(return_to))
    ):
        return_to = "/"
    response = RedirectResponse(return_to, status_code=303)
    response.set_cookie(
        LANGUAGE_COOKIE, language, max_age=365 * 24 * 60 * 60,
        httponly=True, secure=request.url.scheme == "https", samesite="strict", path="/",
    )
    return response
