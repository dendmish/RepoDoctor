"""Manual A3 smoke: real uvicorn on loopback, synthetic repos, no external API calls.

Run from backend: .venv/Scripts/python.exe tests/smoke_offline.py
Not collected by pytest; the child process always receives empty API credentials.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx


def main() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = dict(
        os.environ,
        APP_ENV="test",
        REPOSITORY_MODE="fixture",
        USE_DEV_STUBS="false",
        OPENAI_API_KEY="",
        OPENAI_MODEL="",
        GITHUB_TOKEN="",
        STORE_TTL_SECONDS="1",
    )
    process = subprocess.Popen(  # noqa: S603 -- fixed module/arguments, no shell or repo code
        [
            sys.executable,
            "-m",
            "uvicorn",
            "repodoctor.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        check_server(process, port)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def check_server(process: subprocess.Popen, port: int) -> None:
    with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10) as client:
        deadline = time.monotonic() + 20
        while True:
            try:
                assert client.get("/api/v1/health").status_code == 200
                break
            except httpx.ConnectError:
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("Server startup failed") from None
                time.sleep(0.1)
        analysis_id = ""
        for name, target, log in [
            (
                "python-cli-demo",
                {"os": "windows", "shell": "powershell"},
                "ModuleNotFoundError: No module named 'requests'",
            ),
            ("node-api-demo", {"os": "linux", "shell": "bash"}, "npm ERR! EBADENGINE"),
        ]:
            result = client.post(
                "/api/v1/analyses",
                json={
                    "repo_url": f"https://github.com/repodoctor-fixtures/{name}",
                    "target": target,
                    "use_ai": False,
                },
            )
            assert result.status_code == 201, result.status_code
            analysis = result.json()
            analysis_id = analysis["analysis_id"]
            result = client.post(
                f"/api/v1/analyses/{analysis_id}/diagnoses", json={"log": log, "use_ai": False}
            )
            assert result.status_code == 200, result.status_code
            print(
                json.dumps(
                    {
                        "fixture": name,
                        "analysis": 201,
                        "diagnosis": 200,
                        "source": analysis["source_mode"],
                        "mode": analysis["generation"]["mode"],
                        "causes": len(result.json()["causes"]),
                    }
                )
            )
        result = client.post(
            "/api/v1/analyses",
            json={
                "repo_url": "http://127.0.0.1/private",
                "target": {"os": "linux", "shell": "bash"},
                "use_ai": False,
            },
        )
        assert result.status_code == 422
        time.sleep(1.2)
        result = client.post(
            f"/api/v1/analyses/{analysis_id}/diagnoses", json={"log": "EADDRINUSE", "use_ai": False}
        )
        assert result.status_code == 404
        print("invalid URL: 422; expired analysis: 404; no stubs or external API calls")


if __name__ == "__main__":
    main()
