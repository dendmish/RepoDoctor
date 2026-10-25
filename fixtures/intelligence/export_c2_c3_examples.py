"""Generate integration examples through the real service with explicit synthetic AI.

Run with backend Python. No credentials, network, API wiring, or live-model claims.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from repodoctor.contracts.api import AnalysisResponse
from repodoctor.contracts.domain import AnalysisContext, SanitizedLog, StaticAnalysis
from repodoctor.intelligence.provider import (
    ModelCauseOutput,
    ModelDiagnosisOutput,
    ModelPlanOutput,
    ProviderError,
)
from repodoctor.intelligence.rules import build_fallback_plan
from repodoctor.intelligence.service import IntelligenceServiceImpl

HERE = Path(__file__).resolve().parent
EXAMPLES = HERE.parents[1] / "contracts" / "examples"


class ExampleProvider:
    """Only for this exporter; production never imports or automatically selects it."""

    model = "synthetic-example-model"

    def __init__(self, output):
        self.output = output

    async def generate_plan(self, scan, target):
        return self.output

    async def generate_diagnosis(self, context, log, command):
        if isinstance(self.output, ProviderError):
            raise self.output
        return self.output


def load_context(name: str) -> AnalysisContext:
    response = AnalysisResponse.model_validate_json((EXAMPLES / name).read_text(encoding="utf-8"))
    scan = StaticAnalysis(
        repository=response.repository,
        source_mode=response.source_mode,
        facts=response.facts,
        findings=response.findings,
        evidence=response.evidence,
        coverage=response.coverage,
        selected_files=[],
    )
    return AnalysisContext(response=response, scan=scan)


def write(name: str, result, *, synthetic_ai: bool = False) -> None:
    if synthetic_ai:
        result.warnings.append("Синтетический model output из exporter; live AI не вызывался.")
    (HERE / name).write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")


async def main() -> None:
    node = load_context("analysis_node.json")
    output = ModelPlanOutput(
        run_plan=build_fallback_plan(node.scan, node.response.target),
        additional_findings=[],
    )
    output.run_plan.summary = (
        "Пример валидированного AI-плана на synthetic output; запуск не выполнялся."
    )
    service = IntelligenceServiceImpl(ExampleProvider(output))
    result = await service.build_plan(node.scan, node.response.target, True)
    write("plan_ai_synthetic.json", result, synthetic_ai=True)

    context = load_context("analysis_python.json")
    sanitized = SanitizedLog(
        text="Traceback (most recent call last):\nModuleNotFoundError: No module named 'requests'",
        redactions_count=0,
        truncated=False,
    )
    rules = IntelligenceServiceImpl()
    local = await rules.diagnose(context, sanitized, None, False)
    write("diagnosis_rules_module.json", local)
    unknown = await rules.diagnose(
        context,
        SanitizedLog(text="Unclassified synthetic failure", redactions_count=0, truncated=False),
        None,
        False,
    )
    write("diagnosis_unknown.json", unknown)
    output = ModelDiagnosisOutput(
        summary="Пример AI-диагностики: проверьте окружение и установку manifest.",
        causes=[
            ModelCauseOutput(**cause.model_dump(exclude={"id", "origin"})) for cause in local.causes
        ],
        questions=local.questions,
    )
    result = await IntelligenceServiceImpl(ExampleProvider(output)).diagnose(
        context, sanitized, None, True
    )
    write("diagnosis_ai_synthetic.json", result, synthetic_ai=True)
    result = await IntelligenceServiceImpl(ExampleProvider(ProviderError("timeout"))).diagnose(
        context,
        sanitized,
        None,
        True,
    )
    write("diagnosis_ai_timeout.json", result)


if __name__ == "__main__":
    asyncio.run(main())
