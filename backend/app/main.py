"""AIJewel earring earlobe-alignment QA API."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.adapters.tryon_application import TryOnError
from app.api.routes import applications, execution, health, references, results, tests
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.database import init_db
from app.utils.files import StorageError


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level)
    settings.ensure_dirs()
    init_db()
    yield


class PrivateNetworkAccessMiddleware:
    """Let a public HTTPS page call this API on localhost.

    Chrome treats that as a private-network request. The preflight is blocked
    unless the response includes Access-Control-Allow-Private-Network.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        requested = Headers(scope=scope).get("access-control-request-private-network") == "true"

        async def send_with_header(message: Message) -> None:
            if requested and message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Access-Control-Allow-Private-Network"] = "true"
            await send(message)

        await self.app(scope, receive, send_with_header)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AIJewel Earring QA",
        summary="Local earlobe alignment QA for the AIJewel virtual try-on.",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_origin_regex=(
            r"https?://(localhost|127\.0\.0\.1)(:\d+)?"
            r"|https://([a-z0-9-]+\.)+amplifyapp\.com"
        ),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(PrivateNetworkAccessMiddleware)

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(settings.frontend_url)

    prefix = settings.api_prefix
    app.include_router(health.router, prefix=prefix)
    app.include_router(applications.router, prefix=prefix)
    app.include_router(references.router, prefix=prefix)
    app.include_router(tests.router, prefix=prefix)
    app.include_router(execution.router, prefix=prefix)
    app.include_router(results.router, prefix=prefix)

    @app.exception_handler(TryOnError)
    async def tryon_error(_request: Request, exc: TryOnError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "detail": {
                    "code": exc.code,
                    "message": str(exc),
                    "recommended_action": exc.recommended_action,
                }
            },
        )

    @app.exception_handler(StorageError)
    async def storage_error(_request: Request, exc: StorageError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": {"code": exc.code, "message": str(exc)}})

    return app


app = create_app()
