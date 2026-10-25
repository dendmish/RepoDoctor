from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from repodoctor.contracts.domain import AnalysisContext, ServerBusyError
from repodoctor.security.limits import BodyLimitMiddleware, OperationLimiter
from repodoctor.services.store import ContextTooLargeError, MemoryAnalysisStore

from .fakes import PYTHON_EXAMPLE, FakeAnalyzer, FakeSource


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


async def _context(analysis_id: str | None = None) -> AnalysisContext:
    snapshot = await FakeSource().fetch(None)  # type: ignore[arg-type]
    response = PYTHON_EXAMPLE.model_copy(update={"analysis_id": analysis_id or str(uuid.uuid4())})
    return AnalysisContext(response=response, scan=FakeAnalyzer().analyze(snapshot))


# --- store ----------------------------------------------------------------------------------


async def test_store_ttl_uses_monotonic_clock() -> None:
    clock = FakeClock()
    store = MemoryAnalysisStore(ttl_seconds=1800, max_items=30, monotonic=clock)
    ctx = await _context()
    store.put(ctx)
    clock.now += 1799
    assert store.get(ctx.response.analysis_id) is ctx
    clock.now += 1
    assert store.get(ctx.response.analysis_id) is None
    assert len(store) == 0


async def test_store_access_does_not_extend_ttl() -> None:
    clock = FakeClock()
    store = MemoryAnalysisStore(ttl_seconds=10, max_items=30, monotonic=clock)
    ctx = await _context()
    store.put(ctx)
    for _ in range(3):
        clock.now += 3
        assert store.get(ctx.response.analysis_id) is ctx
    clock.now += 1
    assert store.get(ctx.response.analysis_id) is None


async def test_store_evicts_least_recently_used() -> None:
    store = MemoryAnalysisStore(ttl_seconds=100, max_items=2, monotonic=FakeClock())
    a, b, c = await _context(), await _context(), await _context()
    store.put(a)
    store.put(b)
    assert store.get(a.response.analysis_id) is a  # a becomes most recent
    store.put(c)
    assert store.get(b.response.analysis_id) is None
    assert store.get(a.response.analysis_id) is a
    assert store.get(c.response.analysis_id) is c


async def test_purge_expired_returns_count() -> None:
    clock = FakeClock()
    store = MemoryAnalysisStore(ttl_seconds=5, max_items=30, monotonic=clock)
    store.put(await _context())
    store.put(await _context())
    clock.now += 5
    assert store.purge_expired() == 2


async def test_store_rejects_oversized_context() -> None:
    store = MemoryAnalysisStore(ttl_seconds=5, max_items=30, max_context_bytes=1000)
    with pytest.raises(ContextTooLargeError):
        store.put(await _context())


# --- limiter --------------------------------------------------------------------------------


async def test_limiter_fails_fast_and_releases() -> None:
    limiter = OperationLimiter(1)
    async with limiter.acquire_operation_slot():
        with pytest.raises(ServerBusyError):
            async with limiter.acquire_operation_slot():
                pass
    assert limiter.active == 0
    async with limiter.acquire_operation_slot():
        assert limiter.active == 1


async def test_limiter_releases_on_error_and_cancel() -> None:
    limiter = OperationLimiter(2)
    with pytest.raises(RuntimeError):
        async with limiter.acquire_operation_slot():
            raise RuntimeError

    entered = asyncio.Event()

    async def hold() -> None:
        async with limiter.acquire_operation_slot():
            entered.set()
            await asyncio.sleep(60)

    task = asyncio.create_task(hold())
    await entered.wait()
    assert limiter.active == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert limiter.active == 0


# --- body limit -----------------------------------------------------------------------------


@pytest.fixture
def echo_client() -> TestClient:
    app = FastAPI()

    @app.post("/echo")
    async def echo(request: Request) -> dict:
        return {"size": len(await request.body())}

    app.add_middleware(BodyLimitMiddleware, max_bytes=1024)
    return TestClient(app)


def test_body_under_limit_passes(echo_client: TestClient) -> None:
    response = echo_client.post("/echo", content=b"a" * 1024)
    assert response.status_code == 200 and response.json() == {"size": 1024}


def test_body_over_content_length_is_rejected(echo_client: TestClient) -> None:
    response = echo_client.post("/echo", content=b"a" * 1025)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_huge_declared_body_is_rejected_without_reading() -> None:
    app = FastAPI()
    received: list[int] = []

    @app.post("/echo")
    async def echo(request: Request) -> dict:
        received.append(len(await request.body()))
        return {}

    app.add_middleware(BodyLimitMiddleware, max_bytes=1024, drain_limit=4096)
    response = TestClient(app).post("/echo", content=b"a" * 5000)
    assert response.status_code == 413 and received == []


def test_chunked_body_without_length_is_rejected(echo_client: TestClient) -> None:
    def chunks():
        for _ in range(5):
            yield b"a" * 300

    response = echo_client.post("/echo", content=chunks())
    assert "content-length" not in {k.lower() for k in response.request.headers}
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_chunked_body_under_limit_passes(echo_client: TestClient) -> None:
    def chunks():
        yield b"a" * 300
        yield b"b" * 300

    response = echo_client.post("/echo", content=chunks())
    assert response.status_code == 200 and response.json() == {"size": 600}
