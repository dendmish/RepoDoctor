"""GigaChat REST: OAuth Authorization Key, cached token and one JSON-schema completion.

Official API: https://developers.sber.ru/docs/ru/gigachat/guides/structured-output
No SDK dependency, tool loop, vendor substitution, redirects or TLS bypass.
"""

from __future__ import annotations

import asyncio
import json
import math
import ssl
import uuid
from pathlib import Path
from time import time as utc_time

from httpx import AsyncClient, RequestError, TimeoutException
from pydantic import SecretStr, ValidationError

from repodoctor import __version__
from repodoctor.config import Settings
from repodoctor.contracts.api import TargetEnvironment
from repodoctor.contracts.domain import AnalysisContext, SanitizedLog, StaticAnalysis
from repodoctor.intelligence.context import encode
from repodoctor.intelligence.provider import (
    PROMPTS,
    ModelDiagnosisOutput,
    ModelPlanOutput,
    OutputT,
    ProviderError,
    diagnosis_payload,
    plan_payload,
)
from repodoctor.observability import log_event, request_id_var

OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
CHAT_URL = "https://api.giga.chat/v1/chat/completions"
MODELS_URL = "https://api.giga.chat/v1/models"
MAX_RESPONSE_BYTES = 256 * 1024
# GigaChat API docs recommend a client User-Agent to avoid authorization errors.
USER_AGENT = f"RepoDoctor/{__version__}"
BUNDLED_CA = Path(__file__).resolve().parents[1] / "certificates" / "russian_trusted_root_ca.pem"


class GigaChatProvider:
    plan_prompt_version = "analysis-gigachat-v2"
    diagnosis_prompt_version = "diagnosis-gigachat-v2"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self.model = settings.gigachat_model
        self._token: SecretStr | None = None
        self._expires_at = 0.0
        self._token_lock = asyncio.Lock()

    def _client(self) -> AsyncClient:
        context = ssl.create_default_context()
        context.load_verify_locations(cafile=str(BUNDLED_CA))
        if self._settings.gigachat_ca_bundle is not None:
            context.load_verify_locations(cafile=str(self._settings.gigachat_ca_bundle))
        return AsyncClient(
            verify=context,
            timeout=self._settings.ai_timeout_seconds,
            follow_redirects=False,
            trust_env=False,
        )

    async def _json(self, client: AsyncClient, url: str, *, method: str = "POST", **kwargs) -> dict:
        async with client.stream(method, url, **kwargs) as response:
            status = response.status_code
            if status != 200:
                # Status and endpoint only: upstream bodies may echo prompts or credentials.
                log_event("gigachat_http_error", endpoint=url.rsplit("/", 1)[-1], status=status)
            if status in {401, 403}:
                raise ProviderError("authentication_failed")
            if status == 429:
                raise ProviderError("rate_limited")
            if status in {400, 404, 413, 422}:
                # Bad model name, unsupported schema or oversized request: not an outage.
                raise ProviderError("request_rejected")
            if status != 200:
                raise ProviderError("provider_unavailable")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise ProviderError("invalid_output")
            document = json.loads(body)
            if not isinstance(document, dict):
                raise ProviderError("invalid_output")
            return document

    async def _access_token(self, client: AsyncClient) -> str:
        async with self._token_lock:
            if self._token is not None and self._expires_at > utc_time():
                return self._token.get_secret_value()
            document = await self._json(
                client,
                OAUTH_URL,
                headers={
                    "Authorization": "Basic " + self._settings.gigachat_auth_key.get_secret_value(),
                    "RqUID": str(uuid.uuid4()),
                    "Accept": "application/json",
                    "User-Agent": USER_AGENT,
                },
                data={"scope": self._settings.gigachat_scope.value},
            )
            token, expires = document.get("access_token"), document.get("expires_at")
            if not isinstance(token, str) or not token or not isinstance(expires, (int, float)):
                raise ProviderError("invalid_output")
            # Accept epoch milliseconds (API) and seconds (some documentation examples).
            expires = expires / 1000 if expires > 100_000_000_000 else expires
            if not math.isfinite(expires) or expires <= utc_time() + 30:
                raise ProviderError("authentication_failed")
            self._token = SecretStr(token)
            self._expires_at = expires - 30
            return token

    async def _request(self, prompt: str, payload: dict, schema: type[OutputT]) -> OutputT:
        if not self._settings.gigachat_configured:
            raise ProviderError("ai_not_configured")
        try:
            async with asyncio.timeout(self._settings.ai_timeout_seconds):
                async with self._client() as client:
                    token = await self._access_token(client)
                    document = await self._json(
                        client,
                        CHAT_URL,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Accept": "application/json",
                            "User-Agent": USER_AGENT,
                            # Correlates our logs with GigaChat support; no user data inside.
                            "X-Request-ID": request_id_var.get() or str(uuid.uuid4()),
                        },
                        json={
                            "model": self.model,
                            "stream": False,
                            "max_tokens": self._settings.ai_max_output_tokens,
                            "messages": [
                                {
                                    "role": "system",
                                    "content": (PROMPTS / prompt).read_text(encoding="utf-8"),
                                },
                                {"role": "user", "content": encode(payload)},
                            ],
                            "response_format": {
                                "type": "json_schema",
                                "schema": schema.model_json_schema(),
                                "strict": True,
                            },
                        },
                    )
            choices = document.get("choices")
            if (
                not isinstance(choices, list)
                or len(choices) != 1
                or not isinstance(choices[0], dict)
            ):
                raise ProviderError("invalid_output")
            choice = choices[0]
            finish = choice.get("finish_reason")
            if finish in {"blacklist", "content_filter"}:
                raise ProviderError("refusal")
            if finish == "length":
                raise ProviderError("incomplete")
            if finish != "stop":
                raise ProviderError("invalid_output")
            message = choice.get("message")
            if (
                not isinstance(message, dict)
                or message.get("function_call")
                or message.get("tool_calls")
            ):
                raise ProviderError("invalid_output")
            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ProviderError("invalid_output")
            return schema.model_validate_json(content)
        except ProviderError as exc:
            if exc.reason == "authentication_failed":
                self._token = None
                self._expires_at = 0.0
            raise
        except (TimeoutException, TimeoutError) as exc:
            raise ProviderError("timeout") from exc
        except RequestError as exc:
            reason = (
                "tls_error" if "CERTIFICATE_VERIFY_FAILED" in str(exc) else "provider_unavailable"
            )
            raise ProviderError(reason) from exc
        except (ssl.SSLError, OSError) as exc:
            raise ProviderError("tls_error") from exc
        except (ValidationError, ValueError) as exc:
            raise ProviderError("invalid_output") from exc

    async def generate_plan(
        self, scan: StaticAnalysis, target: TargetEnvironment
    ) -> ModelPlanOutput:
        if not self._settings.gigachat_configured:
            raise ProviderError("ai_not_configured")
        return await self._request(
            "analysis_gigachat.txt", plan_payload(scan, target), ModelPlanOutput
        )

    async def generate_diagnosis(
        self, context: AnalysisContext, log: SanitizedLog, command: str | None
    ) -> ModelDiagnosisOutput:
        if not self._settings.gigachat_configured:
            raise ProviderError("ai_not_configured")
        return await self._request(
            "diagnosis_gigachat.txt", diagnosis_payload(context, log, command), ModelDiagnosisOutput
        )
