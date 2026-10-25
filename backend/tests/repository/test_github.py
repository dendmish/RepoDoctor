from __future__ import annotations

import asyncio
import base64
import hashlib
from dataclasses import replace

import httpx
import pytest

from repodoctor.contracts.api import AnalysisRequest
from repodoctor.contracts.domain import (
    EmptyRepositoryError,
    GitHubRateLimitedError,
    GitHubUnavailableError,
    RefNotFoundError,
    RepositoryNotFoundError,
    UnsupportedRepositoryError,
)
from repodoctor.repository.github import GitHubRepositorySource
from repodoctor.repository.selection import RepositoryLimits
from repodoctor.scanners.analyzer import RepositoryAnalyzer

pytestmark = pytest.mark.usefixtures("mock_transport_http")
COMMIT, TREE = "c" * 40, "d" * 40


class GitHubFixture:
    def __init__(self, files: dict[str, bytes] | None = None):
        files = (
            files
            if files is not None
            else {
                "README.md": b"# Demo\n```bash\npython -m app\n```\n",
                "requirements.txt": b"requests>=2\n",
                "app.py": b"print('do not execute')\n",
                ".env.example": b"API_TOKEN=fake-value\nPORT=1234\n",
            }
        )
        self.metadata = {
            "private": False,
            "owner": {"login": "example"},
            "name": "demo",
            "default_branch": "main",
            "description": "Synthetic HTTP transport fixture",
        }
        self.commit = {"sha": COMMIT, "commit": {"tree": {"sha": TREE}}}
        self.entries = []
        self.blobs = {}
        self.calls: list[httpx.Request] = []
        self.override = None
        self.truncated = False
        for path, raw in files.items():
            sha = hashlib.sha1(
                f"blob {len(raw)}\0".encode() + raw, usedforsecurity=False
            ).hexdigest()
            self.entries.append(dict(path=path, type="blob", mode="100644", sha=sha, size=len(raw)))
            self.blobs[sha] = dict(
                sha=sha, size=len(raw), encoding="base64", content=base64.b64encode(raw).decode()
            )

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.override:
            result = await self.override(request)
            if result is not None:
                return result
        path = request.url.path
        if path == "/repos/example/demo":
            data = self.metadata
        elif "/commits/" in path:
            data = self.commit
        elif "/git/trees/" in path:
            assert path.endswith(TREE)
            data = {"tree": self.entries, "truncated": self.truncated}
        else:
            data = self.blobs[path.rsplit("/", 1)[-1]]
        return httpx.Response(200, json=data)

    async def fetch(self, analysis_request: AnalysisRequest, **kwargs):
        request = analysis_request.model_copy(
            update={"repo_url": "https://github.com/example/demo"}
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.handle)) as client:
            return await GitHubRepositorySource(client, **kwargs).fetch(request)


async def test_commit_pinned_selection_and_redaction(analysis_request: AnalysisRequest) -> None:
    upstream = GitHubFixture()
    snapshot = await upstream.fetch(analysis_request, token="synthetic-token")
    assert snapshot.repository.resolved_commit == COMMIT
    assert snapshot.source_mode == "github"
    assert {f.path for f in snapshot.files} == {
        "README.md",
        "requirements.txt",
        "app.py",
        ".env.example",
    }
    env = next(f for f in snapshot.files if f.path == ".env.example")
    assert env.content == "API_TOKEN=[REDACTED]\nPORT=[REDACTED]\n"
    assert env.size_bytes == len(b"API_TOKEN=fake-value\nPORT=1234\n")
    assert all(req.headers["Authorization"] == "Bearer synthetic-token" for req in upstream.calls)
    assert all(req.url.host == "api.github.com" for req in upstream.calls)
    assert len(upstream.calls) == 7
    scan = RepositoryAnalyzer().analyze(snapshot)
    assert "requests" in {dep.name for dep in scan.facts.dependencies}
    assert set(scan.facts.env_var_names) == {"API_TOKEN", "PORT"}
    assert all(COMMIT in ev.url for ev in scan.evidence if ev.url)
    # The analyzer does not perform another HTTP request after the snapshot is loaded.
    assert len(upstream.calls) == 7


async def test_branch_slash_is_encoded(analysis_request: AnalysisRequest) -> None:
    upstream = GitHubFixture()
    await upstream.fetch(analysis_request.model_copy(update={"ref": "feature/offline"}))
    commit = next(req for req in upstream.calls if "/commits/" in req.url.path)
    assert b"feature%2Foffline" in commit.url.raw_path


