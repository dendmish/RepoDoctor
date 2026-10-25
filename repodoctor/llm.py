"""Обёртка над Ollama: проверка доступности, вызов модели, извлечение JSON."""

import json
import os
import re
import subprocess
import time

import requests

OLLAMA_URL = os.environ.get("OLLAMA_URL", "")
_CANDIDATE_URLS = (
    os.environ.get("OLLAMA_URL"),
    "http://localhost:11434",
    "http://localhost:11435",
)
_resolved: list = []

_ACTIVE_URL = os.environ.get("OLLAMA_URL") or "http://localhost:11434"


def _probe(url: str) -> tuple[bool, int]:
    """Живой ли Ollama и сколько моделей видит (0 = жив, но пусто)."""
    try:
        r = requests.get(f"{url}/api/tags", timeout=3)
        r.raise_for_status()
        n = len(r.json().get("models", []))
        return True, n
    except (requests.RequestException, ValueError):
        return False, 0


def resolve_url() -> str:
    """Выбирает рабочий URL Ollama: env → сначала URL с моделями → любой живой."""
    global _ACTIVE_URL, _resolved
    if _resolved:
        return _ACTIVE_URL
    best_dead = None
    for url in _CANDIDATE_URLS:
        if url is None:
            continue
        ok, n = _probe(url)
        if ok and n > 0:
            _ACTIVE_URL = url
            break
        if ok and best_dead is None:
            best_dead = url
    else:
        if best_dead is not None:
            _ACTIVE_URL = best_dead
    _resolved = [_ACTIVE_URL]
    return _ACTIVE_URL


def active_url() -> str:
    return resolve_url()
DEFAULT_MODEL = "qwen2.5-coder:7b"
FALLBACK_MODELS = ["granite4.2:3b", "qwen3:4b", "qwen2.5:3b"]
TIMEOUT = 300


def ollama_ok() -> bool:
    ok, _n = _probe(resolve_url())
    return ok


def ensure_serve() -> None:
    if ollama_ok():
        return
    try:
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=open("/tmp/opencode/ollama-serve.log", "ab"),
            stderr=subprocess.STDOUT,
        )
    except OSError:
        pass
    deadline = time.time() + 10
    while time.time() < deadline:
        if ollama_ok():
            return
        time.sleep(0.5)
    resolve_url.cache_clear if hasattr(resolve_url, "cache_clear") else None
    _resolved.clear()


def installed_models() -> list[str]:
    try:
        r = requests.get(f"{resolve_url()}/api/tags", timeout=5)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except (requests.RequestException, ValueError):
        return []


def pick_model() -> str:
    """Выбирает первую установленную модель из списка приоритета."""
    have = installed_models()
    for m in [DEFAULT_MODEL] + FALLBACK_MODELS:
        if m in have:
            return m
    return have[0] if have else DEFAULT_MODEL


def generate(prompt: str, model: str = "") -> str:
    """Вызывает Ollama /api/generate (non-streaming). Бросает RuntimeError при недоступности."""
    ensure_serve()
    m = model or pick_model()
    try:
        r = requests.post(
            f"{resolve_url()}/api/generate",
            json={"model": m, "prompt": prompt, "stream": False, "options": {"temperature": 0.2}},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return r.json().get("response", "")
    except requests.RequestException as e:
        raise RuntimeError(f"Ollama недоступен: {e}. Запустите 'ollama serve' и 'ollama pull {m}'")


def extract_json(text: str):
    """Достаёт первый JSON-объект из ответа LLM (в том числе внутри ```json)."""
    m = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
    if m:
        return _try_load(m.group(1))
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return _try_load(text[start:i + 1])
    return None


def _try_load(raw: str):
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
