from __future__ import annotations

import pytest

from repodoctor.contracts.api import TargetEnvironment
from repodoctor.contracts.ports import IntelligenceService
from repodoctor.intelligence.provider import ModelPlanOutput, PlanProvider, ProviderError
from repodoctor.intelligence.rules import build_fallback_plan
from repodoctor.intelligence.service import IntelligenceServiceImpl
from tests.intelligence.fakes import FakeProvider

TARGET = TargetEnvironment(os="windows", shell="powershell")  # noqa: S604 -- DTO, not subprocess


async def test_disabled_ai_never_calls_injected_provider(python_scan):
    provider = FakeProvider(ProviderError("timeout"))
    service = IntelligenceServiceImpl(provider)
    result = await service.build_plan(python_scan, TARGET, use_ai=False)
    assert isinstance(service, IntelligenceService)
    assert result.generation.mode == "fallback"
    assert result.generation.reason == "disabled_by_user"
    assert result.generation.model is None
    assert result.generation.prompt_version == "fallback-v1"
    assert not provider.calls


async def test_missing_provider_does_not_construct_network_clients(python_scan, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("C1 must not create a network client")

    monkeypatch.setattr("httpx.AsyncClient", forbidden)
    monkeypatch.setattr("openai.AsyncOpenAI", forbidden)
    original = python_scan.model_dump_json()
    result = await IntelligenceServiceImpl().build_plan(python_scan, TARGET, use_ai=True)
    assert result.generation.reason == "ai_not_configured"
    assert result.generation.model is None
    assert result.evidence == python_scan.evidence
    assert not result.additional_findings
    assert python_scan.model_dump_json() == original
    assert any("fixture" in warning for warning in result.warnings)


async def test_invalid_provider_output_uses_whole_fallback(python_scan):
    provider = FakeProvider(ProviderError("invalid_output"))
    result = await IntelligenceServiceImpl(provider).build_plan(python_scan, TARGET, use_ai=True)
    assert result.generation.reason == "invalid_output"
    assert result.generation.mode == "fallback"
    assert len(provider.calls) == 1


async def test_fake_is_typed_deterministic_and_records_calls(python_scan):
    output = ModelPlanOutput(
        run_plan=build_fallback_plan(python_scan, TARGET), additional_findings=[]
    )
    fake = FakeProvider(output, ProviderError("timeout"))
    assert isinstance(fake, PlanProvider)
    returned = await fake.generate_plan(python_scan, TARGET)
    assert returned == output
    assert returned is not output
    returned.run_plan.steps.clear()
    assert output.run_plan.steps
    with pytest.raises(ProviderError, match="timeout"):
        await fake.generate_plan(python_scan, TARGET)
    with pytest.raises(AssertionError, match="Unexpected provider call"):
        await fake.generate_plan(python_scan, TARGET)
    assert len(fake.calls) == 3


def test_provider_errors_do_not_expose_arbitrary_upstream_messages():
    error = ProviderError("Authorization: Bearer synthetic-private-value")
    assert str(error) == "provider_unavailable"
