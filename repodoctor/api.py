"""Фасад: полный цикл «ссылка → анализ → план запуска → пробный запуск → диагноз»."""

import os

from . import clone as _clone
from .analyze import RepoAnalysis, analyze_repo, format_tree
from .checks import ChecksReport, run_checks
from .diagnose import diagnose_log, source_label
from .llm import generate, extract_json, ollama_ok, pick_model, installed_models
from . import runner as _runner
from .runner import prepare_sandbox, build_image, run_image


def inspect_repo(url: str) -> tuple[RepoAnalysis | None, ChecksReport | str]:
    """Клонирует + анализирует репо. Возвращает (analysis, checks) или (None, ошибка)."""
    cr = _clone.clone_repo(url)
    if not cr.ok:
        return None, f"Не удалось склонировать: {cr.error}"
    a = analyze_repo(cr.path)
    checks = run_checks(a)
    return a, checks


def plan_from_analysis(a: RepoAnalysis, checks: ChecksReport, model: str = "") -> dict | str:
    """Пошаговая инструкция + комментарии к рискам, через LLM."""
    prompt_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "prompts")
    with open(os.path.join(prompt_dir, "plan.md"), encoding="utf-8") as fh:
        template = fh.read()
    prompt = (template
              .replace("{findings}", str(checks.as_dicts())[:4000])
              .replace("{tree}", "\n".join(a.tree[:120]))
              .replace("{entry_points}", str(a.entry_points))
              .replace("{deps}", ", ".join(a.dependencies[:60]))
              .replace("{pyver}", a.python_version or "не указан")
              .replace("{readme}", a.readme_snippet[:3000])
              )
    try:
        raw = generate(prompt, model=model)
    except RuntimeError as e:
        return str(e)
    parsed = extract_json(raw)
    if not parsed:
        return raw
    return parsed


def try_run(a: RepoAnalysis, network: bool = True) -> _runner.RunResult:
    """Готовит sandbox, строит образ и запускает проект. Возвращает RunResult с логом."""
    sb = prepare_sandbox(a)
    native = _runner._has_native_dockerfile(sb)
    base = _runner.choose_base(a)
    bres = build_image(sb, a.repo_name or "project", base_image=base)
    if not bres.ok and "образ" in bres.error and base != _runner.PYTHON_IMAGE:
        bres = build_image(sb, a.repo_name or "project")  # fallback на дефолтную базу
    if not bres.ok and native:
        rr = _retry_with_generated(sb, a, network=network)
        rr.log = ("[RepoDoctor] Собственный Dockerfile репо сломан на сборке — пересобрали нашим шаблоном.\n" + rr.log)
        return rr
    if not bres.ok:
        return bres
    tag = bres.image if bres.image else _last_image_from_log(bres.log)
    if not tag:
        return bres
    rres = run_image(tag, network=network)
    rres.image = tag
    if not rres.ok and native:
        if "exit" in (rres.error or "") or rres.duration_s < 120:
            rr = _retry_with_generated(sb, a, network=network)
            rr.log = ("[RepoDoctor] Собственный Dockerfile репо не завёлся — пересобрали нашим шаблоном.\n" + rr.log)
            return rr if rr.ok else _pick_better(rr, rres)
    return rres


def _retry_with_generated(sb: str, a: RepoAnalysis, network: bool = True) -> _runner.RunResult:
    for f in list(os.listdir(sb)):
        if f.lower().startswith("dockerfile") and f != "Dockerfile":
            try:
                os.rename(os.path.join(sb, f), os.path.join(sb, "Dockerfile.repo"))
            except OSError:
                pass
        elif f == "Dockerfile":
            os.rename(os.path.join(sb, f), os.path.join(sb, "Dockerfile.repo"))
    dockerfile, _ = _runner.make_dockerfile(a)
    with open(os.path.join(sb, "Dockerfile"), "w", encoding="utf-8") as fh:
        fh.write(dockerfile)
    bres = build_image(sb, a.repo_name or "project", base_image=_runner.choose_base(a))
    if not bres.ok:
        return bres
    tag = bres.image or _last_image_from_log(bres.log)
    if not tag:
        return bres
    rres = run_image(tag, network=network)
    rres.image = rres.image or tag
    return rres


def _pick_better(new: _runner.RunResult, old: _runner.RunResult) -> _runner.RunResult:
    return new if (new.ok or (new.log and not old.log)) else old


def _last_image_from_log(log: str) -> str:
    for line in reversed(log.splitlines()):
        line = line.strip()
        if line.startswith("Successfully tagged") or "-> Successfully tagged" in line:
            return line.rsplit(" ", 1)[-1]
    return ""
