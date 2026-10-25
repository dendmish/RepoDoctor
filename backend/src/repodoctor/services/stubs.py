"""DEV-ONLY stub services that replay the normative examples from contracts/examples.

Enabled only with USE_DEV_STUBS=true outside production. They never analyze a repository:
only the synthetic example URLs are accepted, every response carries a "DEV STUB" warning
and source_mode stays `fixture`. Replaced by real services in A2/A3.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from repodoctor.contracts.api import (
    AnalysisRequest,
    AnalysisResponse,
    DiagnosisRequest,
    DiagnosisResponse,
    format_utc,
)
from repodoctor.contracts.domain import AnalysisNotFoundError, RepositoryNotFoundError

STUB_WARNING = "DEV STUB: синтетический пример из contracts/examples, а не анализ репозитория."

# example analysis file -> diagnosis example replayed for it
_ANALYSIS_EXAMPLES: dict[str, str] = {
    "analysis_python.json": "diagnosis_python.json",
    "analysis_node.json": "diagnosis_unknown.json",
    "analysis_needs_input.json": "diagnosis_unknown.json",
}


def _normalize_url(url: str) -> str:
    url = url.strip().rstrip("/")
    return url.removesuffix(".git").lower()


class _ExampleLibrary:
    def __init__(self, examples_dir: Path) -> None:
        self._dir = examples_dir
        self.analyses: dict[str, tuple[str, dict]] = {}
        for name in _ANALYSIS_EXAMPLES:
            data = self.load(name)
            self.analyses[_normalize_url(data["repository"]["url"])] = (name, data)

    def load(self, name: str) -> dict:
        return json.loads((self._dir / name).read_text(encoding="utf-8"))


class StubAnalysisService:
    def __init__(self, examples_dir: Path, ttl_seconds: int) -> None:
        self._library = _ExampleLibrary(examples_dir)
        self._ttl = timedelta(seconds=ttl_seconds)
        self.issued: dict[str, str] = {}  # analysis_id -> analysis example name

    @property
    def library(self) -> _ExampleLibrary:
        return self._library

    async def analyze(self, request: AnalysisRequest) -> AnalysisResponse:
        match = self._library.analyses.get(_normalize_url(request.repo_url))
        if match is None:
            raise RepositoryNotFoundError(
                "Dev stub знает только синтетические примеры.",
                details=sorted(self._library.analyses),
            )
        name, data = match
        data = json.loads(json.dumps(data))
        now = datetime.now(UTC)
        data["analysis_id"] = str(uuid.uuid4())
        data["created_at"] = format_utc(now)
        data["expires_at"] = format_utc(now + self._ttl)
        warnings = [STUB_WARNING]
        requested = request.target
        if (requested.os, requested.shell) != (data["target"]["os"], data["target"]["shell"]):
            warnings.append(
                f"DEV STUB: пример подготовлен для {data['target']['os']}/"
                f"{data['target']['shell']}; запрошенное окружение "
                f"{requested.os}/{requested.shell} не применено."
            )
        data["warnings"] = warnings + data["warnings"]
        self.issued[data["analysis_id"]] = name
        return AnalysisResponse.model_validate(data)


class StubDiagnosisService:
    def __init__(self, analyses: StubAnalysisService) -> None:
        self._analyses = analyses

    async def diagnose(self, analysis_id: str, request: DiagnosisRequest) -> DiagnosisResponse:
        name = self._analyses.issued.get(analysis_id)
        if name is None:
            raise AnalysisNotFoundError("Анализ не найден или устарел. Запустите анализ повторно.")
        data = self._analyses.library.load(_ANALYSIS_EXAMPLES[name])
        data["diagnosis_id"] = str(uuid.uuid4())
        data["analysis_id"] = analysis_id
        data["created_at"] = format_utc(datetime.now(UTC))
        data["warnings"] = [STUB_WARNING, *data["warnings"]]
        return DiagnosisResponse.model_validate(data)
