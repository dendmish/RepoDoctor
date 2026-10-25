"""API-level tests of the A2 shell with Protocol fakes (no live network)."""

from __future__ import annotations

import asyncio
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from repodoctor.config import Settings
from repodoctor.contracts.api import AnalysisResponse, DiagnosisResponse
from repodoctor.main import create_app
from repodoctor.services.analysis import CONTEXT_TRIM_NOTE
from repodoctor.services.store import MemoryAnalysisStore

from .conftest import load_example
from .fakes import FakeAnalyzer, FakeIntelligence, FakeSource, make_files

SECRET = "ghp_abcdefghijklmnopqrstuvwxyz012345"


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def parts(test_settings: Settings):
    source, intelligence = FakeSource(), FakeIntelligence()
    clock = Clock()
    store = MemoryAnalysisStore(
        test_settings.store_ttl_seconds, test_settings.store_max_items, monotonic=clock
    )
    return {
        "source": source,
        "analyzer": FakeAnalyzer(),
        "intelligence": intelligence,
        "store": store,
        "clock": clock,
    }


def build(settings: Settings, parts: dict, **overrides) -> TestClient:
    settings = settings.model_copy(update=overrides)
    app = create_app(
        settings,
        source=parts["source"],
        analyzer=parts["analyzer"],
        intelligence=parts["intelligence"],
        store=parts["store"],
    )
    return TestClient(app, raise_server_exceptions=False)


def analyze(client: TestClient, **changes) -> httpx.Response:
    return client.post(
        "/api/v1/analyses", json={**load_example("request_analysis.json"), **changes}
    )


def diagnose(client: TestClient, analysis_id: str, **changes) -> httpx.Response:
    body = {**load_example("request_diagnosis.json"), **changes}
    return client.post(f"/api/v1/analyses/{analysis_id}/diagnoses", json=body)


def test_successful_analysis_and_diagnosis(test_settings: Settings, parts: dict) -> None:
    client = build(test_settings, parts)
    response = analyze(client)
    assert response.status_code == 201
    analysis = AnalysisResponse.model_validate(response.json())
    assert analysis.schema_version == "1.0"
    assert response.headers["x-request-id"]
    # static finding kept once, AI finding appended, evidence deduplicated by ID
    ids = [f.id for f in analysis.findings]
    assert ids == ["ENV_CONFIGURATION_REQUIRED:.env.example", "AI_NOTE:."]
    assert len({e.id for e in analysis.evidence}) == len(analysis.evidence)
    assert parts["store"].get(analysis.analysis_id) is not None

    diag = diagnose(client, analysis.analysis_id)
    assert diag.status_code == 200
    body = DiagnosisResponse.model_validate(diag.json())
    assert body.analysis_id == analysis.analysis_id
    assert body.generation.mode == "ai"


def test_use_ai_false_passes_fallback_through(test_settings: Settings, parts: dict) -> None:
    client = build(test_settings, parts)
    analysis = analyze(client, use_ai=False).json()
    assert analysis["generation"] == {
        "mode": "fallback",
        "reason": "disabled_by_user",
        "model": None,
        "prompt_version": "fallback-v1",
    }
    diag = diagnose(client, analysis["analysis_id"], use_ai=False).json()
    assert diag["generation"]["mode"] == "fallback"


def test_expires_at_matches_ttl(test_settings: Settings, parts: dict) -> None:
    analysis = analyze(build(test_settings, parts)).json()
    from repodoctor.contracts.api import parse_utc

    delta = parse_utc(analysis["expires_at"]) - parse_utc(analysis["created_at"])
    assert delta.total_seconds() == test_settings.store_ttl_seconds


def test_unknown_analysis_id(test_settings: Settings, parts: dict) -> None:
    client = build(test_settings, parts)
    response = diagnose(client, "4f1c2b8e-7d3a-4e5f-9a6b-1c2d3e4f5a6b")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


def test_expired_analysis_is_not_found(test_settings: Settings, parts: dict) -> None:
    client = build(test_settings, parts)
    analysis_id = analyze(client).json()["analysis_id"]
    parts["clock"].now += test_settings.store_ttl_seconds
    response = diagnose(client, analysis_id)
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


