"""Composition root: the only place where implementations are wired to Protocols."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from repodoctor import __version__
from repodoctor.api.dependencies import AnalysisHandler, DiagnosisHandler
from repodoctor.api.errors import install_error_handlers
from repodoctor.api.routes import router
from repodoctor.config import PROJECT_ROOT, AppEnv, Settings, get_settings
from repodoctor.contracts.ports import (
    AnalysisStore,
    IntelligenceService,
    RepositorySource,
    StaticAnalyzer,
)

logger = logging.getLogger("repodoctor")

STATIC_DIR = Path(__file__).resolve().parent / "static"
EXAMPLES_DIR = PROJECT_ROOT / "contracts" / "examples"
DEV_CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


@dataclass(frozen=True)
class Ports:
    """Injected module implementations; A2/A3 compose them into the services."""

    source: RepositorySource | None = None
    analyzer: StaticAnalyzer | None = None
    intelligence: IntelligenceService | None = None
    store: AnalysisStore | None = None


def create_app(
    settings: Settings | None = None,
    *,
    source: RepositorySource | None = None,
    analyzer: StaticAnalyzer | None = None,
    intelligence: IntelligenceService | None = None,
    store: AnalysisStore | None = None,
    analysis_service: AnalysisHandler | None = None,
    diagnosis_service: DiagnosisHandler | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    if (analysis_service is None or diagnosis_service is None) and settings.use_dev_stubs:
        # Dev-only: never reached in production (Settings forbids it).
        from repodoctor.services.stubs import StubAnalysisService, StubDiagnosisService

        stub_analysis = StubAnalysisService(EXAMPLES_DIR, settings.store_ttl_seconds)
        analysis_service = analysis_service or stub_analysis
        diagnosis_service = diagnosis_service or StubDiagnosisService(stub_analysis)
        logger.warning("USE_DEV_STUBS enabled: API returns synthetic example responses")

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "startup env=%s repository_mode=%s ai_configured=%s",
            settings.app_env,
            settings.repository_mode,
            settings.ai_configured,
        )
        yield

    app = FastAPI(
        title="RepoDoctor API",
        version=__version__,
        lifespan=lifespan,
        separate_input_output_schemas=False,
    )
    app.state.settings = settings
    app.state.ports = Ports(source, analyzer, intelligence, store)
    app.state.analysis_service = analysis_service
    app.state.diagnosis_service = diagnosis_service

    install_error_handlers(app)
    if settings.app_env is AppEnv.development:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=DEV_CORS_ORIGINS,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
        )
    app.include_router(router)

    # Registered after API routes: unknown /api/... still gets the JSON 404 envelope.
    if (STATIC_DIR / "index.html").is_file():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

    return app


@cache
def _app_from_env() -> FastAPI:
    return create_app()


def __getattr__(name: str) -> FastAPI:
    # `uvicorn repodoctor.main:app` builds the app lazily so importing this module never
    # reads env or touches the filesystem.
    if name == "app":
        return _app_from_env()
    raise AttributeError(name)
