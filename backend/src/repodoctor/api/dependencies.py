"""FastAPI dependencies: resolve settings and wired services from app.state."""

from __future__ import annotations

from typing import Protocol

from fastapi import Request

from repodoctor.config import Settings
from repodoctor.contracts.api import (
    AnalysisRequest,
    AnalysisResponse,
    DiagnosisRequest,
    DiagnosisResponse,
)
from repodoctor.contracts.domain import RepoDoctorError


class AnalysisHandler(Protocol):
    async def analyze(self, request: AnalysisRequest) -> AnalysisResponse: ...


class DiagnosisHandler(Protocol):
    async def diagnose(self, analysis_id: str, request: DiagnosisRequest) -> DiagnosisResponse: ...


class PipelineNotWiredError(RepoDoctorError):
    """Raised until real services are composed in main.py (A2/A3) or dev stubs are enabled."""


class _UnwiredService:
    """Placeholder that fails on use, so request validation still runs first."""

    async def analyze(self, request: AnalysisRequest) -> AnalysisResponse:
        raise PipelineNotWiredError("Конвейер анализа ещё не подключён на этом сервере.")

    async def diagnose(self, analysis_id: str, request: DiagnosisRequest) -> DiagnosisResponse:
        raise PipelineNotWiredError("Конвейер диагностики ещё не подключён на этом сервере.")


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_analysis_handler(request: Request) -> AnalysisHandler:
    return request.app.state.analysis_service or _UnwiredService()


def get_diagnosis_handler(request: Request) -> DiagnosisHandler:
    return request.app.state.diagnosis_service or _UnwiredService()