def test_evicted_analysis_is_not_found(test_settings: Settings, parts: dict) -> None:
    parts["store"] = MemoryAnalysisStore(100, 1)
    client = build(test_settings, parts)
    first = analyze(client).json()["analysis_id"]
    analyze(client)
    assert diagnose(client, first).json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


def test_whitespace_log_is_invalid(test_settings: Settings, parts: dict) -> None:
    client = build(test_settings, parts)
    analysis_id = analyze(client).json()["analysis_id"]
    response = diagnose(client, analysis_id, log="   \n\t ")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_INPUT"
    assert parts["intelligence"].received_logs == []


def test_oversized_payload_is_413(test_settings: Settings, parts: dict) -> None:
    client = build(test_settings, parts)
    analysis_id = analyze(client).json()["analysis_id"]
    response = client.post(
        f"/api/v1/analyses/{analysis_id}/diagnoses",
        content=b'{"log": "' + b"a" * (130 * 1024) + b'"}',
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


def test_oversized_chunked_payload_is_413(test_settings: Settings, parts: dict) -> None:
    client = build(test_settings, parts)

    def chunks():
        yield b'{"repo_url": "'
        for _ in range(20):
            yield b"a" * 8192
        yield b'"}'

    response = client.post(
        "/api/v1/analyses", content=chunks(), headers={"content-type": "application/json"}
    )
    assert response.status_code == 413
    assert parts["source"].calls == 0


def test_log_is_redacted_before_intelligence_and_never_stored(
    test_settings: Settings, parts: dict, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    client = build(test_settings, parts)
    analysis_id = analyze(client).json()["analysis_id"]
    raw_log = f"\x1b[31mError\x1b[0m\r\nGITHUB_TOKEN={SECRET}\r\nModuleNotFoundError: x"
    response = diagnose(client, analysis_id, log=raw_log, command=f"run --token {SECRET}")
    assert response.status_code == 200
    received = parts["intelligence"].received_logs[-1]
    assert SECRET not in received.text and "\x1b" not in received.text
    assert received.text.count("\n") == 2 and received.redactions_count == 1
    assert SECRET not in (parts["intelligence"].received_commands[-1] or "")
    assert any("замаскировано" in w for w in response.json()["warnings"])
    stored = parts["store"].get(analysis_id)
    assert (
        SECRET not in stored.model_dump_json()
        and "ModuleNotFoundError" not in stored.model_dump_json()
    )
    assert SECRET not in caplog.text and "ModuleNotFoundError" not in caplog.text


async def test_concurrency_cap_returns_server_busy(test_settings: Settings, parts: dict) -> None:
    settings = test_settings.model_copy(update={"max_concurrent_operations": 1})
    app = create_app(
        settings,
        source=parts["source"],
        analyzer=parts["analyzer"],
        intelligence=parts["intelligence"],
        store=parts["store"],
    )
    parts["source"].gate = asyncio.Event()
    body = load_example("request_analysis.json")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = asyncio.create_task(client.post("/api/v1/analyses", json=body))
        await parts["source"].started.wait()
        busy = await client.post("/api/v1/analyses", json=body)
        assert busy.status_code == 429
        assert busy.json()["error"] == {
            **busy.json()["error"],
            "code": "SERVER_BUSY",
            "retryable": True,
        }
        parts["source"].gate.set()
        assert (await first).status_code == 201
        assert (await client.post("/api/v1/analyses", json=body)).status_code == 201
    assert app.state.limiter.active == 0


async def test_analysis_and_diagnosis_share_the_limit(test_settings: Settings, parts: dict) -> None:
    settings = test_settings.model_copy(update={"max_concurrent_operations": 1})
    app = create_app(
        settings,
        source=parts["source"],
        analyzer=parts["analyzer"],
        intelligence=parts["intelligence"],
        store=parts["store"],
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        analysis_id = (
            await client.post("/api/v1/analyses", json=load_example("request_analysis.json"))
        ).json()["analysis_id"]
        parts["source"].gate = asyncio.Event()
        parts["source"].started.clear()
        pending = asyncio.create_task(
            client.post("/api/v1/analyses", json=load_example("request_analysis.json"))
        )
        await parts["source"].started.wait()
        busy = await client.post(f"/api/v1/analyses/{analysis_id}/diagnoses", json={"log": "boom"})
        assert busy.json()["error"]["code"] == "SERVER_BUSY"
        parts["source"].gate.set()
        await pending


def test_analysis_deadline_returns_504_and_frees_slot(test_settings: Settings, parts: dict) -> None:
    parts["source"].delay = 1.0
    client = build(test_settings, parts, analysis_timeout_seconds=0.05)
    response = analyze(client)
    assert response.status_code == 504
    assert response.json()["error"] == {
        **response.json()["error"],
        "code": "ANALYSIS_TIMEOUT",
        "retryable": True,
    }
    assert client.app.state.limiter.active == 0


def test_diagnosis_deadline_returns_504(test_settings: Settings, parts: dict) -> None:
    client = build(test_settings, parts, diagnosis_timeout_seconds=0.05)
    analysis_id = analyze(client).json()["analysis_id"]
    parts["intelligence"].diagnose_delay = 1.0
    response = diagnose(client, analysis_id)
    assert response.status_code == 504
    assert client.app.state.limiter.active == 0


async def test_client_cancellation_releases_slot(test_settings: Settings, parts: dict) -> None:
    app = create_app(
        test_settings,
        source=parts["source"],
        analyzer=parts["analyzer"],
        intelligence=parts["intelligence"],
        store=parts["store"],
    )
    parts["source"].gate = asyncio.Event()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        task = asyncio.create_task(
            client.post("/api/v1/analyses", json=load_example("request_analysis.json"))
        )
        await parts["source"].started.wait()
        assert app.state.limiter.active == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert app.state.limiter.active == 0


def test_large_context_is_trimmed_consistently(test_settings: Settings, parts: dict) -> None:
    parts["source"].files = make_files(count=12, size=60 * 1024)
    client = build(test_settings, parts)
    response = analyze(client)
    assert response.status_code == 201
    body = response.json()
    assert CONTEXT_TRIM_NOTE in body["warnings"]
    assert CONTEXT_TRIM_NOTE in body["coverage"]["limitations"]
    stored = parts["store"].get(body["analysis_id"])
    assert stored.response.model_dump(mode="json") == body
    assert len(stored.scan.selected_files) < 12
    assert stored.scan.coverage == stored.response.coverage


def test_invalid_plan_from_module_is_safe_500(test_settings: Settings, parts: dict) -> None:
    original = parts["intelligence"].build_plan

    async def broken(scan, target, use_ai):
        plan = await original(scan, target, use_ai)
        step = plan.run_plan.steps[0].model_copy(update={"evidence_ids": ["ev_ghost"]})
        run_plan = plan.run_plan.model_copy(update={"steps": [step]})
        return plan.model_copy(update={"run_plan": run_plan})

    parts["intelligence"].build_plan = broken
    response = analyze(build(test_settings, parts))
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "ev_ghost" not in response.text
    assert len(parts["store"]) == 0


def test_dev_cors_only_in_development(test_settings: Settings, parts: dict) -> None:
    dev = build(test_settings, parts, app_env="development")
    origin = {"Origin": "http://localhost:5173"}
    assert dev.get("/api/v1/health", headers=origin).headers.get("access-control-allow-origin")
    evil = dev.get("/api/v1/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in evil.headers
    test_env = build(test_settings, parts)
    assert (
        "access-control-allow-origin" not in test_env.get("/api/v1/health", headers=origin).headers
    )


def test_lifespan_creates_and_closes_github_client(test_settings: Settings, parts: dict) -> None:
    app = create_app(test_settings)
    with TestClient(app):
        client = app.state.github_client
        assert isinstance(client, httpx.AsyncClient)
        assert str(client.base_url) == "https://api.github.com"
        assert client.follow_redirects is False
    assert client.is_closed and app.state.github_client is None
