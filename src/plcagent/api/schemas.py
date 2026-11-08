"""Request/response models (Pydantic v2)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HealthOut(BaseModel):
    status: str
    version: str


class ServiceStatus(BaseModel):
    ok: bool
    detail: str


class InfraOut(BaseModel):
    postgres: ServiceStatus
    redis: ServiceStatus
    rustfs: ServiceStatus


class VerifyIn(BaseModel):
    runs: int = Field(default=50, ge=1, le=10_000,
                      description="Determinism run count")


class VerifyOut(BaseModel):
    ok: bool
    digest: str
    runs: int


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
