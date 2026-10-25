"""DI checks with the merged B2-B4 source/scanner and A2 services, without live I/O."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from repodoctor.config import Settings
from repodoctor.contracts.api import AnalysisResponse, DiagnosisResponse, TargetEnvironment
from repodoctor.contracts.domain import StaticAnalysis
from repodoctor.intelligence.provider import ModelPlanOutput
from repodoctor.intelligence.rules import build_fallback_plan
from repodoctor.intelligence.service import IntelligenceServiceImpl
from repodoctor.main import create_app
from repodoctor.repository.source import FixtureRepositorySource
from repodoctor.scanners.analyzer import RepositoryAnalyzer
from repodoctor.services.store import MemoryAnalysisStore
from tests.intelligence.fakes import FakeProvider

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "repositories"
REPOSITORIES = [
    item["id"]
    for item in json.loads((FIXTURES / "index.json").read_text(encoding="utf-8"))["repositories"]
]


@pytest.mark.parametrize("name", REPOSITORIES)
@pytest.mark.parametrize(
    ("os", "shell"), [("windows", "powershell"), ("linux", "bash"), ("macos", "zsh")]
)
async def test_b3_scans_accept_grounded_model_plans_all_shells(name, os, shell):
    scan = StaticAnalysis.model_validate_json(
        (FIXTURES / name / "scan.json").read_text(encoding="utf-8")
    )
    target = TargetEnvironment(os=os, shell=shell)
    output = ModelPlanOutput(run_plan=build_fallback_plan(scan, target), additional_findings=[])
    result = await IntelligenceServiceImpl(FakeProvider(output)).build_plan(scan, target, True)
    assert result.generation.mode == "ai"
    assert result.evidence == scan.evidence
    assert all(c.shell == shell for step in result.run_plan.steps for c in step.commands)


def test_a2_http_path_redacts_before_real_diagnosis_and_keeps_store_clean(caplog):
    settings = Settings(_env_file=None, app_env="test", openai_api_key=None, openai_model=None)
    store = MemoryAnalysisStore(1800, 5)
    app = create_app(
        settings,
        source=FixtureRepositorySource(),
        analyzer=RepositoryAnalyzer(),
        intelligence=IntelligenceServiceImpl(),
        store=store,
    )
    secret = "ghp_abcdefghijklmnopqrstuvwxyz012345"
    with caplog.at_level(logging.INFO), TestClient(app) as client:
        response = client.post(
            "/api/v1/analyses",
            json={
                "repo_url": "https://github.com/repodoctor-fixtures/python-cli-demo",
                "target": {"os": "windows", "shell": "powershell"},
                "use_ai": False,
            },
        )
        assert response.status_code == 201
        analysis = AnalysisResponse.model_validate(response.json())
        before = store.get(analysis.analysis_id).model_dump_json()
        response = client.post(
            f"/api/v1/analyses/{analysis.analysis_id}/diagnoses",
            json={
                "log": f"TOKEN={secret}\nModuleNotFoundError: No module named 'requests'",
                "command": "python -m demo_cli",
                "use_ai": False,
            },
        )
        assert response.status_code == 200
        diagnosis = DiagnosisResponse.model_validate(response.json())
    assert diagnosis.causes[0].id == "cause_module"
    assert secret not in diagnosis.model_dump_json()
    assert any("[REDACTED]" in ev.excerpt for ev in diagnosis.evidence)
    assert secret not in caplog.text
    assert "ModuleNotFoundError" not in caplog.text
    assert before == store.get(analysis.analysis_id).model_dump_json()
