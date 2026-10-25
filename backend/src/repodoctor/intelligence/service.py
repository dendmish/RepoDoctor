"""C1 implementation of the intelligence port, independent of credentials and network."""

from __future__ import annotations

from repodoctor.contracts.api import (
    GenerationInfo,
    GenerationMode,
    SourceMode,
    TargetEnvironment,
)
from repodoctor.contracts.domain import (
    AnalysisContext,
    DiagnosisResult,
    PlanResult,
    SanitizedLog,
    StaticAnalysis,
)
from repodoctor.intelligence.provider import PlanProvider
from repodoctor.intelligence.rules import build_fallback_plan

FALLBACK_VERSION = "fallback-v1"


class IntelligenceServiceImpl:
    """Inject a provider explicitly; never construct a client or choose a fake implicitly.

    C1 always uses rules. C2 will enable provider calls after content validation exists.
    Keeping that gate explicit avoids returning unvalidated AI content during integration.
    """

    def __init__(self, provider: PlanProvider | None = None) -> None:
        self.provider = provider

    async def build_plan(
        self, scan: StaticAnalysis, target: TargetEnvironment, use_ai: bool
    ) -> PlanResult:
        reason = (
            "disabled_by_user"
            if not use_ai
            else ("ai_not_configured" if self.provider is None else "ai_validation_unavailable")
        )
        warnings = ["Команды не выполнялись; проверьте их перед локальным запуском."]
        if scan.source_mode is SourceMode.fixture:
            warnings.append(
                "Синтетический fixture: URL и commit описывают тестовый снимок; "
                "для запуска нужна локальная копия fixture, GitHub-доступность не подтверждена."
            )
        warnings.extend(scan.coverage.limitations)
        return PlanResult(
            run_plan=build_fallback_plan(scan, target),
            additional_findings=[],
            evidence=scan.evidence.copy(),
            generation=GenerationInfo(
                mode=GenerationMode.fallback,
                reason=reason,
                model=None,
                prompt_version=FALLBACK_VERSION,
            ),
            warnings=warnings,
        )

    async def diagnose(
        self,
        context: AnalysisContext,
        log: SanitizedLog,
        command: str | None,
        use_ai: bool,
    ) -> DiagnosisResult:
        raise NotImplementedError("Диагностика реализуется в C3; C1 предоставляет только план.")
