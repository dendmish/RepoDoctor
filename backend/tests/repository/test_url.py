from __future__ import annotations

from urllib.parse import unquote

import pytest

from repodoctor.contracts.domain import InvalidInputError
from repodoctor.repository.url import encode_ref_segment, normalize_ref, normalize_repo_url


@pytest.mark.parametrize(
    ("url", "owner", "repo"),
    [
        ("https://github.com/Owner/Repo", "owner", "repo"),
        ("https://github.com/Owner/Repo.git", "owner", "repo"),
        ("https://github.com/Owner/Repo.git/", "owner", "repo"),
        ("https://github.com/Owner/Repo.GIT/", "owner", "repo"),
        ("https://github.com/Owner/Repo/", "owner", "repo"),
        ("HTTPS://GITHUB.COM/Some-Org/repo_name.v2", "some-org", "repo_name.v2"),
        ("https://github.com/a/.github", "a", ".github"),
        ("https://github.com/a/one..two", "a", "one..two"),
    ],
)
def test_normalize_repo_url(url: str, owner: str, repo: str) -> None:
    result = normalize_repo_url(url)
    assert (result.owner, result.repo) == (owner, repo)
    assert result.url == f"https://github.com/{owner}/{repo}"
    assert normalize_repo_url(result.url) == result


@pytest.mark.parametrize(
    "url",
    [
        "",
        "http://github.com/a/b",
        "git@github.com:a/b.git",
        "file:///a/b",
        "https://gitlab.com/a/b",
        "https://github.com.evil.invalid/a/b",
        "https://github.com@evil.invalid/a/b",
        "https://user:password@github.com/a/b",
        "https://user@github.com/a/b",
        "https://github.com:443/a/b",
        "https://github.com:80/a/b",
        "https://github.com:/a/b",
        "https://github.com./a/b",
        "https://[broken/a/b",
        "https://github.com/a/b?ref=main",
        "https://github.com/a/b?",
        "https://github.com/a/b#readme",
        "https://github.com/a/b#",
        "https://github.com/a/b/issues",
        "https://github.com/a/b/tree/feature/demo",
        "https://github.com/a/b//",
        "https://github.com//a/b",
        "https://github.com/a",
        "https://github.com/a/.",
        "https://github.com/a/..",
        "https://github.com/../b",
        "https://github.com/a/.git",
        "https://github.com/a/b.git.git",
        "https://github.com/a/b%2Fc",
        "https://github.com/a/b%5cc",
        "https://github.com/a/%252e%252e",
        "https://github.com/a/b%20c",
        "https://github.com/a/b\\c",
        "https://github.com/a/b c",
        " https://github.com/a/b",
        "https://github.com/a/b ",
        "https://github.com/a/b\n",
        "\thttps://github.com/a/b",
        "https://git\nhub.com/a/b",
        "https://github.com/a/b\x00",
        "https://github.com/a/b\x7f",
        "https://github.com/a/b\u0085",
        "https://github.com/a/b\u202e",
        "https://github.com/владелец/repo",
        "https://github.com/bad_owner/repo",
        "https://github.com/-owner/repo",
        "https://github.com/owner-/repo",
        "https://github.com/a--b/repo",
        f"https://github.com/{'a' * 40}/repo",
        f"https://github.com/a/{'b' * 101}",
        f"https://github.com/a/{'b' * 2100}",
    ],
)
def test_invalid_repo_url_rejected(url: str) -> None:
    with pytest.raises(InvalidInputError):
        normalize_repo_url(url)


def test_tree_url_explains_separate_ref() -> None:
    with pytest.raises(InvalidInputError, match="ref"):
        normalize_repo_url("https://github.com/a/b/tree/feature/offline")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        (" main ", "main"),
        ("feature/offline", "feature/offline"),
        ("a" * 40, "a" * 40),
    ],
)
def test_ref_normalization(value: str | None, expected: str | None) -> None:
    assert normalize_ref(value) == expected


@pytest.mark.parametrize("value", ["a" * 201, "main\n", "\tmain", "x\x00y", "x\x7f", "x\u202e"])
def test_invalid_ref(value: str) -> None:
    with pytest.raises(InvalidInputError):
        normalize_ref(value)


@pytest.mark.parametrize("ref", ["feature/offline", "release/v1.0", "a%2Fb", "x?y#z", ".", ".."])
def test_ref_is_one_encoded_segment(ref: str) -> None:
    encoded = encode_ref_segment(ref)
    assert unquote(encoded) == ref
    assert not any(char in encoded for char in "/?#")
    assert encoded not in {".", ".."}


def test_blank_encoded_ref_is_rejected() -> None:
    with pytest.raises(InvalidInputError):
        encode_ref_segment(" ")
