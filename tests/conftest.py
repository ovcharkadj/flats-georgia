"""Shared test helpers: fixture loading and a ready ``Settings``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from flats_georgia.config import Settings, load_settings

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture_json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def settings() -> Settings:
    """Real config.toml, no secrets required."""
    return load_settings(require_secrets=False)
