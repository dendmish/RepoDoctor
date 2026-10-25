"""DiagnosisService: stored context + sanitized log → intelligence → DiagnosisResponse."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime

from repodoctor.contracts.api import (
    SCHEMA_VERSION,
    DiagnosisRequest,
    DiagnosisResponse,
    format_utc,
)
from repodoctor.contracts.domain import AnalysisNotFoundError, AnalysisTimeoutError
from repodoctor.contracts.ports import AnalysisStore, IntelligenceService
from repodoctor.observability import log_event
from repodoctor.security.limits import OperationLimiter
from repodoctor.security.redaction import redact_text, sanitize_log
from repodoctor.services.analysis import new_uuid, utc_now


class DiagnosisService:
    def __init__(
        self,
        *,
        intelligence: IntelligenceService,
        store: AnalysisStore,
        limiter: OperationLimiter,
        timeout_seconds: float,
        clock: Callable[[], datetime] = utc_now,
        id_factory: Callable[[], str] = new_uuid,
    ) -> None:
        self._intelligence = intelligence
        self._store = store
        self._limiter = limiter
        self._timeout = timeout_seconds
        self._clock = clock
        self._new_id = id_factory

    async def diagnose(self, analysis_id: str, request: DiagnosisRequest) -> DiagnosisResponse:
        context = self._store.get(analysis_id)
        if context is None:
            raise AnalysisNotFoundError(
                "Анализ не найден или устарел (TTL, перезапуск сервера). Запустите анализ повторно."
            )
        # The raw log lives only in this call frame: it is never stored or logged.
        log = sanitize_log(request.log)
        command = redact_text(request.command)[0] if request.command is not None else None

        async with self._limiter.acquire_operation_slot():
            try:
                async with asyncio.timeout(self._timeout):
                    result = await self._intelligence.diagnose(
                        context, log, command, request.use_ai
                    )
            except TimeoutError as exc:
                log_event("diagnosis_timeout", timeout_s=self._timeout)
                raise AnalysisTimeoutError(
                    "Диагностика не уложилась в отведённое время. Повторите позже."
                ) from exc

        warnings = list(result.warnings)
        if log.redactions_count:
            warnings.append(
                f"В логе замаскировано фрагментов, похожих на секреты: {log.redactions_count}."
            )
        response = DiagnosisResponse(
            schema_version=SCHEMA_VERSION,
            diagnosis_id=self._new_id(),
            analysis_id=analysis_id,
            created_at=format_utc(self._clock()),
            generation=result.generation,
            summary=result.summary,
            causes=result.causes,
            questions=result.questions,
            evidence=result.evidence,
            warnings=warnings,
        )
        log_event(
            "diagnosis_done",
            analysis_id=analysis_id,
            generation=response.generation.mode,
            causes=len(response.causes),
            redactions=log.redactions_count,
            log_lines=log.text.count("\n") + 1,
        )
        return response
