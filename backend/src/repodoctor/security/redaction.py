"""Best-effort secret masking shared by platform (logs, commands) and repository (files).

Pure functions: no I/O, no logging of matched values. Line count is always preserved so that
evidence line numbers stay valid after redaction. This is not a guarantee of anonymization.
"""

from __future__ import annotations

import re

from repodoctor.contracts.domain import SanitizedLog

REDACTED = "[REDACTED]"

_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|\Z)",
    re.DOTALL,
)

# Whole-match replacements: the match itself is the secret.
_TOKEN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{16,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
)

# Prefix-preserving replacements: group 1 is kept, the rest of the match is masked.
_PREFIXED_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Authorization: Bearer xxx / Authorization: token xxx
    re.compile(
        r"(?i)(\b(?:proxy-)?authorization\s*[:=]\s*(?:bearer|basic|token|digest)?\s*)"
        r"(?!\[REDACTED|(?:bearer|basic|token|digest)\b)[^\s\"',;]+"
    ),
    re.compile(r"(?i)(\bbearer\s+)(?!\[REDACTED)[A-Za-z0-9._~+/=-]{8,}"),
    # scheme://user:password@host -> scheme://[REDACTED]@host
    re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+(?=@)"),
    # NAME_WITH_SECRET=value, "token": "value", password=value in query strings
    re.compile(
        r"(?i)(\b[A-Za-z0-9_.-]*(?:secret|token|passw(?:or)?d|pwd|api[_-]?key|access[_-]?key"
        r"|auth(?:orization)?[_-]?key|private[_-]?key|credentials?)"
        r"[A-Za-z0-9_.-]*[\"']?\s*[=:]\s*[\"']?)"
        r"(?!\[REDACTED)[^\s\"'&,;]+"
    ),
)

_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _mask_private_key(match: re.Match[str]) -> str:
    # Keep the same number of lines as the original block.
    return "[REDACTED PRIVATE KEY]" + "\n" * match.group(0).count("\n")


def redact_text(text: str) -> tuple[str, int]:
    """Mask secrets in `text`. Returns the masked text and the number of replacements."""
    count = 0
    text, n = _PRIVATE_KEY_RE.subn(_mask_private_key, text)
    count += n
    for pattern in _TOKEN_PATTERNS:
        text, n = pattern.subn(REDACTED, text)
        count += n
    for pattern in _PREFIXED_PATTERNS:
        text, n = pattern.subn(lambda m: m.group(1) + REDACTED, text)
        count += n
    return text, count


def sanitize_log(raw: str) -> SanitizedLog:
    """ANSI removal, newline normalization and redaction of a pasted terminal log.

    The result is never persisted; line numbers refer to this processed text.
    """
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = _ANSI_RE.sub("", text)
    text = _CONTROL_RE.sub("", text)
    text, count = redact_text(text)
    return SanitizedLog(text=text, redactions_count=count, truncated=False)
