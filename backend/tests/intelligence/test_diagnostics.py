from __future__ import annotations

import json

import httpx
import pytest

from repodoctor.contracts.api import AnalysisResponse, RuntimeHint, Shell, collect_evidence_refs
from repodoctor.contracts.domain import AnalysisContext, SanitizedLog
from repodoctor.intelligence.context import LOG_CONTEXT_LIMIT, REPO_CONTEXT_LIMIT, encode
from repodoctor.intelligence.diagnostics import prepare_log
from repodoctor.intelligence.provider import (
    ModelCauseOutput,
    ModelDiagnosisOutput,
    OpenAIProvider,
    ProviderError,
)
from repodoctor.intelligence.service import IntelligenceServiceImpl
from tests.intelligence.conftest import EXAMPLES
from tests.intelligence.fakes import FakeProvider
from tests.intelligence.test_ai import install_transport, settings, wire_response


@pytest.fixture
def context(python_scan):
    response = AnalysisResponse.model_validate_json(
        (EXAMPLES / "analysis_python.json").read_text(encoding="utf-8")
    )
    return AnalysisContext(scan=python_scan, response=response)


def log(text):
    return SanitizedLog(text=text, redactions_count=0, truncated=False)


@pytest.mark.parametrize(
    ("text", "cause_id"),
    [
        ("ModuleNotFoundError: No module named 'requests'", "cause_module"),
        ("FileNotFoundError: [Errno 2] No such file: 'data/train.csv'", "cause_file"),
        ("RuntimeError: Missing environment variable: API_KEY", "cause_env"),
        ("ERROR: Package requires a different Python: 3.9 not in >=3.12", "cause_python"),
        ("npm ERR! code EBADENGINE Unsupported engine", "cause_node"),
        ("OSError: [Errno 98] Address already in use", "cause_port"),
        ("RuntimeError: CUDA driver version is insufficient", "cause_cuda"),
        ("something error happened", None),
    ],
)
async def test_eight_diagnostic_classes(context, text, cause_id):
    fake = FakeProvider()
    result = await IntelligenceServiceImpl(fake).diagnose(context, log(text), None, False)
    assert result.generation.reason == "disabled_by_user"
    assert not fake.calls
    assert collect_evidence_refs(result.causes) <= {ev.id for ev in result.evidence}
    if cause_id:
        assert result.causes[0].id == cause_id
        assert result.causes[0].origin == "static"
        assert result.causes[0].confidence == "medium"
        assert "requirements.txt" in result.causes[0].explanation
        assert result.causes[0].verification
        assert result.causes[0].fixes
        assert result.causes[0].evidence_ids[0] == "log_1"
    else:
        assert not result.causes
        assert result.questions
    assert all(ev.path is None and ev.url is None for ev in result.evidence if ev.source == "log")


@pytest.mark.parametrize("package", ["requests", "sklearn", "local_package"])
async def test_missing_module_never_installs_import_name(context, package):
    result = await IntelligenceServiceImpl().diagnose(
        context,
        log(f"ModuleNotFoundError: No module named '{package}'"),
        None,
        False,
    )
    commands = [c.text for cause in result.causes for step in cause.fixes for c in step.commands]
    assert not any(f"pip install {package}" in command for command in commands)
    if package == "requests":
        assert "Одноимённая зависимость" in result.causes[0].explanation
    else:
        assert any(package in question for question in result.questions)
    assert any("sys.executable" in command for command in commands)


async def test_multiline_windows_traceback_redacted_placeholder_line_numbers(context):
    text = (
        "TOKEN=[REDACTED]\nTraceback (most recent call last):\n"
        '  File "C:\\work\\repo\\main.py", line 12, in main\n'
        "FileNotFoundError: C:\\datasets\\train.csv"
    )
    result = await IntelligenceServiceImpl().diagnose(context, log(text), None, False)
    cause = result.causes[0]
    assert "log_4" in cause.evidence_ids
    ev = next(ev for ev in result.evidence if ev.id == "log_4")
    assert ev.line_start == ev.line_end == 4
    assert "C:\\datasets\\train.csv" in ev.excerpt
    assert any("[REDACTED]" in ev.excerpt for ev in result.evidence)
    assert "пустой файл не заменяет dataset" in cause.fixes[0].description
    assert all(
        c.shell == context.response.target.shell for step in cause.fixes for c in step.commands
    )


