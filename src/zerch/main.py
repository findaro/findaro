from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from zerch import __version__
from zerch.api.routes import router
from zerch.config import Settings, get_settings
from zerch.embeddings import Embedder
from zerch.errors import ApiError, api_error_handler, validation_error_handler
from zerch.state import create_state


def create_app(settings: Settings | None = None, embedder: Embedder | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logging.basicConfig(level=logging.INFO)
        logging.getLogger("opensearch").setLevel(logging.WARNING)
        app.state.zerch = await create_state(settings, embedder)
        yield
        await app.state.zerch.close()

    app = FastAPI(title="zerch", version=__version__, lifespan=lifespan)
    # Search keys are meant for browsers (M4 JS SDK), so CORS is open; admin keys must stay server-side.
    app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                       allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                       allow_headers=["authorization", "content-type", "x-zerch-key", "cache-control"])
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.include_router(router)
    return app


app = create_app()
