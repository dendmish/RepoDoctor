"""Conservative content policy; this is not a shell sandbox or truth oracle."""

from __future__ import annotations

import re

from repodoctor.contracts.api import (
    DiagnosisCause,
    Evidence,
    Finding,
    Origin,
    PlanStatus,
    RunStep,
    Shell,
    TargetEnvironment,
    check_evidence_registry,
    collect_evidence_refs,
)
from repodoctor.contracts.domain import AnalysisContext, StaticAnalysis
from repodoctor.intelligence.provider import (
    ModelCauseOutput,
    ModelDiagnosisOutput,
    ModelFindingOutput,
    ModelPlanOutput,
)
from repodoctor.intelligence.rules import build_fallback_plan
from repodoctor.security.redaction import redact_text


class OutputRejected(ValueError):
    """Never return rejected model text to the caller."""


_DANGEROUS = re.compile(
    r"\b(?:sudo|rm|rmdir|del|erase|format|mkfs|remove-item|stop-process|kill|killall|"
    r"taskkill|invoke-expression|iex|eval)\b|--(?:insecure|trusted-host)|"
    r"\b(?:curl|wget|invoke-webrequest|iwr)\b|"
    r"(?:verify|ssl_verify)\s*=\s*false|set-executionpolicy|"
    r"(?:/etc/|/usr/|[A-Z]:\\Windows\\)|[<>]|\$\(|`|\r|\n|&&|\|\||;",
    re.IGNORECASE,
)
_EXECUTED = re.compile(
    r"\b(?:исправлен[аоы]?|проверен[аоы]?|запущен[аоы]?|выполнен[аоы]?|"
    r"verified|fixed|executed)\b",
    re.I,
)
_USER_RAN = re.compile(r"запущен[аоы]?|выполнен[аоы]?|executed", re.I)
_PROSE_COMMAND = re.compile(
    r"\b(?:curl|wget|iwr|invoke-webrequest)\b[^\n]*\|\s*(?:bash|sh|zsh|iex)|"
    r"\b(?:sudo\s+|rm\s+-[a-z]*[rf]|rmdir\s+/s|del\s+/s|"
    r"remove-item\s+[^\n]*-recurse|set-executionpolicy\s+)",
    re.I,
)


# Negations and future/expected outcomes are not claims that something was already executed.
_NOT_EXECUTED_PREFIX = re.compile(
    r"(?:\b(?:не|not|never)\s+(?:(?:был[аои]?|были)\s+)?"
    r"|\b(?:не\s+)?(?:будет|будут|должен\s+быть|должна\s+быть|должно\s+быть|должны\s+быть)\s+)$",
    re.I,
)
_FILE_NAME = re.compile(r"[\w./-]+\.(?:py|js|mjs|cjs|ts)\b")
_RUNTIME_VERSION = re.compile(
    r"\b(python|node(?:\.js)?)\s*(?:версии?\s*)?[:=<>~^ ]*(\d+(?:\.\d+){0,2})", re.I
)


def _content(data: object, scan: StaticAnalysis, field: str = "", *, user_text: str = "") -> None:
    """Reject concrete unsupported claims; this deliberately does not prove prose true.

    `user_text` is the processed log/command the user pasted: file names and runtime versions
    quoted from it are grounded facts in a diagnosis, not invented repository claims.
    """
    if isinstance(data, list):
        for item in data:
            _content(item, scan, field, user_text=user_text)
    elif isinstance(data, dict):
        for name, item in data.items():
            _content(item, scan, name, user_text=user_text)
    elif isinstance(data, str):
        if redact_text(data)[0] != data:
            raise OutputRejected("secret_in_output")
        if _PROSE_COMMAND.search(data):
            raise OutputRejected("dangerous_prose")
        # Verification describes an expected outcome; assumptions/questions preserve uncertainty.
        if field in {"verification", "assumptions", "questions", "text"}:
            return
        for claim in _EXECUTED.finditer(data):
            # In a diagnosis the pasted log proves the *user* ran something ("команда
            # запущена вне <repo>/website"); claims that we fixed/verified stay forbidden.
            if user_text and _USER_RAN.fullmatch(claim.group(0)):
                continue
            if not _NOT_EXECUTED_PREFIX.search(data[: claim.start()]):
                raise OutputRejected("unsupported_execution_claim")
        for runtime, version in _RUNTIME_VERSION.findall(data):
            ecosystem = "node" if runtime.lower().startswith("node") else "python"
            known = [
                hint.constraint
                for hint in scan.facts.runtime_hints
                if hint.runtime.value == ecosystem
            ]
            known.append(user_text)
            if not any(
                re.search(rf"(?<!\d){re.escape(version)}(?!\d)", constraint) for constraint in known
            ):
                raise OutputRejected("unsupported_runtime_claim")
        paths = {ev.path for ev in scan.evidence if ev.path} | {
            file.path for file in scan.selected_files
        }
        paths |= {path.removeprefix("./") for path in _FILE_NAME.findall(user_text)}
        names = paths | {path.rsplit("/", 1)[-1] for path in paths}
        for path in _FILE_NAME.findall(data):
            if path.lower() != "node.js" and path.removeprefix("./") not in names:
                raise OutputRejected("unsupported_entrypoint_claim")


