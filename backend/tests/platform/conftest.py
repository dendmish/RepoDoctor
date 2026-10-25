from __future__ import annotations

import json
from pathlib import Path

import pytest

from repodoctor.config import PROJECT_ROOT, Settings

EXAMPLES_DIR = PROJECT_ROOT / "contracts" / "examples"


def load_example(name: str) -> dict:
    return json.loads((EXAMPLES_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
def examples_dir() -> Path:
    return EXAMPLES_DIR


@pytest.fixture
def test_settings() -> Settings:
    """Settings isolated from the developer's .env and secrets."""
    return Settings(_env_file=None, app_env="test", openai_api_key=None, github_token=None)
