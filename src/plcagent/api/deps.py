"""Shared FastAPI dependencies: error envelope + optional API key auth."""

from __future__ import annotations

import os

from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse

from plcagent import __version__
from plcagent.st.interp import SimFault
from plcagent.st.parser import StSyntaxError


async def error_envelope(request: Request, exc: Exception) -> JSONResponse:
    """Uniform JSON error body for every unhandled exception."""
    if isinstance(exc, StSyntaxError):
        status, code = 400, "st_syntax_error"
        detail = f"line {exc.line}, col {exc.col}: {exc}"
    elif isinstance(exc, SimFault):
        status, code = 422, "sim_fault"
        detail = str(exc)
    else:
        status, code = 500, "internal_error"
        detail = str(exc)
    return JSONResponse(
        status_code=status,
        content={"error": code, "detail": detail},
    )


async def require_api_key(
    x_api_key: str | None = Header(default=None),
) -> None:
    """Enabled only when PLCAGENT_API_KEY is set; unset = open (dev only)."""
    expected = os.environ.get("PLCAGENT_API_KEY", "")
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="invalid or missing API key")


def app_version() -> str:
    return __version__
