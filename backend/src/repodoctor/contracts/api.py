"""Public HTTP DTOs, schema_version 1.0.

Normative source: ARCHITECTURE.md section 5. Field names, enums and nullability here are
the contract shared by backend, examples, OpenAPI and the generated frontend types.
Only agent 1 changes this module (ROADMAP.md, section 2, rule 6).
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1.0"

# Field limits (ARCHITECTURE.md 5, 9).
MAX_REPO_URL_LENGTH = 2048
MAX_REF_LENGTH = 200
MAX_LOG_LENGTH = 30_000
MAX_COMMAND_LENGTH = 2000
MAX_EXCERPT_LENGTH = 500
MAX_PLAN_STEPS = 12
MAX_COMMANDS_PER_STEP = 4
MAX_DIAGNOSIS_CAUSES = 5


class ContractModel(BaseModel):
    """Base for every contract DTO: unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")


# --- Enumerations -------------------------------------------------------------------------


class TargetOS(StrEnum):
    windows = "windows"
    linux = "linux"
    macos = "macos"


class Shell(StrEnum):
    powershell = "powershell"
    bash = "bash"
    zsh = "zsh"


class Stack(StrEnum):
    python = "python"
    node = "node"
    mixed = "mixed"
    unknown = "unknown"


class Severity(StrEnum):
    info = "info"
    warning = "warning"
    blocker = "blocker"


