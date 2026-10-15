"""ProjMemo application assembly; HTTP adapters and services live separately."""

import asyncio
from contextlib import ExitStack, asynccontextmanager, suppress
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .database_access import DatabaseAccessMiddleware, DatabaseBusyError
from .db import MigrationError, init_db
from .errors import ApplicationError
from .form_errors import recover_form_error
from .i18n import get_language, translate_error
from .operations import SafeDiagnosticsMiddleware, error_category, operational_log, prepare_storage
from .routers import accounts, backups, content, exports, health, language, projects, vault
from .runtime import AppRuntime
from .web_security import LocalRequestSecurityMiddleware, NO_STORE_HEADERS, require_csrf


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.startup_ready = False
    resources = ExitStack()
    logger = logging.getLogger("projmemo.operations")
    try:
        path = prepare_storage()
        logger = resources.enter_context(operational_log(path))
        application.state.operations_logger = logger
        init_db()
    except Exception as error:
        code = error_category(error)
        logger.error("startup_failed category=%s; preserve backups and consult docs/local-operations.md", code)
        resources.close()
        application.state.operations_logger = None
        if isinstance(error, MigrationError):
            raise MigrationError(f"ProjMemo startup failed [{code}]. Preserve backups; see docs/local-operations.md.",
                                 snapshot_path=error.snapshot_path, recovered=error.recovered) from None
        raise RuntimeError(f"ProjMemo startup failed [{code}]. Preserve backups; see docs/local-operations.md.") from None
    application.state.startup_ready = True
    logger.info("startup_ready")
    async def reap_sessions():
        while True:
            await asyncio.sleep(30)
            try:
                application.state.runtime.vault_sessions.purge_expired()
            except Exception as error:
                logger.error("session_cleanup_failed category=%s", error_category(error))
    reaper = asyncio.create_task(reap_sessions())
    try:
        yield
    finally:
        application.state.startup_ready = False
        reaper.cancel()
        try:
            with suppress(asyncio.CancelledError):
                await reaper
        finally:
            logger.info("shutdown_complete")
            application.state.operations_logger = None
            resources.close()


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
    # Newer FastAPI treats an explicitly submitted empty Form value as missing.
    # Preserve our 400 blank-value / 422 absent-field distinction without echoing input.
    if request.headers.get("content-type", "").split(";", 1)[0] in {"application/x-www-form-urlencoded", "multipart/form-data"}:
        submitted = await request.form()
        if error.errors() and all(item["type"] == "missing" and len(item["loc"]) == 2
                and item["loc"][0] == "body" and submitted.get(item["loc"][1]) == ""
                for item in error.errors()):
            problem = ApplicationError(400, problem.detail)
    recovered = await recover_form_error(request, problem, fields=fields)
    if recovered is not None:
        return recovered
    # Keep FastAPI's documented detail-array shape, but omit input and ctx.
    if problem.status_code == 400:
        return await localized_http_error(request, HTTPException(400, problem.detail))
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
    application.state.startup_ready = False
    application.state.operations_logger = None
    application.add_middleware(DatabaseAccessMiddleware)
    application.add_middleware(LocalRequestSecurityMiddleware)
    application.add_middleware(SafeDiagnosticsMiddleware)
    application.mount(
        "/static",
        StaticFiles(directory=str(Path(__file__).resolve().parent / "static")),
        name="static",
    )
    application.add_exception_handler(HTTPException, localized_http_error)
    application.add_exception_handler(ApplicationError, application_error)
    application.add_exception_handler(RequestValidationError, validation_error)
    application.add_exception_handler(DatabaseBusyError, database_busy_error)
    for module in (language, projects, content, accounts, vault, backups, exports, health):
        application.include_router(module.router)
    return application


app = create_app()
