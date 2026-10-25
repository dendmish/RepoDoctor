"""Фасад: полный цикл «ссылка → анализ → план запуска → пробный запуск → диагноз»."""

import os

from . import clone as _clone
from .analyze import RepoAnalysis, analyze_repo, format_tree
from .checks import ChecksReport, run_checks
from .diagnose import diagnose_log, source_label
from .llm import generate, extract_json, ollama_ok, pick_model
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
    base = _runner.choose_base(a)
    bres = build_image(sb, a.repo_name or "project", base_image=base)
    if not bres.ok and "образ" in bres.error and base != _runner.PYTHON_IMAGE:
        bres = build_image(sb, a.repo_name or "project")  # fallback на дефолтную базу
    if not bres.ok:
        return bres
    tag = bres.image if bres.image else _last_image_from_log(bres.log)
    if not tag:
        return bres
    rres = run_image(tag, network=network)
    rres.image = tag
    return rres


def _last_image_from_log(log: str) -> str:
    for line in reversed(log.splitlines()):
        line = line.strip()
        if line.startswith("Successfully tagged") or "-> Successfully tagged" in line:
            return line.rsplit(" ", 1)[-1]
    return ""
