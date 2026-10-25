"""Детектор типичных проблем с запуском чужих репозиториев.

Все проверки детерминированные (без LLM) — быстрые и надёжные.
Результаты структуры Finding(severity, title, details, fix).
"""

import os
import re
from dataclasses import dataclass, field

from packaging.version import InvalidVersion, Version

from .analyze import RepoAnalysis


@dataclass
class Finding:
    level: str  # "critical" | "warning" | "info"
    title: str
    details: str = ""
    fix: str = ""

    def as_dict(self):
        return {"level": self.level, "title": self.title,
                "details": self.details, "fix": self.fix}


@dataclass
class ChecksReport:
    findings: list = field(default_factory=list)

    def add(self, level, title, details="", fix=""):
        self.findings.append(Finding(level, title, details, fix))

    @property
    def score(self) -> str:
        c = sum(1 for f in self.findings if f.level == "critical")
        w = sum(1 for f in self.findings if f.level == "warning")
        if c:
            return f"{c} критических, {w} предупреждений"
        if w:
            return f"{w} предупреждений"
        return "явных проблем не найдено"

    def as_dicts(self):
        return [f.as_dict() for f in self.findings]


OLD_PINS = [
    ("tensorflow", 2, 5),
    ("torch", 1, 13),
    ("keras", 2, 0),
    ("numpy", 1, 24),
    ("scipy", 1, 10),
    ("sklearn", 0, 0),
    ("scikit-learn", 0, 0),
    ("pandas", 1, 5),
]

GPU_HINTS = re.compile(r"\b(cudnn|gpu|cuda|nvidia)\b", re.IGNORECASE)
API_KEY_HINTS = re.compile(
    r"(?i)(openai_api_key|hf_token|huggingface_token|github_token|access[_-]?token\s*[:=]"
    r"|api[_-]?key\s*[:=]|anthropic_api_key|mistral_api_key)"
)
DATA_EXT_RE = re.compile(r"\.(csv|tsv|h5|hdf5|pt|pth|pkl|npy|npz|jsonl|lmdb|h5py|parquet|gz|zip|tar)$", re.IGNORECASE)


