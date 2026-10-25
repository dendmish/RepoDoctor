"""Анализ структуры репозитория: тип проекта, зависимости, точки входа, README."""

import os
import re
import ast
import json
from dataclasses import dataclass, field

import yaml

EntryCmd = dict  # {"cmd": str, "source": str}


@dataclass
class RepoAnalysis:
    path: str
    repo_name: str = ""
    project_type: str = "unknown"
    dependencies: list[str] = field(default_factory=list)
    python_version: str = ""
    entry_points: list[EntryCmd] = field(default_factory=list)
    readme_text: str = ""
    readme_snippet: str = ""
    tree: list[str] = field(default_factory=list)
    data_fragments: list[str] = field(default_factory=list)
    hard_paths: list[str] = field(default_factory=list)
    has_requirements: bool = False
    has_dockerfile: bool = False
    has_conda_env: bool = False
    has_pyproject: bool = False
    has_setup_py: bool = False
    has_package_json: bool = False
    has_makefile: bool = False
    has_cargo: bool = False
    has_go_mod: bool = False
    has_cmake: bool = False
    has_pom: bool = False
    has_gradle: bool = False
    has_gemfile: bool = False
    file_count: int = 0


REQUIRED_FILES = [
    "requirements.txt", "environment.yml", "pyproject.toml", "setup.py",
    "package.json", "Dockerfile", "Makefile",
]

# Расширения, которые считаем «кодом» для подсчёта
CODE_EXTS = {".py", ".ipynb", ".sh", ".js", ".ts", ".m", ".lua", ".r", ".cpp", ".c", ".java"}

# Фрагменты, указывающие на пути к данным
DATA_FRAGMENT_RE = re.compile(
    r"(?P<path>\.?(?:/[\w\-.]+){0,6}/(?:data|dataset|datasets|checkpoint|checkpoints|ckpt|weights|"
    r"model|models|features|output|outputs|result|results|log|logs)(?:/[\w\-.]+)*/[\w\-.]+)"
)

HARD_PATH_RE = re.compile(r"(?P<path>/(?:home|mnt|media|opt|Users)\" \+ \"/[\w\-.]+)")

HARD_PATH_SIMPLE_RE = re.compile(
    r"(?<!\w)/(?:home|mnt|media|tmp|var|opt)/[\w\-.]+|C:\\\\\\\\[\w\-.\\\\]+|C:\\\\[\w\-.\\\\]+"
)

RUN_CMD_RE = re.compile(r"```(bash|sh|shell|console|python)\n(.*?)```", re.DOTALL)

README_CANDIDATES = [
    "README.md", "readme.md", "README.rst", "READM.md", "README.txt", "README",
    "Readme.md", "readme.rst", "Readme.rst", "README.MD",
]


def safe_read(path: str, limit: int = 200_000) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read(limit)
    except OSError:
        return ""


def _list_tree(root: str, max_depth: int = 3) -> list[str]:
    lines = []
    base_depth = root.rstrip(os.sep).count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root):
        dirpath = dirpath.rstrip(os.sep)
        depth = dirpath.count(os.sep) - base_depth
        if depth > max_depth:
            dirnames[:] = []
            continue
        # скрыть служебные каталоги
        dirnames[:] = [d for d in dirnames if d not in
                       {".git", "__pycache__", ".ipynb_checkpoints", "node_modules",
                        ".venv", "venv", ".mypy_cache", ".pytest_cache", ".idea", ".vscode"}]
        for f in sorted(filenames):
            rel = os.path.relpath(os.path.join(dirpath, f), root).replace(os.sep, "/")
            lines.append(rel)
    return lines


def _parse_requirements(root: str) -> list[str]:
    headers = ["requirements.txt", "requirements/dev.txt"]
    found = [os.path.join(root, "requirements.txt")]
    if os.path.isdir(os.path.join(root, "requirements")):
        found = sorted(
            os.path.join(root, "requirements", n) for n in
            os.listdir(os.path.join(root, "requirements")) if n.endswith(".txt")
        )
    deps = []
    for path in found:
        if not os.path.isfile(path):
            continue
        for line in safe_read(path).splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("-"):
                continue
            deps.append(line.split("#")[0].strip())
    # удалить дубликаты, сохранив порядок
    return list(dict.fromkeys(deps))


def _parse_environment_yml(root: str) -> tuple[list[str], str]:
    path = os.path.join(root, "environment.yml")
    if not os.path.isfile(path):
        path = os.path.join(root, "environment.yaml")
    if not os.path.isfile(path):
        return [], ""
    try:
        data = yaml.safe_load(safe_read(path)) or {}
    except yaml.YAMLError:
        return [], ""
    deps = []
    for d in data.get("dependencies", []) or []:
        if isinstance(d, str):
            deps.append(d)
        elif isinstance(d, dict):
            for items in d.get("pip", []) or []:
                deps.append("pip:" + str(items))
    return deps, data.get("name", "") or ""


