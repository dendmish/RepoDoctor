from __future__ import annotations

import pytest

from repodoctor.security.redaction import REDACTED, redact_text, sanitize_log

# Synthetic secrets only.
SECRETS = [
    ("Authorization: Bearer abcdefghijklmnop123", "abcdefghijklmnop123"),
    ("authorization: token ghx-not-a-real-token-1", "ghx-not-a-real-token-1"),
    (
        "export GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz012345",
        "ghp_abcdefghijklmnopqrstuvwxyz012345",
    ),
    (
        "token github_pat_11ABCDEFG0123456789_abcdefghijkl",
        "github_pat_11ABCDEFG0123456789_abcdefghijkl",
    ),
    ("OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwx", "sk-proj-abcdefghijklmnopqrstuvwx"),
    ("key is sk-abcdefghijklmnopqrstuvwxyz used", "sk-abcdefghijklmnopqrstuvwxyz"),
    ('DB_PASSWORD="hunter2-secret"', "hunter2-secret"),
    ("git clone https://user:p4ssw0rd@github.com/a/b", "p4ssw0rd"),
    ('{"api_key": "abc123def456"}', "abc123def456"),
    ("GET /cb?password=s3cr3t&x=1", "s3cr3t"),
    ("aws AKIAABCDEFGHIJKLMNOP done", "AKIAABCDEFGHIJKLMNOP"),
    ("xoxb-1234567890-abcdefghij", "xoxb-1234567890-abcdefghij"),
    (
        "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"
        ".dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
        "eyJzdWIiOiIxMjM0NTY3ODkwIn0",
    ),
]


@pytest.mark.parametrize(("text", "secret"), SECRETS)
def test_known_secret_shapes_are_masked(text: str, secret: str) -> None:
    masked, count = redact_text(text)
    assert secret not in masked
    assert REDACTED in masked
    assert count >= 1


@pytest.mark.parametrize(
    "text",
    [
        "Traceback (most recent call last):",
        "ModuleNotFoundError: No module named 'dotenv'",
        "KeyError: 'token'",
        "DEMO_API_TOKEN=",
        "npm ERR! code ENOENT",
        "Error: listen EADDRINUSE: address already in use :::3000",
    ],
)
def test_ordinary_log_lines_are_untouched(text: str) -> None:
    assert redact_text(text) == (text, 0)


def test_private_key_block_keeps_line_count() -> None:
    text = (
        "before\n-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nAAAA\n"
        "-----END RSA PRIVATE KEY-----\nafter"
    )
    masked, count = redact_text(text)
    assert count == 1
    assert "MIIEow" not in masked
    assert masked.count("\n") == text.count("\n")
    assert masked.splitlines()[0] == "before" and masked.splitlines()[-1] == "after"


def test_line_numbers_are_preserved_for_multiline_logs() -> None:
    text = "line1\nTOKEN=abc123456\nline3\nhttps://u:p@host/x\nline5"
    masked, count = redact_text(text)
    assert count == 2
    assert masked.count("\n") == 4
    assert masked.splitlines()[2] == "line3"


def test_redaction_is_idempotent() -> None:
    once, _ = redact_text("API_KEY=abcdef123456 Authorization: Bearer abcdefghijkl")
    twice, count = redact_text(once)
    assert twice == once and count == 0


def test_sanitize_log_strips_ansi_and_normalizes_newlines() -> None:
    raw = "\x1b[31mError\x1b[0m\r\nsecond\rthird\x07\n\x1b]0;title\x07fourth"
    log = sanitize_log(raw)
    assert log.text == "Error\nsecond\nthird\nfourth"
    assert log.redactions_count == 0 and log.truncated is False


def test_sanitize_log_counts_redactions() -> None:
    log = sanitize_log("ok\nGITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz012345\n")
    assert log.redactions_count == 1
    assert "ghp_" not in log.text
