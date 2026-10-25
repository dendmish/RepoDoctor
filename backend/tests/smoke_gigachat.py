"""Explicit live smoke: two GigaChat generations on synthetic repository/log data.

Run from backend: .venv/Scripts/python.exe tests/smoke_gigachat.py
Uses local .env, prints generation metadata only. Never collected by normal pytest.
"""

from __future__ import annotations

import asyncio
import json
from time import perf_counter

from repodoctor.config import AIProvider, Settings
from repodoctor.contracts.api import AnalysisRequest, DiagnosisRequest, RepositoryMode
from repodoctor.main import create_app


async def main() -> int:
    settings = Settings()
    if settings.ai_provider != AIProvider.gigachat or not settings.gigachat_configured:
        print("Set AI_PROVIDER=gigachat, GIGACHAT_AUTH_KEY and GIGACHAT_MODEL in local .env.")
        return 2
    settings = settings.model_copy(
        update={"repository_mode": RepositoryMode.fixture, "use_dev_stubs": False}
    )
    app = create_app(settings)
    start = perf_counter()
    analysis = await app.state.analysis_service.analyze(
        AnalysisRequest(
            repo_url="https://github.com/repodoctor-fixtures/node-api-demo",
            target={"os": "linux", "shell": "bash"},
            use_ai=True,
        )
    )
    print(
        json.dumps(
            {
                "operation": "plan",
                **analysis.generation.model_dump(),
                "elapsed_ms": round((perf_counter() - start) * 1000),
            }
        )
    )
    start = perf_counter()
    diagnosis = await app.state.diagnosis_service.diagnose(
        analysis.analysis_id,
        DiagnosisRequest(
            log="Error: listen EADDRINUSE: address already in use 127.0.0.1:3000",
            command="npm start",
            use_ai=True,
        ),
    )
    print(
        json.dumps(
            {
                "operation": "diagnosis",
                **diagnosis.generation.model_dump(),
                "elapsed_ms": round((perf_counter() - start) * 1000),
                "causes": len(diagnosis.causes),
            }
        )
    )
    return 0 if analysis.generation.mode == diagnosis.generation.mode == "ai" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
