"""Local signatures and evidence from SanitizedLog only; no persistence or execution."""

from __future__ import annotations

import re
from dataclasses import dataclass

from repodoctor.contracts.api import (
    Command,
    Confidence,
    DiagnosisCause,
    Evidence,
    EvidenceSource,
    Origin,
    RunStep,
    Shell,
)
from repodoctor.contracts.domain import AnalysisContext, SanitizedLog
from repodoctor.intelligence.context import LOG_CONTEXT_LIMIT, encode
from repodoctor.intelligence.rules import build_fallback_plan

SIGNATURES = {
    "module": re.compile(r"ModuleNotFoundError:\s*No module named ['\"]([^'\"]+)['\"]"),
    "file": re.compile(r"FileNotFoundError:|ENOENT: no such file or directory", re.I),
    "env": re.compile(
        r"(?:missing|required|not set|undefined)\s+(?:environment|env)(?:\s+variable)?"
        r"\s*[:=]?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)|"
        r"(?:environment|env)(?:\s+variable)?\s+['\"]?([A-Za-z_][A-Za-z0-9_]*)"
        r"['\"]?\s+(?:is\s+)?(?:missing|required|not set|undefined)",
        re.I,
    ),
    "python": re.compile(
        r"requires[- ]python|requires (?:a different |a |an )?python|unsupported python|"
        r"python version.*(?:incompatible|not supported)|python.*version.*required",
        re.I,
    ),
    "node": re.compile(r"EBADENGINE|Unsupported engine|node.*version.*incompatible", re.I),
    "port": re.compile(r"EADDRINUSE|address already in use|WinError 10048", re.I),
    "cuda": re.compile(
        r"CUDA (?:error|driver|out of memory)|no (?:NVIDIA|CUDA).*(?:driver|GPU)|"
        r"not compiled with CUDA|NVIDIA driver.*(?:old|not found|failed)",
        re.I,
    ),
}


@dataclass
class PreparedLog:
    payload: dict
    evidence: list[Evidence]
    truncated: bool


def prepare_log(log: SanitizedLog) -> PreparedLog:
    """Choose head, error/traceback neighborhoods and tail, retaining original line IDs."""
    lines = log.text.split("\n")
    important = [
        i
        for i, line in enumerate(lines)
        if "Traceback (most recent call last)" in line
        or any(pattern.search(line) for pattern in SIGNATURES.values())
    ]
    order = (
        list(range(min(8, len(lines))))
        + important
        + list(range(max(0, len(lines) - 15), len(lines)))
    )
    order += [j for i in important for j in range(max(0, i - 3), min(len(lines), i + 4))]
    order += list(range(len(lines)))
    entries = []
    seen: set[int] = set()
    trimmed = log.truncated
    payload = {"lines": entries, "truncated": True, "line_count": len(lines)}
    size = len(encode(payload)) + 1  # false is one character longer than true
    for i in order:
        if i in seen:
            continue
        seen.add(i)
        text = lines[i][:500]
        entry = {"number": i + 1, "text": text, "evidence_id": f"log_{i + 1}"}
        cost = len(encode(entry)) + (1 if entries else 0)
        if size + cost > LOG_CONTEXT_LIMIT:
            trimmed = True
        else:
            entries.append(entry)
            size += cost
        trimmed |= len(lines[i]) > 500
    entries.sort(key=lambda entry: entry["number"])
    payload["truncated"] = trimmed
    evidence = [
        Evidence(
            id=entry["evidence_id"],
            source=EvidenceSource.log,
            path=None,
            url=None,
            line_start=entry["number"],
            line_end=entry["number"],
            excerpt=entry["text"],
        )
        for entry in entries
    ]
    return PreparedLog(payload, evidence, trimmed)


def diagnostic_commands(context: AnalysisContext) -> list[dict[str, str]]:
    target = context.response.target
    roots = context.scan.facts.project_roots
    result = []
    if len(roots) == 1:
        root = roots[0].path
        cwd = "<repo>" if root == "." else f"<repo>/{root}"
        python = (
            ".venv/Scripts/python.exe" if target.shell is Shell.powershell else ".venv/bin/python"
        )
        if roots[0].stack.value == "python":
            result.extend(
                {"text": text, "cwd": cwd}
                for text in (
                    f"{python} --version",
                    f"{python} -m pip check",
                    f'{python} -c "import sys; print(sys.executable)"',
                )
            )
        if roots[0].stack.value == "node":
            result.append({"text": "node --version", "cwd": cwd})
    # Only manifest installation from our own rules, never pip install <import-name>.
    plan = build_fallback_plan(context.scan, target)
    for step in plan.steps:
        if step.id == "step_install":
            result.extend({"text": c.text, "cwd": c.cwd} for c in step.commands)
    return result


