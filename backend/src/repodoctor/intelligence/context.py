"""Deterministic, bounded JSON data; instructions live separately in prompts/."""

from __future__ import annotations

import json

from repodoctor.contracts.api import TargetEnvironment
from repodoctor.contracts.domain import StaticAnalysis
from repodoctor.security.redaction import redact_text

REPO_CONTEXT_LIMIT = 48_000
LOG_CONTEXT_LIMIT = 16_000


def encode(data: object) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _redacted(value: object) -> object:
    if isinstance(value, str):
        return redact_text(value)[0]
    if isinstance(value, list):
        return [_redacted(item) for item in value]
    if isinstance(value, dict):
        return {key: _redacted(item) for key, item in value.items()}
    return value


def build_context(
    scan: StaticAnalysis, target: TargetEnvironment, *, baseline: dict | None = None
) -> dict:
    """Pack facts with their evidence atomically; never leave dangling model-input refs."""
    data = _redacted(
        {
            "target": target.model_dump(mode="json"),
            "repository": scan.repository.model_dump(mode="json"),
            "source_mode": scan.source_mode.value,
            "facts": {"stack": scan.facts.stack.value},
            "findings": [],
            "evidence": [],
            "excerpts": [],
            "limitations": [],
            "truncated": False,
            "baseline_plan": baseline,
        }
    )
    if len(encode(data)) > REPO_CONTEXT_LIMIT - 200:
        # Import locally: provider imports this pure context builder.
        from repodoctor.intelligence.provider import ProviderError

        raise ProviderError("context_too_large")
    registry = {ev.id: ev for ev in scan.evidence}
    included: set[str] = set()
    omitted = False

    def add(collection: list, item: object, refs: list[str] = ()) -> None:
        nonlocal omitted
        missing = sorted(set(refs) - included)
        if any(ref not in registry for ref in missing):
            omitted = True
            return
        extra = [_redacted(registry[ref].model_dump(mode="json")) for ref in missing]
        collection.append(_redacted(item))
        data["evidence"].extend(extra)
        # Reserve space for an explicit limitation and the truncation flag.
        if len(encode(data)) > REPO_CONTEXT_LIMIT - 200:
            collection.pop()
            if extra:
                del data["evidence"][-len(extra) :]
            omitted = True
        else:
            included.update(missing)

    for limitation in scan.coverage.limitations:
        add(data["limitations"], limitation)
    for name in (
        "project_roots",
        "runtime_hints",
        "package_managers",
        "entrypoints",
        "dependencies",
        "env_var_names",
        "data_hints",
        "gpu_hints",
    ):
        data["facts"][name] = []
        for item in getattr(scan.facts, name):
            value = item.model_dump(mode="json") if hasattr(item, "model_dump") else item
            add(data["facts"][name], value, getattr(item, "evidence_ids", []))
    for finding in scan.findings:
        add(data["findings"], finding.model_dump(mode="json"), finding.evidence_ids)
    for evidence in sorted(scan.evidence, key=lambda ev: ev.id):
        if evidence.id not in included:
            add(data["excerpts"], {"evidence_id": evidence.id}, [evidence.id])
    for file in sorted(scan.selected_files, key=lambda file: file.path):
        # Files have already been redacted by the repository layer; mask again defensively.
        content = redact_text(file.content[:2000])[0]
        add(data["excerpts"], {"path": file.path, "excerpt": content})
        omitted |= len(file.content) > 2000
    if omitted:
        data["truncated"] = True
        data["limitations"].append("Контекст сокращён; отсутствующие факты требуют уточнения.")

    return data
