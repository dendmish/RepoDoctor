"""Static Python metadata parsing: no imports, eval, builds, or package resolution."""

from __future__ import annotations

import posixpath
import re
import tomllib
from pathlib import PurePosixPath

from packaging.requirements import InvalidRequirement, Requirement

from repodoctor.contracts.api import Dependency, EntryPoint, PackageManagerHint, RuntimeHint
from repodoctor.contracts.domain import TextFile
from repodoctor.repository.selection import safe_path
from repodoctor.scanners.common import ScanState, join_path, root_of


def _unsupported(state: ScanState, file: TextFile, line: str) -> None:
    state.issue(
        "UNSUPPORTED_DEPENDENCY_SPEC",
        file.path,
        "Есть локальная, URL, editable, option или неразобранная спецификация зависимости.",
        "Проверьте указанный manifest и workflow установки вручную.",
        state.file_ids(file, line),
    )


def _dependency(state: ScanState, file: TextFile, value: str, kind: str, ids: list[str]) -> None:
    try:
        requirement = Requirement(value)
    except InvalidRequirement:
        _unsupported(state, file, value)
        return
    if requirement.url:
        _unsupported(state, file, value)
        return
    constraint = str(requirement.specifier) or None
    extras = f"[{','.join(sorted(requirement.extras))}]" if requirement.extras else ""
    if requirement.marker:
        constraint = (constraint or "") + f"; {requirement.marker}"
    state.facts.dependencies.append(
        Dependency(
            name=requirement.name + extras,
            constraint=constraint,
            ecosystem="python",
            kind=kind,
            manifest_path=file.path,
            evidence_ids=ids,
        )
    )


def parse_requirements(state: ScanState, file: TextFile, visited: set[str] | None = None) -> None:
    visited = visited if visited is not None else set()
    if file.path in visited:
        _unsupported(state, file, "")
        return
    visited.add(file.path)
    root = root_of(file.path)
    state.facts.package_managers.append(
        PackageManagerHint(
            name="pip",
            root=root,
            evidence_ids=state.file_ids(file),
        )
    )
    for number, raw in enumerate(file.content.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        ids = [state.registry.file(file, number)]
        include = re.fullmatch(r"(?:-r\s*|--requirement(?:=|\s+))(.+)", line)
        if include:
            target = posixpath.normpath(join_path(root, include[1].strip()))
            if safe_path(target) and target in state.files and target not in visited:
                parse_requirements(state, state.files[target], visited)
            else:
                _unsupported(state, file, raw)
            continue
        # Constraint files are not runtime dependencies; don't mislabel their packages.
        if line.startswith(("-", ".", "/")) or " --" in line:
            _unsupported(state, file, raw)
            continue
        line = re.split(r"\s+#", line, maxsplit=1)[0]
        _dependency(state, file, line, "dev" if "dev" in file.path else "runtime", ids)


def parse_pyproject(state: ScanState, file: TextFile) -> None:
    try:
        data = tomllib.loads(file.content)
        project = data.get("project", {})
        if not isinstance(project, dict):
            raise ValueError
        deps = project.get("dependencies", [])
        optional = project.get("optional-dependencies", {})
        if not isinstance(deps, list) or not isinstance(optional, dict):
            raise ValueError
        for value in deps:
            if not isinstance(value, str):
                raise ValueError
            _dependency(state, file, value, "runtime", state.file_ids(file, value))
        for values in optional.values():
            if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                raise ValueError
            for value in values:
                _dependency(state, file, value, "optional", state.file_ids(file, value))
        runtime = project.get("requires-python")
        if runtime is not None:
            if not isinstance(runtime, str) or not runtime.strip():
                raise ValueError
            state.facts.runtime_hints.append(
                RuntimeHint(
                    runtime="python",
                    constraint=runtime,
                    evidence_ids=state.file_ids(file, runtime),
                )
            )
        tool = data.get("tool", {})
        if not isinstance(tool, dict):
            raise ValueError
        poetry = tool.get("poetry")
        manager = "poetry" if poetry is not None else "uv" if "uv" in tool else "pip"
        root = root_of(file.path)
        if manager != "pip":
            state.explicit_managers[root, "python"] = manager
        state.facts.package_managers.append(
            PackageManagerHint(
                name=manager,
                root=root,
                evidence_ids=state.file_ids(file, f"{manager}" if manager != "pip" else "project"),
            )
        )
        if poetry is not None:
            if not isinstance(poetry, dict) or not isinstance(poetry.get("dependencies", {}), dict):
                raise ValueError
            for name, constraint in poetry.get("dependencies", {}).items():
                ids = state.file_ids(file, name)
                if name == "python":
                    if isinstance(constraint, str):
                        state.facts.runtime_hints.append(
                            RuntimeHint(runtime="python", constraint=constraint, evidence_ids=ids)
                        )
                elif isinstance(constraint, str):
                    state.facts.dependencies.append(
                        Dependency(
                            name=name,
                            constraint=constraint,
                            ecosystem="python",
                            kind="runtime",
                            manifest_path=file.path,
                            evidence_ids=ids,
                        )
                    )
                else:
                    _unsupported(state, file, name)
            if "group" in poetry or "dev-dependencies" in poetry:
                _unsupported(state, file, "poetry")
        # Scripts are only candidates if the actual module exists in the observed tree.
        scripts = project.get("scripts", {})
        if not isinstance(scripts, dict):
            raise ValueError
        for name, target in scripts.items():
            if not isinstance(target, str):
                raise ValueError
            module = target.split(":", 1)[0].replace(".", "/")
            candidates = [join_path(root, module + suffix) for suffix in (".py", "/__init__.py")]
            candidates.extend(
                join_path(root, "src/" + module + suffix) for suffix in (".py", "/__init__.py")
            )
            found = next(
                (
                    entry.path
                    for entry in state.snapshot.tree
                    if entry.path in candidates and entry.mode in {"100644", "100755"}
                ),
                None,
            )
            if found and re.fullmatch(r"[A-Za-z0-9_.-]+", name):
                state.facts.entrypoints.append(
                    EntryPoint(
                        root=root,
                        command_hint=name,
                        kind="script",
                        evidence_ids=[*state.file_ids(file, target), state.registry.tree(found)],
                    )
                )
        if project.get("dynamic") or data.get("dependency-groups"):
            _unsupported(state, file, "dependencies")
    except (tomllib.TOMLDecodeError, ValueError, TypeError):
        state.issue(
            "MANIFEST_PARSE_FAILED",
            file.path,
            "Не удалось разобрать Python manifest.",
            "Проверьте синтаксис и структуру pyproject.toml.",
            state.file_ids(file),
            confidence="high",
        )


def parse_python(state: ScanState) -> None:
    visited: set[str] = set()
    for file in state.files.values():
        name = PurePosixPath(file.path).name
        if name.startswith("requirements") and name.endswith(".txt"):
            if file.path not in visited:
                parse_requirements(state, file, visited)
        elif name == "pyproject.toml":
            parse_pyproject(state, file)
        elif name == ".python-version" and file.content.strip():
            state.facts.runtime_hints.append(
                RuntimeHint(
                    runtime="python",
                    constraint=file.content.strip(),
                    evidence_ids=state.file_ids(file),
                )
            )
        elif name in {"setup.py", "environment.yml", "environment.yaml"}:
            _unsupported(state, file, "")