@pytest.mark.parametrize(
    ("path_kind", "status", "error"),
    [
        ("metadata", 404, RepositoryNotFoundError),
        ("commit", 404, RefNotFoundError),
        ("commit", 409, EmptyRepositoryError),
        ("metadata", 301, GitHubUnavailableError),
        ("metadata", 403, GitHubUnavailableError),
        ("metadata", 429, GitHubRateLimitedError),
    ],
)
async def test_status_mapping(path_kind, status, error, analysis_request):
    upstream = GitHubFixture()

    async def override(req):
        match = (
            "/commits/" in req.url.path
            if path_kind == "commit"
            else req.url.path == "/repos/example/demo"
        )
        if match:
            return httpx.Response(
                status, json={"message": "Forbidden"}, headers={"Location": "https://evil.invalid"}
            )

    upstream.override = override
    with pytest.raises(error):
        await upstream.fetch(analysis_request)
    assert all(req.url.host == "api.github.com" for req in upstream.calls)


async def test_private_repo_rejected_even_with_token(analysis_request):
    upstream = GitHubFixture()
    upstream.metadata["private"] = True
    with pytest.raises(UnsupportedRepositoryError):
        await upstream.fetch(analysis_request, token="synthetic-token")
    assert len(upstream.calls) == 1


@pytest.mark.parametrize(
    "headers",
    [{"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "9999999999"}, {"Retry-After": "60"}],
)
async def test_rate_limit_headers_no_retries(headers, analysis_request):
    upstream = GitHubFixture()

    async def override(req):
        return httpx.Response(403, json={"message": "secondary rate limit"}, headers=headers)

    upstream.override = override
    with pytest.raises(GitHubRateLimitedError) as caught:
        await upstream.fetch(analysis_request)
    assert caught.value.retry_after_seconds is not None
    assert len(upstream.calls) == 1


@pytest.mark.parametrize("variant", ["truncated", "entry_limit", "tree_bytes", "missing_tree"])
async def test_partial_tree_variants(variant, analysis_request):
    upstream = GitHubFixture()
    limits = RepositoryLimits()
    if variant == "truncated":
        upstream.truncated = True
    elif variant == "entry_limit":
        limits = replace(limits, tree_entries=1)
    elif variant == "tree_bytes":
        limits = replace(limits, tree_bytes=1)
    else:

        async def override(req):
            if "/git/trees/" in req.url.path:
                return httpx.Response(404)

        upstream.override = override
    snapshot = await upstream.fetch(analysis_request, limits=limits)
    assert snapshot.coverage.status == "partial"
    assert snapshot.coverage.limitations
    scan = RepositoryAnalyzer().analyze(snapshot)
    assert "PARTIAL_COVERAGE" in {finding.rule_id for finding in scan.findings}
    assert "README_MISSING" not in {finding.rule_id for finding in scan.findings}
    if variant in {"tree_bytes", "missing_tree"}:
        assert not snapshot.tree and not snapshot.files


@pytest.mark.parametrize(
    "variant", ["base64", "utf8", "nul", "size", "sha", "encoding", "large", "404", "lfs"]
)
async def test_bad_blob_is_skipped_without_losing_manifest(variant, analysis_request):
    raw = {"README.md": b"# Demo\n", "requirements.txt": b"requests\n"}
    if variant == "utf8":
        raw["README.md"] = b"\xff"
    elif variant == "nul":
        raw["README.md"] = b"a\x00b"
    elif variant == "lfs":
        raw["README.md"] = b"version https://git-lfs.github.com/spec/v1\noid sha256:demo\n"
    upstream = GitHubFixture(raw)
    sha = next(e["sha"] for e in upstream.entries if e["path"] == "README.md")
    blob = upstream.blobs[sha]
    if variant == "base64":
        blob["content"] = "%%%"
    elif variant == "encoding":
        blob["encoding"] = "utf8"
    elif variant == "size":
        blob["size"] += 1
    elif variant == "sha":
        blob["sha"] = "e" * 40
    elif variant == "large":
        blob["content"] = base64.b64encode(b"x" * (64 * 1024 + 1)).decode()
    elif variant == "404":

        async def override(req):
            if req.url.path.endswith(sha):
                return httpx.Response(404)

        upstream.override = override
    snapshot = await upstream.fetch(analysis_request)
    assert [f.path for f in snapshot.files] == ["requirements.txt"]
    assert snapshot.coverage.status == "partial"


async def test_unsafe_tree_files_never_requested(analysis_request):
    upstream = GitHubFixture(
        {
            "requirements.txt": b"requests\n",
            ".env": b"password=unsafe",
            "key.pem": b"unsafe",
            "node_modules/package.json": b"{}",
        }
    )
    upstream.entries.extend(
        [
            dict(path="README.md", type="blob", mode="120000", sha="a" * 40, size=5),
            dict(path="submodule", type="commit", mode="160000", sha="b" * 40, size=None),
            dict(path="../package.json", type="blob", mode="100644", sha="e" * 40, size=2),
        ]
    )
    snapshot = await upstream.fetch(analysis_request)
    assert [file.path for file in snapshot.files] == ["requirements.txt"]
    assert len(upstream.calls) == 4


@pytest.mark.parametrize("failure", ["timeout", "503"])
async def test_get_retry_once(failure, analysis_request):
    upstream = GitHubFixture()

    async def override(req):
        if len(upstream.calls) == 1:
            if failure == "timeout":
                raise httpx.ReadTimeout("synthetic timeout")
            return httpx.Response(503)

    upstream.override = override
    snapshot = await upstream.fetch(analysis_request)
    assert snapshot.files
    assert len([r for r in upstream.calls if r.url.path == "/repos/example/demo"]) == 2


async def test_source_deadline(analysis_request):
    upstream = GitHubFixture()

    async def override(req):
        await asyncio.sleep(0.05)

    upstream.override = override
    with pytest.raises(GitHubUnavailableError, match="срок"):
        await upstream.fetch(
            analysis_request, limits=replace(RepositoryLimits(), timeout_seconds=0.01)
        )


async def test_call_budget_never_exceeded(analysis_request):
    upstream = GitHubFixture()
    snapshot = await upstream.fetch(analysis_request, limits=replace(RepositoryLimits(), calls=3))
    assert len(upstream.calls) == 3
    assert not snapshot.files
    assert snapshot.coverage.status == "partial"


async def test_deterministic_total_byte_budget(analysis_request):
    upstream = GitHubFixture(
        {
            "README.md": b"# Demo\n",
            "requirements.txt": b"requests\n",
            "pyproject.toml": b"[project]\nname='demo'\n",
        }
    )
    limits = replace(RepositoryLimits(), total_bytes=10)
    first = await upstream.fetch(analysis_request, limits=limits)
    upstream.entries.reverse()
    second = await upstream.fetch(analysis_request, limits=limits)
    assert first == second
    assert first.coverage.bytes_read <= 10


async def test_chunked_body_limit_before_json(analysis_request):
    upstream = GitHubFixture()

    class Chunks(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(5):
                yield b"x" * 10

    async def override(req):
        return httpx.Response(200, stream=Chunks())

    upstream.override = override
    with pytest.raises(GitHubUnavailableError, match="размера"):
        await upstream.fetch(analysis_request, limits=replace(RepositoryLimits(), json_bytes=20))


async def test_parallel_blob_limit_file_limit_and_retry_call_budget(analysis_request):
    upstream = GitHubFixture(
        {f"requirements-{i:02d}.txt": f"requests # {i}\n".encode() for i in range(25)}
    )
    active, maximum = 0, 0
    hits: dict[str, int] = {}

    async def override(req):
        nonlocal active, maximum
        if "/git/blobs/" not in req.url.path:
            return None
        active += 1
        maximum = max(maximum, active)
        try:
            await asyncio.sleep(0.001)
            hits[req.url.path] = hits.get(req.url.path, 0) + 1
            if hits[req.url.path] == 1:
                return httpx.Response(503)
        finally:
            active -= 1

    upstream.override = override
    snapshot = await upstream.fetch(analysis_request)
    assert 1 < maximum <= 4
    assert len(upstream.calls) <= 28
    assert snapshot.coverage.files_selected <= 20
    assert snapshot.coverage.status == "partial"


@pytest.mark.parametrize("variant", ["metadata", "commit", "tree"])
async def test_invalid_upstream_shapes(variant, analysis_request):
    upstream = GitHubFixture()
    if variant == "metadata":
        upstream.metadata["owner"] = None
    elif variant == "commit":
        upstream.commit["sha"] = "not-a-sha"
    else:
        upstream.entries.append("not-a-tree-entry")
    with pytest.raises(GitHubUnavailableError):
        await upstream.fetch(analysis_request)


async def test_rate_limit_in_blob_is_not_silently_partial(analysis_request):
    upstream = GitHubFixture()

    async def override(req):
        if "/git/blobs/" in req.url.path:
            return httpx.Response(429, json={"message": "rate limit"}, headers={"Retry-After": "2"})

    upstream.override = override
    with pytest.raises(GitHubRateLimitedError):
        await upstream.fetch(analysis_request)
