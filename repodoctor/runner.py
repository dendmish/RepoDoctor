"""Запуск чужого проекта в изолированном Docker-контейнере.

Схема:
1. Копируем клон репо в sandbox-каталог (чтобы не трогать оригинал).
2. Генерируем Dockerfile по типу проекта (python3.10-slim + requirements, node, generic).
3. docker build -> docker run (с таймаутом, без сети по желанию).
4. Собираем stdout/stderr — лог можно сразу отдать в диагностику.

Изоляция: контейнер одноразовый, никаких mount'ов хоста, CPU/RAM лимиты.
"""

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field

from .analyze import RepoAnalysis

SANDBOX_ROOT = os.path.join(os.path.expanduser("~"), ".repodoctor", "sandbox")
BUILD_TIMEOUT = 900
RUN_TIMEOUT = 180
MAX_LOG_BYTES = 60_000

IMAGE_TAG_RE = re.compile(r"[\W\s]")  # для санитизации тегов

PYTHON_IMAGE = "python:3.10-slim"
NODE_IMAGE = "node:20-slim"

MIRRORS = [
    "",                          # Docker Hub напрямую
    "mirror.gcr.io/",            # Google mirror
    "docker.m.daocloud.io/",     # DaoCloud mirror
]


def ensure_base_image(image: str) -> tuple[bool, str]:
    """Если базового образа нет локально — пробуем pull через доступные зеркала."""
    p = subprocess.run(["docker", "image", "inspect", image], capture_output=True, text=True)
    if p.returncode == 0:
        return True, ""
    candidates = [f"library/{image}", image]
    for mirror in MIRRORS:
        for cand in candidates:
            remote = mirror + cand
            p = subprocess.run(["docker", "pull", remote], capture_output=True, text=True, timeout=600)
            if p.returncode == 0:
                subprocess.run(["docker", "tag", remote, image], capture_output=True, text=True)
                return True, remote
    return False, "не удалось получить базовый образ ни из одного источника"


@dataclass
class RunResult:
    ok: bool
    stage: str = ""          # "build" | "run" | "prepare"
    log: str = ""            # комбинированный stdout+stderr
    image: str = ""
    command: str = ""
    duration_s: float = 0.0
    error: str = ""


def _sanitize_tag(s: str) -> str:
    return re.sub(r"[^a-z0-9._-]", "-", s.lower())[:64]


def make_dockerfile(a: RepoAnalysis) -> tuple[str, str]:
    """Возвращает (dockerfile_text, run_command)."""
    if a.project_type == "node":
        cmd = _pick_cmd(a, default="npm start")
        dockerfile = (
            f"FROM {NODE_IMAGE}\n"
            "WORKDIR /app\n"
            "COPY . .\n"
            "RUN npm install --no-audit --no-fund || true\n"
            f"CMD {cmd}\n"
        )
        return dockerfile, cmd
    cmd = _pick_cmd(a, default="python main.py")
    install = "RUN pip install --no-cache-dir -r requirements.txt || true" if a.has_requirements else ""
    dockerfile = (
        f"FROM {PYTHON_IMAGE}\n"
        "ENV PYTHONUNBUFFERED=1\n"
        "WORKDIR /app\n"
        "RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git build-essential || true\n"
        f"{install}\n"
        "COPY . .\n"
        f"CMD {cmd}\n"
    )
    return dockerfile, cmd


def _pick_cmd(a: RepoAnalysis, default: str) -> str:
    """Формирует CMD для Dockerfile по найденным точкам входа."""
    for entry in a.entry_points:
        c = entry["cmd"] if isinstance(entry, dict) else entry
        c = c.strip()
        if c.startswith("python ") and "pip" not in c[:8]:
            script = c.split(maxsplit=1)[-1].split()[0]
            return _cmd_json(["python", script])
        if re.match(r"^\./[\w.\-]+\.py(\s|$)?", c):
            script = c.split()[0].lstrip("./")
            return _cmd_json(["python", script])
    if a.project_type == "node":
        return _cmd_json(["npm", "start"])
    return _cmd_json(["sh", "-c", default])


