"""ProjMemo application assembly; HTTP adapters and services live separately."""

import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .database_access import DatabaseAccessMiddleware, DatabaseBusyError
from .db import init_db
from .errors import ApplicationError
from .form_errors import recover_form_error
from .i18n import get_language, translate_error
from .routers import accounts, backups, content, exports, language, projects, vault
from .runtime import AppRuntime
from .web_security import LocalRequestSecurityMiddleware, NO_STORE_HEADERS, require_csrf


@asynccontextmanager
async def lifespan(application: FastAPI):
    init_db()
    async def reap_sessions():
        while True:
            await asyncio.sleep(30)
            application.state.runtime.vault_sessions.purge_expired()
    reaper = asyncio.create_task(reap_sessions())
    try:
        yield
    finally:
        reaper.cancel()
        with suppress(asyncio.CancelledError):
            await reaper


async def localized_http_error(request: Request, error: HTTPException) -> JSONResponse:
    detail = translate_error(error.detail, get_language(request)) if isinstance(error.detail, str) else error.detail
    return JSONResponse({"detail": detail}, status_code=error.status_code,
                        headers={**NO_STORE_HEADERS, **(error.headers or {})})


async def application_error(request: Request, error: ApplicationError) -> JSONResponse:
    recovered = await recover_form_error(request, error)
    if recovered is not None:
        return recovered
    return await localized_http_error(request, HTTPException(error.status_code, error.detail))


async def validation_error(request: Request, error: RequestValidationError):
    # Do not serialize Pydantic input/ctx: they can contain submitted passwords.
    fields = {str(item["loc"][-1]): "此欄位為必填或格式不正確。" for item in error.errors()}
    problem = ApplicationError(422, "請檢查必填欄位與輸入格式。")
    recovered = await recover_form_error(request, problem, fields=fields)
    if recovered is not None:
        return recovered
    # Keep FastAPI's documented detail-array shape, but omit input and ctx.
    return JSONResponse({"detail": [{"loc": list(item["loc"]), "type": item["type"],
        "msg": translate_error("此欄位為必填或格式不正確。", get_language(request))}
        for item in error.errors()]}, status_code=422, headers=NO_STORE_HEADERS)


async def database_busy_error(request: Request, error: DatabaseBusyError) -> JSONResponse:
    return JSONResponse({"detail": translate_error(str(error), get_language(request))},
                        status_code=503, headers={"Retry-After": "1", "Cache-Control": "no-store"})


def create_app(runtime: AppRuntime | None = None) -> FastAPI:
    application = FastAPI(title="ProjMemo", version="0.1.0", lifespan=lifespan,
                          dependencies=[Depends(require_csrf)])
    application.state.runtime = runtime if runtime is not None else AppRuntime()
    application.add_middleware(DatabaseAccessMiddleware)
    application.add_middleware(LocalRequestSecurityMiddleware)
    application.mount(
        "/static",
        StaticFiles(directory=str(Path(__file__).resolve().parent / "static")),
        name="static",
    )
    application.add_exception_handler(HTTPException, localized_http_error)
    application.add_exception_handler(ApplicationError, application_error)
    application.add_exception_handler(RequestValidationError, validation_error)
    application.add_exception_handler(DatabaseBusyError, database_busy_error)
    for module in (language, projects, content, accounts, vault, backups, exports):
        application.include_router(module.router)
    return application


app = create_app()
