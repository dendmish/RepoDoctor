"""A3 acceptance uses create_app defaults, real fixture/scanner/rules and SDK transport."""

from __future__ import annotations

import builtins
import json
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient

from repodoctor.config import Settings
from repodoctor.contracts.api import AnalysisResponse, DiagnosisResponse, parse_utc
from repodoctor.intelligence.provider import ModelPlanOutput, OpenAIProvider
from repodoctor.intelligence.service import IntelligenceServiceImpl
from repodoctor.main import create_app
from repodoctor.repository.github import GitHubRepositorySource
from repodoctor.repository.source import FixtureRepositorySource
from repodoctor.scanners.analyzer import RepositoryAnalyzer
from repodoctor.services.store import MemoryAnalysisStore
from tests.intelligence.test_ai import install_transport, wire_response

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "repositories"
ENTRIES = json.loads((FIXTURES / "index.json").read_text(encoding="utf-8"))["repositories"]


def config(**kwargs):
    return Settings(
        _env_file=None,
        app_env="production",
        openai_api_key=None,
        openai_model=None,
        github_token=None,
        **kwargs,
    )


def request_for(name="python-cli-demo", *, os="linux", shell="bash", use_ai=False):
    return {
        "repo_url": f"https://github.com/repodoctor-fixtures/{name}",
        "target": {"os": os, "shell": shell},
        "use_ai": use_ai,
    }


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda entry: entry["id"])
@pytest.mark.parametrize(
    ("os", "shell"), [("windows", "powershell"), ("linux", "bash"), ("macos", "zsh")]
)
def test_default_production_fixture_analysis_and_diagnosis(entry, os, shell, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Fixture mode must not send network requests")

    monkeypatch.setattr("httpx.AsyncHTTPTransport.handle_async_request", forbidden)
    app = create_app(config())
    assert isinstance(app.state.ports.source, FixtureRepositorySource)
    assert isinstance(app.state.ports.analyzer, RepositoryAnalyzer)
    assert isinstance(app.state.ports.intelligence, IntelligenceServiceImpl)
    with TestClient(app) as client:
        result = client.post("/api/v1/analyses", json=request_for(entry["id"], os=os, shell=shell))
        assert result.status_code == 201
        analysis = AnalysisResponse.model_validate(result.json())
        assert analysis.schema_version == "1.0"
        assert UUID(analysis.analysis_id).version == 4
        assert analysis.repository.url == entry["url"]
        assert analysis.source_mode == "fixture"
        assert analysis.generation.reason == "disabled_by_user"
        assert parse_utc(analysis.expires_at) > parse_utc(analysis.created_at)
        assert analysis.coverage.files_read > 0
        assert all(
            command.shell == shell and command.requires_review
            for step in analysis.run_plan.steps
            for command in step.commands
        )
        assert not any("DEV STUB" in warning for warning in analysis.warnings)
        if entry["id"] == "python-cli-demo":
            assert "requests" in {dep.name for dep in analysis.facts.dependencies}
            assert "ENV_CONFIGURATION_REQUIRED" in {
                finding.rule_id for finding in analysis.findings
            }
        if not analysis.facts.entrypoints:
            assert analysis.run_plan.status == "needs_input"
            assert analysis.run_plan.questions
        store = app.state.ports.store
        before = store.get(analysis.analysis_id).model_dump_json()
        result = client.post(
            f"/api/v1/analyses/{analysis.analysis_id}/diagnoses",
            json={
                "log": "TOKEN=ghp_abcdefghijklmnopqrstuvwxyz012345\nEADDRINUSE",
                "command": "npm start" if analysis.facts.stack == "node" else "python -m demo_cli",
                "use_ai": False,
            },
        )
        assert result.status_code == 200
        diagnosis = DiagnosisResponse.model_validate(result.json())
        assert diagnosis.schema_version == "1.0"
        assert UUID(diagnosis.diagnosis_id).version == 4
        assert diagnosis.analysis_id == analysis.analysis_id
        assert diagnosis.generation.reason == "disabled_by_user"
        assert diagnosis.causes[0].id == "cause_port"
        assert any(ev.id == "log_2" for ev in diagnosis.evidence)
        assert "abcdefghijklmnopqrstuvwxyz" not in result.text
        assert store.get(analysis.analysis_id).model_dump_json() == before


def test_default_production_never_imports_dev_stubs(monkeypatch):
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == "repodoctor.services.stubs":
            raise AssertionError("Production must not import stubs")
        return original(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", guarded)
    with TestClient(create_app(config())) as client:
        assert client.post("/api/v1/analyses", json=request_for()).status_code == 201


def test_default_api_invalid_unknown_ref_and_expired_analysis():
    now = [0.0]
    store = MemoryAnalysisStore(10, 2, monotonic=lambda: now[0])
    with TestClient(create_app(config(), store=store)) as client:
        for patch, code in [
            ({"repo_url": "http://127.0.0.1/private"}, "INVALID_INPUT"),
            ({"repo_url": "https://github.com/not-in/fixture-index"}, "REPOSITORY_NOT_FOUND"),
            ({"ref": "not-in-fixture"}, "REF_NOT_FOUND"),
        ]:
            result = client.post("/api/v1/analyses", json={**request_for(), **patch})
            assert result.json()["error"]["code"] == code
        result = client.post("/api/v1/analyses", json=request_for())
        analysis_id = result.json()["analysis_id"]
        now[0] += 11
        result = client.post(
            f"/api/v1/analyses/{analysis_id}/diagnoses", json={"log": "EADDRINUSE", "use_ai": False}
        )
        assert result.status_code == 404
        assert result.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


@pytest.mark.parametrize(
    ("status", "code"),
    [(404, "REPOSITORY_NOT_FOUND"), (500, "GITHUB_UNAVAILABLE"), (403, "GITHUB_RATE_LIMITED")],
)
def test_live_source_failure_never_substitutes_fixture_and_closes_client(monkeypatch, status, code):
    requests = []
    clients = []

    def handler(request):
        requests.append(request)
        assert request.url.host == "api.github.com"
        headers = {"x-ratelimit-remaining": "0", "retry-after": "5"} if status == 403 else {}
        return httpx.Response(
            status, json={"message": "synthetic upstream failure"}, headers=headers
        )

    def factory(settings):
        client = httpx.AsyncClient(
            base_url="https://api.github.com", transport=httpx.MockTransport(handler)
        )
        clients.append(client)
        return client

    monkeypatch.setattr("repodoctor.main.create_github_client", factory)
    app = create_app(config(repository_mode="live"))
    with TestClient(app) as client:
        assert isinstance(app.state.ports.source, GitHubRepositorySource)
        assert app.state.ports.source.client is app.state.github_client
        # This URL is in fixture index: a hidden source substitution would wrongly succeed.
        result = client.post("/api/v1/analyses", json=request_for())
        assert result.status_code >= 400
        assert result.json()["error"]["code"] == code
        assert len(app.state.ports.store) == 0
    assert requests
    assert clients[0].is_closed
    assert app.state.github_client is None
    assert app.state.ports.source is None


@pytest.mark.parametrize(("key", "model"), [(None, None), ("synthetic-key", None), (None, "model")])
def test_incomplete_ai_config_does_not_construct_provider(monkeypatch, key, model):
    def forbidden(*args, **kwargs):
        raise AssertionError("Incomplete credentials must not construct provider")

    monkeypatch.setattr("repodoctor.main.OpenAIProvider", forbidden)
    settings = Settings(_env_file=None, app_env="test", openai_api_key=key, openai_model=model)
    with TestClient(create_app(settings)) as client:
        result = client.post("/api/v1/analyses", json=request_for(use_ai=True))
        assert result.status_code == 201
        assert result.json()["generation"]["reason"] == "ai_not_configured"


def test_configured_provider_and_both_http_ai_operations(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        body = json.loads(request.content)
        payload = json.loads(body["input"])
        if "repo_context" not in payload:
            output = ModelPlanOutput.model_validate(
                {"run_plan": payload["baseline_plan"], "additional_findings": []}
            ).model_dump_json()
        else:
            output = json.dumps(
                {
                    "summary": "Вероятно, порт занят; проверьте настройки проекта.",
                    "causes": [
                        {
                            "title": "Порт занят",
                            "explanation": "Сигнатура EADDRINUSE в обработанном логе.",
                            "confidence": "medium",
                            "evidence_ids": [payload["log"]["lines"][0]["evidence_id"]],
                            "fixes": [],
                            "verification": "Сравните новый лог после проверки порта.",
                        }
                    ],
                    "questions": [],
                }
            )
        return httpx.Response(200, json=wire_response(output))

    clients = install_transport(monkeypatch, handler)
    settings = Settings(
        _env_file=None,
        app_env="production",
        openai_api_key="synthetic-test-key",
        openai_model="configured-model",
    )
    app = create_app(settings)
    assert isinstance(app.state.ports.intelligence.provider, OpenAIProvider)
    with TestClient(app) as client:
        result = client.post("/api/v1/analyses", json=request_for("node-api-demo", use_ai=True))
        assert result.status_code == 201
        analysis = AnalysisResponse.model_validate(result.json())
        assert analysis.generation.mode == "ai"
        result = client.post(
            f"/api/v1/analyses/{analysis.analysis_id}/diagnoses",
            json={"log": "EADDRINUSE", "use_ai": True},
        )
        assert result.status_code == 200
        diagnosis = DiagnosisResponse.model_validate(result.json())
        assert diagnosis.generation.mode == "ai"
        assert diagnosis.causes[0].origin == "ai"
        # Same configured provider, user-disabled operation does not make another request.
        assert client.post("/api/v1/analyses", json=request_for(use_ai=False)).status_code == 201
    assert len(requests) == 2
    assert all(client.is_closed() for client in clients)


def test_live_success_uses_real_source_scanner_and_rules_on_mock_transport(monkeypatch):
    from tests.repository.test_github import COMMIT, GitHubFixture

    upstream = GitHubFixture()

    def factory(settings):
        return httpx.AsyncClient(
            base_url="https://api.github.com", transport=httpx.MockTransport(upstream.handle)
        )

    monkeypatch.setattr("repodoctor.main.create_github_client", factory)
    with TestClient(create_app(config(repository_mode="live"))) as client:
        result = client.post(
            "/api/v1/analyses",
            json={**request_for(), "repo_url": "https://github.com/example/demo"},
        )
        assert result.status_code == 201
        analysis = AnalysisResponse.model_validate(result.json())
        assert analysis.source_mode == "github"
        assert analysis.repository.resolved_commit == COMMIT
        assert "requests" in {dep.name for dep in analysis.facts.dependencies}
        assert analysis.generation.mode == "fallback"
        assert upstream.calls
        result = client.post(
            f"/api/v1/analyses/{analysis.analysis_id}/diagnoses",
            json={"log": "ModuleNotFoundError: No module named 'requests'", "use_ai": False},
        )
        assert result.status_code == 200
        diagnosis = DiagnosisResponse.model_validate(result.json())
        assert diagnosis.causes[0].id == "cause_module"
        assert all(ev.url is None or COMMIT in ev.url for ev in diagnosis.evidence)


def test_live_startup_failure_closes_client_and_clears_state(monkeypatch):
    clients = []

    def factory(settings):
        client = httpx.AsyncClient()
        clients.append(client)
        return client

    def broken(*args, **kwargs):
        raise RuntimeError("synthetic startup failure")

    monkeypatch.setattr("repodoctor.main.create_github_client", factory)
    monkeypatch.setattr("repodoctor.main.create_repository_source", broken)
    app = create_app(config(repository_mode="live"))
    with pytest.raises(RuntimeError, match="synthetic startup failure"), TestClient(app):
        pass
    assert clients[0].is_closed
    assert app.state.github_client is None
    assert app.state.ports.source is None


def test_explicit_source_wins_over_live_default(monkeypatch):
    source = FixtureRepositorySource()
    app = create_app(config(repository_mode="live"), source=source)
    with TestClient(app) as client:
        assert app.state.ports.source is source
        result = client.post("/api/v1/analyses", json=request_for())
        assert result.status_code == 201
        assert result.json()["source_mode"] == "fixture"


def test_schema_export_does_not_construct_pipeline_or_clients(monkeypatch):
    from repodoctor.export_openapi import render_openapi

    def forbidden(*args, **kwargs):
        raise AssertionError("Schema export must be independent of runtime resources")

    monkeypatch.setattr("repodoctor.main.create_repository_source", forbidden)
    monkeypatch.setattr("repodoctor.main.OpenAIProvider", forbidden)
    monkeypatch.setattr("repodoctor.main.create_github_client", forbidden)
    assert "/api/v1/analyses" in json.loads(render_openapi())["paths"]