class Confidence(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class Origin(StrEnum):
    static = "static"
    ai = "ai"


class EvidenceSource(StrEnum):
    file = "file"
    tree = "tree"
    log = "log"


class CoverageStatus(StrEnum):
    complete = "complete"
    partial = "partial"


class PlanStatus(StrEnum):
    actionable = "actionable"
    needs_input = "needs_input"


class GenerationMode(StrEnum):
    ai = "ai"
    fallback = "fallback"


class SourceMode(StrEnum):
    github = "github"
    fixture = "fixture"


class RepositoryMode(StrEnum):
    live = "live"
    fixture = "fixture"


class Ecosystem(StrEnum):
    python = "python"
    node = "node"


class DependencyKind(StrEnum):
    runtime = "runtime"
    dev = "dev"
    optional = "optional"


class PackageManager(StrEnum):
    pip = "pip"
    uv = "uv"
    poetry = "poetry"
    npm = "npm"
    yarn = "yarn"
    pnpm = "pnpm"
    conda = "conda"


class EntryPointKind(StrEnum):
    readme = "readme"
    script = "script"
    module = "module"
    file = "file"


class ErrorCode(StrEnum):
    INVALID_INPUT = "INVALID_INPUT"
    REPOSITORY_NOT_FOUND = "REPOSITORY_NOT_FOUND"
    REF_NOT_FOUND = "REF_NOT_FOUND"
    ANALYSIS_NOT_FOUND = "ANALYSIS_NOT_FOUND"
    EMPTY_REPOSITORY = "EMPTY_REPOSITORY"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    UNSUPPORTED_REPOSITORY = "UNSUPPORTED_REPOSITORY"
    SERVER_BUSY = "SERVER_BUSY"
    GITHUB_RATE_LIMITED = "GITHUB_RATE_LIMITED"
    GITHUB_UNAVAILABLE = "GITHUB_UNAVAILABLE"
    ANALYSIS_TIMEOUT = "ANALYSIS_TIMEOUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    # Baseline clarification (docs/decisions.md D-004): unknown routes/methods still use the
    # common envelope instead of a framework default body.
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"


ALLOWED_TARGETS: frozenset[tuple[TargetOS, Shell]] = frozenset(
    {
        (TargetOS.windows, Shell.powershell),
        (TargetOS.linux, Shell.bash),
        (TargetOS.macos, Shell.zsh),
    }
)

# --- Reusable validated scalar types ------------------------------------------------------

_UTC_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")
_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_CWD_RE = re.compile(r"^(\.|<repo>(/[^/\\]+)*)$")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")


def _check_uuid4(value: str) -> str:
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise ValueError("must be a UUID4 string") from exc
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError("must be a canonical lowercase UUID4 string")
    return value


def _check_utc_timestamp(value: str) -> str:
    if not _UTC_TIMESTAMP_RE.match(value):
        raise ValueError("must be UTC ISO 8601 with 'Z' suffix")
    datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value


def _check_repo_path(value: str) -> str:
    """Repo-relative POSIX path: no leading '/', no '..', no backslash; root is '.'."""
    if value == ".":
        return value
    if not value or value.startswith("/") or "\\" in value or _CONTROL_CHARS_RE.search(value):
        raise ValueError("must be a repo-relative POSIX path ('.' for the root)")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("must not contain empty, '.' or '..' segments")
    return value


def _check_commit_sha(value: str) -> str:
    if not _COMMIT_SHA_RE.match(value):
        raise ValueError("must be a 40-character lowercase hex commit SHA")
    return value


def _check_github_url(value: str) -> str:
    if not value.startswith("https://github.com/"):
        raise ValueError("must be an https://github.com/ URL built by the server")
    return value


def _check_cwd(value: str) -> str:
    if not _CWD_RE.match(value) or ".." in value.split("/"):
        raise ValueError("must be '.', '<repo>' or '<repo>/<subdir>'")
    return value


Uuid4Str = Annotated[str, AfterValidator(_check_uuid4)]
UtcTimestamp = Annotated[str, AfterValidator(_check_utc_timestamp)]
RepoPath = Annotated[str, AfterValidator(_check_repo_path)]
CommitSha = Annotated[str, AfterValidator(_check_commit_sha)]
GitHubUrl = Annotated[str, AfterValidator(_check_github_url)]
CommandCwd = Annotated[str, AfterValidator(_check_cwd)]
NonEmptyStr = Annotated[str, Field(min_length=1)]


def format_utc(moment: datetime) -> str:
    """Render an aware datetime in the contract timestamp format (UTC, 'Z')."""
    if moment.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_utc(value: str) -> datetime:
    """Parse a contract timestamp back into an aware datetime."""
    return datetime.fromisoformat(_check_utc_timestamp(value).replace("Z", "+00:00"))


# --- Common DTOs --------------------------------------------------------------------------


class TargetEnvironment(ContractModel):
    os: TargetOS
    shell: Shell

    @model_validator(mode="after")
    def _allowed_pair(self) -> TargetEnvironment:
        if (self.os, self.shell) not in ALLOWED_TARGETS:
            raise ValueError("supported pairs: windows/powershell, linux/bash, macos/zsh")
        return self


class Evidence(ContractModel):
    id: NonEmptyStr
    source: EvidenceSource
    path: RepoPath | None
    line_start: Annotated[int, Field(ge=1)] | None
    line_end: Annotated[int, Field(ge=1)] | None
    excerpt: Annotated[str, Field(max_length=MAX_EXCERPT_LENGTH)]
    url: GitHubUrl | None

    @model_validator(mode="after")
    def _shape_by_source(self) -> Evidence:
        has_lines = self.line_start is not None and self.line_end is not None
        if (self.line_start is None) != (self.line_end is None):
            raise ValueError("line_start and line_end must be both set or both null")
        if has_lines and self.line_end < self.line_start:  # type: ignore[operator]
            raise ValueError("line_end must be >= line_start")
        if self.source is EvidenceSource.file and (self.path is None or not has_lines):
            raise ValueError("file evidence requires path and lines")
        if self.source is EvidenceSource.tree and (self.path is None or has_lines):
            raise ValueError("tree evidence requires path and null lines")
        if self.source is EvidenceSource.log:
            if self.path is not None or self.url is not None or not has_lines:
                raise ValueError("log evidence requires null path/url and processed-log lines")
            if not self.id.startswith("log_"):
                raise ValueError("log evidence id must start with 'log_'")
        elif self.id.startswith("log_"):
            raise ValueError("'log_' id prefix is reserved for log evidence")
        return self


class Finding(ContractModel):
    id: NonEmptyStr
    rule_id: NonEmptyStr
    title: NonEmptyStr
    description: str
    severity: Severity
    confidence: Confidence
    origin: Origin
    evidence_ids: list[str]
    suggested_action: str


class Command(ContractModel):
    shell: Shell
    text: Annotated[str, Field(min_length=1, max_length=MAX_COMMAND_LENGTH)]
    cwd: CommandCwd
    explanation: str
    requires_review: bool


class RunStep(ContractModel):
    id: NonEmptyStr
    title: NonEmptyStr
    description: str
    commands: Annotated[list[Command], Field(max_length=MAX_COMMANDS_PER_STEP)]
    evidence_ids: list[str]
    verification: str
    assumptions: list[str]


class RunPlan(ContractModel):
    status: PlanStatus
    summary: str
    prerequisites: list[str]
    steps: Annotated[list[RunStep], Field(max_length=MAX_PLAN_STEPS)]
    questions: list[str]

    @model_validator(mode="after")
    def _needs_input_has_questions(self) -> RunPlan:
        if self.status is PlanStatus.needs_input and not self.questions:
            raise ValueError("needs_input plan must contain at least one question")
        return self


class Coverage(ContractModel):
    status: CoverageStatus
    tree_entries_seen: Annotated[int, Field(ge=0)]
    files_selected: Annotated[int, Field(ge=0)]
    files_read: Annotated[int, Field(ge=0)]
    bytes_read: Annotated[int, Field(ge=0)]
    limitations: list[str]


class GenerationInfo(ContractModel):
    mode: GenerationMode
    reason: str | None
    model: str | None
    prompt_version: NonEmptyStr


class RepositoryInfo(ContractModel):
    owner: NonEmptyStr
    name: NonEmptyStr
    url: GitHubUrl
    default_branch: NonEmptyStr
    resolved_commit: CommitSha
    description: str | None


class Dependency(ContractModel):
    name: NonEmptyStr
    constraint: str | None
    ecosystem: Ecosystem
    kind: DependencyKind
    manifest_path: RepoPath
    evidence_ids: list[str]


class RuntimeHint(ContractModel):
    runtime: Ecosystem
    constraint: NonEmptyStr
    evidence_ids: list[str]


class PackageManagerHint(ContractModel):
    name: PackageManager
    root: RepoPath
    evidence_ids: list[str]


class EntryPoint(ContractModel):
    root: RepoPath
    command_hint: NonEmptyStr
    kind: EntryPointKind
    evidence_ids: list[str]


class ProjectRoot(ContractModel):
    path: RepoPath
    stack: Stack
    manifest_paths: list[RepoPath]


class RepositoryFacts(ContractModel):
    stack: Stack
    project_roots: list[ProjectRoot]
    dependencies: list[Dependency]
    runtime_hints: list[RuntimeHint]
    package_managers: list[PackageManagerHint]
    entrypoints: list[EntryPoint]
    env_var_names: list[str]
    data_hints: list[str]
    gpu_hints: list[str]


# --- Reference integrity helpers ----------------------------------------------------------


def collect_evidence_refs(*holders: object) -> set[str]:
    """Collect every evidence ID referenced by facts, findings, steps or causes."""
    refs: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, BaseModel):
            ids = getattr(node, "evidence_ids", None)
            if isinstance(ids, list):
                refs.update(ids)
            for name in type(node).model_fields:
                walk(getattr(node, name))
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for holder in holders:
        walk(holder)
    return refs


