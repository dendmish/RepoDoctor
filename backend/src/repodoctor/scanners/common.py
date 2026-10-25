"""Internal parser state; public DTOs remain owned by contracts/."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath

from repodoctor.contracts.api import Finding, RepositoryFacts
from repodoctor.contracts.domain import RepositorySnapshot, TextFile
from repodoctor.scanners.evidence import EvidenceRegistry, stable_id


def root_of(path: str) -> str:
    return str(PurePosixPath(path).parent)


def join_path(root: str, path: str) -> str:
    return path if root == "." else root + "/" + path


@dataclass
class ScanState:
    snapshot: RepositorySnapshot
    facts: RepositoryFacts
    registry: EvidenceRegistry
    files: dict[str, TextFile]
    findings: list[Finding] = field(default_factory=list)
    signals: dict[str, list[str]] = field(default_factory=dict)
    explicit_managers: dict[tuple[str, str], str] = field(default_factory=dict)

    def signal(self, name: str, evidence_id: str) -> None:
        self.signals.setdefault(name, []).append(evidence_id)

    def issue(
        self,
        rule: str,
        path: str,
        description: str,
        action: str,
        ids: list[str] | None = None,
        *,
        severity: str = "warning",
        confidence: str = "medium",
    ) -> None:
        self.findings.append(
            Finding(
                id=stable_id("finding", rule, path),
                rule_id=rule,
                title=rule.replace("_", " "),
                description=description,
                severity=severity,
                confidence=confidence,
                origin="static",
                evidence_ids=sorted(set(ids or [])),
                suggested_action=action,
            )
        )

    def file_ids(self, file: TextFile, text: str = "") -> list[str]:
        return [self.registry.match(file, text)] if file.content.splitlines() else []
