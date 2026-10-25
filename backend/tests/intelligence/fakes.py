"""Deterministic provider double. Production code never imports this module."""

from __future__ import annotations

from collections import deque

from repodoctor.contracts.api import TargetEnvironment
from repodoctor.contracts.domain import AnalysisContext, SanitizedLog, StaticAnalysis
from repodoctor.intelligence.provider import ModelDiagnosisOutput, ModelPlanOutput, ProviderError


class FakeProvider:
    model = "synthetic-example-model"

    def __init__(self, *results: ModelPlanOutput | ModelDiagnosisOutput | ProviderError) -> None:
        self.results = deque(results)
        self.calls: list[tuple[StaticAnalysis, TargetEnvironment]] = []

    async def generate_plan(
        self, scan: StaticAnalysis, target: TargetEnvironment
    ) -> ModelPlanOutput:
        self.calls.append((scan, target))
        if not self.results:
            raise AssertionError("Unexpected provider call: no queued output")
        result = self.results.popleft()
        if isinstance(result, ProviderError):
            raise result
        return result.model_copy(deep=True)

    async def generate_diagnosis(
        self, context: AnalysisContext, log: SanitizedLog, command: str | None
    ) -> ModelDiagnosisOutput:
        self.calls.append((context, log, command))
        if not self.results:
            raise AssertionError("Unexpected provider call: no queued output")
        result = self.results.popleft()
        if isinstance(result, ProviderError):
            raise result
        return result.model_copy(deep=True)
