"""Read-only note authoring tools: no mutations, vault access or draft persistence."""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

from ..i18n import get_language
from ..markdown_editor import editor_templates, validate_preview
from ..presentation import PREVIEW_CSP, page_context, preview_document, templates
from ..web_security import NO_STORE_HEADERS


router = APIRouter()


@router.get("/editor")
def markdown_workspace(request: Request, template: str = ""):
    choices = editor_templates(get_language(request))
    content = next((item["content"] for item in choices if item["id"] == template), "")
    return templates.TemplateResponse(request=request, name="markdown_workspace.html",
        context=page_context(request, content=content))


@router.post("/editor/preview")
def markdown_preview(request: Request, content_markdown: str = Form("")):
    document = preview_document(validate_preview(content_markdown), get_language(request))
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"document": document}, headers=NO_STORE_HEADERS)
    return HTMLResponse(document, headers={"Content-Security-Policy": PREVIEW_CSP})