def command_allowed(text: str) -> bool:
    # <repo> is a cwd placeholder, not a shell redirection in command.text.
    if re.fullmatch(
        r'\.venv/(?:Scripts/python\.exe|bin/python) -c "import sys; print\(sys.executable\)"', text
    ):
        return True
    return not _DANGEROUS.search(text)


def _links(data: object, scan: StaticAnalysis) -> None:
    allowed = {scan.repository.url, scan.repository.url + ".git"}
    allowed.update(ev.url for ev in scan.evidence if ev.url)

    def walk(value: object) -> None:
        if isinstance(value, str):
            for url in re.findall(r"https?://[^\s'\"<>]+", value):
                if url.rstrip(".,)") not in allowed:
                    raise OutputRejected("unverified_url")
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)

    walk(data)


MAX_LIST_ITEMS = 40


def _bounded(data: object, field: str = "") -> None:
    """Size limits. `evidence_ids` lengths are checked by their owners (_steps, findings,
    causes) because a server-built baseline step may legitimately cite more sources."""
    if isinstance(data, str):
        if len(data) > 3000 or "\x00" in data:
            raise OutputRejected("text_limit")
    elif isinstance(data, list):
        if len(data) > MAX_LIST_ITEMS and field != "evidence_ids":
            raise OutputRejected("list_limit")
        for value in data:
            _bounded(value)
    elif isinstance(data, dict):
        for name, value in data.items():
            _bounded(value, name)


def _evidence_limit(ids: list[str], allowed: int = MAX_LIST_ITEMS) -> None:
    if len(ids) > max(allowed, MAX_LIST_ITEMS):
        raise OutputRejected("list_limit")


def _steps(
    steps: list[RunStep],
    evidence: list[Evidence],
    target: TargetEnvironment,
    baseline_sizes: dict[str, int] | None = None,
) -> None:
    """`baseline_sizes` maps a baseline step id to its evidence count, so an exact copy of the
    server-built plan is never rejected for citing the sources the server itself chose."""
    if len(steps) > 12 or len({step.id for step in steps}) != len(steps):
        raise OutputRejected("steps")
    check_evidence_registry(evidence, collect_evidence_refs(steps))
    for step in steps:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", step.id):
            raise OutputRejected("step_id")
        _evidence_limit(step.evidence_ids, (baseline_sizes or {}).get(step.id, 0))
        if not step.verification.strip() or not (step.evidence_ids or step.assumptions):
            raise OutputRejected("ungrounded_step")
        for command in step.commands:
            if command.shell != target.shell or not command_allowed(command.text):
                raise OutputRejected("command_policy")
            if target.shell is Shell.powershell and re.search(r"\bsource\b", command.text):
                raise OutputRejected("wrong_shell")
            if target.shell is not Shell.powershell and ".venv/Scripts/" in command.text:
                raise OutputRejected("wrong_shell")
            command.requires_review = True


def _command_keys(steps: list[RunStep]) -> list[tuple[str, str, str]]:
    return [(c.text, c.cwd, c.shell.value) for step in steps for c in step.commands]


def _normalized(text: str) -> str:
    return re.sub(r"[\W_]+", " ", text).strip().lower()


def _accept_findings(
    raw: list[ModelFindingOutput], scan: StaticAnalysis
) -> tuple[list[Finding], list[str]]:
    """Keep only new, grounded and policy-clean AI findings; drop the rest one by one.

    Models often echo the static findings they were shown (sometimes with empty
    evidence_ids). An echo or one ungrounded note must not discard a valid run plan.
    """
    registry = {ev.id for ev in scan.evidence}
    known = {_normalized(f.title) for f in scan.findings}
    known |= {_normalized(f.rule_id) for f in scan.findings}
    existing_ids = {finding.id for finding in scan.findings}
    accepted: list[Finding] = []
    dropped: list[str] = []
    for finding in raw:
        reason = None
        if len(accepted) >= 10:
            reason = "findings_limit"
        elif not finding.title.strip() or not finding.evidence_ids:
            reason = "ungrounded_finding"
        elif len(finding.evidence_ids) > MAX_LIST_ITEMS:
            reason = "list_limit"
        elif not set(finding.evidence_ids) <= registry:
            reason = "unknown_evidence"
        elif _normalized(finding.title) in known:
            reason = "duplicate_static_finding"
        else:
            try:
                data = finding.model_dump()
                _bounded(data)
                _content(data, scan)
                _links(data, scan)
            except OutputRejected as exc:
                reason = str(exc)
        if reason is not None:
            dropped.append(reason)
            continue
        known.add(_normalized(finding.title))
        identifier = f"ai_finding_{len(accepted) + 1}"
        while identifier in existing_ids:
            identifier = "ai_" + identifier
        existing_ids.add(identifier)
        accepted.append(
            Finding(
                id=identifier,
                rule_id="AI_ADDITIONAL_FINDING",
                origin=Origin.ai,
                **finding.model_dump(),
            )
        )
    return accepted, dropped