def _cmd_json(parts: list[str]) -> str:
    import json
    return json.dumps(parts)


def prepare_sandbox(a: RepoAnalysis) -> str:
    """Копирует клон в sandbox и пишет туда Dockerfile. Возвращает путь sandbox."""
    os.makedirs(SANDBOX_ROOT, exist_ok=True)
    tag = _sanitize_tag(a.repo_name or "project")
    dest = os.path.join(SANDBOX_ROOT, tag)
    if os.path.exists(dest):
        shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(a.path, dest, ignore=shutil.ignore_patterns(
        ".git", "__pycache__", "node_modules", ".venv", "venv", ".ipynb_checkpoints"))
    dockerfile, _ = make_dockerfile(a)
    with open(os.path.join(dest, "Dockerfile"), "w", encoding="utf-8") as fh:
        fh.write(dockerfile)
    return dest


def choose_base(a: RepoAnalysis) -> str:
    """Выбирает базовый образ по типу проекта и указанной версии Python."""
    if a.project_type == "node":
        return NODE_IMAGE
    import re as _re
    m = _re.match(r"(\d+\.\d+)", a.python_version or "")
    if m:
        return f"python:{m.group(1)}-slim"
    return PYTHON_IMAGE


def build_image(sb_path: str, repo_name: str, base_image: str = "", memory: str = "4g") -> RunResult:
    t0 = time.time()
    tag = f"repodoctor/{_sanitize_tag(repo_name)}-{int(time.time())}"
    ok, _src = ensure_base_image(base_image or PYTHON_IMAGE)
    if not ok:
        return RunResult(ok=False, stage="build",
                         error="Базовый образ Docker недоступен (Docker Hub заблокирован?)",
                         log="не удалось скачать базовый образ ни напрямую, ни через зеркала")
    cmd = ["docker", "build", "-t", tag,
           "--memory", memory, "--memory-swap", memory, sb_path]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return RunResult(ok=False, stage="build", error=str(e), log=str(e))
    log = _combine(p.stdout, p.stderr)
    if p.returncode != 0:
        return RunResult(ok=False, stage="build", log=_clip(log), duration_s=time.time() - t0,
                         error="образ собрать не удалось")
    return RunResult(ok=True, stage="build", log=_clip(log), image=tag, command=" ".join(cmd),
                     duration_s=time.time() - t0)


def run_image(tag: str, workdir: str = "/app", network: bool = True) -> RunResult:
    t0 = time.time()
    args = ["docker", "run", "--rm",
            "--memory", "1g", "--memory-swap", "1g", "--cpus=2",
            "-w", workdir]
    if not network:
        args.append("--network=none")
    args.append(tag)
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=RUN_TIMEOUT)
    except subprocess.TimeoutExpired as e:
        out = _clip(_combine(e.stdout or b"", e.stderr or b""))
        note = ("\n[RepoDoctor] Процесс превышен таймаут {} с — остановлен. "
                "Для исследований (обучение модели) это нормально; запустите с большим таймаутом."
                ).format(RUN_TIMEOUT)
        return RunResult(ok=False, stage="run", log=out + note, duration_s=RUN_TIMEOUT)
    log = _clip(_combine(p.stdout, p.stderr))
    return RunResult(ok=p.returncode == 0, stage="run", log=log,
                     duration_s=time.time() - t0, command=" ".join(args),
                     error="" if p.returncode == 0 else f"не нулевой код выхода {p.returncode}")


def _combine(a: str | bytes, b: str | bytes) -> str:
    def dec(x):
        if isinstance(x, bytes):
            return x.decode("utf-8", errors="replace")
        return x or ""
    return dec(a) + "\n" + dec(b)


def _clip(log: str) -> str:
    if len(log) > MAX_LOG_BYTES:
        return "…(усечено в начале)…\n" + log[-MAX_LOG_BYTES:]
    return log
