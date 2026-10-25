"""Conservative, deterministic launch plans. This module never executes commands."""

from __future__ import annotations

import json
import re
import shlex
import tomllib
from pathlib import PurePosixPath

from repodoctor.contracts.api import (
    Command,
    Ecosystem,
    EntryPoint,
    EvidenceSource,
    PackageManager,
    PlanStatus,
    ProjectRoot,
    RunPlan,
    RunStep,
    Shell,
    Stack,
    TargetEnvironment,
)
from repodoctor.contracts.domain import StaticAnalysis

_MANAGER_FILES = {
    "uv.lock": PackageManager.uv,
    "poetry.lock": PackageManager.poetry,
    "environment.yml": PackageManager.conda,
    "environment.yaml": PackageManager.conda,
    "yarn.lock": PackageManager.yarn,
    "pnpm-lock.yaml": PackageManager.pnpm,
    "package-lock.json": PackageManager.npm,
    "npm-shrinkwrap.json": PackageManager.npm,
}
_PYTHON_MANAGERS = {
    PackageManager.pip,
    PackageManager.uv,
    PackageManager.poetry,
    PackageManager.conda,
}
_NODE_MANAGERS = {PackageManager.npm, PackageManager.yarn, PackageManager.pnpm}
_SAFE_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_MODULE = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", re.ASCII)
MAX_RESOURCE_EVIDENCE = 10
_PYTHON = re.compile(r"python(?:3(?:\.\d+)?)?")


def _join(root: str, name: str) -> str:
    return name if root == "." else f"{root}/{name}"


def _quote(value: str, shell: Shell) -> str:
    # Single-quoted literals prevent interpolation; quote escaping differs by shell.
    escaped = (
        value.replace("'", "''") if shell is Shell.powershell else value.replace("'", "'\"'\"'")
    )
    return "'" + escaped + "'"


