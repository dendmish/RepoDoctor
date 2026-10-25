"""Pure, deterministic RepositorySnapshot -> StaticAnalysis assembly."""

from __future__ import annotations

import json
from pathlib import PurePosixPath

from repodoctor.contracts.api import (
    PackageManagerHint,
    ProjectRoot,
    RepositoryFacts,
    check_evidence_registry,
    collect_evidence_refs,
)
from repodoctor.contracts.domain import RepositorySnapshot, StaticAnalysis
from repodoctor.repository.selection import (
    RepositoryLimits,
    eligible,
    is_manifest,
    project_root_paths,
)
from repodoctor.repository.text import redact_file_text
from repodoctor.scanners.common import ScanState, root_of
from repodoctor.scanners.evidence import EvidenceRegistry
from repodoctor.scanners.node import parse_node
from repodoctor.scanners.python import parse_python
from repodoctor.scanners.readme import extract_readme_hints
from repodoctor.scanners.risks import evaluate_risks

LOCK_MANAGERS = {
    "uv.lock": "uv",
    "poetry.lock": "poetry",
    "package-lock.json": "npm",
    "npm-shrinkwrap.json": "npm",
    "yarn.lock": "yarn",
    "pnpm-lock.yaml": "pnpm",
    "environment.yml": "conda",
    "environment.yaml": "conda",
}


def _dedupe(items: list) -> list:
    unique = {}
    for item in items:
        key = json.dumps(item.model_dump(mode="json", exclude={"evidence_ids"}), sort_keys=True)
        if key in unique:
            ids = sorted(set(unique[key].evidence_ids) | set(item.evidence_ids))
            unique[key] = item.model_copy(update={"evidence_ids": ids})
        else:
            unique[key] = item.model_copy(deep=True)
    return [unique[key] for key in sorted(unique)]


def detect_project_roots(snapshot: RepositorySnapshot, limit: int = 3) -> list[ProjectRoot]:
    roots = []
    for root in project_root_paths(snapshot.tree, limit):
        manifests = sorted(
            e.path
            for e in snapshot.tree
            if eligible(e) and is_manifest(e.path) and root_of(e.path) == root
        )
        python = any(PurePosixPath(path).name != "package.json" for path in manifests)
        node = any(PurePosixPath(path).name == "package.json" for path in manifests)
        roots.append(
            ProjectRoot(
                path=root,
                stack="mixed" if python and node else "python" if python else "node",
                manifest_paths=manifests,
            )
        )
    return roots


