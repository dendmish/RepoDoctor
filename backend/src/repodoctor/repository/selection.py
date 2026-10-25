"""Deterministic, bounded file selection; no filesystem or network access."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from pydantic import TypeAdapter, ValidationError

from repodoctor.contracts.api import RepoPath
from repodoctor.contracts.domain import TextFile, TreeEntry

PATH = TypeAdapter(RepoPath)
EXCLUDED = {".git", "node_modules", ".venv", "venv", "dist", "build", "datasets", "checkpoints"}
LOCKS = {
    "uv.lock",
    "poetry.lock",
    "package-lock.json",
    "npm-shrinkwrap.json",
    "yarn.lock",
    "pnpm-lock.yaml",
}
RUNTIMES = {".python-version", ".nvmrc", ".node-version", ".env.example"}


@dataclass(frozen=True)
class RepositoryLimits:
    json_bytes: int = 512 * 1024
    tree_bytes: int = 8 * 1024 * 1024
    tree_entries: int = 20_000
    files: int = 100
    file_bytes: int = 64 * 1024
    total_bytes: int = 1024 * 1024
    subroots: int = 3
    calls: int = 108
    parallel_blobs: int = 4
    timeout_seconds: float = 35


def safe_path(path: str) -> bool:
    try:
        PATH.validate_python(path)
    except ValidationError:
        return False
    # Also prevent Windows drive syntax and control format characters in source links.
    return path != "." and ":" not in path and not any(ord(c) < 32 for c in path)


def is_manifest(path: str) -> bool:
    name = PurePosixPath(path).name
    return name in {
        "pyproject.toml",
        "package.json",
        "setup.py",
        "environment.yml",
        "environment.yaml",
    } or (name.startswith("requirements") and name.endswith(".txt"))


def is_readme(path: str) -> bool:
    return PurePosixPath(path).name.lower() in {"readme", "readme.md", "readme.rst", "readme.txt"}


def project_root_paths(tree: list[TreeEntry], limit: int = 3) -> list[str]:
    roots = {str(PurePosixPath(e.path).parent) for e in tree if is_manifest(e.path) and eligible(e)}
    nested = sorted(roots - {"."}, key=lambda p: (p.count("/"), p))
    return (["."] if "." in roots else []) + nested[:limit]


def eligible(entry: TreeEntry) -> bool:
    if not safe_path(entry.path) or entry.type != "blob" or entry.mode not in {"100644", "100755"}:
        return False
    parts = PurePosixPath(entry.path).parts
    name = parts[-1]
    return not (
        set(parts[:-1]) & EXCLUDED
        or name == ".env"
        or (name.startswith(".env.") and name != ".env.example")
        or name.lower().endswith((".pem", ".key", ".p12", ".pfx", ".csv", ".bin", ".pt", ".pth"))
        or name in {"id_rsa", "id_ed25519"}
    )


def select_files(
    tree: list[TreeEntry], limits: RepositoryLimits, loaded: list[TextFile] | None = None
) -> tuple[list[TreeEntry], list[str]]:
    roots = set(project_root_paths(tree, limits.subroots)) | {"."}
    nested = {
        str(PurePosixPath(e.path).parent) for e in tree if is_manifest(e.path) and eligible(e)
    } - {"."}
    limitations = []
    if len(nested) > limits.subroots:
        limitations.append(
            "Число вложенных project roots превышает лимит; выбраны первые по глубине и пути."
        )
    loaded = loaded or []
    # Only source paths mentioned in selected text can become second-pass candidates.
    mentions = "\n".join(f.content for f in loaded)
    mentioned_paths = set(re.findall(r"[\w./-]+\.(?:py|js|mjs|ts|sh)\b", mentions))
    mentioned_paths.update(re.findall(r"""["']([^"'\n]+\.(?:py|js|mjs|ts|sh))["']""", mentions))
    mentioned_names = {PurePosixPath(path).name for path in mentioned_paths}
    module_paths = set()
    for module in re.findall(r"python(?:3|\.exe)?\s+-m\s+([\w.]+)", mentions):
        for root in roots:
            prefix = "" if root == "." else root + "/"
            for suffix in (".py", "/__main__.py"):
                module_paths.add(prefix + module.replace(".", "/") + suffix)
                module_paths.add(prefix + "src/" + module.replace(".", "/") + suffix)
    ranked = []
    for entry in tree:
        if not eligible(entry):
            continue
        path = PurePosixPath(entry.path)
        root, name = str(path.parent), path.name
        if name in LOCKS:
            continue  # Presence in tree is sufficient; do not spend a blob on lock contents.
        if root in roots and (is_readme(entry.path) or is_manifest(entry.path)):
            rank = 0 if root == "." else 1
        elif root in roots and name in RUNTIMES:
            rank = 2
        elif (
            loaded
            and path.suffix in {".py", ".js", ".mjs", ".ts", ".sh"}
            and (
                entry.path in mentioned_paths
                or name in mentioned_names
                or entry.path in module_paths
            )
        ):
            rank = 3
        else:
            continue
        if entry.size is not None and entry.size > limits.file_bytes:
            limitations.append(f"Пропущен {entry.path}: файл превышает лимит размера.")
            continue
        ranked.append((rank, entry.path, entry))
    ranked.sort(key=lambda row: row[:2])
    if len(ranked) > limits.files:
        limitations.append("Число подходящих файлов превышает лимит выборки.")
    return [entry for _, _, entry in ranked[: limits.files]], limitations