def check_evidence_registry(evidence: list[Evidence], refs: set[str]) -> None:
    ids = [item.id for item in evidence]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        raise ValueError(f"duplicate evidence ids: {duplicates}")
    missing = sorted(refs - set(ids))
    if missing:
        raise ValueError(f"evidence_ids not present in evidence registry: {missing}")


def _commands(steps: list[RunStep]) -> list[Command]:
    return [command for step in steps for command in step.commands]


# --- HTTP DTOs ----------------------------------------------------------------------------


class HealthResponse(ContractModel):
    status: Literal["ok"]
    version: str
    repository_mode: RepositoryMode
    ai_configured: bool


class AnalysisRequest(ContractModel):
    repo_url: Annotated[str, Field(min_length=1, max_length=MAX_REPO_URL_LENGTH)]
    ref: Annotated[str, Field(max_length=MAX_REF_LENGTH)] | None = None
    target: TargetEnvironment
    use_ai: bool = True

    @field_validator("ref")
    @classmethod
    def _normalize_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if _CONTROL_CHARS_RE.search(value):
            raise ValueError("ref must not contain control characters")
        return value


class AnalysisResponse(ContractModel):
    schema_version: Literal["1.0"]
    analysis_id: Uuid4Str
    created_at: UtcTimestamp
    expires_at: UtcTimestamp
    source_mode: SourceMode
    repository: RepositoryInfo
    target: TargetEnvironment
    facts: RepositoryFacts
    coverage: Coverage
    findings: list[Finding]
    evidence: list[Evidence]
    run_plan: RunPlan
    generation: GenerationInfo
    warnings: list[str]

    @model_validator(mode="after")
    def _integrity(self) -> AnalysisResponse:
        check_evidence_registry(
            self.evidence, collect_evidence_refs(self.facts, self.findings, self.run_plan)
        )
        if any(item.source is EvidenceSource.log for item in self.evidence):
            raise ValueError("analysis evidence must not contain log evidence")
        wrong = [c.text for c in _commands(self.run_plan.steps) if c.shell != self.target.shell]
        if wrong:
            raise ValueError("every command shell must match target.shell")
        if parse_utc(self.expires_at) <= parse_utc(self.created_at):
            raise ValueError("expires_at must be later than created_at")
        return self


class DiagnosisRequest(ContractModel):
    log: Annotated[str, Field(min_length=1, max_length=MAX_LOG_LENGTH)]
    command: Annotated[str, Field(max_length=MAX_COMMAND_LENGTH)] | None = None
    use_ai: bool = True

    @field_validator("log")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("log must not be whitespace-only")
        return value

    @field_validator("command")
    @classmethod
    def _blank_command_is_null(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return value


class DiagnosisCause(ContractModel):
    id: NonEmptyStr
    title: NonEmptyStr
    explanation: str
    confidence: Confidence
    origin: Origin
    evidence_ids: list[str]
    fixes: Annotated[list[RunStep], Field(max_length=MAX_PLAN_STEPS)]
    verification: str


class DiagnosisResponse(ContractModel):
    schema_version: Literal["1.0"]
    diagnosis_id: Uuid4Str
    analysis_id: Uuid4Str
    created_at: UtcTimestamp
    generation: GenerationInfo
    summary: str
    causes: Annotated[list[DiagnosisCause], Field(max_length=MAX_DIAGNOSIS_CAUSES)]
    questions: list[str]
    evidence: list[Evidence]
    warnings: list[str]

    @model_validator(mode="after")
    def _integrity(self) -> DiagnosisResponse:
        check_evidence_registry(self.evidence, collect_evidence_refs(self.causes))
        if not self.causes and not self.questions:
            raise ValueError("diagnosis without causes must ask at least one question")
        return self


class ErrorBody(ContractModel):
    code: ErrorCode
    message: str
    retryable: bool
    details: list[str]
    request_id: str


class ErrorResponse(ContractModel):
    error: ErrorBody
