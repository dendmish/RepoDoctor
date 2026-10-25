"""Клонирование GitHub-репозитория для анализа.

Стратегия:
1. git clone --depth 1 (быстро, сохраняет git-контекст)
2. Fallback: скачивание tarball через codeload.github.com (если git недоступен)
"""

import os
import re
import shutil
import subprocess
import tempfile
import tarfile
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

REPO_ROOT = os.path.join(tempfile.gettempdir(), "repodoctor")
CLONE_TIMEOUT = 120
TARBALL_TIMEOUT = 120
UA = {"User-Agent": "RepoDoctor/0.1 (+https://github.com/)"}

_GH_URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/(?P<owner>[A-Za-z0-9_.\-]+)/(?P<repo>[A-Za-z0-9_.\-]+?)(?:\.git)?/?$"
)

VALID_URL = re.compile(
    r"https?://github\.com/[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+"
)


@dataclass
class CloneResult:
    ok: bool
    path: str = ""
    owner: str = ""
    repo: str = ""
    url: str = ""
    method: str = ""
    error: str = ""


def parse_repo_url(url: str) -> tuple[str, str] | None:
    """Возвращает (owner, repo) или None."""
    url = url.strip()
    m = _GH_URL_RE.match(url)
    if not m:
        return None
    return m.group("owner"), m.group("repo")


def normalize_url(url: str) -> str:
    owner, repo = parse_repo_url(url)
    return f"https://github.com/{owner}/{repo}"


def _already_cloned(owner: str, repo: str) -> str | None:
    path = os.path.join(REPO_ROOT, f"{owner}__{repo}")
    if os.path.isdir(path) and os.path.isdir(os.path.join(path, ".git")):
        return path
    return None


def clone_repo(url: str) -> CloneResult:
    """Клонирует GitHub-репозиторий поверхностно. Повторный вызов — переиспользует кэш."""
    parsed = parse_repo_url(url)
    if not parsed:
        return CloneResult(ok=False, error="Не похоже на ссылку GitHub-репозитория")
    owner, repo = parsed
    dest = os.path.join(REPO_ROOT, f"{owner}__{repo}")

    cached = _already_cloned(owner, repo)
    if cached:
        return CloneResult(ok=True, path=cached, owner=owner, repo=repo,
                           url=normalize_url(url), method="cache")

    os.makedirs(REPO_ROOT, exist_ok=True)
    if os.path.exists(dest):
        shutil.rmtree(dest, ignore_errors=True)

    git_url = f"https://github.com/{owner}/{repo}.git"
    ok, err = _git_clone(git_url, dest)
    if ok:
        return CloneResult(ok=True, path=dest, owner=owner, repo=repo,
                           url=normalize_url(url), method="git")

    shutil.rmtree(dest, ignore_errors=True)
    ok2, err2 = _tarball_download(owner, repo, dest)
    if ok2:
        return CloneResult(ok=True, path=dest, owner=owner, repo=repo,
                           url=normalize_url(url), method="tarball")
    return CloneResult(ok=False, owner=owner, repo=repo, url=normalize_url(url),
                       error=f"git: {err} | tarball: {err2}")


def _git_clone(git_url: str, dest: str) -> tuple[bool, str]:
    try:
        p = subprocess.run(
            ["git", "clone", "--depth", "1", "--single-branch", git_url, dest],
            capture_output=True, text=True, timeout=CLONE_TIMEOUT,
        )
        if p.returncode == 0 and os.path.isdir(dest):
            return True, ""
        return False, (p.stderr or "").strip().splitlines()[-1:][0] if p.stderr else "неизвестная ошибка git"
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return False, str(e)


def _tarball_download(owner: str, repo: str, dest: str) -> tuple[bool, str]:
    url = f"https://codeload.github.com/{owner}/{repo}/tar.gz/HEAD"
    try:
        with requests.get(url, headers=UA, timeout=TARBALL_TIMEOUT, stream=True) as r:
            r.raise_for_status()
            tmp = dest + ".tar.gz"
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    fh.write(chunk)
        with tarfile.open(tmp, "r:gz") as tf:
            members = tf.getmembers()
            root = os.path.commonprefix([m.name.split("/")[0] for m in members if m.name])
            tf.extractall(REPO_ROOT)  # noqa: S202 — источник codeload, путь проверяем ниже
        os.remove(tmp)
        inner = os.path.join(REPO_ROOT, root)
        if not os.path.isdir(inner):
            return False, "неожиданная структура tarball"
        shutil.move(inner, dest)
        return True, ""
    except requests.RequestException as e:
        return False, f"HTTP: {e}"
    except (tarfile.TarError, OSError) as e:
        return False, f"tar: {e}"


def clear_cache():
    shutil.rmtree(REPO_ROOT, ignore_errors=True)


def is_github_repo(url: str) -> bool:
    """Проверяет существование репозитория по GitHub API (2xx = существует)."""
    parsed = parse_repo_url(url)
    if not parsed:
        return False
    owner, repo = parsed
    try:
        r = requests.get(f"https://api.github.com/repos/{owner}/{repo}",
                         headers=UA, timeout=15)
        return r.status_code == 200
    except requests.RequestException:
        return False