def validate_plan(
    output: ModelPlanOutput, scan: StaticAnalysis, target: TargetEnvironment
) -> tuple[ModelPlanOutput, list[Finding], list[str]]:
    """Strict for the run plan (whole-result rejection); lenient per AI finding.

    Returns the plan, accepted findings and the reasons of dropped findings.
    """
    # Reparse even typed providers: model_copy(update=...) bypasses Pydantic validation.
    result = ModelPlanOutput.model_validate(output.model_dump())
    plan_data = result.run_plan.model_dump()
    _bounded(plan_data)
    if len(result.additional_findings) > 40:
        raise OutputRejected("list_limit")
    _content(plan_data, scan)
    _links(plan_data, scan)
    baseline = build_fallback_plan(scan, target)
    sizes = {step.id: len(step.evidence_ids) for step in baseline.steps}
    _steps(result.run_plan.steps, scan.evidence, target, sizes)
    if _command_keys(result.run_plan.steps) != _command_keys(baseline.steps):
        # Only server-confirmed commands, in prerequisite order. No partial plan repair.
        raise OutputRejected("unsupported_command_or_order")
    if (
        baseline.status is PlanStatus.needs_input
        and result.run_plan.status is PlanStatus.actionable
    ):
        raise OutputRejected("unsupported_actionable")
    if not set(baseline.prerequisites) <= set(result.run_plan.prerequisites):
        raise OutputRejected("missing_prerequisites")
    # A valid but unrelated evidence ID must not justify a runtime or entrypoint command.
    expected = {
        (command.text, command.cwd): set(step.evidence_ids)
        for step in baseline.steps
        for command in step.commands
    }
    for step in result.run_plan.steps:
        for command in step.commands:
            if not expected[(command.text, command.cwd)] <= set(step.evidence_ids):
                raise OutputRejected("missing_command_sources")
    findings, dropped = _accept_findings(result.additional_findings, scan)
    result.additional_findings = []
    return result, findings, dropped


def _check_cause(
    cause: ModelCauseOutput,
    context: AnalysisContext,
    evidence: list[Evidence],
    allowed: list[dict[str, str]],
    install_sources: dict[tuple[str, str], set[str]],
    user_text: str,
) -> None:
    if not cause.title.strip() or not cause.verification.strip():
        raise OutputRejected("empty_cause")
    data = cause.model_dump()
    _content(data, context.scan, user_text=user_text)
    _links(data, context.scan)
    try:
        check_evidence_registry(evidence, set(cause.evidence_ids))
    except OutputRejected:
        raise
    except ValueError as exc:
        raise OutputRejected("unknown_evidence") from exc
    _evidence_limit(cause.evidence_ids)
    if not any(ref.startswith("log_") for ref in cause.evidence_ids):
        raise OutputRejected("missing_log_evidence")
    try:
        _steps(cause.fixes, evidence, context.response.target)
    except OutputRejected:
        raise
    except ValueError as exc:
        raise OutputRejected("unknown_evidence") from exc
    for step in cause.fixes:
        for command in step.commands:
            if {"text": command.text, "cwd": command.cwd} not in allowed:
                raise OutputRejected("unsupported_diagnostic_command")
            if not install_sources.get((command.text, command.cwd), set()) <= set(
                step.evidence_ids
            ):
                raise OutputRejected("missing_install_sources")


def validate_diagnosis(
    output: ModelDiagnosisOutput,
    context: AnalysisContext,
    evidence: list[Evidence],
    *,
    user_text: str = "",
) -> tuple[ModelDiagnosisOutput, list[str]]:
    """Summary/questions are checked strictly; each cause is accepted or dropped on its own.

    If the model proposed causes and none survives, the whole result is rejected so the
    deterministic rules answer instead of an empty AI diagnosis. Returns the reasons of
    dropped causes.
    """
    from repodoctor.intelligence.diagnostics import diagnostic_commands

    result = ModelDiagnosisOutput.model_validate(output.model_dump())
    _bounded(result.model_dump())
    shared = {"summary": result.summary, "questions": result.questions}
    _content(shared, context.scan, user_text=user_text)
    _links(shared, context.scan)
    if len(result.causes) > 5 or (not result.causes and not result.questions):
        raise OutputRejected("causes")
    allowed = diagnostic_commands(context)
    install_sources = {
        (command.text, command.cwd): set(step.evidence_ids)
        for step in build_fallback_plan(context.scan, context.response.target).steps
        if step.id == "step_install"
        for command in step.commands
    }
    kept, dropped = [], []
    for cause in result.causes:
        try:
            _check_cause(cause, context, evidence, allowed, install_sources, user_text)
        except OutputRejected as exc:
            dropped.append(str(exc))
        else:
            kept.append(cause)
    if result.causes and not kept:
        raise OutputRejected(dropped[0])
    result.causes = kept
    return result, dropped


def model_causes(output: ModelDiagnosisOutput) -> list[DiagnosisCause]:
    return [
        DiagnosisCause(id=f"ai_cause_{i}", origin=Origin.ai, **cause.model_dump())
        for i, cause in enumerate(output.causes, 1)
    ]
