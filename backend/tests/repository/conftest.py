from __future__ import annotations

import socket
import subprocess

import httpx
import pytest

from repodoctor.contracts.api import AnalysisRequest


@pytest.fixture(autouse=True)
def offline_only(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("B1 must not use DNS, network, shell or repository subprocesses")

    # Windows asyncio creates a loopback socketpair while setting up its event loop.
    # Deny DNS/HTTP/connection helpers without breaking that internal wakeup pipe.
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)


@pytest.fixture
def analysis_request() -> AnalysisRequest:
    return AnalysisRequest(
        repo_url="https://github.com/repodoctor-fixtures/python-cli-demo",
        target={"os": "windows", "shell": "powershell"},
        use_ai=False,
    )
