"""README candidates and resource hints. Text is evidence, never an instruction to us."""

from __future__ import annotations

import re
import shlex

from repodoctor.contracts.api import EntryPoint, PackageManagerHint
from repodoctor.repository.selection import is_readme, safe_path
from repodoctor.scanners.common import ScanState, join_path, root_of

_RESOURCE = re.compile(r"(?i)(?:[\w.-]+/)+(?:[\w.-]+\.(?:csv|tsv|jsonl|parquet|bin|pt|pth|ckpt))")
_MODULE = re.compile(r"python(?:3(?:\.\d+)?)?(?:\.exe)?\s+-m\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)")
_ENV = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def extract_readme_hints(state: ScanState) -> None:
    readme_managers: dict[str, set[str]] = {}
    tree = {
        e.path for e in state.snapshot.tree if e.type == "blob" and e.mode in {"100644", "100755"}
    }
    for file in state.files.values():
        root = root_of(file.path)
        readme = is_readme(file.path)
        if file.path.endswith(".env.example"):
            for number, line in enumerate(file.content.splitlines(), 1):
                match = _ENV.match(line)
                if match:
                    state.facts.env_var_names.append(match[1])
                    state.signal("env", state.registry.file(file, number))
        in_fence = False
        for number, line in enumerate(file.content.splitlines(), 1):
            # Do not read node lock contents as instructions, nor arbitrary text as commands.
            if readme and line.strip().startswith(("```", "~~~")):
                in_fence = not in_fence
                continue
            resources = _RESOURCE.findall(line)
            for resource in resources:
                state.facts.data_hints.append(resource)
                state.signal("data", state.registry.file(file, number))
            if re.search(r"\b(cuda|gpu|cudnn|nvidia)\b", line, re.IGNORECASE):
                state.facts.gpu_hints.append(
                    "Упоминание GPU/CUDA; необходимость и совместимость не проверены."
                )
                state.signal("gpu", state.registry.file(file, number))
            if not (readme and in_fence):
                continue
            ids = [state.registry.file(file, number)]
            module = _MODULE.search(line)
            if module:
                name = module[1]
                stem = name.replace(".", "/")
                candidates = [
                    join_path(root, stem + ".py"),
                    join_path(root, stem + "/__main__.py"),
                    join_path(root, "src/" + stem + ".py"),
                    join_path(root, "src/" + stem + "/__main__.py"),
                ]
                found = next((path for path in candidates if path in tree), None)
                if found:
                    state.facts.entrypoints.append(
                        EntryPoint(
                            root=root,
                            command_hint=f"python -m {name}",
                            kind="module",
                            evidence_ids=[*ids, state.registry.tree(found)],
                        )
                    )
            else:
                try:
                    tokens = shlex.split(line.strip().removeprefix("$ "))
                except ValueError:
                    continue
                if len(tokens) == 2 and re.fullmatch(
                    r"(?:.*[/\\])?python[\d.]*(?:\.exe)?", tokens[0]
                ):
                    path = join_path(root, tokens[1])
                    if tokens[1].endswith(".py") and safe_path(path) and path in tree:
                        state.facts.entrypoints.append(
                            EntryPoint(
                                root=root,
                                command_hint="python " + shlex.quote(tokens[1]),
                                kind="file",
                                evidence_ids=[*ids, state.registry.tree(path)],
                            )
                        )
            manager = re.search(r"^\s*(?:\$\s*)?(npm|pnpm|yarn)\s+(?:ci|install)\b", line)
            if manager:
                readme_managers.setdefault(root, set()).add(manager[1])
                state.facts.package_managers.append(
                    PackageManagerHint(name=manager[1], root=root, evidence_ids=ids)
                )
    for root, names in readme_managers.items():
        if len(names) == 1:
            # An explicit packageManager in the manifest takes precedence over README.
            state.explicit_managers.setdefault((root, "node"), next(iter(names)))
