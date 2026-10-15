"""HTTP form adapters for project content; SQL and validation live in services."""

from fastapi import APIRouter, Form
from fastapi.responses import RedirectResponse

from ..presentation import redirect_to_project
from ..services import content

from ..submissions import MutationRoute

router = APIRouter(route_class=MutationRoute)


@router.post("/projects/{project_id}/urls")
def add_url(
    project_id: int,
    type: str = Form("other"),
    title: str = Form(...),
    url: str = Form(...),
    note: str = Form(""),
) -> RedirectResponse:
    project_id = content.add_url(project_id=project_id, type=type, title=title, url=url, note=note)
    return redirect_to_project(project_id)


@router.post("/urls/{url_id}/edit")
def update_url(
    url_id: int,
    type: str = Form("other"),
    title: str = Form(...),
    url: str = Form(...),
    note: str = Form(""),
) -> RedirectResponse:
    project_id = content.update_url(url_id=url_id, type=type, title=title, url=url, note=note)
    return redirect_to_project(project_id)


@router.post("/urls/{url_id}/delete")
def delete_url(url_id: int) -> RedirectResponse:
    project_id = content.delete_url(url_id=url_id)
    return redirect_to_project(project_id)


@router.post("/projects/{project_id}/notes")
def add_note(
    project_id: int,
    category: str = Form("note"),
    title: str = Form(...),
    content_markdown: str = Form(...),
    priority: str = Form("normal"),
) -> RedirectResponse:
    project_id = content.add_note(
        project_id=project_id,
        category=category,
        title=title,
        content_markdown=content_markdown,
        priority=priority,
    )
    return redirect_to_project(project_id)


@router.post("/notes/{note_id}/edit")
def update_note(
    note_id: int,
    category: str = Form("note"),
    title: str = Form(...),
    content_markdown: str = Form(...),
    priority: str = Form("normal"),
) -> RedirectResponse:
    project_id = content.update_note(
        note_id=note_id,
        category=category,
        title=title,
        content_markdown=content_markdown,
        priority=priority,
    )
    return redirect_to_project(project_id)


@router.post("/notes/{note_id}/delete")
def delete_note(note_id: int) -> RedirectResponse:
    project_id = content.delete_note(note_id=note_id)
    return redirect_to_project(project_id)


@router.post("/projects/{project_id}/checklist")
def add_checklist_item(
    project_id: int,
    category: str = Form("other"),
    title: str = Form(...),
    description: str = Form(""),
    owner: str = Form(""),
    note: str = Form(""),
) -> RedirectResponse:
    project_id = content.add_checklist_item(
        project_id=project_id,
        category=category,
        title=title,
        description=description,
        owner=owner,
        note=note,
    )
    return redirect_to_project(project_id)


@router.post("/checklist/{item_id}/toggle")
def toggle_checklist(item_id: int) -> RedirectResponse:
    project_id = content.toggle_checklist(item_id=item_id)
    return redirect_to_project(project_id)


@router.post("/checklist/{item_id}/edit")
def update_checklist_item(
    item_id: int,
    category: str = Form("other"),
    title: str = Form(...),
    description: str = Form(""),
    owner: str = Form(""),
    note: str = Form(""),
) -> RedirectResponse:
    project_id = content.update_checklist_item(
        item_id=item_id,
        category=category,
        title=title,
        description=description,
        owner=owner,
        note=note,
    )
    return redirect_to_project(project_id)


@router.post("/checklist/{item_id}/delete")
def delete_checklist_item(item_id: int) -> RedirectResponse:
    project_id = content.delete_checklist_item(item_id=item_id)
    return redirect_to_project(project_id)


@router.post("/projects/{project_id}/environment-variables")
def add_environment_variable(
    project_id: int,
    key: str = Form(...),
    environment: str = Form("local"),
    description: str = Form(""),
    source_or_owner: str = Form(""),
    is_secret: bool = Form(False),
) -> RedirectResponse:
    project_id = content.add_environment_variable(
        project_id=project_id,
        key=key,
        environment=environment,
        description=description,
        source_or_owner=source_or_owner,
        is_secret=is_secret,
    )
    return redirect_to_project(project_id)


@router.post("/environment-variables/{variable_id}/edit")
def update_environment_variable(
    variable_id: int,
    key: str = Form(...),
    environment: str = Form("local"),
    description: str = Form(""),
    source_or_owner: str = Form(""),
    is_secret: bool = Form(False),
) -> RedirectResponse:
    project_id = content.update_environment_variable(
        variable_id=variable_id,
        key=key,
        environment=environment,
        description=description,
        source_or_owner=source_or_owner,
        is_secret=is_secret,
    )
    return redirect_to_project(project_id)


@router.post("/environment-variables/{variable_id}/delete")
def delete_environment_variable(variable_id: int) -> RedirectResponse:
    project_id = content.delete_environment_variable(variable_id=variable_id)
    return redirect_to_project(project_id)
