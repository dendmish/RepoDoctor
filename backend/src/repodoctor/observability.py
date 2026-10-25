"""Request-scoped context and structured log events.

Logs carry IDs, phases, durations, counts and statuses only: never bodies, prompts, logs or keys.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("repodoctor_request_id", default=None)

logger = logging.getLogger("repodoctor")


def log_event(event: str, **fields: object) -> None:
    """Emit `event key=value ...` with the current request_id attached."""
    parts = [f"request_id={request_id_var.get() or '-'}"]
    parts.extend(f"{key}={value}" for key, value in fields.items())
    logger.info("%s %s", event, " ".join(parts))
