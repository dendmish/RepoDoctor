from __future__ import annotations

import hashlib
import json
import re
import shutil
import tomllib
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from repodoctor.config import PROJECT_ROOT
from repodoctor.contracts.api import AnalysisRequest, RepoPath
from repodoctor.contracts.domain import (
    RefNotFoundError,
    RepositoryNotFoundError,
    RepositorySnapshot,
)
from repodoctor.contracts.ports import RepositorySource
from repodoctor.repository.source import FixtureLibraryError, FixtureRepositorySource

LIBRARY = PROJECT_ROOT / "fixtures" / "repositories"
INDEX = json.loads((LIBRARY / "index.json").read_text(encoding="utf-8"))
ENTRIES = INDEX["repositories"]


def copied_library(tmp_path: Path) -> Path:
    shutil.copytree(LIBRARY, tmp_path / "repositories")
    return tmp_path


def edit_snapshot(fixtures_dir: Path, change) -> None:
    path = fixtures_dir / "repositories" / "python-cli-demo" / "snapshot.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")


async def test_source_satisfies_port(analysis_request: AnalysisRequest) -> None:
    source = FixtureRepositorySource()
    assert isinstance(source, RepositorySource)
    assert isinstance(await source.fetch(analysis_request), RepositorySnapshot)


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda entry: entry["id"])
async def test_all_fixtures_valid_deterministic_and_consistent(
    entry: dict, analysis_request: AnalysisRequest
) -> None:
    source = FixtureRepositorySource(PROJECT_ROOT / "fixtures")
    request = analysis_request.model_copy(update={"repo_url": entry["url"]})
    snapshot = await source.fetch(request)
    assert snapshot == await source.fetch(request)
    assert snapshot.source_mode == "fixture"
    assert snapshot.repository.url == entry["url"]
    assert snapshot.repository.description.startswith("SYNTHETIC fixture:")
    assert any("SYNTHETIC fixture" in item for item in snapshot.coverage.limitations)
    assert re.fullmatch(r"[0-9a-f]{40}", snapshot.repository.resolved_commit)
    assert snapshot.coverage.tree_entries_seen == len(snapshot.tree)
    assert snapshot.coverage.files_selected == snapshot.coverage.files_read == len(snapshot.files)
    assert snapshot.coverage.bytes_read == sum(file.size_bytes for file in snapshot.files)
    assert len(snapshot.files) <= 20
    assert snapshot.coverage.bytes_read <= 256 * 1024
    tree = {item.path: item for item in snapshot.tree}
    assert len(tree) == len(snapshot.tree)
    validator = TypeAdapter(RepoPath)
    for item in snapshot.tree:
        assert validator.validate_python(item.path) == item.path
        assert re.fullmatch(r"[0-9a-f]{40}", item.sha)
        assert item.mode in {"100644", "040000"}
    for file in snapshot.files:
        assert validator.validate_python(file.path) == file.path
        assert file.path in tree
        assert tree[file.path].mode == "100644"
        assert tree[file.path].type == "blob"
        raw = file.content.encode("utf-8")
        expected_sha = hashlib.sha1(
            f"blob {len(raw)}\0".encode() + raw, usedforsecurity=False
        ).hexdigest()
        assert file.sha == tree[file.path].sha == expected_sha
        assert len(raw) == file.size_bytes == tree[file.path].size
        assert len(raw) <= 64 * 1024
    for absent in entry["expected"].get("absent_paths", []):
        assert absent not in tree


@pytest.mark.parametrize("ref", [None, "main", "feature/offline-demo"])
async def test_allowed_refs_and_sha(ref: str | None, analysis_request: AnalysisRequest) -> None:
    source = FixtureRepositorySource()
    request = analysis_request.model_copy(update={"ref": ref})
    snapshot = await source.fetch(request)
    by_sha = await source.fetch(
        request.model_copy(update={"ref": snapshot.repository.resolved_commit})
    )
    assert snapshot == by_sha


async def test_url_variants_match_fixture(analysis_request: AnalysisRequest) -> None:
    request = analysis_request.model_copy(
        update={"repo_url": "HTTPS://GITHUB.COM/RepoDoctor-Fixtures/Python-Cli-Demo.git/"}
    )
    snapshot = await FixtureRepositorySource().fetch(request)
    assert snapshot.repository.url == analysis_request.repo_url


async def test_unknown_ref_does_not_fall_back(analysis_request: AnalysisRequest) -> None:
    with pytest.raises(RefNotFoundError):
        await FixtureRepositorySource().fetch(
            analysis_request.model_copy(update={"ref": "missing"})
        )


async def test_unknown_repository_does_not_fall_back(analysis_request: AnalysisRequest) -> None:
    request = analysis_request.model_copy(update={"repo_url": "https://github.com/other/repo"})
    with pytest.raises(RepositoryNotFoundError) as caught:
        await FixtureRepositorySource().fetch(request)
    assert len(caught.value.details) == 6


