"""Offline RepositorySource reading explicit, pre-redacted synthetic snapshots.

No imports of repository code, shell commands, HTTP clients, or example API responses.
Shared A2 redaction can be injected; the G0 fixture library is already sanitized.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import httpx
from pydantic import Field, ValidationError

from repodoctor.config import PROJECT_ROOT, Settings
from repodoctor.contracts.api import AnalysisRequest, ContractModel, SourceMode
from repodoctor.contracts.domain import (
    RefNotFoundError,
    RepoDoctorError,
    RepositoryNotFoundError,
    RepositorySnapshot,
)
from repodoctor.contracts.ports import RepositorySource
from repodoctor.repository.url import normalize_ref, normalize_repo_url
from repodoctor.security.redaction import redact_text

Redactor = Callable[[str], tuple[str, int]]
_SYNTHETIC_NOTICE = "SYNTHETIC fixture: локальные данные; репозиторий не загружался с GitHub."


class FixtureLibraryError(RepoDoctorError):
    """Broken local installation, distinct from an unknown user-supplied repo/ref."""


class _FixtureEntry(ContractModel):
    id: str
    url: str
    snapshot: str
    refs: list[str] = Field(min_length=1)
    expected: dict[str, object]


class _FixtureIndex(ContractModel):
    schema_version: str
    repositories: list[_FixtureEntry]


def _safe_file(root: Path, relative: str) -> Path:
    """Only ordinary files beneath the configured library, never symlink targets."""
    parts = relative.split("/")
    if not relative or "\\" in relative or any(part in {"", ".", ".."} for part in parts):
        raise FixtureLibraryError("Некорректный путь в локальной библиотеке fixtures.")
    candidate = root
    for part in parts:
        candidate /= part
        if candidate.is_symlink():
            raise FixtureLibraryError("Символические ссылки в fixtures не поддерживаются.")
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise FixtureLibraryError("Путь fixture выходит за пределы локальной библиотеки.")
    return candidate


def _check_env_examples(snapshot: RepositorySnapshot) -> None:
    """Fail closed on non-placeholder env values; not a competing secret masker."""
    for file in snapshot.files:
        if file.path.rsplit("/", 1)[-1] != ".env.example":
            continue
        for line in file.content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            _, separator, value = stripped.partition("=")
            if not separator or value.strip() not in {"", "[REDACTED]"}:
                raise FixtureLibraryError("Значения .env.example должны быть очищены заранее.")


class FixtureRepositorySource:
    """RepositorySource port; `fixtures_dir` is Settings.fixtures_dir (not its child).

    Instantiate with `FixtureRepositorySource(settings.fixtures_dir,
    redactor=redact_text)` when the shared A2 sanitizer becomes available.
    With no redactor the checked-in, pre-redacted library is usable at G0.
    """

    def __init__(
        self, fixtures_dir: Path | None = None, *, redactor: Redactor | None = None
    ) -> None:
        self._root = fixtures_dir if fixtures_dir is not None else PROJECT_ROOT / "fixtures"
        self._root = self._root / "repositories"
        self._redactor = redactor
        try:
            index = _FixtureIndex.model_validate_json(
                _safe_file(self._root, "index.json").read_text(encoding="utf-8")
            )
            if index.schema_version != "1.0":
                raise FixtureLibraryError("Неподдерживаемая версия fixture index.")
            self._entries: dict[str, _FixtureEntry] = {}
            for entry in index.repositories:
                normalized = normalize_repo_url(entry.url)
                if normalized.owner != "repodoctor-fixtures" or normalized.url in self._entries:
                    raise FixtureLibraryError("Некорректная идентичность fixture в index.")
                if entry.url != normalized.url:
                    raise FixtureLibraryError("URL в fixture index должен быть каноническим.")
                self._entries[entry.url] = entry
        except (OSError, ValidationError, ValueError) as exc:
            raise FixtureLibraryError("Не удалось прочитать локальный fixture index.") from exc

    async def fetch(self, request: AnalysisRequest) -> RepositorySnapshot:
        normalized = normalize_repo_url(request.repo_url)
        ref = normalize_ref(request.ref)
        entry = self._entries.get(normalized.url)
        if entry is None:
            raise RepositoryNotFoundError(
                "Fixture-режим поддерживает только заранее заданные синтетические репозитории.",
                details=sorted(self._entries),
            )
        try:
            snapshot = RepositorySnapshot.model_validate_json(
                _safe_file(self._root, entry.snapshot).read_text(encoding="utf-8")
            )
        except (OSError, ValidationError, ValueError) as exc:
            raise FixtureLibraryError("Не удалось прочитать локальный synthetic snapshot.") from exc
        repository = snapshot.repository
        if (
            snapshot.source_mode != SourceMode.fixture
            or repository.url != normalized.url
            or repository.owner != normalized.owner
            or repository.name != normalized.repo
            or repository.default_branch not in entry.refs
        ):
            raise FixtureLibraryError("Snapshot не соответствует fixture index.")
        if ref is not None and ref not in {*entry.refs, repository.resolved_commit}:
            raise RefNotFoundError("Запрошенный ref отсутствует в синтетическом репозитории.")

        # Build a fresh model for each call; callers cannot mutate a shared cached fixture.
        # Original byte counts and blob SHAs describe text before optional A2 redaction.
        if self._redactor is not None:
            for file in snapshot.files:
                content, _ = self._redactor(file.content)
                if re.findall(r"\r\n|\r|\n", content) != re.findall(r"\r\n|\r|\n", file.content):
                    raise FixtureLibraryError("Redaction должна сохранять номера строк.")
                file.content = content
        _check_env_examples(snapshot)
        snapshot.coverage.limitations = list(
            dict.fromkeys([_SYNTHETIC_NOTICE, *snapshot.coverage.limitations])
        )
        return snapshot


def create_repository_source(
    settings: Settings, client: httpx.AsyncClient | None = None
) -> RepositorySource:
    """Factory for the composition root; client lifecycle remains owned by the platform."""
    if settings.repository_mode == "fixture":
        return FixtureRepositorySource(settings.fixtures_dir, redactor=redact_text)
    if client is None:
        raise ValueError("Live repository mode requires the platform's shared AsyncClient")
    from repodoctor.repository.github import GitHubRepositorySource

    return GitHubRepositorySource(
        client,
        token=settings.github_token.get_secret_value() if settings.github_token else None,
        api_version=settings.github_api_version,
    )
