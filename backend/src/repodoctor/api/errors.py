"""Single ErrorResponse envelope for every failure (ARCHITECTURE.md section 5, "Ошибки").

Handlers never echo request bodies, input values, headers or tracebacks.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from repodoctor.contracts.api import ErrorBody, ErrorCode, ErrorResponse
from repodoctor.contracts.domain import GitHubRateLimitedError, RepoDoctorError

logger = logging.getLogger("repodoctor.api")

STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.INVALID_INPUT: 422,
    ErrorCode.REPOSITORY_NOT_FOUND: 404,
    ErrorCode.REF_NOT_FOUND: 404,
    ErrorCode.ANALYSIS_NOT_FOUND: 404,
    ErrorCode.EMPTY_REPOSITORY: 409,
    ErrorCode.PAYLOAD_TOO_LARGE: 413,
    ErrorCode.UNSUPPORTED_REPOSITORY: 422,
    ErrorCode.SERVER_BUSY: 429,
    ErrorCode.GITHUB_RATE_LIMITED: 429,
    ErrorCode.GITHUB_UNAVAILABLE: 502,
    ErrorCode.ANALYSIS_TIMEOUT: 504,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.METHOD_NOT_ALLOWED: 405,
}

REQUEST_ID_HEADER = "X-Request-ID"


def get_request_id(request: Request) -> str:
    """Server-generated request ID, created lazily once per request."""
    request_id = getattr(request.state, "request_id", None)
    if request_id is None:
        request_id = uuid.uuid4().hex
        request.state.request_id = request_id
    return request_id


def to_error_response(
    code: ErrorCode,
    message: str,
    *,
    request_id: str,
    retryable: bool = False,
    details: list[str] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            retryable=retryable,
            details=list(details or []),
            request_id=request_id,
        )
    )
    return JSONResponse(
        status_code=STATUS_BY_CODE[code],
        content=body.model_dump(mode="json"),
        headers={REQUEST_ID_HEADER: request_id, **(headers or {})},
    )


def _validation_details(exc: RequestValidationError) -> list[str]:
    details: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ()) if part != "body")
        # Only location + message: pydantic's "input" may contain the user's log or secrets.
        details.append(f"{location or 'body'}: {error.get('msg', 'invalid value')}")
    return details[:20]


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RepoDoctorError)
    async def _domain_error(request: Request, exc: RepoDoctorError) -> JSONResponse:
        headers = None
        if isinstance(exc, GitHubRateLimitedError) and exc.retry_after_seconds is not None:
            headers = {"Retry-After": str(exc.retry_after_seconds)}
        return to_error_response(
            exc.code,
            exc.message,
            request_id=get_request_id(request),
            retryable=exc.retryable,
            details=exc.details,
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return to_error_response(
            ErrorCode.INVALID_INPUT,
            "Запрос не прошёл проверку.",
            request_id=get_request_id(request),
            details=_validation_details(exc),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        if exc.status_code == 405:
            code, message = ErrorCode.METHOD_NOT_ALLOWED, "Метод не поддерживается."
        elif exc.status_code == 404:
            code, message = ErrorCode.NOT_FOUND, "Ресурс не найден."
        elif exc.status_code == 413:
            code, message = ErrorCode.PAYLOAD_TOO_LARGE, "Запрос слишком большой."
        else:
            code, message = ErrorCode.INTERNAL_ERROR, "Внутренняя ошибка сервера."
        return to_error_response(code, message, request_id=get_request_id(request))

    @app.exception_handler(Exception)
    async def _unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        request_id = get_request_id(request)
        logger.error("unhandled error request_id=%s type=%s", request_id, type(exc).__name__)
        return to_error_response(
            ErrorCode.INTERNAL_ERROR,
            "Внутренняя ошибка сервера. Сообщите request_id.",
            request_id=request_id,
        )
