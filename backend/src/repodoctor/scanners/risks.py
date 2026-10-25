"""Evidence-aware risks; absence is never asserted from an incomplete tree."""

from __future__ import annotations

from repodoctor.repository.selection import is_readme
from repodoctor.scanners.common import ScanState, root_of


def evaluate_risks(state: ScanState) -> None:
    partial = state.snapshot.coverage.status == "partial"
    if partial:
        state.issue(
            "PARTIAL_COVERAGE",
            ".",
            "Анализ ограничен: " + "; ".join(state.snapshot.coverage.limitations),
            "Проверьте пропущенные файлы перед окончательными выводами.",
            confidence="high",
        )
    paths = {entry.path for entry in state.snapshot.tree}
    if not partial and not any(is_readme(path) and root_of(path) == "." for path in paths):
        state.issue(
            "README_MISSING",
            ".",
            "В наблюдаемом полном дереве нет корневого README.",
            "Уточните workflow запуска у автора проекта.",
            confidence="high",
        )
    for root in state.facts.project_roots:
        ecosystems = {"python", "node"} if root.stack == "mixed" else {str(root.stack)}
        for ecosystem in ecosystems - {"unknown"}:
            # RuntimeHint has no root field; scope it via the paths in its evidence.
            runtime = [
                hint
                for hint in state.facts.runtime_hints
                if hint.runtime == ecosystem
                and any(
                    root_of(state.registry.items[eid].path or ".") == root.path
                    for eid in hint.evidence_ids
                )
            ]
            if not runtime:
                ids = [state.registry.tree(path) for path in root.manifest_paths if path in paths]
                state.issue(
                    "RUNTIME_UNSPECIFIED",
                    root.path + "/" + ecosystem,
                    f"Не найдена явная версия {ecosystem} для {root.path}.",
                    "Уточните совместимую версию runtime; версия не угадывается.",
                    ids,
                )
        managers = [m for m in state.facts.package_managers if m.root == root.path]
        for ecosystem, group in (
            ("node", {"npm", "pnpm", "yarn"}),
            ("python", {"pip", "uv", "poetry", "conda"}),
        ):
            scoped = [m for m in managers if m.name in group]
            if (
                len({m.name for m in scoped}) > 1
                and (root.path, ecosystem) not in state.explicit_managers
            ):
                state.issue(
                    "MULTIPLE_PACKAGE_MANAGERS",
                    root.path + "/" + ecosystem,
                    "В одном project root обнаружено несколько возможных package managers.",
                    "Выберите workflow по README/manifest; не смешивайте lock-файлы.",
                    [eid for manager in scoped for eid in manager.evidence_ids],
                )
        if not any(entry.root == root.path for entry in state.facts.entrypoints):
            state.issue(
                "ENTRYPOINT_UNCLEAR",
                root.path,
                "Подтверждённая точка входа не найдена.",
                "Уточните команду запуска выбранного подпроекта.",
            )
    if not state.facts.project_roots:
        state.issue(
            "ENTRYPOINT_UNCLEAR",
            ".",
            "Стек и точка входа не определены.",
            "Укажите manifest и команду запуска проекта.",
        )
    if state.facts.env_var_names:
        state.issue(
            "ENV_CONFIGURATION_REQUIRED",
            ".",
            "Нужна настройка переменных: " + ", ".join(state.facts.env_var_names),
            "Заполните окружение локально, не отправляйте секретные значения.",
            state.signals.get("env"),
        )
    if state.facts.data_hints:
        description = "Упомянуты внешние данные/модели: " + ", ".join(state.facts.data_hints)
        description += (
            ". Дерево неполное: отсутствие ресурса не доказано."
            if partial
            else ". Доступность и получение ресурса требуют проверки."
        )
        state.issue(
            "EXTERNAL_DATA_REFERENCED",
            ".",
            description,
            "Проверьте путь, рабочую папку и инструкции получения ресурсов.",
            state.signals.get("data"),
        )
    if state.facts.gpu_hints:
        state.issue(
            "GPU_REQUIREMENT_UNCLEAR",
            ".",
            "Есть GPU/CUDA hints; необходимость GPU не доказана.",
            "Уточните CPU/GPU workflow и совместимость драйвера отдельно.",
            state.signals.get("gpu"),
        )