def test_trim_preserves_error_traceback_head_tail_and_original_numbers():
    lines = ["noise " * 20 for _ in range(400)]
    lines[0] = "start"
    lines[200] = "Traceback (most recent call last):"
    lines[202] = "ModuleNotFoundError: No module named 'requests'"
    lines[-1] = "end"
    prepared = prepare_log(log("\n".join(lines)))
    assert prepared.truncated
    assert len(encode(prepared.payload)) <= LOG_CONTEXT_LIMIT
    evidence = {ev.id: ev for ev in prepared.evidence}
    assert evidence["log_1"].excerpt == "start"
    assert evidence["log_201"].excerpt.startswith("Traceback")
    assert evidence["log_203"].line_start == 203
    assert evidence["log_400"].excerpt == "end"
    assert len(prepared.evidence) < 400


def test_log_evidence_counts_sanitized_newlines_only():
    prepared = prepare_log(log("first\u0085same line\nEADDRINUSE\n"))
    assert prepared.payload["line_count"] == 3
    assert prepared.evidence[0].excerpt == "first\u0085same line"
    assert prepared.evidence[1].id == "log_2"
    assert prepared.evidence[1].excerpt == "EADDRINUSE"


async def test_conflicting_python_constraints_ask_question(context):
    context.scan.facts.runtime_hints.append(
        RuntimeHint(
            runtime="python",
            constraint="<3.10",
            evidence_ids=context.scan.facts.runtime_hints[0].evidence_ids,
        )
    )
    result = await IntelligenceServiceImpl().diagnose(
        context,
        log("ERROR: requires Python >=3.12"),
        None,
        False,
    )
    assert any("различаются" in question for question in result.questions)
    assert "<3.10" in result.causes[0].explanation
    assert "3.12" in result.causes[0].explanation
    assert not any(
        "downgrade" in c.text
        for cause in result.causes
        for step in cause.fixes
        for c in step.commands
    )


async def test_env_keyerror_only_for_repo_known_names(context):
    context.scan.facts.env_var_names = ["DEMO_TOKEN"]
    result = await IntelligenceServiceImpl().diagnose(
        context, log("KeyError: 'DEMO_TOKEN'"), None, False
    )
    assert result.causes[0].id == "cause_env"
    result = await IntelligenceServiceImpl().diagnose(
        context, log("KeyError: 'dict_key'"), None, False
    )
    assert not result.causes


async def model_diagnosis(context):
    fallback = await IntelligenceServiceImpl().diagnose(context, log("EADDRINUSE"), None, False)
    cause = fallback.causes[0]
    return ModelDiagnosisOutput(
        summary="Вероятно, порт занят; требуется проверка.",
        causes=[ModelCauseOutput(**cause.model_dump(exclude={"id", "origin"}))],
        questions=[],
    )


async def test_ai_diagnosis_success_and_no_context_mutation(context):
    original = context.model_dump_json()
    fake = FakeProvider(await model_diagnosis(context))
    result = await IntelligenceServiceImpl(fake).diagnose(
        context, log("EADDRINUSE"), "npm start", True
    )
    assert result.generation.mode == "ai"
    assert result.generation.prompt_version == "diagnosis-v1"
    assert result.causes[0].origin == "ai"
    assert result.causes[0].id == "ai_cause_1"
    assert context.model_dump_json() == original
    assert len(fake.calls) == 1
    assert context.scan.evidence[0] in result.evidence


