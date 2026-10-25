"""Protocol-compatible test doubles built from the normative examples (no network)."""

from __future__ import annotations

import asyncio

from repodoctor.contracts.api import (
    AnalysisRequest,
    AnalysisResponse,
    DiagnosisResponse,
    Evidence,
    Finding,
    GenerationInfo,
    TargetEnvironment,
)
from repodoctor.contracts.domain import (
    AnalysisContext,
    DiagnosisResult,
    PlanResult,
    RepositorySnapshot,
    SanitizedLog,
    StaticAnalysis,
    TextFile,
)

from .conftest import load_example

PYTHON_EXAMPLE = AnalysisResponse.model_validate(load_example("analysis_python.json"))
DIAGNOSIS_EXAMPLE = DiagnosisResponse.model_validate(load_example("diagnosis_python.json"))

FALLBACK = GenerationInfo(
    mode="fallback", reason="disabled_by_user", model=None, prompt_version="fallback-v1"
)


def make_files(count: int = 2, size: int = 64) -> list[TextFile]:
    return [
        TextFile(path=f"file_{i}.txt", content="x" * size, size_bytes=size, sha=f"{i:040x}")
        for i in range(count)
    ]


class FakeSource:
    def __init__(self, files: list[TextFile] | None = None) -> None:
        self.files = files if files is not None else make_files()
        self.calls = 0
        self.gate: asyncio.Event | None = None
        self.started = asyncio.Event()
        self.delay = 0.0

    async def fetch(self, request: AnalysisRequest) -> RepositorySnapshot:
        self.calls += 1
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.delay:
            await asyncio.sleep(self.delay)
        return RepositorySnapshot(
            repository=PYTHON_EXAMPLE.repository,
            source_mode=PYTHON_EXAMPLE.source_mode,
            tree=[],
            files=self.files,
            coverage=PYTHON_EXAMPLE.coverage,
        )


class FakeAnalyzer:
    def analyze(self, snapshot: RepositorySnapshot) -> StaticAnalysis:
        return StaticAnalysis(
            repository=snapshot.repository,
            source_mode=snapshot.source_mode,
            facts=PYTHON_EXAMPLE.facts,
            findings=PYTHON_EXAMPLE.findings,
            evidence=PYTHON_EXAMPLE.evidence,
            coverage=snapshot.coverage,
            selected_files=snapshot.files,
        )


class FakeIntelligence:
    def __init__(self) -> None:
        self.received_logs: list[SanitizedLog] = []
        self.received_commands: list[str | None] = []
        self.diagnose_delay = 0.0

    async def build_plan(
        self, scan: StaticAnalysis, target: TargetEnvironment, use_ai: bool
    ) -> PlanResult:
        extra = Finding(
            id="AI_NOTE:.",
            rule_id="AI_NOTE",
            title="AI note",
            description="",
            severity="info",
            confidence="low",
            origin="ai",
            evidence_ids=["ev_requirements"],
            suggested_action="",
        )
        duplicate_static = scan.findings[0]  # must not be duplicated in the response
        # AI re-references an existing evidence item: must be deduplicated by ID.
        reused: list[Evidence] = [scan.evidence[0]]
        return PlanResult(
            run_plan=PYTHON_EXAMPLE.run_plan,
            additional_findings=[duplicate_static, extra],
            evidence=reused,
            generation=PYTHON_EXAMPLE.generation if use_ai else FALLBACK,
            warnings=[] if use_ai else ["AI отключён пользователем."],
        )

    async def diagnose(
        self,
        context: AnalysisContext,
        log: SanitizedLog,
        command: str | None,
        use_ai: bool,
    ) -> DiagnosisResult:
        self.received_logs.append(log)
        self.received_commands.append(command)
        if self.diagnose_delay:
            await asyncio.sleep(self.diagnose_delay)
        return DiagnosisResult(
            summary=DIAGNOSIS_EXAMPLE.summary,
            causes=DIAGNOSIS_EXAMPLE.causes,
            questions=DIAGNOSIS_EXAMPLE.questions,
            evidence=DIAGNOSIS_EXAMPLE.evidence,
            generation=DIAGNOSIS_EXAMPLE.generation if use_ai else FALLBACK,
            warnings=[],
        )
