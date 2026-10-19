"""Export download responses; data loading, policy and rendering use services."""

from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import Response

from ..runtime import VAULT_COOKIE_NAME, get_runtime
from ..export_options import ExportOptions, SECTION_LABELS
from ..errors import ApplicationError
from ..presentation import page_context, templates
from ..services import exports
from ..services.projects import load_project


router = APIRouter()


def export_response(project_id: int, artifact: exports.ExportArtifact) -> Response:
    suffix = "-sensitive" if artifact.sensitive else ""
    headers = {
        "Content-Disposition": (
            f'attachment; filename="projmemo-{project_id}{suffix}.{artifact.extension}"; '
            f"filename*=UTF-8''{quote(artifact.filename)}"
        ),
        "Cache-Control": "no-store, private", "Pragma": "no-cache",
    }
    if artifact.sensitive:
        headers["Referrer-Policy"] = "no-referrer"
    return Response(content=artifact.content, media_type=artifact.media_type, headers=headers)


@router.get("/projects/{project_id}/export.pdf")
def export_pdf(project_id: int) -> Response:
    return export_response(project_id, exports.export_project(project_id, "pdf"))


@router.get("/projects/{project_id}/export.md")
def export_markdown(project_id: int) -> Response:
    return export_response(project_id, exports.export_project(project_id, "markdown"))


@router.post("/projects/{project_id}/export-with-secrets")
def export_project_with_secrets(request: Request, project_id: int, export_format: str = Form(...),
                                confirm_sensitive_export: bool = Form(False)) -> Response:
    artifact = exports.export_sensitive_project(get_runtime(request), request.cookies.get(VAULT_COOKIE_NAME),
                                                project_id, export_format, confirm_sensitive_export)
    return export_response(project_id, artifact)


@router.get("/projects/{project_id}/export")
def export_options(request: Request, project_id: int):
    return templates.TemplateResponse(request=request, name="export_options.html",
        context=page_context(request, project=load_project(project_id), export_sections=SECTION_LABELS))


@router.post("/projects/{project_id}/export")
def configured_export(request: Request, project_id: int, export_format: str = Form(...),
                      document_language: str = Form(...), sections: list[str] = Form([]),
                      include_secrets: bool = Form(False), confirm_sensitive_export: bool = Form(False)):
    try:
        options = ExportOptions(document_language, tuple(sections))
        if include_secrets:
            artifact = exports.export_sensitive_project(get_runtime(request), request.cookies.get(VAULT_COOKIE_NAME),
                project_id, export_format, confirm_sensitive_export, options=options)
        else:
            artifact = exports.export_project(project_id, export_format, options=options)
    except ApplicationError as error:
        if "text/html" not in request.headers.get("accept", ""):
            raise
        # Read-only download errors retain only choices, never credentials or a
        # sensitive-export acknowledgment. A retry always requires confirmation.
        return templates.TemplateResponse(request=request, name="export_options.html", status_code=error.status_code,
            context=page_context(request, project=load_project(project_id), export_sections=SECTION_LABELS,
                selected_sections=sections, document_language=document_language,
                export_format=export_format, error=error.detail))
    return export_response(project_id, artifact)