@pytest.mark.parametrize(
    "mutation",
    ["wrong_id", "no_log", "empty", "six_causes", "wrong_shell", "bad_path", "import_install"],
)
async def test_diagnosis_invalid_ai_uses_local_causes(context, mutation):
    output = await model_diagnosis(context)
    cause = output.causes[0]
    match mutation:
        case "wrong_id":
            cause.evidence_ids = ["log_invented"]
        case "no_log":
            cause.evidence_ids = [context.scan.evidence[0].id]
        case "empty":
            output.causes = []
        case "six_causes":
            output.causes *= 6
        case "wrong_shell" | "bad_path" | "import_install":
            from repodoctor.contracts.api import Command

            cause.fixes[0].commands = [
                Command(  # noqa: S604 -- DTO, no subprocess
                    text=".venv/Scripts/python.exe --version",
                    shell="powershell",
                    cwd="<repo>",
                    explanation="Проверить версию",
                    requires_review=True,
                )
            ]
            if mutation == "wrong_shell":
                cause.fixes[0].commands[0].shell = Shell.bash
            if mutation == "bad_path":
                cause.fixes[0].commands[0].cwd = "../outside"
            if mutation == "import_install":
                cause.fixes[0].commands[0].text = "pip install sklearn"
    fake = FakeProvider(output)
    result = await IntelligenceServiceImpl(fake).diagnose(context, log("EADDRINUSE"), None, True)
    assert result.generation.reason == "invalid_output"
    assert result.causes[0].id == "cause_port"
    assert result.causes[0].origin == "static"
    assert len(fake.calls) == 1


async def test_diagnosis_provider_failure_unknown_log_asks_questions(context):
    result = await IntelligenceServiceImpl(FakeProvider(ProviderError("timeout"))).diagnose(
        context,
        log("something went wrong"),
        None,
        True,
    )
    assert result.generation.reason == "timeout"
    assert result.questions
    assert not result.causes


async def test_diagnosis_sdk_payload_separates_bounded_repo_and_log(monkeypatch, context):
    output = await model_diagnosis(context)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=wire_response(output.model_dump_json()))

    install_transport(monkeypatch, handler)
    result = await IntelligenceServiceImpl(OpenAIProvider(settings())).diagnose(
        context,
        log("EADDRINUSE\nTOKEN=[REDACTED]"),
        "npm start",
        True,
    )
    assert result.generation.mode == "ai"
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    payload = json.loads(body["input"])
    assert len(encode(payload["repo_context"])) <= REPO_CONTEXT_LIMIT
    assert len(encode(payload["log"])) <= LOG_CONTEXT_LIMIT
    assert payload["command"] == "npm start"
    assert "[REDACTED]" in encode(payload["log"])
    assert payload["repo_context"]["baseline_plan"]
    assert "EADDRINUSE" not in body["instructions"]
    assert "TOKEN" not in body["instructions"]


async def test_ai_missing_module_allows_canonical_interpreter_check(context):
    sanitized = log("ModuleNotFoundError: No module named 'requests'")
    local = await IntelligenceServiceImpl().diagnose(context, sanitized, None, False)
    cause = local.causes[0]
    output = ModelDiagnosisOutput(
        summary="Проверьте Python-окружение.",
        causes=[ModelCauseOutput(**cause.model_dump(exclude={"id", "origin"}))],
        questions=[],
    )
    result = await IntelligenceServiceImpl(FakeProvider(output)).diagnose(
        context, sanitized, None, True
    )
    assert result.generation.mode == "ai"
    assert "sys.executable" in result.causes[0].fixes[0].commands[0].text


async def test_node_engine_uses_node_runtime_and_selected_subroot(node_scan):
    response = AnalysisResponse.model_validate_json(
        (EXAMPLES / "analysis_node.json").read_text(encoding="utf-8")
    )
    node_scan.facts.project_roots[0].path = "apps/api"
    context = AnalysisContext(scan=node_scan, response=response)
    result = await IntelligenceServiceImpl().diagnose(
        context, log("npm ERR! EBADENGINE"), None, False
    )
    commands = result.causes[0].fixes[0].commands
    assert commands[0].text == "node --version"
    assert commands[0].cwd == "<repo>/apps/api"
    assert commands[0].shell == "bash"
    assert "apps/api" in result.causes[0].explanation
