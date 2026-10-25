"""Диагностика лога ошибки через LLM."""

import os

from pathlib import Path

from .analyze import RepoAnalysis
from .llm import extract_json, generate

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

CATEGORIES_RU = {
    "missing_package": "недостающий пакет",
    "version_conflict": "конфликт версий",
    "missing_data": "отсутствуют данные/файл",
    "missing_api_key": "нет API-ключа",
    "syntax_or_path": "синтаксическая/ошибка пути",
    "hardware_or_cuda": "аппаратные ограничения/CUDA",
    "other": "другое",
}


def _render(template: str, **kwargs) -> str:
    out = template
    for k, v in kwargs.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def diagnose_log(log: str, source: str, a: RepoAnalysis | None = None,
                 environment: str = "python (host)", model: str = "") -> dict | str:
    """Возвращает dict с полями diagnosis/category/fix_commands или строку-ошибку."""
    t = (_PROMPTS_DIR / "diagnose.md").read_text(encoding="utf-8")
    prompt = _render(
        t,
        source=source,
        environment=environment,
        log=log[:8000],
        tree=(repr(a.tree[:80]) if a else "неизвестно"),
        readme=(a.readme_snippet[:3000] if a else "неизвестно"),
    )
    try:
        raw = generate(prompt, model=model)
    except RuntimeError as e:
        return str(e)
    parsed = extract_json(raw)
    if not parsed:
        return raw
    parsed.setdefault("category_label", CATEGORIES_RU.get(parsed.get("category", ""), "другое"))
    return parsed


def source_label(mode: str) -> str:
    return {
        "docker": "автоматический запуск в Docker-контейнере",
        "run": "запуск на машине пользователя",
        "paste": "вставлен пользователем вручную",
    }.get(mode, mode)
