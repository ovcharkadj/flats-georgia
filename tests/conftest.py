"""Shared test helpers: fixture loading and a ready ``Settings``."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from flats_georgia.config import Settings, load_settings
from flats_georgia.models import Listing

FIXTURES = Path(__file__).parent / "fixtures"
_TZ = ZoneInfo("Asia/Tbilisi")


def make_listing(listing_id: int, **overrides: Any) -> Listing:
    """A plausible Listing for tests; override any field by keyword."""
    base: dict[str, Any] = {
        "id": listing_id,
        "url": f"https://www.myhome.ge/en/pr/{listing_id}/",
        "title": f"1 room apartment for rent in saburtalo #{listing_id}",
        "price_usd": 420,
        "price_gel": 1100,
        "area_m2": 40.0,
        "rooms": "1",
        "bedrooms": "1",
        "floor": 3,
        "total_floors": 8,
        "area_name": "Saburtalo",
        "district": "Vake-Saburtalo",
        "metro_station_id": 2,
        "posted_at": datetime(2026, 9, 6, 11, 30, tzinfo=_TZ),
        "is_agency": False,
    }
    base.update(overrides)
    return Listing(**base)


def load_fixture_json(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def settings() -> Settings:
    """Real config.toml, no secrets required."""
    return load_settings(require_secrets=False)
