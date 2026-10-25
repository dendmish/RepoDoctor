"""Bounded GitHub REST reader pinned to one commit; never executes repository code."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import re
import time
from dataclasses import dataclass

import httpx
from pydantic import ValidationError

from repodoctor.contracts.api import AnalysisRequest, Coverage, RepositoryInfo
from repodoctor.contracts.domain import (
    EmptyRepositoryError,
    GitHubRateLimitedError,
    GitHubUnavailableError,
    InvalidInputError,
    RefNotFoundError,
    RepositoryNotFoundError,
    RepositorySnapshot,
    TextFile,
    TreeEntry,
    UnsupportedRepositoryError,
)
from repodoctor.repository.selection import RepositoryLimits, safe_path, select_files
from repodoctor.repository.text import redact_file_text
from repodoctor.repository.url import encode_ref_segment, normalize_ref, normalize_repo_url

_SHA = re.compile(r"[0-9a-f]{40}")


class _TooLarge(Exception):
    pass


class _Missing(Exception):
    pass


@dataclass
class _Budget:
    limits: RepositoryLimits
    deadline: float
    calls: int = 0

    def take(self) -> None:
        if self.calls >= self.limits.calls or time.monotonic() >= self.deadline:
            raise GitHubUnavailableError("Исчерпан бюджет загрузки GitHub.")
        self.calls += 1


def _sha(value: object) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise GitHubUnavailableError("GitHub вернул некорректный SHA.")
    return value


def _retry_after(headers: httpx.Headers) -> int | None:
    value = headers.get("retry-after")
    if value and value.isdigit():
        return int(value)
    reset = headers.get("x-ratelimit-reset")
    return max(0, int(reset) - int(time.time())) if reset and reset.isdigit() else None


class GitHubRepositorySource:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        token: str | None = None,
        api_version: str = "2026-03-10",
        limits: RepositoryLimits | None = None,
    ) -> None:
        self.client = client
        self.limits = limits or RepositoryLimits()
        self._headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "RepoDoctor/0.1",
            "X-GitHub-Api-Version": api_version,
        }
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

    async def request_json_limited(self, path: str, budget: _Budget, max_bytes: int) -> dict:
        for attempt in range(2):
            budget.take()
            try:
                async with self.client.stream(
                    "GET",
                    "https://api.github.com" + path,
                    headers=self._headers,
                    follow_redirects=False,
                    auth=None,
                    timeout=httpx.Timeout(10, connect=5),
                ) as response:
                    if response.status_code in {502, 503, 504} and attempt == 0:
                        continue
                    chunks = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(chunks) + len(chunk) > max_bytes:
                            raise _TooLarge
                        chunks.extend(chunk)
                    try:
                        data = json.loads(chunks)
                    except (ValueError, UnicodeDecodeError):
                        data = None
                    message = data.get("message", "") if isinstance(data, dict) else ""
                    if response.status_code == 429 or (
                        response.status_code == 403
                        and (
                            response.headers.get("x-ratelimit-remaining") == "0"
                            or (isinstance(message, str) and "rate limit" in message.lower())
                        )
                    ):
                        raise GitHubRateLimitedError(
                            "GitHub ограничил частоту запросов. Повторите позже.",
                            retry_after_seconds=_retry_after(response.headers),
                        )
                    if response.status_code == 404:
                        raise _Missing
                    if response.status_code == 409:
                        raise EmptyRepositoryError("У репозитория пока нет доступного commit/tree.")
                    if response.is_redirect:
                        raise GitHubUnavailableError(
                            "Вставьте актуальный canonical URL репозитория."
                        )
                    if response.status_code != 200 or not isinstance(data, dict):
                        raise GitHubUnavailableError("GitHub недоступен или вернул неверный ответ.")
                    return data
            except httpx.TransportError:
                if attempt:
                    raise GitHubUnavailableError("Сетевая ошибка при чтении GitHub.") from None
        raise GitHubUnavailableError("Не удалось прочитать GitHub.")

    async def fetch(self, request: AnalysisRequest) -> RepositorySnapshot:
        identity = normalize_repo_url(request.repo_url)
        ref = normalize_ref(request.ref)
        budget = _Budget(self.limits, time.monotonic() + self.limits.timeout_seconds)
        try:
            async with asyncio.timeout(self.limits.timeout_seconds):
                return await self._fetch(identity.url, ref, budget)
        except TimeoutError:
            raise GitHubUnavailableError("Истёк общий срок загрузки GitHub.") from None
        except _TooLarge:
            raise GitHubUnavailableError("Ответ GitHub превысил ограничение размера.") from None
        except (KeyError, TypeError, ValueError, ValidationError, InvalidInputError):
            raise GitHubUnavailableError("GitHub вернул некорректные метаданные.") from None

    async def _fetch(self, url: str, ref: str | None, budget: _Budget) -> RepositorySnapshot:
        identity = normalize_repo_url(url)
        prefix = f"/repos/{identity.owner}/{identity.repo}"
        try:
            metadata = await self.request_json_limited(prefix, budget, self.limits.json_bytes)
        except _Missing:
            raise RepositoryNotFoundError("Репозиторий не найден или недоступен.") from None
        if metadata.get("private") is not False:
            raise UnsupportedRepositoryError("Поддерживаются только публичные репозитории.")
        canonical = normalize_repo_url(
            f"https://github.com/{metadata['owner']['login']}/{metadata['name']}"
        )
        if canonical != identity:
            raise GitHubUnavailableError("Метаданные относятся к другому репозиторию.")
        branch = normalize_ref(metadata["default_branch"])
        if branch is None:
            raise EmptyRepositoryError("У репозитория нет ветки по умолчанию.")
        try:
            commit = await self.request_json_limited(
                prefix + "/commits/" + encode_ref_segment(ref or branch),
                budget,
                self.limits.json_bytes,
            )
        except _Missing:
            raise RefNotFoundError("Указанный ref не найден.") from None
        repository = RepositoryInfo(
            owner=identity.owner,
            name=identity.repo,
            url=identity.url,
            default_branch=branch,
            resolved_commit=_sha(commit["sha"]),
            description=(
                redact_file_text("metadata", metadata["description"])
                if isinstance(metadata.get("description"), str)
                else metadata.get("description")
            ),
        )
        limitations: list[str] = []
        try:
            raw = await self.request_json_limited(
                prefix + "/git/trees/" + _sha(commit["commit"]["tree"]["sha"]) + "?recursive=1",
                budget,
                self.limits.tree_bytes,
            )
        except _TooLarge:
            raw = {"tree": [], "truncated": True}
            limitations.append("Ответ дерева превысил лимит; сохранены только метаданные.")
        except (_Missing, GitHubUnavailableError):
            raw = {"tree": [], "truncated": True}
            limitations.append("Дерево недоступно; сохранены только метаданные.")
        if not isinstance(raw.get("tree"), list) or not isinstance(raw.get("truncated"), bool):
            raise GitHubUnavailableError("Некорректный ответ дерева GitHub.")
        if raw["truncated"]:
            limitations.append("GitHub вернул truncated tree: отсутствие файлов не доказано.")
        if len(raw["tree"]) > self.limits.tree_entries:
            limitations.append("Дерево ограничено локальным лимитом числа записей.")
        tree: list[TreeEntry] = []
        seen: set[str] = set()
        # Sort before limiting so selection is independent of upstream order.
        items = raw["tree"]
        if not all(isinstance(item, dict) and isinstance(item.get("path"), str) for item in items):
            raise GitHubUnavailableError("Некорректные записи дерева GitHub.")
        for item in sorted(items, key=lambda item: item["path"])[: self.limits.tree_entries]:
            try:
                entry = TreeEntry(
                    **{key: item.get(key) for key in ("path", "type", "mode", "sha", "size")}
                )
                if not safe_path(entry.path) or entry.path in seen:
                    raise ValueError
                _sha(entry.sha)
            except (ValidationError, ValueError):
                limitations.append("Пропущена некорректная запись дерева.")
                continue
            tree.append(entry)
            seen.add(entry.path)
        files: list[TextFile] = []
        attempted: set[str] = set()
        selected_count = 0
        # Second pass can load a few entrypoints referenced by the first-pass manifests/README.
        for _ in range(2):
            selected, notes = select_files(tree, self.limits, files)
            limitations.extend(notes)
            pending = [e for e in selected if e.path not in attempted]
            pending = pending[: max(0, self.limits.files - selected_count)]
            selected_count += len(pending)
            attempted.update(e.path for e in pending)
            for start in range(0, len(pending), self.limits.parallel_blobs):
                batch = pending[start : start + self.limits.parallel_blobs]
                results = await asyncio.gather(
                    *(self._blob(prefix, e, budget) for e in batch), return_exceptions=True
                )
                # Commit in selected order, not completion order: byte budget is deterministic.
                for entry, result in zip(batch, results, strict=True):
                    if isinstance(result, BaseException):
                        raise result
                    if isinstance(result, str):
                        limitations.append(f"Пропущен {entry.path}: {result}")
                    elif (
                        sum(f.size_bytes for f in files) + result.size_bytes
                        > self.limits.total_bytes
                    ):
                        limitations.append(
                            f"Пропущен {entry.path}: суммарный бюджет текстов исчерпан."
                        )
                    else:
                        files.append(result)
        return RepositorySnapshot(
            repository=repository,
            source_mode="github",
            tree=tree,
            files=files,
            coverage=Coverage(
                status="partial" if limitations else "complete",
                tree_entries_seen=len(tree),
                files_selected=selected_count,
                files_read=len(files),
                bytes_read=sum(f.size_bytes for f in files),
                limitations=list(dict.fromkeys(limitations)),
            ),
        )

    async def _blob(self, prefix: str, entry: TreeEntry, budget: _Budget) -> TextFile | str:
        try:
            blob = await self.request_json_limited(
                prefix + "/git/blobs/" + entry.sha, budget, self.limits.json_bytes
            )
            if blob.get("encoding") != "base64" or not isinstance(blob.get("content"), str):
                return "неподдерживаемая кодировка blob."
            raw = base64.b64decode(re.sub(r"[\r\n]", "", blob["content"]), validate=True)
            if len(raw) > self.limits.file_bytes:
                return "decoded файл превышает лимит."
            actual = hashlib.sha1(
                f"blob {len(raw)}\0".encode() + raw, usedforsecurity=False
            ).hexdigest()
            if actual != entry.sha or blob.get("sha", entry.sha) != entry.sha:
                return "SHA blob не соответствует дереву."
            if blob.get("size") != len(raw) or (entry.size is not None and entry.size != len(raw)):
                return "размер blob не соответствует метаданным."
            content = raw.decode("utf-8")
            if "\x00" in content:
                return "бинарный файл."
            if content.startswith("version https://git-lfs.github.com/spec/v1"):
                return "LFS pointer; внешний объект не скачивался."
            return TextFile(
                path=entry.path,
                content=redact_file_text(entry.path, content),
                size_bytes=len(raw),
                sha=entry.sha,
            )
        except (ValueError, UnicodeDecodeError, binascii.Error):
            return "невалидный base64 или UTF-8."
        except (_TooLarge, _Missing, GitHubUnavailableError):
            return "blob недоступен или превышает бюджет загрузки."
