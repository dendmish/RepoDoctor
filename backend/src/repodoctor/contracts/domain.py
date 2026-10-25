"""Internal domain DTOs and domain errors shared by platform, repository and intelligence.

Normative source: ARCHITECTURE.md section 6. Provider-output models (ModelPlanOutput,
ModelDiagnosisOutput) are private to `intelligence/` and intentionally not defined here.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field

from repodoctor.contracts.api import (
    AnalysisResponse,
    ContractModel,
    Coverage,
    DiagnosisCause,
    ErrorCode,
    Evidence,
    Finding,
    GenerationInfo,
    RepositoryFacts,
    RepositoryInfo,
    RunPlan,
    SourceMode,
)


class TreeEntryType(StrEnum):
    blob = "blob"
    tree = "tree"
    commit = "commit"  # submodule (mode 160000): never read as a file


# GitHub git modes that must not be treated as regular files.
SYMLINK_MODE = "120000"
SUBMODULE_MODE = "160000"


class TreeEntry(ContractModel):
    """One git tree entry. String fields come from GitHub and are re-checked before use."""

    path: str
    type: TreeEntryType
    mode: str
    sha: str
    size: Annotated[int, Field(ge=0)] | None


class TextFile(ContractModel):
    """Selected text file. `content` is already redacted with the line count preserved;
    `size_bytes` is the decoded size before redaction."""

    path: str
    content: str
    size_bytes: Annotated[int, Field(ge=0)]
    sha: str


class RepositorySnapshot(ContractModel):
    repository: RepositoryInfo
    source_mode: SourceMode
    tree: list[TreeEntry]
    files: list[TextFile]
    coverage: Coverage


class StaticAnalysis(ContractModel):
    repository: RepositoryInfo
    source_mode: SourceMode
    facts: RepositoryFacts
    findings: list[Finding]
    evidence: list[Evidence]
    coverage: Coverage
    selected_files: list[TextFile]


class PlanResult(ContractModel):
    """`evidence` is a subset of the existing registry; AI never invents file evidence."""

    run_plan: RunPlan
    additional_findings: list[Finding]
    evidence: list[Evidence]
    generation: GenerationInfo
    warnings: list[str]


class AnalysisContext(ContractModel):
    """Stored per analysis. The full snapshot tree is not kept."""

    response: AnalysisResponse
    scan: StaticAnalysis


class SanitizedLog(ContractModel):
    text: str
    redactions_count: Annotated[int, Field(ge=0)]
    truncated: bool


class DiagnosisResult(ContractModel):
    summary: str
    causes: list[DiagnosisCause]
    questions: list[str]
    evidence: list[Evidence]
    generation: GenerationInfo
    warnings: list[str]


# --- Domain errors ------------------------------------------------------------------------
# Modules raise these; api/errors.py maps them to HTTP status + ErrorResponse.
# `message` and `details` must be safe to show: no raw logs, headers or secrets.


class RepoDoctorError(Exception):
    code: ErrorCode = ErrorCode.INTERNAL_ERROR
    retryable: bool = False

    def __init__(self, message: str, *, details: list[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = list(details or [])


class InvalidInputError(RepoDoctorError):
    code = ErrorCode.INVALID_INPUT


class RepositoryNotFoundError(RepoDoctorError):
    code = ErrorCode.REPOSITORY_NOT_FOUND


class RefNotFoundError(RepoDoctorError):
    code = ErrorCode.REF_NOT_FOUND


class AnalysisNotFoundError(RepoDoctorError):
    code = ErrorCode.ANALYSIS_NOT_FOUND


class EmptyRepositoryError(RepoDoctorError):
    code = ErrorCode.EMPTY_REPOSITORY


class PayloadTooLargeError(RepoDoctorError):
    code = ErrorCode.PAYLOAD_TOO_LARGE


class UnsupportedRepositoryError(RepoDoctorError):
    code = ErrorCode.UNSUPPORTED_REPOSITORY


class ServerBusyError(RepoDoctorError):
    code = ErrorCode.SERVER_BUSY
    retryable = True


class GitHubRateLimitedError(RepoDoctorError):
    code = ErrorCode.GITHUB_RATE_LIMITED
    retryable = True

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: int | None = None,
        details: list[str] | None = None,
    ) -> None:
        super().__init__(message, details=details)
        self.retry_after_seconds = retry_after_seconds


class GitHubUnavailableError(RepoDoctorError):
    code = ErrorCode.GITHUB_UNAVAILABLE
    retryable = True


class AnalysisTimeoutError(RepoDoctorError):
    code = ErrorCode.ANALYSIS_TIMEOUT
    retryable = True