class RepositoryAnalyzer:
    def __init__(self, *, limits: RepositoryLimits | None = None) -> None:
        self.limits = limits or RepositoryLimits()

    def analyze(self, snapshot: RepositorySnapshot) -> StaticAnalysis:
        # Copy and sanitize even custom injected snapshots; don't mutate a shared caller input.
        snapshot = snapshot.model_copy(deep=True)
        snapshot.tree = sorted(snapshot.tree, key=lambda e: e.path)
        roots = detect_project_roots(snapshot, self.limits.subroots)
        chosen_roots = {root.path for root in roots}
        all_roots = {root_of(e.path) for e in snapshot.tree if eligible(e) and is_manifest(e.path)}
        if all_roots - chosen_roots:
            snapshot.coverage.status = "partial"
            snapshot.coverage.limitations.append("Scanner ограничил число вложенных project roots.")
        paths = {e.path for e in snapshot.tree if eligible(e)}
        files = []
        retained_bytes = 0
        for file in sorted(snapshot.files, key=lambda f: f.path):
            measured_bytes = max(file.size_bytes, len(file.content.encode("utf-8")))
            if (
                file.path not in paths
                or len(files) >= self.limits.files
                or measured_bytes > self.limits.file_bytes
                or "\x00" in file.content
                or (is_manifest(file.path) and root_of(file.path) not in chosen_roots)
            ):
                snapshot.coverage.status = "partial"
                snapshot.coverage.limitations.append(
                    "Scanner пропустил небезопасный или слишком большой текст."
                )
                continue
            if retained_bytes + measured_bytes > self.limits.total_bytes:
                snapshot.coverage.status = "partial"
                snapshot.coverage.limitations.append("Scanner ограничил суммарный размер текстов.")
                continue
            file.content = redact_file_text(file.path, file.content)
            files.append(file)
            retained_bytes += measured_bytes
        snapshot.files = files
        snapshot.coverage.files_read = len(files)
        snapshot.coverage.bytes_read = sum(file.size_bytes for file in files)
        stacks = {str(root.stack) for root in roots}
        stack = (
            "mixed"
            if "mixed" in stacks or {"python", "node"} <= stacks
            else next(iter(stacks), "unknown")
        )
        facts = RepositoryFacts(
            stack=stack,
            project_roots=roots,
            dependencies=[],
            runtime_hints=[],
            package_managers=[],
            entrypoints=[],
            env_var_names=[],
            data_hints=[],
            gpu_hints=[],
        )
        registry = EvidenceRegistry(snapshot)
        state = ScanState(snapshot, facts, registry, {file.path: file for file in files})
        parse_python(state)
        parse_node(state)
        extract_readme_hints(state)
        for entry in snapshot.tree:
            name = PurePosixPath(entry.path).name
            if eligible(entry) and name in LOCK_MANAGERS:
                facts.package_managers.append(
                    PackageManagerHint(
                        name=LOCK_MANAGERS[name],
                        root=root_of(entry.path),
                        evidence_ids=[registry.tree(entry.path)],
                    )
                )
        # Implicit pip loses to Python lock workflows; explicit manifest/README chooses a manager.
        managers = []
        for hint in facts.package_managers:
            ecosystem = "node" if hint.name in {"npm", "pnpm", "yarn"} else "python"
            explicit = state.explicit_managers.get((hint.root, ecosystem))
            if explicit and hint.name != explicit:
                continue
            if hint.name == "pip" and any(
                m.root == hint.root and m.name in {"uv", "poetry", "conda"}
                for m in facts.package_managers
            ):
                continue
            managers.append(hint)
        facts.package_managers = managers
        # npm is a default only when package.json has no competing lock/explicit manager.
        for root in roots:
            if (
                root.stack in {"node", "mixed"}
                and (root.path, "node") not in state.explicit_managers
                and not any(
                    m.root == root.path and m.name in {"npm", "pnpm", "yarn"} for m in managers
                )
            ):
                manifest = next(
                    (
                        f
                        for f in files
                        if root_of(f.path) == root.path and f.path.endswith("package.json")
                    ),
                    None,
                )
                if manifest and not any(
                    f.rule_id == "MANIFEST_PARSE_FAILED"
                    and any(registry.items[eid].path == manifest.path for eid in f.evidence_ids)
                    for f in state.findings
                ):
                    facts.package_managers.append(
                        PackageManagerHint(
                            name="npm", root=root.path, evidence_ids=state.file_ids(manifest)
                        )
                    )
        for field in ("dependencies", "runtime_hints", "package_managers", "entrypoints"):
            setattr(facts, field, _dedupe(getattr(facts, field)))
        for field in ("env_var_names", "data_hints", "gpu_hints"):
            setattr(facts, field, sorted(set(getattr(facts, field))))
        evaluate_risks(state)
        findings = sorted({f.id: f for f in state.findings}.values(), key=lambda f: f.id)
        evidence = sorted(registry.items.values(), key=lambda e: e.id)
        check_evidence_registry(evidence, collect_evidence_refs(facts, findings))
        return StaticAnalysis(
            repository=snapshot.repository,
            source_mode=snapshot.source_mode,
            facts=facts,
            findings=findings,
            evidence=evidence,
            coverage=snapshot.coverage,
            selected_files=files,
        )
