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
from repodoctor.intelligence.provider import ModelDiagnosisOutput, ModelPlanOutput
from repodoctor.intelligence.rules import build_fallback_plan


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


def _bounded(data: object) -> None:
    if isinstance(data, str):
        if len(data) > 3000 or "\x00" in data:
            raise OutputRejected("text_limit")
    elif isinstance(data, list):
        if len(data) > 40:
            raise OutputRejected("list_limit")
        for value in data:
            _bounded(value)
    elif isinstance(data, dict):
        for value in data.values():
            _bounded(value)


def _steps(steps: list[RunStep], evidence: list[Evidence], target: TargetEnvironment) -> None:
    if len(steps) > 12 or len({step.id for step in steps}) != len(steps):
        raise OutputRejected("steps")
    check_evidence_registry(evidence, collect_evidence_refs(steps))
    for step in steps:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", step.id):
            raise OutputRejected("step_id")
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


def validate_plan(
    output: ModelPlanOutput, scan: StaticAnalysis, target: TargetEnvironment
) -> tuple[ModelPlanOutput, list[Finding]]:
    # Reparse even typed providers: model_copy(update=...) bypasses Pydantic validation.
    result = ModelPlanOutput.model_validate(output.model_dump())
    _bounded(result.model_dump())
    _links(result.model_dump(), scan)
    _steps(result.run_plan.steps, scan.evidence, target)
    baseline = build_fallback_plan(scan, target)
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
    if len(result.additional_findings) > 10:
        raise OutputRejected("findings_limit")
    findings = []
    existing_ids = {finding.id for finding in scan.findings}
    for i, finding in enumerate(result.additional_findings, 1):
        if not finding.title.strip() or not finding.evidence_ids:
            raise OutputRejected("ungrounded_finding")
        check_evidence_registry(scan.evidence, set(finding.evidence_ids))
        identifier = f"ai_finding_{i}"
        while identifier in existing_ids:
            identifier = "ai_" + identifier
        existing_ids.add(identifier)
        findings.append(
            Finding(
                id=identifier,
                rule_id="AI_ADDITIONAL_FINDING",
                origin=Origin.ai,
                **finding.model_dump(),
            )
        )
    return result, findings


def validate_diagnosis(
    output: ModelDiagnosisOutput, context: AnalysisContext, evidence: list[Evidence]
) -> ModelDiagnosisOutput:
    from repodoctor.intelligence.diagnostics import diagnostic_commands

    result = ModelDiagnosisOutput.model_validate(output.model_dump())
    _bounded(result.model_dump())
    _links(result.model_dump(), context.scan)
    if len(result.causes) > 5 or (not result.causes and not result.questions):
        raise OutputRejected("causes")
    allowed = diagnostic_commands(context)
    install_sources = {
        (command.text, command.cwd): set(step.evidence_ids)
        for step in build_fallback_plan(context.scan, context.response.target).steps
        if step.id == "step_install"
        for command in step.commands
    }
    for cause in result.causes:
        if not cause.title.strip() or not cause.verification.strip():
            raise OutputRejected("empty_cause")
        check_evidence_registry(evidence, set(cause.evidence_ids))
        if not any(ref.startswith("log_") for ref in cause.evidence_ids):
            raise OutputRejected("missing_log_evidence")
        _steps(cause.fixes, evidence, context.response.target)
        for step in cause.fixes:
            for command in step.commands:
                if {"text": command.text, "cwd": command.cwd} not in allowed:
                    raise OutputRejected("unsupported_diagnostic_command")
                if not install_sources.get((command.text, command.cwd), set()) <= set(
                    step.evidence_ids
                ):
                    raise OutputRejected("missing_install_sources")
    return result


def model_causes(output: ModelDiagnosisOutput) -> list[DiagnosisCause]:
    return [
        DiagnosisCause(id=f"ai_cause_{i}", origin=Origin.ai, **cause.model_dump())
        for i, cause in enumerate(output.causes, 1)
    ]
