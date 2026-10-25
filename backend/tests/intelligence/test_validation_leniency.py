"""Live GigaChat regressions: valid plans/diagnoses must not be discarded for one bad item.

Observed on 2026-10-25 with GigaChat-3-Ultra: HTTP 200 + valid JSON, but the whole result
fell back because the model echoed a static finding with empty evidence_ids, quoted a file
from the user's own log, or produced one cause without a log_ reference.
"""

from __future__ import annotations

import logging

from repodoctor.contracts.domain import SanitizedLog
from repodoctor.intelligence.provider import (
    ModelCauseOutput,
    ModelDiagnosisOutput,
    ModelFindingOutput,
)
from repodoctor.intelligence.service import IntelligenceServiceImpl
from repodoctor.intelligence.validation import _content
from tests.intelligence.fakes import FakeProvider
from tests.intelligence.test_adversarial import context_from
from tests.intelligence.test_ai import TARGET, model_plan


def finding(evidence_ids: list[str], title: str = "Проверить manifest") -> ModelFindingOutput:
    return ModelFindingOutput(
        title=title,
        description="Сверьте параметры локального запуска.",
        severity="info",
        confidence="low",
        evidence_ids=evidence_ids,
        suggested_action="Сопоставьте manifest с окружением.",
    )


async def test_echoed_and_ungrounded_findings_are_dropped_not_the_plan(node_scan, caplog):
    caplog.set_level(logging.INFO, logger="repodoctor")
    output = model_plan(node_scan)
    static = node_scan.findings[0]
    output.additional_findings = [
        finding([], title="ENTRYPOINT UNCLEAR"),  # echo with empty evidence (live case)
        finding([node_scan.evidence[0].id], title=static.title),  # duplicate static
        finding(["ev_invented"]),
        finding([node_scan.evidence[0].id], title="Внешняя ссылка https://nodejs.org"),
        finding([node_scan.evidence[0].id]),  # the only new grounded note
    ]
    result = await IntelligenceServiceImpl(FakeProvider(output)).build_plan(node_scan, TARGET, True)
    assert result.generation.mode == "ai"
    assert [f.title for f in result.additional_findings] == ["Проверить manifest"]
    assert result.additional_findings[0].id == "ai_finding_1"
    warning = next(w for w in result.warnings if w.startswith("Отброшено AI-наблюдений"))
    assert ": 4 " in warning and "ungrounded_finding" in warning
    assert "ev_invented" not in result.model_dump_json()
    assert "ai_findings_dropped" in caplog.text


async def test_invalid_run_plan_still_rejects_whole_result_with_rule(node_scan, caplog):
    caplog.set_level(logging.INFO, logger="repodoctor")
    output = model_plan(node_scan)
    output.run_plan.steps[0].description = "Скачайте https://unverified.invalid/install"
    result = await IntelligenceServiceImpl(FakeProvider(output)).build_plan(node_scan, TARGET, True)
    assert result.generation.reason == "invalid_output"
    assert any("invalid_output: unverified_url" in w for w in result.warnings)
    assert "rule=unverified_url" in caplog.text
    assert "unverified.invalid" not in caplog.text


def _diagnosis(node_scan, *causes: ModelCauseOutput):
    return ModelDiagnosisOutput(summary="Вероятно, порт занят.", causes=list(causes), questions=[])


async def _local_cause(context, log) -> ModelCauseOutput:
    baseline = await IntelligenceServiceImpl().diagnose(context, log, None, False)
    return ModelCauseOutput(**baseline.causes[0].model_dump(exclude={"id", "origin"}))


async def test_cause_without_log_evidence_is_dropped_others_kept(node_scan):
    context = context_from(node_scan)
    log = SanitizedLog(text="EADDRINUSE", redactions_count=0, truncated=False)
    good = await _local_cause(context, log)
    bad = good.model_copy(
        update={"title": "Без строки лога", "evidence_ids": [node_scan.evidence[0].id]}
    )
    fake = FakeProvider(_diagnosis(node_scan, bad, good))
    result = await IntelligenceServiceImpl(fake).diagnose(context, log, None, True)
    assert result.generation.mode == "ai"
    assert [c.title for c in result.causes] == [good.title]
    assert any("missing_log_evidence" in w for w in result.warnings)


async def test_all_causes_invalid_falls_back_with_rule(node_scan):
    context = context_from(node_scan)
    log = SanitizedLog(text="EADDRINUSE", redactions_count=0, truncated=False)
    good = await _local_cause(context, log)
    bad = good.model_copy(update={"evidence_ids": [node_scan.evidence[0].id]})
    result = await IntelligenceServiceImpl(FakeProvider(_diagnosis(node_scan, bad))).diagnose(
        context, log, None, True
    )
    assert result.generation.mode == "fallback"
    assert any("invalid_output: missing_log_evidence" in w for w in result.warnings)


async def test_file_and_version_quoted_from_user_log_are_allowed(node_scan):
    context = context_from(node_scan)
    text = 'File "C:\\work\\app.py", line 1\nModuleNotFoundError under Python 3.11\nEADDRINUSE'
    log = SanitizedLog(text=text, redactions_count=0, truncated=False)
    good = await _local_cause(context, log)
    cause = good.model_copy(
        update={"explanation": "Ошибка возникает при импорте в app.py под Python 3.11."}
    )
    fake = FakeProvider(_diagnosis(node_scan, cause))
    result = await IntelligenceServiceImpl(fake).diagnose(context, log, "python app.py", True)
    assert result.generation.mode == "ai"
    # The same claim without the user's log is still an invented entrypoint.
    fake = FakeProvider(_diagnosis(node_scan, cause))
    other = SanitizedLog(text="EADDRINUSE", redactions_count=0, truncated=False)
    result = await IntelligenceServiceImpl(fake).diagnose(context, other, None, True)
    assert result.generation.mode == "fallback"


def test_negated_and_future_outcomes_are_not_execution_claims(node_scan):
    for text in [
        "Сервер не будет запущен, пока порт занят.",
        "После этого сервер будет запущен на порту 3000.",
        "Команды не были выполнены.",
    ]:
        _content({"description": text}, node_scan)
