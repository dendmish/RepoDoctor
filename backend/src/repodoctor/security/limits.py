"""Shared operation limiter and ASGI request-body limit (ARCHITECTURE.md section 10)."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from repodoctor.contracts.api import ErrorBody, ErrorCode, ErrorResponse
from repodoctor.contracts.domain import ServerBusyError
from repodoctor.observability import log_event, request_id_var

MAX_BODY_BYTES = 128 * 1024
# Oversized bodies up to this size are read and discarded so the client receives the 413
# envelope; larger declared bodies are rejected immediately and the connection is closed.
DRAIN_LIMIT_BYTES = 1024 * 1024
REQUEST_ID_HEADER = b"x-request-id"


class OperationLimiter:
    """Fail-fast cap on heavy operations; analysis and diagnosis share one instance.

    No queue: when all slots are taken the caller gets SERVER_BUSY immediately. The check
    and the increment happen without an await, so they are atomic on the event loop.
    """

    def __init__(self, max_operations: int) -> None:
        if max_operations < 1:
            raise ValueError("max_operations must be positive")
        self._max = max_operations
        self._active = 0

    @property
    def active(self) -> int:
        return self._active

    @asynccontextmanager
    async def acquire_operation_slot(self) -> AsyncIterator[None]:
        if self._active >= self._max:
            raise ServerBusyError(
                "Сервер занят другими операциями. Повторите через несколько секунд."
            )
        self._active += 1
        try:
            yield
        finally:  # released on success, error, timeout and cancellation
            self._active -= 1


def _new_request_id() -> str:
    return uuid.uuid4().hex


class RequestContextMiddleware:
    """Assigns a server-side request_id, exposes it as X-Request-ID and logs the outcome."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = _new_request_id()
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_var.set(request_id)
        started = time.monotonic()
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                headers = [
                    (k, v) for k, v in message.get("headers", []) if k.lower() != REQUEST_ID_HEADER
                ]
                headers.append((REQUEST_ID_HEADER, request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            log_event(
                "http_request",
                method=scope.get("method"),
                path=scope.get("path"),
                status=status,
                duration_ms=round((time.monotonic() - started) * 1000),
            )
            request_id_var.reset(token)


class BodyLimitMiddleware:
    """Rejects bodies above `max_bytes` while reading, including chunked uploads.

    Content-Length is checked first, but the actual received bytes are counted too, so a
    missing or false header does not bypass the limit. At most max_bytes + one chunk is
    buffered before the request is rejected.
    """

    def __init__(
        self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES, drain_limit: int = DRAIN_LIMIT_BYTES
    ) -> None:
        self.app = app
        self.max_bytes = max_bytes
        self.drain_limit = max(drain_limit, max_bytes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = 0
        for name, value in scope.get("headers", []):
            if name.lower() == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = 0
        if declared > self.drain_limit:
            await self._reject(scope, send)
            return

        chunks: list[bytes] = []
        total = 0
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            more_body = message.get("more_body", False)
            total += len(body)
            if total > self.max_bytes:
                await self._drain(receive, total, more_body)
                await self._reject(scope, send)
                return
            chunks.append(body)

        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    async def _drain(self, receive: Receive, total: int, more_body: bool) -> None:
        """Read and discard the rest of a moderately oversized body (nothing is buffered).

        Responding before the client finished sending makes the server close the socket,
        and the client may see a connection reset instead of the JSON 413 envelope.
        """
        while more_body and total <= self.drain_limit:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            total += len(message.get("body", b""))
            more_body = message.get("more_body", False)

    async def _reject(self, scope: Scope, send: Send) -> None:
        state = scope.get("state") or {}
        request_id = state.get("request_id") or _new_request_id()
        body = ErrorResponse(
            error=ErrorBody(
                code=ErrorCode.PAYLOAD_TOO_LARGE,
                message=f"Тело запроса превышает {self.max_bytes // 1024} KiB.",
                retryable=False,
                details=[],
                request_id=request_id,
            )
        ).model_dump_json()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body.encode())).encode()),
                    (b"connection", b"close"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body.encode()})
