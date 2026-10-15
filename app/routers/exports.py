"""Export download responses; data loading, policy and rendering use services."""

from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import Response

from ..runtime import VAULT_COOKIE_NAME, get_runtime
from ..services import exports


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
