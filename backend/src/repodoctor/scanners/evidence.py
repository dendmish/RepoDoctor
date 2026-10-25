"""Deterministic evidence registry over sanitized text and observed tree entries."""

from __future__ import annotations

import hashlib
from urllib.parse import quote

from repodoctor.contracts.api import Evidence
from repodoctor.contracts.domain import RepositorySnapshot, TextFile
from repodoctor.repository.selection import safe_path
from repodoctor.repository.text import redact_file_text


def stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode()).hexdigest()[:20]
    return f"{prefix}_{digest}"


class EvidenceRegistry:
    def __init__(self, snapshot: RepositorySnapshot) -> None:
        self.snapshot = snapshot
        self.items: dict[str, Evidence] = {}

    def _url(self, path: str, start: int | None, end: int | None) -> str | None:
        if self.snapshot.source_mode == "fixture":
            return None
        repo = self.snapshot.repository
        url = f"{repo.url}/blob/{repo.resolved_commit}/{quote(path, safe='/')}"
        return url + (f"#L{start}-L{end}" if start is not None else "")

    def file(self, file: TextFile, start: int = 1, end: int | None = None) -> str:
        lines = file.content.splitlines()
        if not lines or not safe_path(file.path):
            raise ValueError("File evidence requires actual text lines and a safe path")
        end = start if end is None else end
        if not 1 <= start <= end <= len(lines):
            raise ValueError("Evidence line span is outside the selected text")
        key = stable_id("file", file.path, str(start), str(end))
        self.items[key] = Evidence(
            id=key,
            source="file",
            path=file.path,
            line_start=start,
            line_end=end,
            excerpt=redact_file_text(file.path, "\n".join(lines[start - 1 : end]))[:500],
            url=self._url(file.path, start, end),
        )
        return key

    def match(self, file: TextFile, text: str) -> str:
        for number, line in enumerate(file.content.splitlines(), 1):
            if text in line:
                return self.file(file, number)
        return self.file(file)

    def tree(self, path: str) -> str:
        entry = next((item for item in self.snapshot.tree if item.path == path), None)
        if entry is None or not safe_path(path):
            raise ValueError("Tree evidence requires an observed path")
        key = stable_id("tree", path)
        self.items[key] = Evidence(
            id=key,
            source="tree",
            path=path,
            line_start=None,
            line_end=None,
            excerpt=f"Наблюдаемая запись дерева: {path} ({entry.type}, mode {entry.mode}).",
            url=self._url(path, None, None),
        )
        return key
