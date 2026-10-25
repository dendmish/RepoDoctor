"""Node manifest extraction; npm semver stays raw, scripts are never executed."""

from __future__ import annotations

import json
from pathlib import PurePosixPath

from repodoctor.contracts.api import Dependency, EntryPoint, PackageManagerHint, RuntimeHint
from repodoctor.contracts.domain import TextFile
from repodoctor.scanners.common import ScanState, root_of


def parse_package_json(state: ScanState, file: TextFile) -> None:
    try:
        data = json.loads(file.content)
        if not isinstance(data, dict):
            raise ValueError
        root = root_of(file.path)
        for group, kind in (
            ("dependencies", "runtime"),
            ("devDependencies", "dev"),
            ("optionalDependencies", "optional"),
        ):
            values = data.get(group, {})
            if not isinstance(values, dict):
                raise ValueError
            for name, value in values.items():
                if not isinstance(value, str):
                    raise ValueError
                ids = state.file_ids(file, f'"{name}"')
                state.facts.dependencies.append(
                    Dependency(
                        name=name,
                        constraint=value,
                        ecosystem="node",
                        kind=kind,
                        manifest_path=file.path,
                        evidence_ids=ids,
                    )
                )
                if value.startswith(("file:", "git", "http", "workspace:", "link:")):
                    state.issue(
                        "UNSUPPORTED_DEPENDENCY_SPEC",
                        file.path,
                        "Есть зависимость вне обычного npm registry; совместимость не проверена.",
                        "Проверьте локальные workspace/URL зависимости.",
                        ids,
                    )
        engines = data.get("engines", {})
        if not isinstance(engines, dict):
            raise ValueError
        if "node" in engines:
            if not isinstance(engines["node"], str) or not engines["node"].strip():
                raise ValueError
            state.facts.runtime_hints.append(
                RuntimeHint(
                    runtime="node",
                    constraint=engines["node"],
                    evidence_ids=state.file_ids(file, '"node"'),
                )
            )
        manager = data.get("packageManager")
        if manager is not None:
            if not isinstance(manager, str):
                raise ValueError
            name = manager.split("@", 1)[0]
            if name in {"npm", "yarn", "pnpm"}:
                state.explicit_managers[root, "node"] = name
                state.facts.package_managers.append(
                    PackageManagerHint(
                        name=name,
                        root=root,
                        evidence_ids=state.file_ids(file, "packageManager"),
                    )
                )
            else:
                state.explicit_managers[root, "node"] = "unsupported"
                state.issue(
                    "UNSUPPORTED_DEPENDENCY_SPEC",
                    file.path,
                    "Указан неподдерживаемый packageManager.",
                    "Уточните workflow установки.",
                    state.file_ids(file, "packageManager"),
                )
        scripts = data.get("scripts", {})
        if not isinstance(scripts, dict) or not all(
            isinstance(value, str) for value in scripts.values()
        ):
            raise ValueError
        for name in ("start", "dev"):
            if scripts.get(name):
                state.facts.entrypoints.append(
                    EntryPoint(
                        root=root,
                        command_hint=f"npm run {name}",
                        kind="script",
                        evidence_ids=state.file_ids(file, f'"{name}"'),
                    )
                )
    except (ValueError, TypeError):
        state.issue(
            "MANIFEST_PARSE_FAILED",
            file.path,
            "Не удалось разобрать Node manifest.",
            "Проверьте JSON и типы полей package.json.",
            state.file_ids(file),
            confidence="high",
        )


def parse_node(state: ScanState) -> None:
    for file in state.files.values():
        name = PurePosixPath(file.path).name
        if name == "package.json":
            parse_package_json(state, file)
        elif name in {".nvmrc", ".node-version"} and file.content.strip():
            state.facts.runtime_hints.append(
                RuntimeHint(
                    runtime="node",
                    constraint=file.content.strip(),
                    evidence_ids=state.file_ids(file),
                )
            )
