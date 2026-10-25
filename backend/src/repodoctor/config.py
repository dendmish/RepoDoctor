"""Application settings (ARCHITECTURE.md section 12).

The root `.env` is resolved by absolute path from this file, independent of the current
working directory. In a container env comes from compose and no `.env` file is present.
Secrets are SecretStr: their values never appear in repr, logs or health output.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from repodoctor.contracts.api import RepositoryMode

# backend/src/repodoctor/config.py -> project root
PROJECT_ROOT = Path(__file__).resolve().parents[3]
ROOT_ENV_FILE = PROJECT_ROOT / ".env"


class AppEnv(StrEnum):
    development = "development"
    test = "test"
    production = "production"


class AIProvider(StrEnum):
    gigachat = "gigachat"
    openai = "openai"


class GigaChatScope(StrEnum):
    personal = "GIGACHAT_API_PERS"
    business = "GIGACHAT_API_B2B"
    corporate = "GIGACHAT_API_CORP"


PositiveSeconds = Annotated[float, Field(gt=0)]
PositiveCount = Annotated[int, Field(gt=0)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: AppEnv = AppEnv.development
    repository_mode: RepositoryMode = RepositoryMode.fixture
    github_token: SecretStr | None = None
    github_api_version: str = "2026-03-10"
    ai_provider: AIProvider = AIProvider.gigachat
    gigachat_auth_key: SecretStr | None = None
    gigachat_model: str | None = None
    gigachat_scope: GigaChatScope = GigaChatScope.personal
    gigachat_ca_bundle: Path | None = None
    openai_api_key: SecretStr | None = None
    openai_model: str | None = None
    ai_timeout_seconds: PositiveSeconds = 40
    ai_max_output_tokens: PositiveCount = 6000
    analysis_timeout_seconds: PositiveSeconds = 85
    diagnosis_timeout_seconds: PositiveSeconds = 45
    store_ttl_seconds: PositiveCount = 1800
    store_max_items: PositiveCount = 30
    max_concurrent_operations: PositiveCount = 2
    fixtures_dir: Path = PROJECT_ROOT / "fixtures"
    # Dev-only synthetic responses from services/stubs.py. Forbidden in production.
    use_dev_stubs: bool = False

    @field_validator("github_token", "openai_api_key", "gigachat_auth_key", mode="before")
    @classmethod
    def _blank_secret_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("openai_model", "gigachat_model", mode="before")
    @classmethod
    def _blank_model_is_none(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("gigachat_ca_bundle", mode="before")
    @classmethod
    def _ca_bundle_path(cls, value: object) -> Path | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        path = Path(value)
        return path if path.is_absolute() else PROJECT_ROOT / path

    @model_validator(mode="after")
    def _no_stubs_in_production(self) -> Settings:
        if self.use_dev_stubs and self.app_env is AppEnv.production:
            raise ValueError("USE_DEV_STUBS is not allowed when APP_ENV=production")
        return self

    @property
    def ai_configured(self) -> bool:
        """Credentials for the selected provider only; never silently switch vendors."""
        if self.ai_provider is AIProvider.gigachat:
            return self.gigachat_configured
        return self.openai_configured

    @property
    def gigachat_configured(self) -> bool:
        return self.gigachat_auth_key is not None and self.gigachat_model is not None

    @property
    def openai_configured(self) -> bool:
        return self.openai_api_key is not None and self.openai_model is not None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
