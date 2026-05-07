import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.config import get_settings
from app.database import get_engine
from app.exceptions import AppError
from app.middleware.request_id import RequestIDMiddleware
from app.services.logging_config import setup_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup and shutdown lifecycle."""
    logger.info("OmniDiff starting up")
    yield
    await get_engine().dispose()
    logger.info("OmniDiff shut down")


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(level=settings.log_level)

    app = FastAPI(
        title="OmniDiff",
        description="Semantic search for Git commits",
        version=settings.app_version,
        lifespan=lifespan,
    )

    # Middleware ordering: Starlette runs middleware in REVERSE order of
    # `add_middleware` calls. We want `RequestIDMiddleware` to be the
    # outermost layer (first to see the request, last to see the
    # response) so every response — including CORS preflights — carries
    # `X-Request-ID`. So it goes last in code, first in execution.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIDMiddleware)

    # Error handlers
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.message},
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error: %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error"},
        )

    # Routers
    app.include_router(api_router)

    return app


app = create_app()
