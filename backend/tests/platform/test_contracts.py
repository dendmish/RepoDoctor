from __future__ import annotations

import copy

import pytest
from pydantic import BaseModel, ValidationError

from repodoctor.contracts.api import (
    AnalysisRequest,
    AnalysisResponse,
    DiagnosisRequest,
    DiagnosisResponse,
    ErrorResponse,
    Evidence,
    Shell,
    TargetEnvironment,
    TargetOS,
    format_utc,
)
from repodoctor.contracts.domain import AnalysisContext, StaticAnalysis

from .conftest import EXAMPLES_DIR, load_example

MODEL_BY_PREFIX: dict[str, type[BaseModel]] = {
    "analysis_": AnalysisResponse,
    "diagnosis_": DiagnosisResponse,
    "error_": ErrorResponse,
    "request_analysis": AnalysisRequest,
    "request_diagnosis": DiagnosisRequest,
}


def _model_for(name: str) -> type[BaseModel]:
    for prefix, model in MODEL_BY_PREFIX.items():
        if name.startswith(prefix):
            return model
    raise AssertionError(f"example {name} has no DTO mapping")


ALL_EXAMPLES = sorted(path.name for path in EXAMPLES_DIR.glob("*.json"))


@pytest.mark.parametrize("name", ALL_EXAMPLES)
def test_every_example_validates_against_its_dto(name: str) -> None:
    _model_for(name).model_validate(load_example(name))


def test_required_example_set_is_present() -> None:
    required = {
        "analysis_python.json",
        "analysis_node.json",
        "analysis_needs_input.json",
        "diagnosis_python.json",
        "diagnosis_unknown.json",
        "error_invalid_input.json",
        "request_analysis.json",
        "request_diagnosis.json",
    }
    assert required <= set(ALL_EXAMPLES)


def test_examples_cover_modes_and_statuses() -> None:
    python = AnalysisResponse.model_validate(load_example("analysis_python.json"))
    node = AnalysisResponse.model_validate(load_example("analysis_node.json"))
    needs = AnalysisResponse.model_validate(load_example("analysis_needs_input.json"))
    assert python.generation.mode == "ai" and node.generation.mode == "fallback"
    assert needs.run_plan.status == "needs_input" and needs.coverage.status == "partial"
    assert {python.facts.stack, node.facts.stack} == {"python", "node"}
    assert {python.target.shell, node.target.shell, needs.target.shell} == set(Shell)


def test_diagnosis_examples_reference_their_analyses() -> None:
    python = load_example("analysis_python.json")
    diagnosis = load_example("diagnosis_python.json")
    assert diagnosis["analysis_id"] == python["analysis_id"]
    repo_evidence = {item["id"]: item for item in python["evidence"]}
    for item in diagnosis["evidence"]:
        if item["source"] != "log":
            assert repo_evidence[item["id"]] == item, "repo evidence must keep ID and content"
    unknown = load_example("diagnosis_unknown.json")
    assert unknown["analysis_id"] == load_example("analysis_node.json")["analysis_id"]


def test_example_diagnosis_log_line_matches_request() -> None:
    log_lines = load_example("request_diagnosis.json")["log"].split("\n")
    log_evidence = next(
        item
        for item in load_example("diagnosis_python.json")["evidence"]
        if item["source"] == "log"
    )
    assert log_lines[log_evidence["line_start"] - 1] == log_evidence["excerpt"]


def test_examples_are_marked_synthetic() -> None:
    for name in ALL_EXAMPLES:
        if name.startswith(("analysis_", "diagnosis_")):
            data = load_example(name)
            assert any("Синтетический" in warning for warning in data["warnings"]), name
            if name.startswith("analysis_"):
                assert data["source_mode"] == "fixture"
                assert data["repository"]["owner"] == "repodoctor-fixtures"


@pytest.mark.parametrize(
    ("os_name", "shell"),
    [(o, s) for o in TargetOS for s in Shell],
)
def test_only_three_target_pairs_are_allowed(os_name: TargetOS, shell: Shell) -> None:
    allowed = {("windows", "powershell"), ("linux", "bash"), ("macos", "zsh")}
    if (os_name.value, shell.value) in allowed:
        TargetEnvironment(os=os_name, shell=shell)
    else:
        with pytest.raises(ValidationError):
            TargetEnvironment(os=os_name, shell=shell)


def test_extra_fields_are_rejected() -> None:
    data = load_example("request_analysis.json")
    data["unexpected"] = 1
    with pytest.raises(ValidationError):
        AnalysisRequest.model_validate(data)
    nested = load_example("analysis_python.json")
    nested["repository"]["stars"] = 5
    with pytest.raises(ValidationError):
        AnalysisResponse.model_validate(nested)