def local_diagnosis(
    context: AnalysisContext, log: SanitizedLog, prepared: PreparedLog
) -> tuple[list[DiagnosisCause], list[str]]:
    scan = context.scan
    facts = scan.facts
    registry = {ev.id: ev for ev in scan.evidence}
    available_log = {ev.line_start: ev.id for ev in prepared.evidence}
    causes = []
    questions = []
    roots = facts.project_roots
    if len(roots) != 1:
        questions.append("Какой корень проекта запускался и из какой рабочей папки?")
    manifests = [path for root in roots for path in root.manifest_paths]
    manifest_refs = [ev.id for ev in scan.evidence if ev.path in manifests]
    location = ", ".join(root.path for root in roots) or "неизвестный корень"
    manifest_text = ", ".join(manifests) or "manifest не определён"
    root_note = f"Корень: {location}; manifest: {manifest_text}. "
    lines = log.text.split("\n")
    for kind, pattern in SIGNATURES.items():
        hit = next(
            (
                (i, pattern.search(line))
                for i, line in enumerate(lines, 1)
                if pattern.search(line) and i in available_log
            ),
            None,
        )
        if hit is None and kind == "env":
            hit = next(
                (
                    (i, re.search(r"KeyError:\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]", line))
                    for i, line in enumerate(lines, 1)
                    if i in available_log
                    and any(
                        f"KeyError: '{name}'" in line or f'KeyError: "{name}"' in line
                        for name in facts.env_var_names
                    )
                ),
                None,
            )
        if hit is None:
            continue
        number, match = hit
        refs = [available_log[number], *manifest_refs]
        command = None
        if kind == "module":
            module = match[1].split(".")[0]
            dependencies = [dep for dep in facts.dependencies if dep.name == module]
            refs.extend(ref for dep in dependencies for ref in dep.evidence_ids)
            title = "Модуль недоступен в текущем Python-окружении"
            explanation = (
                f"Python сообщает об отсутствии {module}. "
                + (
                    "Одноимённая зависимость есть в manifest; её установка не подтверждена. "
                    if dependencies
                    else "Связь import с distribution не подтверждена manifest. "
                )
                + root_note
            )
            action = (
                "Проверьте интерпретатор и виртуальное окружение. Выполните установку по "
                "подтверждённому manifest и workflow плана; не устанавливайте пакет по import-name."
            )
            options = diagnostic_commands(context)
            command = next(
                (item for item in options if "print(sys.executable)" in item["text"]), None
            )
            if not dependencies:
                questions.append(f"Какая distribution или локальный модуль предоставляет {module}?")
        elif kind == "file":
            title = "Файл недоступен по ожидаемому пути"
            explanation = "Лог сообщает об отсутствующем файле; проверьте путь и cwd. " + root_note
            action = (
                "Сопоставьте путь из traceback с рабочей папкой и документацией данных. "
                "Внешний ресурс получите из подтверждённого источника; "
                "пустой файл не заменяет dataset."
            )
            if facts.data_hints:
                action += " В snapshot есть указания на внешние данные."
            questions.append(
                "Из какой cwd запущена команда и где должен находиться файл из traceback?"
            )
        elif kind == "env":
            name = next((group for group in match.groups() if group), "")
            title = "Не задана необходимая переменная окружения"
            explanation = (
                f"Ошибка указывает имя {name}; значение не требуется для диагностики. " + root_note
            )
            action = (
                f"Проверьте наличие {name} в окружении процесса по документации проекта. "
                "Не публикуйте значение."
            )
            if name not in facts.env_var_names:
                questions.append(
                    f"Подтверждается ли необходимость {name} документацией этого проекта?"
                )
        elif kind in {"python", "node"}:
            runtime = "Python" if kind == "python" else "Node"
            hints = [hint for hint in facts.runtime_hints if hint.runtime.value == kind]
            refs.extend(ref for hint in hints for ref in hint.evidence_ids)
            constraints = "; ".join(hint.constraint for hint in hints)
            title = f"Версия {runtime} может не соответствовать требованиям"
            explanation = "Лог сообщает о несовместимости runtime. " + root_note
            if constraints:
                explanation += f"Требования snapshot: {constraints}. "
            action = (
                "Сравните фактически используемую версию с manifest и текстом ошибки; "
                "выберите версию по пересечению требований, без произвольного downgrade."
            )
            options = diagnostic_commands(context)
            command = next(
                (
                    item
                    for item in options
                    if item["text"].endswith(" --version")
                    and ((kind == "node") == item["text"].startswith("node "))
                ),
                None,
            )
            if len({hint.constraint for hint in hints}) != 1:
                questions.append(
                    f"Уточните версию {runtime}: требования отсутствуют или различаются."
                )
        elif kind == "port":
            title = "Адрес или порт уже занят"
            explanation = "Сигнатура bind указывает на занятый адрес/порт. " + root_note
            action = (
                "Проверьте владельца порта средствами ОС и настройку порта проекта. "
                "Выберите свободный порт по документации; не завершайте неизвестный процесс."
            )
        else:
            title = "Несовместимость GPU, CUDA или драйвера"
            explanation = "В логе есть конкретная сигнатура CUDA/драйвера. " + root_note
            action = (
                "Сопоставьте GPU, драйвер, CUDA и сборку библиотеки с требованиями проекта. "
                "Уточните поддержку CPU; универсальной команды установки для всех ОС нет."
            )
            questions.append(
                "Какие GPU, драйвер и сборка библиотеки используются? Секреты не нужны."
            )
        refs = list(dict.fromkeys(ref for ref in refs if ref in registry or ref.startswith("log_")))
        verification = (
            "Повторите исходную команду в указанной cwd и сравните новый обезличенный лог."
        )
        fixes = [
            RunStep(
                id=f"fix_{kind}",
                title="Проверить окружение и требования проекта",
                description=action,
                commands=[
                    Command(
                        shell=context.response.target.shell,
                        text=command["text"],
                        cwd=command["cwd"],
                        explanation="Диагностическая проверка; команда ещё не выполнялась.",
                        requires_review=True,
                    )
                ]
                if command
                else [],
                evidence_ids=refs,
                verification=verification,
                assumptions=[],
            )
        ]
        causes.append(
            DiagnosisCause(
                id=f"cause_{kind}",
                title=title,
                explanation=explanation,
                confidence=Confidence.medium,
                origin=Origin.static,
                evidence_ids=refs,
                fixes=fixes,
                verification=verification,
            )
        )
        if len(causes) == 5:
            break
    if not causes:
        questions.extend(
            [
                "Какая команда и рабочая папка привели к ошибке?",
                "Приведите обезличенные начало ошибки и traceback, "
                "версии runtime и ожидаемый результат.",
            ]
        )
    return causes, questions
