"""Composition root: the only place where implementations are wired to Protocols."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from repodoctor import __version__
from repodoctor.api.dependencies import AnalysisHandler, DiagnosisHandler
from repodoctor.api.errors import install_error_handlers
from repodoctor.api.routes import router
from repodoctor.config import PROJECT_ROOT, AIProvider, AppEnv, Settings, get_settings
from repodoctor.contracts.ports import (
    AnalysisStore,
    IntelligenceService,
    RepositorySource,
    StaticAnalyzer,
)
from repodoctor.intelligence.gigachat import GigaChatProvider
from repodoctor.intelligence.provider import OpenAIProvider
from repodoctor.intelligence.service import IntelligenceServiceImpl
from repodoctor.repository.source import create_repository_source
from repodoctor.scanners.analyzer import RepositoryAnalyzer
from repodoctor.security.limits import (
    MAX_BODY_BYTES,
    BodyLimitMiddleware,
    OperationLimiter,
    RequestContextMiddleware,
)
from repodoctor.services.analysis import AnalysisService
from repodoctor.services.diagnosis import DiagnosisService
from repodoctor.services.store import MemoryAnalysisStore

logger = logging.getLogger("repodoctor")

STATIC_DIR = Path(__file__).resolve().parent / "static"
EXAMPLES_DIR = PROJECT_ROOT / "contracts" / "examples"
DEV_CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
GITHUB_API_BASE = "https://api.github.com"


def create_github_client(settings: Settings) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=GITHUB_API_BASE,
        follow_redirects=False,
        timeout=httpx.Timeout(10.0, connect=5.0),
        limits=httpx.Limits(max_connections=4),
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"RepoDoctor/{__version__}",
            "X-GitHub-Api-Version": settings.github_api_version,
        },
    )


@dataclass(frozen=True)
class Ports:
    """Resolved module implementations, including explicit test/application overrides."""

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
    if store is None:  # explicit check: an empty store is falsy (__len__)
        store = MemoryAnalysisStore(settings.store_ttl_seconds, settings.store_max_items)
    limiter = OperationLimiter(settings.max_concurrent_operations)

    # Explicit handlers/ports win; dev stubs remain opt-in and cannot run in production.
    need_real_modules = not settings.use_dev_stubs and (
        analysis_service is None or diagnosis_service is None
    )
    if need_real_modules:
        if analyzer is None:
            analyzer = RepositoryAnalyzer()
        if intelligence is None:
            provider = None
            if settings.ai_configured:
                provider = (
                    GigaChatProvider(settings)
                    if settings.ai_provider == AIProvider.gigachat
                    else OpenAIProvider(settings)
                )
            intelligence = IntelligenceServiceImpl(provider)
        if source is None and analysis_service is None and settings.repository_mode == "fixture":
            source = create_repository_source(settings)

    def compose_analysis(selected_source: RepositorySource) -> AnalysisService:
        return AnalysisService(
            source=selected_source,
            analyzer=analyzer,
            intelligence=intelligence,
            store=store,
            limiter=limiter,
            ttl_seconds=settings.store_ttl_seconds,
            timeout_seconds=settings.analysis_timeout_seconds,
        )

    if analysis_service is None and None not in (source, analyzer, intelligence):
        analysis_service = compose_analysis(source)
    if diagnosis_service is None and intelligence is not None:
        diagnosis_service = DiagnosisService(
            intelligence=intelligence,
            store=store,
            limiter=limiter,
            timeout_seconds=settings.diagnosis_timeout_seconds,
        )

    if (analysis_service is None or diagnosis_service is None) and settings.use_dev_stubs:
        # Dev-only: never reached in production (Settings forbids it).
        from repodoctor.services.stubs import StubAnalysisService, StubDiagnosisService

        stub_analysis = StubAnalysisService(EXAMPLES_DIR, settings.store_ttl_seconds)
        analysis_service = analysis_service or stub_analysis
        diagnosis_service = diagnosis_service or StubDiagnosisService(stub_analysis)
        logger.warning("USE_DEV_STUBS enabled: API returns synthetic example responses")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "startup env=%s repository_mode=%s ai_configured=%s",
            settings.app_env,
            settings.repository_mode,
            settings.ai_configured,
        )
        # Live source is composed only within its shared client's lifetime.
        async with create_github_client(settings) as client:
            app.state.github_client = client
            auto_live = need_real_modules and source is None and analysis_service is None
            try:
                if auto_live:
                    live_source = create_repository_source(settings, client)
                    app.state.ports = Ports(live_source, analyzer, intelligence, store)
                    app.state.analysis_service = compose_analysis(live_source)
                yield
            finally:
                app.state.github_client = None
                if auto_live:
                    app.state.analysis_service = None
                    app.state.ports = Ports(None, analyzer, intelligence, store)

    app = FastAPI(
        title="RepoDoctor API",
        version=__version__,
        lifespan=lifespan,
        separate_input_output_schemas=False,
    )
    app.state.settings = settings
    app.state.ports = Ports(source, analyzer, intelligence, store)
    app.state.limiter = limiter
    app.state.github_client = None
    app.state.analysis_service = analysis_service
    app.state.diagnosis_service = diagnosis_service

    install_error_handlers(app)
    # add_middleware wraps: the last one added is the outermost.
    app.add_middleware(BodyLimitMiddleware, max_bytes=MAX_BODY_BYTES)
    if settings.app_env == AppEnv.development:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=DEV_CORS_ORIGINS,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type"],
        )
    app.add_middleware(RequestContextMiddleware)
    app.include_router(router)

    # Registered after API routes: unknown /api/... still gets the JSON 404 envelope.
    if (STATIC_DIR / "index.html").is_file():
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

    return app


def configure_logging() -> None:
    """Plain stderr handler for the `repodoctor` logger (uvicorn configures only its own)."""
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False


@cache
def _app_from_env() -> FastAPI:
    configure_logging()
    return create_app()


def __getattr__(name: str) -> FastAPI:
    # `uvicorn repodoctor.main:app` builds the app lazily so importing this module never
    # reads env or touches the filesystem.
    if name == "app":
        return _app_from_env()
    raise AttributeError(name)
