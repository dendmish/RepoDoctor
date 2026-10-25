"""Deterministic provider double. Production code never imports this module."""

from __future__ import annotations

from collections import deque

from repodoctor.contracts.api import TargetEnvironment
from repodoctor.contracts.domain import StaticAnalysis
from repodoctor.intelligence.provider import ModelPlanOutput, ProviderError


class FakeProvider:
    def __init__(self, *results: ModelPlanOutput | ProviderError) -> None:
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
