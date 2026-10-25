"""Regression (ludovic111/horizon, 2026-10-25): a website hardware table produced 91 GPU
evidence lines, step_resources cited 92, and even an exact copy of the server baseline
failed `list_limit`, so GigaChat answers were always discarded."""

from __future__ import annotations

import pytest

from repodoctor.contracts.api import Evidence, Finding
from repodoctor.intelligence import rules
from repodoctor.intelligence.provider import ModelPlanOutput
from repodoctor.intelligence.rules import build_fallback_plan
from repodoctor.intelligence.validation import OutputRejected, validate_plan
from repodoctor.scanners.common import MAX_SIGNAL_EVIDENCE
from tests.intelligence.test_ai import TARGET
from tests.repository.test_scanners import analyze

HARDWARE_TABLE = "\n".join(
    f'  {{ name: "NVIDIA GeForce RTX {4000 + i}", tflops: {i}, vram_gb: 8 }},  // GPU'
    for i in range(80)
)


def test_gpu_signal_is_capped_and_unused_lines_are_not_registered():
    scan = analyze(
        {
            "package.json": '{"name": "site", "scripts": {"start": "node serve.mjs"}}',
            "src/hardware.js": HARDWARE_TABLE,
        }
    )
    gpu = next(f for f in scan.findings if f.rule_id == "GPU_REQUIREMENT_UNCLEAR")
    assert len(gpu.evidence_ids) == MAX_SIGNAL_EVIDENCE
    hardware_evidence = [ev for ev in scan.evidence if ev.path == "src/hardware.js"]
    assert len(hardware_evidence) == MAX_SIGNAL_EVIDENCE
    plan = build_fallback_plan(scan, TARGET)
    resources = next(step for step in plan.steps if step.id == "step_resources")
    assert 0 < len(resources.evidence_ids) <= rules.MAX_RESOURCE_EVIDENCE


def test_exact_baseline_copy_passes_for_scanned_repository():
    scan = analyze({"package.json": "{}", "src/hardware.js": HARDWARE_TABLE})
    baseline = build_fallback_plan(scan, TARGET)
    validate_plan(ModelPlanOutput(run_plan=baseline, additional_findings=[]), scan, TARGET)


def _scan_with_many_sources(node_scan, count: int):
    extra = [
        Evidence(
            id=f"ev_gpu_{i}",
            source="tree",
            path=f"src/gpu_{i}.js",
            line_start=None,
            line_end=None,
            excerpt="Наблюдаемая запись дерева.",
            url=None,
        )
        for i in range(count)
    ]
    finding = Finding(
        id="finding_gpu",
        rule_id="GPU_REQUIREMENT_UNCLEAR",
        title="GPU REQUIREMENT UNCLEAR",
        description="Есть GPU/CUDA hints; необходимость GPU не доказана.",
        severity="warning",
        confidence="medium",
        origin="static",
        evidence_ids=[ev.id for ev in extra],
        suggested_action="Уточните CPU/GPU workflow.",
    )
    scan = node_scan.model_copy(deep=True)
    scan.evidence.extend(extra)
    scan.findings.append(finding)
    scan.facts.gpu_hints = ["Упоминание GPU/CUDA; необходимость и совместимость не проверены."]
    return scan


def test_exact_copy_passes_even_if_baseline_step_exceeds_list_limit(node_scan, monkeypatch):
    # Defence in depth: even if a future planner cites more than 40 sources in one step,
    # the model copying that server-built step must not be rejected.
    monkeypatch.setattr(rules, "MAX_RESOURCE_EVIDENCE", 100)
    scan = _scan_with_many_sources(node_scan, 60)
    baseline = build_fallback_plan(scan, TARGET)
    resources = next(step for step in baseline.steps if step.id == "step_resources")
    assert len(resources.evidence_ids) > 40
    validate_plan(ModelPlanOutput(run_plan=baseline, additional_findings=[]), scan, TARGET)


def test_model_cannot_inflate_a_step_beyond_its_baseline(node_scan):
    scan = _scan_with_many_sources(node_scan, 60)
    baseline = build_fallback_plan(scan, TARGET)
    inflated = baseline.model_copy(deep=True)
    step = next(step for step in inflated.steps if step.id == "step_install")
    step.evidence_ids = [*step.evidence_ids, *[f"ev_gpu_{i}" for i in range(41)]]
    with pytest.raises(OutputRejected, match="list_limit"):
        validate_plan(ModelPlanOutput(run_plan=inflated, additional_findings=[]), scan, TARGET)
