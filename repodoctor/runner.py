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
import tarfile
import time
from dataclasses import dataclass, field

from .analyze import RepoAnalysis, _parse_cargo_toml, _parse_go_mod

SANDBOX_ROOT = os.environ.get(
    "REPODOCTOR_SANDBOX",
    os.path.join(os.path.expanduser("~"), ".repodoctor", "sandbox"),
)
# режим «приложение работает в контейнере»: пути sandbox хост-демон не увидит,
# поэтому build-контекст передаём потоком через stdin
IN_CONTAINER = bool(os.environ.get("REPODOCTOR_SANDBOX"))
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
    """Возвращает (dockerfile_text, run_command) по типу проекта."""
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

    if a.project_type == "rust":
        return _dockerfile_rust(a)

    if a.project_type == "go":
        return _dockerfile_go(a)

    if a.project_type in ("java-maven", "java-gradle"):
        return _dockerfile_java(a)

    if a.project_type == "cmake/make":
        return _dockerfile_cmake(a)

    if a.project_type == "ruby":
        return _dockerfile_ruby(a)

    return _dockerfile_python(a)


def _dockerfile_rust(a: RepoAnalysis) -> tuple[str, str]:
    RUST_IMAGE = "rust:1-slim"
    cmd = _readme_cmd(a, ("cargo run", "cargo build")) or '["cargo", "run"]'
    dockerfile = (
        f"FROM {RUST_IMAGE}\n"
        "WORKDIR /app\n"
        "RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq build-essential pkg-config && rm -rf /var/lib/apt/lists/* || true\n"
        "COPY . .\n"
        "RUN cargo build --release || true\n"
        f"CMD {cmd}\n"
    )
    return dockerfile, cmd


def _dockerfile_go(a: RepoAnalysis) -> tuple[str, str]:
    GO_IMAGE = "golang:1.23-slim"
    _, go_ver = _parse_go_mod(a.path)
    image = f"golang:{go_ver}-slim" if go_ver else GO_IMAGE
    cmd = _readme_cmd(a, ("go run",)) or '["go", "run", "."]'
    dockerfile = (
        f"FROM {image}\n"
        "WORKDIR /app\n"
        "COPY go.mod .\n" + ("COPY go.sum .\n" if (a.path and os.path.isfile(os.path.join(a.path, "go.sum"))) else "") +
        "RUN go mod download 2>&1 | tail -3 || true\n"
        "COPY . .\n"
        "RUN go build -o repodoctor-app . || true\n"
        f"CMD {cmd}\n"
    )
    return dockerfile, cmd


def _dockerfile_java(a: RepoAnalysis) -> tuple[str, str]:
    if a.project_type == "java-maven":
        image, build, default = "maven:3.9-slim", "RUN mvn -q -DskipTests package || true", '["mvn", "exec:java"]'
        cmd = _readme_cmd(a, ("mvn ",)) or default
    else:
        image = "gradle:8-slim"
        build = "RUN gradle build -x test -q || true"
        cmd = _readme_cmd(a, ("gradle ",)) or _cmd_json(["gradle", "run"])
    dockerfile = (
        f"FROM {image}\n"
        "WORKDIR /app\n"
        "COPY . .\n"
        f"{build}\n"
        f"CMD {cmd}\n"
    )
    return dockerfile, cmd


def _dockerfile_cmake(a: RepoAnalysis) -> tuple[str, str]:
    img = TYPE_BASE["cmake/make"]
    build = (
        "RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build --parallel 2 "
        "|| make -j2 || true\n"
    )
    cmd = _readme_cmd(a, ("make", "./")) or \
        '["sh", "-c", "b=$(find ./bin ./build -maxdepth 2 -type f -executable 2>/dev/null | head -1); if [ -n \"$b\" ]; then exec ./$b; else exit 1; fi"]'
    dockerfile = (
        f"FROM {img}\n"
        "WORKDIR /app\n"
        "RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq cmake make && rm -rf /var/lib/apt/lists/* || true\n"
        "COPY . .\n"
        f"{build}"
        f"CMD {cmd}\n"
    )
    return dockerfile, cmd


def _dockerfile_ruby(a: RepoAnalysis) -> tuple[str, str]:
    cmd = _readme_cmd(a, ("ruby ",)) or '["ruby", "main.rb"]'
    dockerfile = (
        "FROM ruby:3.3-slim\n"
        "WORKDIR /app\n"
        + ("RUN bundle install || true\n" if a.has_gemfile else "") +
        "COPY . .\n"
        f"CMD {cmd}\n"
    )
    return dockerfile, cmd