def _parse_pyproject(root: str) -> list[str]:
    path = os.path.join(root, "pyproject.toml")
    if not os.path.isfile(path):
        return []
    try:
        text = safe_read(path)
    except OSError:
        return []
    deps = []
    # грубый парсинг без toml-либы (в stdlib py3.11+ есть tomllib)
    try:
        import tomllib
        data = tomllib.loads(text)
        deps = data.get("project", {}).get("dependencies", []) or []
        opt = data.get("project", {}).get("optional-dependencies", {})
        for v in opt.values():
            if isinstance(v, list):
                deps.extend(v)
    except (ValueError, OSError, ModuleNotFoundError):
        for line in text.splitlines():
            if re.search(r"^\"?[A-Za-z0-9_.\-]+\[?", line) and ("==" in line or ">=" in line or "," in line or "\"" in line):
                deps.append(line.strip().strip(","))
    return deps


def _parse_setup_py(root: str) -> list[str]:
    path = os.path.join(root, "setup.py")
    if not os.path.isfile(path):
        return []
    text = safe_read(path)
    deps = []
    m = re.search(r"install_requires\s*=\s*\[(.*?)\]", text, re.DOTALL)
    if m:
        for raw in m.group(1).split(","):
            raw = raw.strip().strip("'\"")
            if raw:
                deps.append(raw)
    return deps


def _parse_package_json(root: str) -> list[str]:
    path = os.path.join(root, "package.json")
    if not os.path.isfile(path):
        return []
    try:
        data = json.loads(safe_read(path))
    except (json.JSONDecodeError, ValueError):
        return []
    deps = (data.get("dependencies") or {}).keys()
    scripts = data.get("scripts") or {}
    return list(deps)


def _parse_cargo_toml(root: str) -> tuple[list[str], str]:
    path = os.path.join(root, "Cargo.toml")
    if not os.path.isfile(path):
        return [], ""
    try:
        import tomllib
        data = tomllib.loads(safe_read(path))
    except (ValueError, OSError, ModuleNotFoundError):
        return [], ""
    deps = []
    for key in ("dependencies", "dev-dependencies"):
        for name in (data.get(key) or {}):
            deps.append(name)
    has_bin = bool(data.get("bin") or (data.get("package", {}).get("name")))
    return deps, (data.get("package", {}).get("name") or "") if has_bin else ""


def _parse_go_mod(root: str) -> tuple[list[str], str]:
    path = os.path.join(root, "go.mod")
    if not os.path.isfile(path):
        return [], ""
    text = safe_read(path)
    go_ver = ""
    m = re.search(r"^go\s+(\d+(?:\.\d+)?)", text, re.MULTILINE)
    if m:
        go_ver = m.group(1)
    deps = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("//") and "/" in line and not line.startswith(("module", "go ", "require", "exclude", "replace")):
            deps.append(line.split()[0])
    return deps[:20], go_ver


def _extract_python_version(root: str, readme: str) -> str:
    path = os.path.join(root, ".python-version")
    if os.path.isfile(path):
        v = safe_read(path).strip()
        if v:
            return v
    for text in [readme]:
        m = re.search(r"[Pp]ython[\s:\-]*(\d+\.\d+(?:\.\d+)?)", text or "")
        if m:
            return m.group(1)
    return ""


def _scan_code_fragments(root: str, max_files: int = 400) -> tuple[list[str], list[str]]:
    """Ищет пути к данным и жёстко зашитые пути в коде."""
    data_frags: list[str] = []
    hard_paths: list[str] = []
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in
                       {".git", "__pycache__", "node_modules", ".ipynb_checkpoints"}]
        for fn in filenames:
            if not fn.endswith((".py", ".ipynb", ".sh", ".yml", ".yaml", ".md")):
                continue
            if count >= max_files:
                break
            count += 1
            text = safe_read(os.path.join(dirpath, fn), limit=100_000)
            for m in DATA_FRAGMENT_RE.finditer(text):
                frag = m.group("path").strip()
                if len(frag) > 5 and frag not in data_frags:
                    data_frags.append(frag)
            for m in HARD_PATH_SIMPLE_RE.finditer(text):
                p = m.group(0).strip()
                if p not in hard_paths:
                    hard_paths.append(p)
    return data_frags[:40], hard_paths[:40]


LAUNCH_PREFIXES = (
    "python ", "python3 ", "pip ", "./", "cargo run", "cargo build",
    "go run", "go build", "make", "mvn ", "gradle ", "cmake ", "npm ",
    "ruby ", "bash ", "sh ",
)