async def test_results_do_not_share_mutable_state(analysis_request: AnalysisRequest) -> None:
    source = FixtureRepositorySource()
    first = await source.fetch(analysis_request)
    first.files[0].content = "corrupted"
    first.tree.clear()
    first.coverage.limitations.append("corrupted")
    second = await source.fetch(analysis_request)
    assert second.tree
    assert second.files[0].content != "corrupted"
    assert "corrupted" not in second.coverage.limitations


async def test_scenarios_contain_the_intended_inputs(analysis_request: AnalysisRequest) -> None:
    source = FixtureRepositorySource()
    snapshots = {}
    for entry in ENTRIES:
        request = analysis_request.model_copy(update={"repo_url": entry["url"]})
        snapshots[entry["id"]] = await source.fetch(request)
    python = {file.path: file.content for file in snapshots["python-cli-demo"].files}
    assert "data/input.csv" in python["README.md"]
    assert "DEMO_API_TOKEN=[REDACTED]" in python[".env.example"]
    node = {file.path: file.content for file in snapshots["node-api-demo"].files}
    package = json.loads(node["package.json"])
    lock = json.loads(node["package-lock.json"])
    assert package["scripts"]["start"] == "node src/server.js"
    assert package["engines"]["node"] == ">=22.12.0"
    assert package["version"] == lock["packages"][""]["version"]
    mixed = {file.path: file.content for file in snapshots["ml-experiments-demo"].files}
    assert (
        "fastapi>=0.115"
        in tomllib.loads(mixed["backend/pyproject.toml"])["project"]["dependencies"]
    )
    assert "dev" in json.loads(mixed["frontend/package.json"])["scripts"]
    broken = {file.path: file.content for file in snapshots["malformed-manifest-demo"].files}
    with pytest.raises(json.JSONDecodeError):
        json.loads(broken["package.json"])
    with pytest.raises(tomllib.TOMLDecodeError):
        tomllib.loads(broken["pyproject.toml"])
    partial = snapshots["partial-tree-demo"]
    assert partial.coverage.status == "partial"
    assert any("truncated" in limitation for limitation in partial.coverage.limitations)


async def test_injected_common_redactor_is_used(analysis_request: AnalysisRequest) -> None:
    calls: list[str] = []

    def shared_redactor(text: str) -> tuple[str, int]:
        calls.append(text)
        return text.replace("Local fixture", "Masked fixture"), 1

    snapshot = await FixtureRepositorySource(redactor=shared_redactor).fetch(analysis_request)
    assert len(calls) == len(snapshot.files)
    readme = next(file for file in snapshot.files if file.path == "README.md")
    assert "Masked fixture" in readme.content


async def test_redactor_cannot_break_line_numbers(analysis_request: AnalysisRequest) -> None:
    source = FixtureRepositorySource(redactor=lambda text: (text.replace("\n", ""), 1))
    with pytest.raises(FixtureLibraryError, match="строк"):
        await source.fetch(analysis_request)


async def test_unredacted_env_example_rejected(
    tmp_path: Path, analysis_request: AnalysisRequest
) -> None:
    fixtures_dir = copied_library(tmp_path)

    def change(data: dict) -> None:
        for file in data["files"]:
            if file["path"] == ".env.example":
                file["content"] = "DEMO_API_TOKEN=synthetic-unsafe-value\n"

    edit_snapshot(fixtures_dir, change)
    with pytest.raises(FixtureLibraryError, match="очищены"):
        await FixtureRepositorySource(fixtures_dir).fetch(analysis_request)


async def test_mismatched_snapshot_rejected(
    tmp_path: Path, analysis_request: AnalysisRequest
) -> None:
    fixtures_dir = copied_library(tmp_path)
    edit_snapshot(fixtures_dir, lambda data: data.update(source_mode="github"))
    with pytest.raises(FixtureLibraryError, match="index"):
        await FixtureRepositorySource(fixtures_dir).fetch(analysis_request)


@pytest.mark.parametrize("snapshot_path", ["../outside.json", "/outside.json", "a\\b.json"])
async def test_index_cannot_escape_fixture_directory(
    snapshot_path: str, tmp_path: Path, analysis_request: AnalysisRequest
) -> None:
    fixtures_dir = copied_library(tmp_path)
    index_path = fixtures_dir / "repositories" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["repositories"][0]["snapshot"] = snapshot_path
    index_path.write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(FixtureLibraryError):
        await FixtureRepositorySource(fixtures_dir).fetch(analysis_request)


def test_missing_library_has_safe_domain_error(tmp_path: Path) -> None:
    with pytest.raises(FixtureLibraryError, match="index"):
        FixtureRepositorySource(tmp_path)
