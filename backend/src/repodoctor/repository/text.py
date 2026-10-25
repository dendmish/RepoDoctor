"""Use the platform sanitizer; env templates expose names, never values."""

from __future__ import annotations

import re

from repodoctor.security.redaction import redact_text


def redact_file_text(path: str, content: str) -> str:
    content, _ = redact_text(content)
    if path.rsplit("/", 1)[-1] == ".env.example":
        content = re.sub(
            r"(?m)^([ \t]*(?:export[ \t]+)?[A-Za-z_][A-Za-z0-9_]*[ \t]*=)[^\r\n]*",
            r"\1[REDACTED]",
            content,
        )
    return content
