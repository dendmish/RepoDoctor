"""Protocol interfaces between modules. Signatures are normative (ARCHITECTURE.md section 6).

Implementations are wired only in the composition root (main.py); modules of agents 2 and 3
import contracts/config/security, never FastAPI routes or each other.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from repodoctor.contracts.api import AnalysisRequest, TargetEnvironment
from repodoctor.contracts.domain import (
    AnalysisContext,
    DiagnosisResult,
    PlanResult,
    RepositorySnapshot,
    SanitizedLog,
    StaticAnalysis,
)


@runtime_checkable
class RepositorySource(Protocol):
    async def fetch(self, request: AnalysisRequest) -> RepositorySnapshot: ...


@runtime_checkable
class StaticAnalyzer(Protocol):
    def analyze(self, snapshot: RepositorySnapshot) -> StaticAnalysis: ...


@runtime_checkable
class IntelligenceService(Protocol):
    async def build_plan(
        self, scan: StaticAnalysis, target: TargetEnvironment, use_ai: bool
    ) -> PlanResult: ...

    async def diagnose(
        self,
        context: AnalysisContext,
        log: SanitizedLog,
        command: str | None,
        use_ai: bool,
    ) -> DiagnosisResult: ...


@runtime_checkable
class AnalysisStore(Protocol):
    def put(self, context: AnalysisContext) -> None: ...

    def get(self, analysis_id: str) -> AnalysisContext | None: ...

    def purge_expired(self) -> int: ...