def _readme_cmd(a: RepoAnalysis, prefixes) -> str | None:
    """Первый README-команда, начинающийся с одного из prefixes (без restore to shell)."""
    for entry in a.entry_points:
        c = entry["cmd"] if isinstance(entry, dict) else entry
        c = c.strip()
        if any(c.startswith(p) for p in prefixes):
            import json as _json
            return _json.dumps(["sh", "-c", c])
    return None


def _dockerfile_python(a: RepoAnalysis) -> tuple[str, str]:
    cmd = _pick_cmd(a, default="python main.py")
    torch_pkgs = [d.split()[0] for d in a.dependencies
                  if d.split()[0].split(":", 1)[-1].lower().split("[")[0] in
                  ("torch", "torchvision", "torchaudio")]
    torch_first = ""
    if torch_pkgs:
        pkgs = " ".join(dict.fromkeys(torch_pkgs))
        torch_first = ("RUN pip install --no-cache-dir " + pkgs +
                       " --index-url https://download.pytorch.org/whl/cpu || true\n")
    install = "RUN pip install --no-cache-dir -r requirements.txt || true" if a.has_requirements else ""
    dockerfile = (
        f"FROM {PYTHON_IMAGE}\n"
        "ENV PYTHONUNBUFFERED=1\n"
        "WORKDIR /app\n"
        "RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git build-essential || true\n"
        f"{torch_first}"
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
            args = c.split()
            if len(args) >= 2 and args[1].endswith(".py") and "/" not in args[1]:
                return _cmd_json(["python", args[1]])
            if len(args) >= 3 and args[1] == "-m" and args[2].endswith(".py"):
                return _cmd_json(["python", "-m", args[2]])
            continue
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
    """Копирует клон в sandbox и пишет туда Dockerfile (или сохраняет свой). Возвращает путь."""
    os.makedirs(SANDBOX_ROOT, exist_ok=True)
    tag = _sanitize_tag(a.repo_name or "project")
    dest = os.path.join(SANDBOX_ROOT, tag)
    if os.path.exists(dest):
        shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(a.path, dest, ignore=shutil.ignore_patterns(
        ".git", "__pycache__", "node_modules", ".venv", "venv", ".ipynb_checkpoints"))
    if not _has_native_dockerfile(dest):
        dockerfile, _ = make_dockerfile(a)
        with open(os.path.join(dest, "Dockerfile"), "w", encoding="utf-8") as fh:
            fh.write(dockerfile)
    return dest


def _has_native_dockerfile(dest: str) -> bool:
    return any(f.lower().startswith("dockerfile") for f in os.listdir(dest))


TYPE_BASE = {
    "node": NODE_IMAGE,
    "rust": "rust:1-slim",
    "java-maven": "maven:3.9-slim",
    "java-gradle": "gradle:8-slim",
    "cmake/make": "gcc:13",
    "ruby": "ruby:3.3-slim",
}


def choose_base(a: RepoAnalysis) -> str:
    """Выбирает базовый образ по типу проекта и указанным версиям."""
    base = TYPE_BASE.get(a.project_type)
    if base:
        return base
    if a.project_type == "go":
        _, go_ver = _parse_go_mod(a.path)
        return f"golang:{go_ver}-slim" if go_ver else "golang:1.23-slim"
    m = re.match(r"(\d+\.\d+)", a.python_version or "")
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
    if IN_CONTAINER:
        return _build_from_tar(sb_path, tag, memory, t0)
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


def _build_from_tar(sb_path: str, tag: str, memory: str, t0: float) -> RunResult:
    """Build-контекст tar-стримом: работает, когда sandbox смонтирован в контейнер приложения,
    а docker-демон крутится на хосте."""
    tar_path = os.path.join(SANDBOX_ROOT, f".buildctx-{tag.split('-')[-1]}.tar")
    try:
        with tarfile.open(tar_path, "w", format=tarfile.USTAR_FORMAT) as tf:
            for name in sorted(os.listdir(sb_path)):
                tf.add(os.path.join(sb_path, name), arcname=name)
        with open(tar_path, "rb") as fh:
            p = subprocess.run(
                ["docker", "build", "-t", tag,
                 "--memory", memory, "--memory-swap", memory, "-"],
                stdin=fh, capture_output=True, text=True, timeout=BUILD_TIMEOUT)
    except (tarfile.TarError, OSError, subprocess.TimeoutExpired) as e:
        return RunResult(ok=False, stage="build", error=str(e),
                         duration_s=time.time() - t0)
    finally:
        try:
            os.remove(tar_path)
        except OSError:
            pass
    log = _combine(p.stdout, p.stderr)
    if p.returncode != 0:
        return RunResult(ok=False, stage="build", log=_clip(log), duration_s=time.time() - t0,
                         error="образ собрать не удалось")
    return RunResult(ok=True, stage="build", log=_clip(log), image=tag,
                     command=f"docker build -t {tag} - (stdin-tar)",
                     duration_s=time.time() - t0)
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
