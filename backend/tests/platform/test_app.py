from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from repodoctor.config import AIProvider, Settings
from repodoctor.contracts.api import AnalysisResponse, DiagnosisResponse, ErrorResponse
from repodoctor.contracts.domain import GitHubRateLimitedError
from repodoctor.export_openapi import render_openapi
from repodoctor.main import create_app

from .conftest import load_example


@pytest.fixture
def client(test_settings: Settings) -> TestClient:
    return TestClient(create_app(test_settings), raise_server_exceptions=False)


@pytest.fixture
def stub_client(test_settings: Settings) -> TestClient:
    settings = test_settings.model_copy(update={"use_dev_stubs": True})
    return TestClient(create_app(settings), raise_server_exceptions=False)


def _assert_error(response, status: int, code: str) -> dict:
    assert response.status_code == status
    body = ErrorResponse.model_validate(response.json())
    assert body.error.code == code
    assert body.error.request_id
    return response.json()


def test_health_without_keys(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["repository_mode"] == "fixture"
    assert body["ai_configured"] is False


def test_health_never_exposes_keys(test_settings: Settings) -> None:
    settings = test_settings.model_copy(
        update={
            "ai_provider": AIProvider.openai,
            "openai_api_key": SecretStr("sk-test-SECRET123"),
            "openai_model": "m",
        }
    )
    response = TestClient(create_app(settings)).get("/api/v1/health")
    assert response.json()["ai_configured"] is True
    assert "SECRET123" not in response.text
    assert "SECRET123" not in repr(settings)


def test_default_pipeline_returns_real_fixture_analysis(client: TestClient) -> None:
    payload = {**load_example("request_analysis.json"), "use_ai": False}
    response = client.post("/api/v1/analyses", json=payload)
    assert response.status_code == 201
    analysis = AnalysisResponse.model_validate(response.json())
    assert analysis.generation.mode == "fallback"
    assert analysis.facts.dependencies
    assert not any("DEV STUB" in warning for warning in analysis.warnings)


def test_validation_error_envelope_hides_input(client: TestClient) -> None:
    secret_log = "token=ghp_SHOULD_NOT_ECHO"
    payload = {"repo_url": secret_log, "target": {"os": "linux", "shell": "zsh"}}
    response = client.post("/api/v1/analyses", json=payload)
    body = _assert_error(response, 422, "INVALID_INPUT")
    assert body["error"]["details"]
    assert "ghp_SHOULD_NOT_ECHO" not in response.text


def test_invalid_analysis_id_is_invalid_input(client: TestClient) -> None:
    response = client.post("/api/v1/analyses/not-a-uuid/diagnoses", json={"log": "x"})
    _assert_error(response, 422, "INVALID_INPUT")


def test_unknown_api_route_is_json_404(client: TestClient) -> None:
    _assert_error(client.get("/api/v1/nope"), 404, "NOT_FOUND")
    _assert_error(client.get("/api/v1/analyses"), 405, "METHOD_NOT_ALLOWED")


def test_domain_error_mapping_and_retry_after(test_settings: Settings) -> None:
    class RateLimited:
        async def analyze(self, request):
            raise GitHubRateLimitedError("limit", retry_after_seconds=60)

    app = create_app(test_settings, analysis_service=RateLimited())
    response = TestClient(app).post("/api/v1/analyses", json=load_example("request_analysis.json"))
    body = _assert_error(response, 429, "GITHUB_RATE_LIMITED")
    assert body["error"]["retryable"] is True
    assert response.headers["Retry-After"] == "60"


def test_unexpected_exception_is_sanitized(test_settings: Settings) -> None:
    class Broken:
        async def analyze(self, request):
            raise RuntimeError("internal path C:/secret/value")

    app = create_app(test_settings, analysis_service=Broken())
    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/v1/analyses", json=load_example("request_analysis.json")
    )
    _assert_error(response, 500, "INTERNAL_ERROR")
    assert "secret" not in response.text


def test_dev_stub_flow_is_marked_and_bounded(stub_client: TestClient) -> None:
    response = stub_client.post("/api/v1/analyses", json=load_example("request_analysis.json"))
    assert response.status_code == 201
    analysis = AnalysisResponse.model_validate(response.json())
    assert analysis.source_mode == "fixture"
    assert analysis.warnings[0].startswith("DEV STUB")

    diagnosis = stub_client.post(
        f"/api/v1/analyses/{analysis.analysis_id}/diagnoses",
        json=load_example("request_diagnosis.json"),
    )
    assert diagnosis.status_code == 200
    body = DiagnosisResponse.model_validate(diagnosis.json())
    assert body.analysis_id == analysis.analysis_id


def test_dev_stub_rejects_unknown_repository(stub_client: TestClient) -> None:
    payload = {
        "repo_url": "https://github.com/someone/real",
        "target": {"os": "linux", "shell": "bash"},
    }
    _assert_error(stub_client.post("/api/v1/analyses", json=payload), 404, "REPOSITORY_NOT_FOUND")


def test_dev_stub_unknown_analysis_id(stub_client: TestClient) -> None:
    response = stub_client.post(
        "/api/v1/analyses/4f1c2b8e-7d3a-4e5f-9a6b-1c2d3e4f5a6b/diagnoses", json={"log": "boom"}
    )
    _assert_error(response, 404, "ANALYSIS_NOT_FOUND")


def test_dev_stubs_forbidden_in_production() -> None:
    with pytest.raises(ValueError, match="USE_DEV_STUBS"):
        Settings(_env_file=None, app_env="production", use_dev_stubs=True)


def test_settings_reject_non_positive_limits() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, store_max_items=0)


def test_openapi_is_reproducible_and_complete() -> None:
    first, second = render_openapi(), render_openapi()
    assert first == second
    schema = json.loads(first)
    paths = schema["paths"]
    assert {
        "/api/v1/health",
        "/api/v1/analyses",
        "/api/v1/analyses/{analysis_id}/diagnoses",
    } <= set(paths)
    created = paths["/api/v1/analyses"]["post"]["responses"]
    assert "201" in created and "422" in created
    assert created["422"]["content"]["application/json"]["schema"]["$ref"].endswith("ErrorResponse")
    assert "HTTPValidationError" not in schema["components"]["schemas"]


def test_committed_openapi_is_up_to_date() -> None:
    from repodoctor.export_openapi import DEFAULT_OUTPUT

    assert DEFAULT_OUTPUT.read_text(encoding="utf-8") == render_openapi(), (
        "contracts/openapi.json is stale: run `uv run python -m repodoctor.export_openapi`"
    )