def run_checks(a: RepoAnalysis) -> ChecksReport:
    report = ChecksReport()

    has_dep_file = (a.has_requirements or a.has_conda_env or a.has_pyproject or a.has_setup_py
                    or a.has_cargo or a.has_go_mod or a.has_package_json
                    or a.has_pom or a.has_gradle or a.has_gemfile or a.has_makefile)
    if not has_dep_file:
        report.findings.append(
            Finding(
                "critical",
                "Нет файла зависимостей",
                "В репозитории нет requirements.txt / environment.yml / pyproject.toml / setup.py / "
                "package.json / Cargo.toml / go.mod / pom.xml.",
                "Попробуйте: pip install pipreqs и сгенерировать зависимости по импортам, "
                "или посмотрите, какие библиотеки импортируются в главном скрипте.",
            )
        )

    for dep in a.dependencies:
        d = dep.lower().split(":", 1)[-1]
        name = re.split(r"[<>=!~\[;]", d)[0].strip()
        m = re.search(r"(==|>=|<=|~=|<|>)\s*([\d][\w.]*)", d)
        if not m:
            continue
        op, ver_str = m.group(1), m.group(2)
        try:
            v = Version(ver_str)
        except InvalidVersion:
            try:
                cut = ver_str.rsplit(".", 1)[0]
                v = Version(cut)
            except InvalidVersion:
                continue
        for pkg, maj, mino in OLD_PINS:
            if name == pkg:
                try:
                    base = Version(f"{maj}.{mino}")
                except InvalidVersion:
                    continue
                if v < base and op in {"==", "<", "<="}:
                    report.add(
                        "warning",
                        f"Устаревший пин зависимости: {dep}",
                        f"{pkg} в версии {ver_str} сильно устаревшая (< {base}). "
                        "Скорее всего код писался давно и может не собраться на современных версиях.",
                        "Запускать в отдельном окружении (conda/venv) с этой версией Python, "
                        "либо попытаться обновить код под новые API.",
                    )

    if a.python_version:
        report.add(
            "info",
            f"Указан Python {a.python_version}",
            "В README указана конкретная версия Python — используйте именно её.",
            f"python{a.python_version.split()[0]} -m venv .venv",
        )

    if a.data_fragments and len(a.data_fragments) >= 1:
        missing = [f for f in a.data_fragments if not _fragment_exists(a.path, f)]
        if missing:
            report.add(
                "critical",
                "Пути к данным, которых нет в репозитории",
                "В коде/README упоминаются файлы данных, но в репо их нет "
                "(обычные датасеты/checkpoints выкладывают отдельно): "
                + "; ".join(list(dict.fromkeys(missing))[:8]),
                "Инструкция по скачиванию датасета обычно в README. Если её нет — "
                "найти в оригинальной статье или открыть issue.",
            )

    if a.hard_paths:
        report.add(
            "warning",
            "Жёстко зашитые абсолютные пути",
            "Найдены пути вида /home/... или C:\\... — они на машине автора и у вас не существуют: "
            + "; ".join(list(dict.fromkeys(a.hard_paths))[:8]),
            "Переписать на относительные пути или переменные окружения.",
        )

    gpu_names = [d for d in a.dependencies if GPU_HINTS.search(d)]
    if gpu_names:
        report.add(
            "warning",
            "GPU/CUDA-зависимости",
            "Среди зависимостей есть CUDA/GPU компоненты: " + ", ".join(gpu_names[:6]) + ". "
            "Без NVIDIA GPU + правильной версии CUDA проект не заведётся (можно попробовать CPU-сборки).",
            "pip install torch --index-url https://download.pytorch.org/whl/cpu для CPU-версии.",
        )

    key_refs = _scan_for_env_keys(a)
    if key_refs:
        report.add(
            "warning",
            "Возможно, нужны API-ключи",
            "В коде есть обращения к API-ключам: " + ", ".join(list(dict.fromkeys(key_refs))[:8]),
            "Создать .env с нужными ключами (обычно указано в README).",
        )

    if a.readme_text:
        if len(a.readme_text) < 200:
            report.add(
                "info",
                "README подозрительно короткий",
                "Скорее всего инструкция по запуску неполная.",
                "Полагайтесь на структуру проекта и точки входа.",
            )
        if "```" not in a.readme_text and "pip install" not in a.readme_text.lower():
            report.add(
                "warning",
                "В README нет команд установки",
                "Нет блоков кода с pip install / инструкцией по установке.",
                "Ориентироваться на файлы зависимостей и точки входа.",
            )

    if a.has_makefile:
        report.add("info", "Есть Makefile",
                   "Может содержать цели для подготовки данных и запуска.",
                   "make (или make help / набрать make -pn)")

    if a.has_dockerfile:
        report.add("info", "Есть Dockerfile",
                   "Наиболее надёжный запуск — через Docker, чтобы не собирать окружение вручную.",
                   "docker build -t image . && docker run image")

    if a.has_conda_env and a.project_type == "conda":
        report.add("info", "Conda environments",
                   "Проект рассчитан на conda — venv может не подойти (нужны не-pip пакеты).",
                   "conda env create -f environment.yml && conda activate <name>")

    return report


def _fragment_exists(repo_root: str, fragment: str) -> bool:
    """Проверяет, существует ли файл, на который похоже указывает fragment (последняя 1–2 компоненты)."""
    tail = fragment.strip("/").split("/")[-1]
    if not tail:
        return True
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        if tail in filenames or tail in dirnames:
            return True
    return False


def _scan_for_env_keys(a: RepoAnalysis) -> list[str]:
    hits = []
    for dirpath, dirnames, filenames in os.walk(a.path):
        dirnames[:] = [d for d in dirnames if d not in {".git", "node_modules", "__pycache__", ".github"}]
        for fn in filenames:
            if not fn.endswith((".py", ".md", ".sh", ".yml", ".yaml", ".json")):
                continue
            try:
                with open(os.path.join(dirpath, fn), encoding="utf-8", errors="replace") as fh:
                    text = fh.read(150_000)
            except OSError:
                continue
            for m in API_KEY_HINTS.finditer(text):
                tok = m.group(0)
                if tok not in hits:
                    hits.append(tok)
    return hits[:10]
