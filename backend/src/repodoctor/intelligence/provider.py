"""Private schemas and a lazy, single-request Responses Structured Outputs adapter."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol, TypeVar, runtime_checkable

from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
)
from pydantic import ValidationError

from repodoctor.config import Settings
from repodoctor.contracts.api import (
    Confidence,
    ContractModel,
    RunPlan,
    RunStep,
    Severity,
    TargetEnvironment,
)
from repodoctor.contracts.domain import AnalysisContext, SanitizedLog, StaticAnalysis
from repodoctor.intelligence.context import build_context, encode
from repodoctor.intelligence.rules import build_fallback_plan

ANALYSIS_PROMPT_VERSION = "analysis-v1"
DIAGNOSIS_PROMPT_VERSION = "diagnosis-v1"
PROMPTS = Path(__file__).with_name("prompts")
OutputT = TypeVar("OutputT", bound=ContractModel)


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


class ModelCauseOutput(ContractModel):
    title: str
    explanation: str
    confidence: Confidence
    evidence_ids: list[str]
    fixes: list[RunStep]
    verification: str


class ModelDiagnosisOutput(ContractModel):
    summary: str
    causes: list[ModelCauseOutput]
    questions: list[str]


class ProviderError(Exception):
    """Only a fixed reason may cross the provider boundary, never upstream error bodies."""

    def __init__(self, reason: str = "provider_unavailable") -> None:
        allowed = {
            "provider_unavailable",
            "timeout",
            "refusal",
            "invalid_output",
            "incomplete",
            "rate_limited",
            "ai_not_configured",
            "context_too_large",
            "authentication_failed",
            "tls_error",
            "request_rejected",
        }
        self.reason = reason if reason in allowed else "provider_unavailable"
        super().__init__(self.reason)


@runtime_checkable
class PlanProvider(Protocol):
    async def generate_plan(
        self, scan: StaticAnalysis, target: TargetEnvironment
    ) -> ModelPlanOutput: ...


@runtime_checkable
class DiagnosisProvider(Protocol):
    async def generate_diagnosis(
        self, context: AnalysisContext, log: SanitizedLog, command: str | None
    ) -> ModelDiagnosisOutput: ...


class IntelligenceProvider(PlanProvider, DiagnosisProvider, Protocol):
    model: str | None


def plan_payload(scan: StaticAnalysis, target: TargetEnvironment) -> dict:
    baseline = build_fallback_plan(scan, target)
    return build_context(scan, target, baseline=baseline.model_dump(mode="json"))


def diagnosis_payload(context: AnalysisContext, log: SanitizedLog, command: str | None) -> dict:
    from repodoctor.intelligence.diagnostics import diagnostic_commands, prepare_log

    return {
        "repo_context": build_context(
            context.scan,
            context.response.target,
            baseline=context.response.run_plan.model_dump(mode="json"),
        ),
        "command": command,
        "log": prepare_log(log).payload,
        "allowed_commands": diagnostic_commands(context),
    }


class OpenAIProvider:
    """Settings-only credentials. No client until an enabled operation actually calls us.

    The client is owned per operation and always closed, including on cancellation.
    No ambient base URL, tools, automatic retries, prompt logging or response storage.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.model = settings.openai_model

    async def _request(self, prompt: str, payload: dict, schema: type[OutputT]) -> OutputT:
        settings = self._settings
        if not settings.openai_configured:
            raise ProviderError("ai_not_configured")
        try:
            async with asyncio.timeout(settings.ai_timeout_seconds):
                async with self._client() as client:
                    response = await client.responses.parse(
                        model=self.model,
                        instructions=(PROMPTS / prompt).read_text(encoding="utf-8"),
                        input=encode(payload),
                        text_format=schema,
                        max_output_tokens=settings.ai_max_output_tokens,
                        store=False,
                    )
            if not isinstance(response.output, list):
                raise ProviderError("invalid_output")
            if any(
                getattr(part, "type", None) == "refusal"
                for item in response.output
                for part in (getattr(item, "content", None) or [])
            ):
                raise ProviderError("refusal")
            if response.status == "incomplete":
                raise ProviderError("incomplete")
            if response.status != "completed":
                raise ProviderError("provider_unavailable")
            if response.output_parsed is None:
                raise ProviderError("invalid_output")
            return schema.model_validate(response.output_parsed.model_dump())
        except (APITimeoutError, TimeoutError) as exc:
            raise ProviderError("timeout") from exc
        except APIStatusError as exc:
            reason = "rate_limited" if exc.status_code == 429 else "provider_unavailable"
            raise ProviderError(reason) from exc
        except APIConnectionError as exc:
            raise ProviderError("provider_unavailable") from exc
        except (APIResponseValidationError, ValidationError, ValueError) as exc:
            raise ProviderError("invalid_output") from exc

    def _client(self) -> AsyncOpenAI:
        return AsyncOpenAI(
            api_key=self._settings.openai_api_key.get_secret_value(),
            base_url="https://api.openai.com/v1",
            timeout=self._settings.ai_timeout_seconds,
            max_retries=0,
        )

    async def generate_plan(
        self, scan: StaticAnalysis, target: TargetEnvironment
    ) -> ModelPlanOutput:
        if not self._settings.openai_configured:
            raise ProviderError("ai_not_configured")
        return await self._request("analysis.txt", plan_payload(scan, target), ModelPlanOutput)

    async def generate_diagnosis(
        self, context: AnalysisContext, log: SanitizedLog, command: str | None
    ) -> ModelDiagnosisOutput:
        if not self._settings.openai_configured:
            raise ProviderError("ai_not_configured")
        return await self._request(
            "diagnosis.txt", diagnosis_payload(context, log, command), ModelDiagnosisOutput
        )
