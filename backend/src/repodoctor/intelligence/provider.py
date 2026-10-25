"""Private typed provider boundary. The live adapter and validation arrive in C2."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from repodoctor.contracts.api import (
    Confidence,
    ContractModel,
    RunPlan,
    Severity,
    TargetEnvironment,
)
from repodoctor.contracts.domain import StaticAnalysis


class ModelFindingOutput(ContractModel):
    title: str
    description: str
    severity: Severity
    confidence: Confidence
    evidence_ids: list[str]
    suggested_action: str


class ModelPlanOutput(ContractModel):
    """Model content only: no response IDs, timestamps, URLs or evidence registry."""

    run_plan: RunPlan
    additional_findings: list[ModelFindingOutput]


class ProviderError(Exception):
    """Only a fixed reason may cross the provider boundary, never upstream error bodies."""

    def __init__(self, reason: str = "provider_unavailable") -> None:
        allowed = {"provider_unavailable", "timeout", "refusal", "invalid_output", "incomplete"}
        self.reason = reason if reason in allowed else "provider_unavailable"
        super().__init__(self.reason)


@runtime_checkable
class PlanProvider(Protocol):
    async def generate_plan(
        self, scan: StaticAnalysis, target: TargetEnvironment
    ) -> ModelPlanOutput: ...
