"""Bounded AI orchestration with whole-result deterministic fallback."""

from __future__ import annotations

from repodoctor.contracts.api import (
    GenerationInfo,
    GenerationMode,
    SourceMode,
    TargetEnvironment,
    check_evidence_registry,
    collect_evidence_refs,
)
from repodoctor.contracts.domain import (
    AnalysisContext,
    DiagnosisResult,
    PlanResult,
    SanitizedLog,
    StaticAnalysis,
)
from repodoctor.intelligence.context import build_context
from repodoctor.intelligence.diagnostics import local_diagnosis, prepare_log
from repodoctor.intelligence.provider import (
    ANALYSIS_PROMPT_VERSION,
    DIAGNOSIS_PROMPT_VERSION,
    IntelligenceProvider,
    ProviderError,
)
from repodoctor.intelligence.rules import build_fallback_plan
from repodoctor.intelligence.validation import (
    OutputRejected,
    model_causes,
    validate_diagnosis,
    validate_plan,
)
from repodoctor.observability import log_event

FALLBACK_VERSION = "fallback-v1"


def _rule(exc: ValueError) -> str:
    """Fixed validator code only; never model text or IDs supplied by the model."""
    if isinstance(exc, OutputRejected):
        return str(exc)
    return "schema_or_evidence"


def _codes(reasons: list[str]) -> str:
    return ", ".join(sorted(set(reasons)))


class IntelligenceServiceImpl:
    """Inject a provider explicitly; never construct a client or choose a fake implicitly.

    The platform injects OpenAIProvider(settings) at A3; a fake is never selected here.
    """

    def __init__(self, provider: IntelligenceProvider | None = None) -> None:
        self.provider = provider

    async def build_plan(
        self, scan: StaticAnalysis, target: TargetEnvironment, use_ai: bool
    ) -> PlanResult:
        reason = "disabled_by_user" if not use_ai else "ai_not_configured"
        warnings = ["Команды не выполнялись; проверьте их перед локальным запуском."]
        if scan.source_mode is SourceMode.fixture:
            warnings.append(
                "Синтетический fixture: URL и commit описывают тестовый снимок; "
                "для запуска нужна локальная копия fixture, GitHub-доступность не подтверждена."
            )
        warnings.extend(scan.coverage.limitations)
        if use_ai and self.provider is not None:
            try:
                output = await self.provider.generate_plan(scan, target)
                output, findings, dropped = validate_plan(output, scan, target)
                payload = build_context(
                    scan, target, baseline=build_fallback_plan(scan, target).model_dump(mode="json")
                )
                # Also restrict fake/other providers to IDs actually visible within the budget.
                visible = {item["id"] for item in payload["evidence"]}
                if not collect_evidence_refs(output.run_plan) <= visible:
                    raise OutputRejected("evidence_outside_context")
                outside = [f for f in findings if not set(f.evidence_ids) <= visible]
                dropped += ["evidence_outside_context"] * len(outside)
                findings = [f for f in findings if f not in outside]
                check_evidence_registry(
                    scan.evidence, collect_evidence_refs(output.run_plan, findings)
                )
                if dropped:
                    log_event("ai_findings_dropped", count=len(dropped), reasons=_codes(dropped))
                    warnings.append(
                        f"Отброшено AI-наблюдений без подтверждения: {len(dropped)} "
                        f"({_codes(dropped)})."
                    )
                if payload["truncated"]:
                    warnings.append("Контекст AI сокращён; часть данных не передавалась модели.")
                return PlanResult(
                    run_plan=output.run_plan,
                    additional_findings=findings,
                    evidence=scan.evidence.copy(),
                    generation=self._generation(
                        getattr(self.provider, "plan_prompt_version", ANALYSIS_PROMPT_VERSION)
                    ),
                    warnings=warnings,
                )
            except ProviderError as exc:
                reason, rule = exc.reason, None
            except TimeoutError:
                reason, rule = "timeout", None
            except ValueError as exc:
                reason, rule = "invalid_output", _rule(exc)
            log_event("ai_plan_fallback", reason=reason, rule=rule or "-")
            detail = f"{reason}: {rule}" if rule else reason
            warnings.append(f"AI-план недоступен ({detail}); использованы локальные правила.")
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
        prepared = prepare_log(log)
        evidence = [*context.scan.evidence, *prepared.evidence]
        warnings = ["Причины предположительные; исправления и команды не выполнялись."]
        warnings.extend(context.scan.coverage.limitations)
        if prepared.truncated:
            warnings.append("Обработанный лог сокращён для AI; номера строк сохранены.")
        if context.scan.source_mode is SourceMode.fixture:
            warnings.append("Диагностика использует synthetic fixture репозитория.")
        reason = "disabled_by_user" if not use_ai else "ai_not_configured"
        if use_ai and self.provider is not None:
            try:
                output = await self.provider.generate_diagnosis(context, log, command)
                payload = build_context(
                    context.scan,
                    context.response.target,
                    baseline=context.response.run_plan.model_dump(mode="json"),
                )
                visible = {item["id"] for item in payload["evidence"]}
                validation_evidence = [
                    ev for ev in evidence if ev.id in visible or ev.id.startswith("log_")
                ]
                output, dropped = validate_diagnosis(
                    output,
                    context,
                    validation_evidence,
                    user_text="\n".join(filter(None, [log.text, command])),
                )
                if dropped:
                    log_event("ai_causes_dropped", count=len(dropped), reasons=_codes(dropped))
                    warnings.append(
                        f"Отброшено AI-причин без подтверждения: {len(dropped)} "
                        f"({_codes(dropped)})."
                    )
                if payload["truncated"]:
                    warnings.append("Контекст AI сокращён; часть данных не передавалась модели.")
                return DiagnosisResult(
                    summary=output.summary,
                    causes=model_causes(output),
                    questions=output.questions,
                    evidence=evidence,
                    generation=self._generation(
                        getattr(self.provider, "diagnosis_prompt_version", DIAGNOSIS_PROMPT_VERSION)
                    ),
                    warnings=warnings,
                )
            except ProviderError as exc:
                reason, rule = exc.reason, None
            except TimeoutError:
                reason, rule = "timeout", None
            except ValueError as exc:
                reason, rule = "invalid_output", _rule(exc)
            log_event("ai_diagnosis_fallback", reason=reason, rule=rule or "-")
            detail = f"{reason}: {rule}" if rule else reason
            warnings.append(
                f"AI-диагностика недоступна ({detail}); использованы локальные правила."
            )
        causes, questions = local_diagnosis(context, log, prepared)
        return DiagnosisResult(
            summary=(
                "Возможные причины по сигнатурам обработанного лога."
                if causes
                else "Надёжная сигнатура не найдена; нужны уточнения."
            ),
            causes=causes,
            questions=questions,
            evidence=evidence,
            generation=GenerationInfo(
                mode=GenerationMode.fallback,
                reason=reason,
                model=None,
                prompt_version="diagnosis-rules-v1",
            ),
            warnings=warnings,
        )

    def _generation(self, version: str) -> GenerationInfo:
        return GenerationInfo(
            mode=GenerationMode.ai,
            reason=None,
            model=getattr(self.provider, "model", None),
            prompt_version=version,
        )
