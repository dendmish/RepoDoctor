from __future__ import annotations

from pathlib import Path

import pytest

from repodoctor.contracts.api import check_evidence_registry, collect_evidence_refs
from repodoctor.contracts.domain import DiagnosisResult, PlanResult
from tests.intelligence.conftest import scan_from_example

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures" / "intelligence"


@pytest.mark.parametrize(
    ("filename", "input_name", "status", "shell"),
    [
        ("plan_node.json", "analysis_node.json", "actionable", "bash"),
        ("plan_python_needs_input.json", "analysis_python.json", "needs_input", "powershell"),
        ("plan_unknown.json", "analysis_needs_input.json", "needs_input", "zsh"),
    ],
)
def test_handoff_examples_have_honest_mode_and_existing_evidence(
    filename, input_name, status, shell
):
    result = PlanResult.model_validate_json((FIXTURES / filename).read_text(encoding="utf-8"))
    scan = scan_from_example(input_name)
    assert result.generation.mode == "fallback"
    assert result.generation.reason == "disabled_by_user"
    assert result.generation.model is None
    assert result.run_plan.status == status
    assert {ev.id for ev in result.evidence} <= {ev.id for ev in scan.evidence}
    check_evidence_registry(result.evidence, collect_evidence_refs(result.run_plan))
    assert all(
        c.shell == shell and c.requires_review for s in result.run_plan.steps for c in s.commands
    )


@pytest.mark.parametrize(
    ("filename", "mode", "reason"),
    [
        ("diagnosis_rules_module.json", "fallback", "disabled_by_user"),
        ("diagnosis_unknown.json", "fallback", "disabled_by_user"),
        ("diagnosis_ai_synthetic.json", "ai", None),
        ("diagnosis_ai_timeout.json", "fallback", "timeout"),
    ],
)
def test_diagnostic_examples_are_self_contained(filename, mode, reason):
    result = DiagnosisResult.model_validate_json((FIXTURES / filename).read_text(encoding="utf-8"))
    check_evidence_registry(result.evidence, collect_evidence_refs(result.causes))
    assert result.generation.mode == mode
    assert result.generation.reason == reason
    assert result.causes or result.questions
    if mode == "ai":
        assert result.generation.model == "synthetic-example-model"
        assert all(cause.origin == "ai" for cause in result.causes)
        assert any("live AI не вызывался" in warning for warning in result.warnings)


def test_ai_plan_example_is_explicitly_synthetic_and_grounded():
    result = PlanResult.model_validate_json(
        (FIXTURES / "plan_ai_synthetic.json").read_text(encoding="utf-8")
    )
    check_evidence_registry(
        result.evidence, collect_evidence_refs(result.run_plan, result.additional_findings)
    )
    assert result.generation.mode == "ai"
    assert result.generation.model == "synthetic-example-model"
    assert any("live AI не вызывался" in warning for warning in result.warnings)