def _entry_points_from_readme(readme: str, path: str) -> list[EntryCmd]:
    hits = []
    for m in RUN_CMD_RE.finditer(readme):
        block = m.group(2)
        for line in block.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("$"):
                line = line.lstrip("$ ").strip()
            if line.startswith("cd ") or line.startswith("git") or len(line) > 160:
                continue
            if not line.startswith(LAUNCH_PREFIXES):
                continue
            source = "README"
            if line.startswith(("cargo ", "go ", "make", "mvn ", "gradle ", "cmake ")):
                source = "README (%s)" % line.split()[0]
            hits.append({"cmd": line, "source": source})
    return hits[:15]


def _entry_points_from_files(root: str) -> list[EntryCmd]:
    hits = []
    common = ["main.py", "train.py", "app.py", "run.py", "demo.py", "test.py", "cli.py"]
    for f in common:
        if os.path.isfile(os.path.join(root, f)):
            hits.append({"cmd": f"python {f}", "source": "файл в корне"})
    return hits[:5]


def analyze_repo(path: str) -> RepoAnalysis:
    analysis = RepoAnalysis(path=path)
    analysis.repo_name = os.path.basename(path).split("__", 1)[-1]
    root = path

    readme = ""
    for cand in README_CANDIDATES:
        p = os.path.join(root, cand)
        if os.path.isfile(p):
            readme = safe_read(p)
            break
    analysis.readme_text = readme
    analysis.readme_snippet = readme[:1200]

    files = _list_tree(root)
    analysis.tree = files
    analysis.file_count = len(files)
    top_level = {f.split("/")[0] for f in files}

    analysis.has_requirements = "requirements.txt" in top_level
    analysis.has_pyproject = "pyproject.toml" in top_level
    analysis.has_setup_py = "setup.py" in top_level
    analysis.has_conda_env = any(x in files for x in ["environment.yml", "environment.yaml"])
    analysis.has_dockerfile = any(f.lower().startswith("dockerfile") for f in files)
    analysis.has_package_json = "package.json" in top_level
    analysis.has_makefile = "Makefile" in top_level
    analysis.has_cargo = "Cargo.toml" in top_level
    analysis.has_go_mod = "go.mod" in top_level
    analysis.has_cmake = any(x in files for x in ["CMakeLists.txt", "CMakeLists"])
    analysis.has_pom = "pom.xml" in top_level
    analysis.has_gradle = any(x in top_level for x in ["build.gradle", "build.gradle.kts"]) \
        or any(f.startswith("gradlew") for f in top_level)
    analysis.has_gemfile = "Gemfile" in top_level

    deps = []
    if analysis.has_requirements:
        deps.extend(_parse_requirements(root))
    if analysis.has_conda_env:
        cdeps, _ = _parse_environment_yml(root)
        deps.extend(cdeps)
    if analysis.has_pyproject:
        deps.extend(_parse_pyproject(root))
    if analysis.has_setup_py:
        deps.extend(_parse_setup_py(root))
    if analysis.has_package_json:
        deps.extend(_parse_package_json(root))
    if analysis.has_cargo:
        cdeps, _ = _parse_cargo_toml(root)
        deps.extend(cdeps)
    if analysis.has_go_mod:
        gdeps, go_ver = _parse_go_mod(root)
        if go_ver:
            deps.append("go " + go_ver)
        deps.extend(gdeps)
    analysis.dependencies = list(dict.fromkeys(deps))[:80]

    analysis.python_version = _extract_python_version(root, readme)

    if analysis.has_requirements:
        analysis.project_type = "pip"
    elif analysis.has_conda_env:
        analysis.project_type = "conda"
    elif analysis.has_pyproject or analysis.has_setup_py:
        analysis.project_type = "python (pyproject/setup)"
    elif analysis.has_cargo:
        analysis.project_type = "rust"
    elif analysis.has_go_mod:
        analysis.project_type = "go"
    elif analysis.has_pom:
        analysis.project_type = "java-maven"
    elif analysis.has_gradle:
        analysis.project_type = "java-gradle"
    elif analysis.has_cmake or analysis.has_makefile:
        analysis.project_type = "cmake/make"
    elif analysis.has_gemfile:
        analysis.project_type = "ruby"
    elif analysis.has_package_json:
        analysis.project_type = "node"
    elif analysis.has_dockerfile:
        analysis.project_type = "docker"

    # Точки входа
    from_readme = _entry_points_from_readme(readme, path)
    from_files = _entry_points_from_files(root)
    analysis.entry_points = list(dict.fromkeys([h["cmd"] for h in from_readme + from_files]))[:15]

    # Пути к данным и жёсткие пути
    data_frags, hard = _scan_code_fragments(root)
    analysis.data_fragments = data_frags
    analysis.hard_paths = hard

    return analysis


def format_tree(tree: list[str], max_lines: int = 250) -> str:
    return "\n".join(tree[:max_lines]) + ("\n... (усечено)" if len(tree) > max_lines else "")
