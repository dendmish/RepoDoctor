"""AnalysisService: fetch → scan → plan → store, under one slot and one deadline."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta

from repodoctor.contracts.api import (
    SCHEMA_VERSION,
    AnalysisRequest,
    AnalysisResponse,
    Evidence,
    Finding,
    format_utc,
)
from repodoctor.contracts.domain import (
    AnalysisContext,
    AnalysisTimeoutError,
    PlanResult,
    RepoDoctorError,
    StaticAnalysis,
)
from repodoctor.contracts.ports import (
    AnalysisStore,
    IntelligenceService,
    RepositorySource,
    StaticAnalyzer,
)
from repodoctor.observability import log_event
from repodoctor.security.limits import OperationLimiter
from repodoctor.services.store import MAX_CONTEXT_BYTES, context_size_bytes

CONTEXT_TRIM_NOTE = (
    "Часть выбранных файлов не сохранена для диагностики: превышен лимит памяти анализа."
)


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_uuid() -> str:
    return str(uuid.uuid4())


def dedupe_by_id[T: (Evidence, Finding)](items: Iterable[T]) -> list[T]:
    """Keep the first occurrence of each ID; static entries come first and win."""
    seen: set[str] = set()
    result: list[T] = []
    for item in items:
        if item.id not in seen:
            seen.add(item.id)
            result.append(item)
    return result


class AnalysisService:
    def __init__(
        self,
        *,
        source: RepositorySource,
        analyzer: StaticAnalyzer,
        intelligence: IntelligenceService,
        store: AnalysisStore,
        limiter: OperationLimiter,
        ttl_seconds: float,
        timeout_seconds: float,
        max_context_bytes: int = MAX_CONTEXT_BYTES,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], str] = new_uuid,
    ) -> None:
        self._source = source
        self._analyzer = analyzer
        self._intelligence = intelligence
        self._store = store
        self._limiter = limiter
        self._ttl = timedelta(seconds=ttl_seconds)
        self._timeout = timeout_seconds
        self._max_context_bytes = max_context_bytes
        self._clock = clock
        self._new_id = id_factory

    async def analyze(self, request: AnalysisRequest) -> AnalysisResponse:
        async with self._limiter.acquire_operation_slot():
            try:
                async with asyncio.timeout(self._timeout):
                    scan, plan = await self._run_pipeline(request)
            except TimeoutError as exc:
                log_event("analysis_timeout", timeout_s=self._timeout)
                raise AnalysisTimeoutError(
                    "Анализ не уложился в отведённое время. Повторите позже."
                ) from exc
            response, context = self._assemble(request, scan, plan)
            self._store.put(context)
        log_event(
            "analysis_done",
            analysis_id=response.analysis_id,
            source_mode=response.source_mode,
            generation=response.generation.mode,
            findings=len(response.findings),
            evidence=len(response.evidence),
            steps=len(response.run_plan.steps),
        )
        return response

    async def _run_pipeline(self, request: AnalysisRequest) -> tuple[StaticAnalysis, PlanResult]:
        started = time.monotonic()
        snapshot = await self._source.fetch(request)
        log_event(
            "phase_fetch",
            duration_ms=_ms(started),
            tree_entries=len(snapshot.tree),
            files=len(snapshot.files),
        )
        started = time.monotonic()
        # Scanner is synchronous CPU work: keep it off the event loop.
        scan = await asyncio.to_thread(self._analyzer.analyze, snapshot)
        log_event("phase_scan", duration_ms=_ms(started), findings=len(scan.findings))
        started = time.monotonic()
        plan = await self._intelligence.build_plan(scan, request.target, request.use_ai)
        log_event("phase_plan", duration_ms=_ms(started), generation=plan.generation.mode)
        return scan, plan

    def _assemble(
        self, request: AnalysisRequest, scan: StaticAnalysis, plan: PlanResult
    ) -> tuple[AnalysisResponse, AnalysisContext]:
        now = self._clock()
        response = AnalysisResponse(
            schema_version=SCHEMA_VERSION,
            analysis_id=self._new_id(),
            created_at=format_utc(now),
            expires_at=format_utc(now + self._ttl),
            source_mode=scan.source_mode,
            repository=scan.repository,
            target=request.target,
            facts=scan.facts,
            coverage=scan.coverage,
            findings=dedupe_by_id([*scan.findings, *plan.additional_findings]),
            evidence=dedupe_by_id([*scan.evidence, *plan.evidence]),
            run_plan=plan.run_plan,
            generation=plan.generation,
            warnings=list(plan.warnings),
        )
        return self._fit_context(response, scan)

    def _fit_context(
        self, response: AnalysisResponse, scan: StaticAnalysis
    ) -> tuple[AnalysisResponse, AnalysisContext]:
        """Drop stored excerpts (selected files) until the context fits; keep response and
        stored context consistent by recording the limitation in both."""
        context = AnalysisContext(response=response, scan=scan)
        if context_size_bytes(context) <= self._max_context_bytes:
            return response, context

        files = list(scan.selected_files)
        coverage = response.coverage.model_copy(
            update={"limitations": [*response.coverage.limitations, CONTEXT_TRIM_NOTE]}
        )
        response = response.model_copy(
            update={"coverage": coverage, "warnings": [*response.warnings, CONTEXT_TRIM_NOTE]}
        )
        while files:
            files.pop()
            trimmed = scan.model_copy(update={"selected_files": files, "coverage": coverage})
            context = AnalysisContext(response=response, scan=trimmed)
            if context_size_bytes(context) <= self._max_context_bytes:
                log_event("context_trimmed", kept_files=len(files))
                return response, context
        trimmed = scan.model_copy(update={"selected_files": [], "coverage": coverage})
        context = AnalysisContext(response=response, scan=trimmed)
        if context_size_bytes(context) > self._max_context_bytes:
            raise RepoDoctorError("Результат анализа слишком велик для сохранения.")
        return response, context


def _ms(started: float) -> int:
    return round((time.monotonic() - started) * 1000)
