from __future__ import annotations

import json
from pathlib import Path

import pytest

from repodoctor.contracts.api import AnalysisResponse
from repodoctor.contracts.domain import StaticAnalysis, TextFile

EXAMPLES = Path(__file__).resolve().parents[3] / "contracts" / "examples"


def scan_from_example(name: str) -> StaticAnalysis:
    response = AnalysisResponse.model_validate_json((EXAMPLES / name).read_text(encoding="utf-8"))
    return StaticAnalysis(
        repository=response.repository,
        source_mode=response.source_mode,
        facts=response.facts,
        findings=response.findings,
        evidence=response.evidence,
        coverage=response.coverage,
        selected_files=[],
    )


def selected_file(path: str, content: str) -> TextFile:
    return TextFile(path=path, content=content, size_bytes=len(content.encode()), sha="a" * 40)


@pytest.fixture
def python_scan() -> StaticAnalysis:
    scan = scan_from_example("analysis_python.json")
    # A standalone root module can run after requirements installation. The normative
    # example has src-layout, for which our conservative planner asks a question instead.
    tree = next(ev for ev in scan.evidence if ev.id == "ev_tree_main")
    tree.path = "demo_cli/__main__.py"
    tree.url = None
    return scan


@pytest.fixture
def node_scan() -> StaticAnalysis:
    scan = scan_from_example("analysis_node.json")
    content = json.dumps(
        {"scripts": {"start": "node src/server.js"}, "engines": {"node": ">=22.12"}}
    )
    scan.selected_files = [selected_file("package.json", content)]
    return scan
