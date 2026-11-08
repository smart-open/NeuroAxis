"""HTTP endpoints. Thin: parse input, call core, shape output."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from plcagent.api.deps import app_version, require_api_key
from plcagent.api.schemas import (
    ErrorResponse,
    HealthOut,
    InfraOut,
    ServiceStatus,
    VerifyIn,
    VerifyOut,
)
from plcagent.infra import check_all
from plcagent.verify import run_scenario

router = APIRouter(dependencies=[Depends(require_api_key)])


@router.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    return HealthOut(status="ok", version=app_version())


@router.get("/infra", response_model=InfraOut,
            responses={500: {"model": ErrorResponse}})
async def infra_status() -> InfraOut:
    results = check_all()
    return InfraOut(**{name: ServiceStatus(ok=ok, detail=detail)
                       for name, (ok, detail) in results.items()})


@router.post("/verify", response_model=VerifyOut,
             responses={422: {"model": ErrorResponse}, 500: {"model": ErrorResponse}})
async def verify(payload: VerifyIn) -> VerifyOut:
    digests = set()
    for _ in range(payload.runs):
        digest, _recorder = run_scenario()
        digests.add(digest)
    return VerifyOut(ok=len(digests) == 1, digest=digests.pop(), runs=payload.runs)
