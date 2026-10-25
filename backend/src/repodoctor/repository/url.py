"""Pure URL/ref policy shared by offline fixtures and the future GitHub source."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

from repodoctor.contracts.api import MAX_REF_LENGTH, MAX_REPO_URL_LENGTH
from repodoctor.contracts.domain import InvalidInputError

_OWNER = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", re.ASCII)
_REPO = re.compile(r"[A-Za-z0-9._-]+", re.ASCII)


def _has_control_characters(value: str) -> bool:
    # Check before urlsplit/strip: those functions can discard dangerous characters.
    return any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in value)


@dataclass(frozen=True, slots=True)
class NormalizedRepositoryURL:
    owner: str
    repo: str
    url: str


def normalize_repo_url(value: str) -> NormalizedRepositoryURL:
    """Accept only a GitHub repository root and return a case-insensitive identity.

    Never resolves DNS or performs I/O. Reject all percent escapes rather than trying
    to decode ambiguous path separators or double-encoded user input.
    """
    if (
        not isinstance(value, str)
        or not value
        or len(value) > MAX_REPO_URL_LENGTH
        or _has_control_characters(value)
        or any(char.isspace() for char in value)
        or any(char in value for char in ("\\", "%", "?", "#"))
    ):
        raise InvalidInputError("Введите HTTPS-ссылку на корень GitHub-репозитория.")

    try:
        parsed = urlsplit(value)
    except ValueError:
        raise InvalidInputError("Некорректная ссылка на GitHub-репозиторий.") from None
    # Exact netloc excludes credentials, explicit ports (even 443), and host suffixes.
    if parsed.scheme.lower() != "https" or parsed.netloc.lower() != "github.com":
        raise InvalidInputError("Поддерживается только https://github.com/OWNER/REPO.")

    path = parsed.path.removesuffix("/")
    segments = path.split("/")
    if len(segments) > 3 and segments[3] == "tree":
        raise InvalidInputError(
            "Укажите корень репозитория, а ветку или commit передайте в поле ref."
        )
    if len(segments) != 3 or segments[0] != "":
        raise InvalidInputError("Ссылка должна содержать только OWNER/REPO.")
    owner, repo = segments[1], segments[2]
    repo = repo.lower().removesuffix(".git")
    if (
        not 1 <= len(owner) <= 39
        or _OWNER.fullmatch(owner) is None
        or not 1 <= len(repo) <= 100
        or _REPO.fullmatch(repo) is None
        or repo in {".", ".."}
        or repo.endswith(".git")
    ):
        raise InvalidInputError("Некорректное имя владельца или репозитория GitHub.")
    owner, repo = owner.lower(), repo.lower()
    return NormalizedRepositoryURL(owner, repo, f"https://github.com/{owner}/{repo}")


def normalize_ref(value: str | None) -> str | None:
    """Normalize a separately supplied ref without forbidding branch slashes."""
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > MAX_REF_LENGTH or _has_control_characters(value):
        raise InvalidInputError("ref должен быть не длиннее 200 символов и без управляющих знаков.")
    return value.strip() or None


def encode_ref_segment(value: str) -> str:
    """Encode exactly one API path segment; this value is never a shell argument."""
    normalized = normalize_ref(value)
    if normalized is None:
        raise InvalidInputError("Для кодирования требуется непустой ref.")
    encoded = quote(normalized, safe="")
    # urllib deliberately leaves dots unescaped, including dot-only path segments.
    return encoded.replace(".", "%2E") if encoded in {".", ".."} else encoded
