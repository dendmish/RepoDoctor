"""In-memory TTL + LRU store of analysis contexts (single worker, lost on restart)."""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable

from repodoctor.contracts.domain import AnalysisContext

MAX_CONTEXT_BYTES = 512 * 1024


def context_size_bytes(context: AnalysisContext) -> int:
    return len(context.model_dump_json().encode("utf-8"))


class ContextTooLargeError(ValueError):
    pass


class MemoryAnalysisStore:
    """OrderedDict keyed by analysis_id.

    Expiry uses a monotonic clock (wall-clock changes do not extend or cut TTL); access
    refreshes LRU order but never extends TTL, so `expires_at` shown to the user stays true.
    Raw logs are never stored: only AnalysisContext (response + redacted selected files).
    """

    def __init__(
        self,
        ttl_seconds: float,
        max_items: int,
        *,
        max_context_bytes: int = MAX_CONTEXT_BYTES,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._max_items = max_items
        self._max_bytes = max_context_bytes
        self._now = monotonic
        self._items: OrderedDict[str, tuple[float, AnalysisContext]] = OrderedDict()

    def __len__(self) -> int:
        return len(self._items)

    def put(self, context: AnalysisContext) -> None:
        self.purge_expired()
        if context_size_bytes(context) > self._max_bytes:
            raise ContextTooLargeError("analysis context exceeds the store size limit")
        analysis_id = context.response.analysis_id
        self._items[analysis_id] = (self._now() + self._ttl, context)
        self._items.move_to_end(analysis_id)
        while len(self._items) > self._max_items:
            self._items.popitem(last=False)

    def get(self, analysis_id: str) -> AnalysisContext | None:
        self.purge_expired()
        entry = self._items.get(analysis_id)
        if entry is None:
            return None
        self._items.move_to_end(analysis_id)
        return entry[1]

    def purge_expired(self) -> int:
        now = self._now()
        expired = [key for key, (deadline, _) in self._items.items() if deadline <= now]
        for key in expired:
            del self._items[key]
        return len(expired)