def test_request_defaults_and_ref_normalization() -> None:
    request = AnalysisRequest.model_validate(
        {
            "repo_url": "https://github.com/a/b",
            "ref": "   ",
            "target": {"os": "linux", "shell": "bash"},
        }
    )
    assert request.ref is None and request.use_ai is True
    with pytest.raises(ValidationError):
        AnalysisRequest.model_validate(
            {
                "repo_url": "https://github.com/a/b",
                "ref": "main\nx",
                "target": {"os": "linux", "shell": "bash"},
            }
        )
    with pytest.raises(ValidationError):
        AnalysisRequest.model_validate(
            {"repo_url": "x" * 2049, "target": {"os": "linux", "shell": "bash"}}
        )


@pytest.mark.parametrize("log", ["", "   \n\t", "x" * 30_001])
def test_diagnosis_request_rejects_bad_logs(log: str) -> None:
    with pytest.raises(ValidationError):
        DiagnosisRequest(log=log)


def test_diagnosis_request_limits() -> None:
    assert DiagnosisRequest(log="error", command="  ").command is None
    with pytest.raises(ValidationError):
        DiagnosisRequest(log="error", command="x" * 2001)


def test_dangling_evidence_reference_is_rejected() -> None:
    data = load_example("analysis_python.json")
    data["findings"][0]["evidence_ids"].append("ev_missing")
    with pytest.raises(ValidationError, match="ev_missing"):
        AnalysisResponse.model_validate(data)


def test_duplicate_evidence_id_is_rejected() -> None:
    data = load_example("analysis_python.json")
    data["evidence"].append(copy.deepcopy(data["evidence"][0]))
    with pytest.raises(ValidationError, match="duplicate"):
        AnalysisResponse.model_validate(data)


def test_command_shell_must_match_target() -> None:
    data = load_example("analysis_python.json")
    data["run_plan"]["steps"][0]["commands"][0]["shell"] = "bash"
    with pytest.raises(ValidationError, match="shell"):
        AnalysisResponse.model_validate(data)


def test_needs_input_requires_questions() -> None:
    data = load_example("analysis_needs_input.json")
    data["run_plan"]["questions"] = []
    with pytest.raises(ValidationError):
        AnalysisResponse.model_validate(data)


@pytest.mark.parametrize(
    "evidence",
    [
        {"id": "e", "source": "file", "path": "a.txt", "line_start": None, "line_end": None},
        {"id": "e", "source": "tree", "path": "a.txt", "line_start": 1, "line_end": 1},
        {"id": "log_1", "source": "log", "path": "a.txt", "line_start": 1, "line_end": 1},
        {"id": "e", "source": "log", "path": None, "line_start": 1, "line_end": 1},
        {"id": "e", "source": "file", "path": "/etc/passwd", "line_start": 1, "line_end": 1},
        {"id": "e", "source": "file", "path": "a/../b", "line_start": 1, "line_end": 1},
        {"id": "e", "source": "file", "path": "a.txt", "line_start": 3, "line_end": 2},
    ],
)
def test_invalid_evidence_shapes(evidence: dict) -> None:
    payload = {"excerpt": "x", "url": None, **evidence}
    with pytest.raises(ValidationError):
        Evidence.model_validate(payload)


def test_evidence_url_must_be_github() -> None:
    with pytest.raises(ValidationError):
        Evidence(
            id="e",
            source="tree",
            path="a",
            line_start=None,
            line_end=None,
            excerpt="x",
            url="https://evil.example/a",
        )


def test_invalid_uuid_and_timestamp_are_rejected() -> None:
    data = load_example("analysis_python.json")
    bad_id = {**data, "analysis_id": "not-a-uuid"}
    with pytest.raises(ValidationError):
        AnalysisResponse.model_validate(bad_id)
    bad_time = {**data, "created_at": "2026-10-25 12:00:00"}
    with pytest.raises(ValidationError):
        AnalysisResponse.model_validate(bad_time)


def test_format_utc_produces_contract_timestamp() -> None:
    from datetime import UTC, datetime, timedelta, timezone

    moment = datetime(2026, 10, 25, 15, 0, tzinfo=timezone(timedelta(hours=3)))
    assert format_utc(moment) == "2026-10-25T12:00:00Z"
    assert format_utc(datetime(2026, 1, 1, tzinfo=UTC)).endswith("Z")


def test_domain_context_round_trip() -> None:
    response = AnalysisResponse.model_validate(load_example("analysis_python.json"))
    scan = StaticAnalysis(
        repository=response.repository,
        source_mode=response.source_mode,
        facts=response.facts,
        findings=response.findings,
        evidence=response.evidence,
        coverage=response.coverage,
        selected_files=[],
    )
    context = AnalysisContext(response=response, scan=scan)
    assert AnalysisContext.model_validate_json(context.model_dump_json()) == context
