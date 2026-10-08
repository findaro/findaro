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
    app.openapi = lambda: build_openapi(app)  # type: ignore[method-assign]
    return app


def build_openapi(app: FastAPI) -> dict:
    """FastAPI's spec plus the /v1/chat event payloads (SSE bodies aren't described by route signatures)."""
    if app.openapi_schema:
        return app.openapi_schema
    from fastapi.openapi.utils import get_openapi
    from pydantic.json_schema import models_json_schema

    from zerch.chat.events import CHAT_EVENTS

    spec = get_openapi(title="zerch", version=__version__, routes=app.routes,
                       description="AI search as a service. Search keys are browser-safe; admin keys are not.")
    spec.setdefault("components", {}).setdefault("schemas", {})
    _, defs = models_json_schema([(m, "serialization") for m in CHAT_EVENTS.values()],
                                 ref_template="#/components/schemas/{model}")
    for name, schema in defs.get("$defs", {}).items():
        spec["components"]["schemas"].setdefault(name, schema)
    chat = spec["paths"].get("/v1/chat", {}).get("post")
    if chat:
        chat["responses"]["200"] = {
            "description": "Server-Sent Events, in order: session, plan, results, clarify (optional), text "
                           "(repeated), done. Each `data:` line is JSON matching the event's schema.",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
        chat["x-sse-events"] = {name: {"$ref": f"#/components/schemas/{m.__name__}"}
                                for name, m in CHAT_EVENTS.items()}
    app.openapi_schema = spec
    return spec


app = create_app()
