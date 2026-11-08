"""ASGI application factory: uvicorn plcagent.api.app:app"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from plcagent.api.deps import error_envelope
from plcagent.api.routes import router


def create_app() -> FastAPI:
    app = FastAPI(
        title="Lingshu NeuroAxis API",
        version="0.1.0",
        description="ST kernel verification and infrastructure status.",
    )
    # Vue dev server ports; tighten before exposing publicly.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:4173"],
        allow_methods=["GET", "POST"],
        allow_headers=["X-API-Key", "Content-Type"],
    )
    app.add_exception_handler(Exception, error_envelope)
    app.include_router(router, prefix="/api/v1")
    return app


app = create_app()