class _Planner:
    def __init__(self, scan: StaticAnalysis, target: TargetEnvironment) -> None:
        self.scan = scan
        self.target = target
        self.registry = {ev.id: ev for ev in scan.evidence if ev.source is not EvidenceSource.log}
        self.steps: list[RunStep] = []
        self.questions: list[str] = []
        self.prerequisites = ["Git; доступ к репозиторию и право создать новую локальную папку."]
        self.root = "."
        self.cwd = "<repo>"

    def refs(self, ids: list[str]) -> list[str]:
        return sorted(set(ids) & self.registry.keys())

    def paths(self, *paths: str) -> list[str]:
        return sorted(ev.id for ev in self.registry.values() if ev.path in paths)

    def step(
        self,
        key: str,
        title: str,
        description: str,
        verification: str,
        *,
        texts: tuple[str, ...] = (),
        ids: list[str] | None = None,
        assumptions: tuple[str, ...] = (),
        cwd: str | None = None,
    ) -> None:
        refs = self.refs(ids or [])
        self.steps.append(
            RunStep(
                id=f"step_{key}",
                title=title,
                description=description,
                commands=[
                    Command(
                        shell=self.target.shell,
                        text=text,
                        cwd=cwd or self.cwd,
                        explanation=description,
                        requires_review=True,
                    )
                    for text in texts
                ],
                evidence_ids=refs,
                verification=verification,
                assumptions=list(assumptions)
                or ([] if refs else ["Шаг основан на метаданных снимка и выбранном окружении."]),
            )
        )

    def build(self) -> RunPlan:
        repo = self.scan.repository
        # RepositoryInfo only checks the URL prefix; fail closed on inconsistent metadata.
        identity = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*")
        canonical = f"https://github.com/{repo.owner}/{repo.name}"
        valid_identity = (
            identity.fullmatch(repo.owner)
            and identity.fullmatch(repo.name)
            and repo.name not in {".", ".."}
            and repo.url == canonical
        )
        if not valid_identity:
            self.questions.append("Уточните канонические owner/name/URL репозитория.")
            return self.finish()
        self.step(
            "clone",
            "Клонировать репозиторий",
            "Создайте новую рабочую копию; существующую папку не перезаписывайте.",
            f"Появилась папка {repo.name}; Git завершился без ошибок.",
            texts=(
                f"git clone -- {_quote(canonical + '.git', self.target.shell)} "
                f"{_quote(repo.name, self.target.shell)}",
            ),
            cwd=".",
            assumptions=("Git установлен; команда выполняется в родительской папке новой копии.",),
        )
        self.step(
            "checkout",
            "Выбрать проанализированный commit",
            "Продолжайте в только что созданной копии с зафиксированным SHA.",
            f"git rev-parse HEAD внутри копии должен вывести {repo.resolved_commit}.",
            texts=(
                f"git -C {_quote(repo.name, self.target.shell)} "
                f"checkout --detach {repo.resolved_commit}",
            ),
            cwd=".",
        )
        roots = self.scan.facts.project_roots
        if len(roots) != 1:
            self.questions.append(
                "Какой подпроект запускать? Укажите корень проекта и его точку входа."
            )
            return self.finish()
        root = roots[0]
        self.root = root.path
        self.cwd = "<repo>" if root.path == "." else f"<repo>/{root.path}"
        relative = repo.name if root.path == "." else f"{repo.name}/{root.path}"
        # PowerShell single quotes escape a quote by doubling, unlike bash/zsh.
        destination = _quote("./" + relative, self.target.shell)
        cd = (
            f"Set-Location -LiteralPath {destination}"
            if self.target.shell is Shell.powershell
            else f"cd -- {destination}"
        )
        self.step(
            "root",
            "Перейти в корень проекта",
            "Все дальнейшие команды выполняйте в указанной рабочей папке.",
            f"Текущая папка соответствует {self.cwd}.",
            texts=(cd,),
            cwd=".",
            ids=self.paths(*root.manifest_paths),
            assumptions=("Переход выполняется из родительской папки клонированного репозитория.",),
        )
        # The local folder can contain shell metacharacters; quoting above is shell-specific.
        if root.stack is Stack.python:
            ready, python, packaged = self.python_setup(root)
            entry = self.python_entry(python, packaged) if ready else None
        elif root.stack is Stack.node:
            ready = self.node_setup(root)
            entry = self.node_entry() if ready else None
        else:
            self.questions.append("Какой стек и workflow установки использовать в этом корне?")
            entry = None
        self.resources()
        if entry:
            text, ids = entry
            self.step(
                "run",
                "Запустить подтверждённую точку входа",
                "Команда основана на фактах и источниках выбранного проекта.",
                "Сравните вывод с README; при ошибке сохраните обезличенный лог для диагностики.",
                texts=(text,),
                ids=ids,
            )
            self.step(
                "verify",
                "Проверить результат запуска",
                "Проверьте ожидаемое поведение по README и отсутствие ошибок в терминале.",
                "Пользователь проверяет результат самостоятельно; RepoDoctor команды не выполнял.",
                ids=ids,
                assumptions=("Адрес сервиса, порт и результат работы не угадываются.",),
            )
        return self.finish()

    def finish(self) -> RunPlan:
        return RunPlan(
            status=PlanStatus.needs_input if self.questions else PlanStatus.actionable,
            summary=(
                "Подготовительные шаги доступны; для полного запуска нужны уточнения."
                if self.questions
                else "План составлен по данным снимка; команды требуют проверки пользователем."
            ),
            prerequisites=self.prerequisites,
            steps=self.steps,
            questions=list(dict.fromkeys(self.questions)),
        )

    def managers(self, allowed: set[PackageManager]) -> set[PackageManager]:
        names = {
            hint.name
            for hint in self.scan.facts.package_managers
            if hint.root == self.root and hint.name in allowed
        }
        for name, manager in _MANAGER_FILES.items():
            if manager in allowed and self.paths(_join(self.root, name)):
                names.add(manager)
        return names

    def runtime(self, ecosystem: Ecosystem) -> tuple[list[str], list[str]]:
        hints = [h for h in self.scan.facts.runtime_hints if h.runtime is ecosystem]
        inherited = (
            {".python-version"} if ecosystem is Ecosystem.python else {".nvmrc", ".node-version"}
        )
        confirmed = [
            h
            for h in hints
            if any(
                ev.path is not None
                and (str(PurePosixPath(ev.path).parent) == self.root or ev.path in inherited)
                for i in self.refs(h.evidence_ids)
                for ev in [self.registry[i]]
            )
        ]
        constraints = list(dict.fromkeys(h.constraint for h in confirmed))
        ids = sorted({i for h in confirmed for i in self.refs(h.evidence_ids)})
        name = "Python" if ecosystem is Ecosystem.python else "Node.js"
        if not constraints:
            self.questions.append(f"Какая версия {name} требуется проекту? В снимке нет источника.")
        elif len(constraints) > 1:
            self.questions.append(
                f"Уточните совместимую версию {name}: источники задают несколько ограничений."
            )
        self.prerequisites.append(
            f"{name}: " + ("; ".join(constraints) if constraints else "версию требуется уточнить")
        )
        return constraints, ids

    def python_setup(self, root: ProjectRoot) -> tuple[bool, str, bool]:
        constraints, runtime_ids = self.runtime(Ecosystem.python)
        exact = (
            re.fullmatch(r"3\.(\d+)(?:\.\d+)?", constraints[0]) if len(constraints) == 1 else None
        )
        launcher = "py -3" if self.target.shell is Shell.powershell else "python3"
        if exact:
            version = f"3.{exact[1]}"
            launcher = (
                f"py -{version}" if self.target.shell is Shell.powershell else f"python{version}"
            )
        python = (
            ".\\.venv\\Scripts\\python.exe"
            if self.target.shell is Shell.powershell
            else ".venv/bin/python"
        )
        managers = self.managers(_PYTHON_MANAGERS)
        pyproject_path = _join(self.root, "pyproject.toml")
        document = next((f for f in self.scan.selected_files if f.path == pyproject_path), None)
        metadata: dict = {}
        if document:
            try:
                metadata = tomllib.loads(document.content)
            except tomllib.TOMLDecodeError:
                self.questions.append("Исправьте или уточните некорректный pyproject.toml.")
                return False, python, False
            tool = metadata.get("tool", {})
            if isinstance(tool, dict):
                if "poetry" in tool:
                    managers.add(PackageManager.poetry)
                if "uv" in tool:
                    managers.add(PackageManager.uv)
        if managers - {PackageManager.pip}:
            self.questions.append(
                "Подтвердите workflow установки Python (Poetry/uv/conda или конфликт менеджеров); "
                "fallback не заменяет его на pip."
            )
            return False, python, False
        self.step(
            "environment",
            "Создать изолированное окружение Python",
            "Используйте интерпретатор, соответствующий ограничениям проекта; активация не нужна.",
            f"{python} --version: сравните версию с требованиями проекта.",
            texts=(f"{launcher} --version", f"{launcher} -m venv .venv"),
            ids=runtime_ids,
            assumptions=(
                "Нужный интерпретатор установлен и доступен указанной командой; "
                "если версия не подходит, сначала выберите другой интерпретатор.",
            ),
        )
        requirements = [
            p
            for p in root.manifest_paths
            if PurePosixPath(p).parent == PurePosixPath(self.root)
            and re.fullmatch(r"requirements[^/]*\.txt", PurePosixPath(p).name)
            and self.paths(p)
        ]
        default = _join(self.root, "requirements.txt")
        requirement = (
            default
            if default in requirements
            else (requirements[0] if len(requirements) == 1 else None)
        )
        project = metadata.get("project", {})
        build = metadata.get("build-system", {})
        packaged = (
            bool(self.paths(pyproject_path))
            and isinstance(project, dict)
            and isinstance(project.get("name"), str)
            and isinstance(build, dict)
            and isinstance(build.get("build-backend"), str)
            and isinstance(build.get("requires"), list)
        )
        if requirement:
            path = PurePosixPath(requirement).name
            install = f"{python} -m pip install -r {_quote(path, self.target.shell)}"
            ids = self.paths(requirement)
        elif packaged:
            install = f"{python} -m pip install ."
            ids = self.paths(pyproject_path)
        else:
            self.questions.append(
                "Как устанавливать Python-проект? Нужен однозначный requirements-файл "
                "или подтверждённый installable pyproject.toml."
            )
            return False, python, False
        # If requirements were used, installing the local package is not implied.
        self.step(
            "install",
            "Установить зависимости Python",
            "Проверьте manifest и build hooks перед локальной установкой зависимостей.",
            f"{python} -m pip check: нет конфликтов установленных зависимостей.",
            texts=(install,),
            ids=ids,
            assumptions=(
                "Установка будет выполнена пользователем локально после проверки manifest.",
            ),
        )
        return True, python, packaged and requirement is None

    def node_setup(self, root: ProjectRoot) -> bool:
        constraints, runtime_ids = self.runtime(Ecosystem.node)
        managers = self.managers(_NODE_MANAGERS)
        manifest = _join(self.root, "package.json")
        document = next((f for f in self.scan.selected_files if f.path == manifest), None)
        if document:
            try:
                metadata = json.loads(document.content)
                declared = metadata.get("packageManager", "") if isinstance(metadata, dict) else ""
                if declared:
                    manager = str(declared).split("@", 1)[0]
                    if manager not in {"npm", "yarn", "pnpm"}:
                        self.questions.append("Уточните packageManager из package.json.")
                        return False
                    managers.add(PackageManager(manager))
            except json.JSONDecodeError:
                self.questions.append("Исправьте или уточните некорректный package.json.")
                return False
        if managers - {PackageManager.npm}:
            self.questions.append(
                "Подтвердите Yarn/pnpm workflow или разрешите конфликт менеджеров; "
                "npm не подставляется."
            )
            return False
        if not managers:
            self.questions.append(
                "Какой менеджер Node.js использовать? Явный npm workflow не подтверждён."
            )
            return False
        if manifest not in root.manifest_paths or not self.paths(manifest):
            # A script/dependency fact can carry package.json evidence even if the manifest
            # itself was not selected. paths() includes those line-level evidence entries.
            self.questions.append("Подтвердите package.json выбранного корня перед установкой.")
            return False
        self.prerequisites.append("npm, соответствующий выбранной версии Node.js.")
        self.step(
            "runtime",
            "Проверить Node.js и npm",
            "Сопоставьте установленную версию Node.js с ограничениями из репозитория.",
            "Версия удовлетворяет: " + ("; ".join(constraints) or "уточняемым требованиям проекта"),
            texts=("node --version", "npm --version"),
            ids=runtime_ids,
            assumptions=(
                "Node.js и npm установлены; при несовместимости сначала выберите нужную версию.",
            ),
        )
        locks = self.paths(
            _join(self.root, "package-lock.json"), _join(self.root, "npm-shrinkwrap.json")
        )
        self.step(
            "install",
            "Установить зависимости Node.js",
            "Используйте npm ci по существующему lock-файлу."
            if locks
            else "В корне не найден npm lock; npm install разрешает версии из package.json.",
            "Установка завершается без ошибок; проверьте сообщения npm.",
            texts=("npm ci" if locks else "npm install",),
            ids=locks or self.paths(manifest),
            assumptions=()
            if locks
            else ("Если вне наблюдаемой части есть иной manager/lock, сначала уточните workflow.",),
        )
        return True

    def entries(self) -> list[EntryPoint]:
        entries = [e for e in self.scan.facts.entrypoints if e.root == self.root]
        unique = {e.command_hint: e for e in entries}
        if len(unique) != 1:
            self.questions.append(
                "Какую точку входа запускать? Нужна одна подтверждённая команда корня."
            )
            return []
        entry = next(iter(unique.values()))
        if not self.refs(entry.evidence_ids) or len(self.refs(entry.evidence_ids)) != len(
            set(entry.evidence_ids)
        ):
            self.questions.append("Подтвердите источник команды запуска: evidence нет в снимке.")
            return []
        return [entry]

    def python_entry(self, python: str, packaged: bool) -> tuple[str, list[str]] | None:
        entries = self.entries()
        if not entries:
            return None
        entry = entries[0]
        # Only translate a small literal Python command grammar, never copy arbitrary README shell.
        try:
            parts = shlex.split(entry.command_hint)
        except ValueError:
            parts = []
        valid = len(parts) >= 2 and bool(_PYTHON.fullmatch(parts[0]))
        module = len(parts) >= 3 and parts[1] == "-m" and bool(_MODULE.fullmatch(parts[2]))
        file = len(parts) >= 2 and bool(re.fullmatch(r"[A-Za-z0-9_/.-]+\.py", parts[1]))
        args = parts[3:] if module else parts[2:]
        valid = (
            valid
            and (module or file)
            and all(
                re.fullmatch(r"[A-Za-z0-9_./=:@%+,-]+", arg)
                and "://" not in arg
                and ".." not in arg.split("/")
                for arg in args
            )
        )
        file_ids: list[str] = []
        if file:
            valid = valid and not any(p in {"", ".", ".."} for p in parts[1].split("/"))
            valid = valid and not parts[1].startswith(("/", "-"))
            file_ids = self.paths(_join(self.root, parts[1]))
            valid = valid and bool(file_ids)
        if module:
            module_path = parts[2].replace(".", "/")
            candidates = [
                _join(self.root, module_path + ".py"),
                _join(self.root, module_path + "/__main__.py"),
            ]
            if packaged:
                candidates.extend(
                    [
                        _join(self.root, "src/" + module_path + ".py"),
                        _join(self.root, "src/" + module_path + "/__main__.py"),
                    ]
                )
            file_ids = self.paths(*candidates)
            valid = valid and bool(file_ids)
        if not valid:
            self.questions.append(
                "Уточните Python-команду и доступность файла/модуля из выбранного корня; "
                "для src-layout может потребоваться установка самого пакета."
            )
            return None
        # Native-command arguments such as @name must remain literal in PowerShell too.
        head = parts[1:3] if module else parts[1:2]
        suffix = " ".join(head + [_quote(arg, self.target.shell) for arg in args])
        return f"{python} {suffix}", sorted(set(self.refs(entry.evidence_ids) + file_ids))

    def node_entry(self) -> tuple[str, list[str]] | None:
        entries = self.entries()
        if not entries:
            return None
        entry = entries[0]
        match = re.fullmatch(r"npm (?:run )?([A-Za-z0-9_:-]+)", entry.command_hint.strip())
        if not match or match[1] not in {"start", "dev"}:
            self.questions.append(
                "Подтвердите npm start/dev script; произвольная команда README "
                "не переносится в план."
            )
            return None
        manifest = _join(self.root, "package.json")
        document = next((f for f in self.scan.selected_files if f.path == manifest), None)
        if document:
            metadata = json.loads(document.content)  # node_setup already checked JSON syntax
            scripts = metadata.get("scripts", {}) if isinstance(metadata, dict) else {}
            script = scripts.get(match[1]) if isinstance(scripts, dict) else None
            if not isinstance(script, str) or not script.strip():
                self.questions.append(
                    "Подтвердите start/dev: script не найден в прочитанном package.json."
                )
                return None
        if not any(
            self.registry[i].path == manifest and self.registry[i].source is EvidenceSource.file
            for i in entry.evidence_ids
        ):
            self.questions.append("Подтвердите объявление start/dev в scripts package.json.")
            return None
        return ("npm start" if match[1] == "start" else "npm run dev"), self.refs(
            entry.evidence_ids
        )

    def resources(self) -> None:
        facts = self.scan.facts
        if not (facts.env_var_names or facts.data_hints or facts.gpu_hints):
            return
        names = [name for name in facts.env_var_names if _SAFE_ID.fullmatch(name)]
        description = "Настройте переменные по документации проекта, не публикуя значения."
        if names:
            description += " Имена: " + ", ".join(names) + "."
        if facts.data_hints:
            description += (
                " Уточните источник данных и ожидаемый путь; не создавайте пустые заменители."
            )
            self.questions.append("Где получить необходимые данные и в какой путь их поместить?")
        if facts.gpu_hints:
            description += " Сопоставьте требования GPU/CUDA с доступным оборудованием."
            self.questions.append(
                "Нужна ли GPU и какие версии драйвера/CUDA предусмотрены проектом?"
            )
        # Representative sources in findings order, bounded so the step stays reviewable.
        ids: list[str] = []
        for finding in self.scan.findings:
            ids.extend(
                ref for ref in finding.evidence_ids if ref in self.registry and ref not in ids
            )
        ids = ids[:MAX_RESOURCE_EVIDENCE]
        self.step(
            "resources",
            "Подготовить окружение и внешние ресурсы",
            description,
            "Имена переменных и пути соответствуют документации; секреты остаются локально.",
            ids=ids,
            assumptions=(
                "Секреты и внешние ресурсы пользователь получает самостоятельно; "
                "команды загрузки и значения не генерируются.",
            ),
        )


def build_fallback_plan(scan: StaticAnalysis, target: TargetEnvironment) -> RunPlan:
    """Return grounded preparation steps, asking questions where facts are insufficient."""
    return _Planner(scan, target).build()
