"""HTTP adapters for /api/v1. Business logic lives in services, not here."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path

from repodoctor import __version__
from repodoctor.api.dependencies import (
    AnalysisHandler,
    DiagnosisHandler,
    get_analysis_handler,
    get_app_settings,
    get_diagnosis_handler,
)
from repodoctor.config import Settings
from repodoctor.contracts.api import (
    AnalysisRequest,
    AnalysisResponse,
    DiagnosisRequest,
    DiagnosisResponse,
    ErrorResponse,
    HealthResponse,
    Uuid4Str,
)


def _errors(*statuses: int) -> dict[int | str, dict[str, Any]]:
    return {status: {"model": ErrorResponse} for status in statuses}


router = APIRouter(prefix="/api/v1")


@router.get(
    "/health",
    response_model=HealthResponse,
    responses=_errors(500),
    summary="Liveness and active configuration (no external calls)",
)
async def health(settings: Annotated[Settings, Depends(get_app_settings)]) -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=__version__,
        repository_mode=settings.repository_mode,
        ai_configured=settings.ai_configured,
    )


@router.post(
    "/analyses",
    status_code=201,
    response_model=AnalysisResponse,
    responses=_errors(404, 409, 413, 422, 429, 500, 502, 504),
    summary="Analyze a public GitHub repository",
)
async def create_analysis(
    body: AnalysisRequest,
    service: Annotated[AnalysisHandler, Depends(get_analysis_handler)],
) -> AnalysisResponse:
    return await service.analyze(body)


@router.post(
    "/analyses/{analysis_id}/diagnoses",
    status_code=200,
    response_model=DiagnosisResponse,
    responses=_errors(404, 413, 422, 429, 500, 504),
    summary="Diagnose a pasted error log in the context of a stored analysis",
)
async def create_diagnosis(
    analysis_id: Annotated[Uuid4Str, Path()],
    body: DiagnosisRequest,
    service: Annotated[DiagnosisHandler, Depends(get_diagnosis_handler)],
) -> DiagnosisResponse:
    return await service.diagnose(analysis_id, body)
