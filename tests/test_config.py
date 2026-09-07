"""Patch 1 - configuration loading and secret handling."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from flats_georgia.config import ConfigError, load_settings

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_default_config_loads_the_locked_filter() -> None:
    settings = load_settings(require_secrets=False)

    assert settings.filter.city == 1
    assert settings.filter.deal_type == 2
    assert settings.filter.real_estate_type == 1
    assert settings.filter.currency == 2
    assert settings.filter.price_from == 300
    assert settings.filter.price_to == 500
    assert settings.filter.urbans == (47,)
    assert settings.behaviour.timezone == "Asia/Tbilisi"
    assert settings.behaviour.daily_digest_hour == 11
    assert settings.behaviour.quiet_hours_local == tuple(range(0, 11))
    assert settings.source.website_key == "myhome"
    assert settings.state_path == REPO_ROOT / "state" / "seen_ids.json"


def test_filter_flattens_to_myhome_query_params() -> None:
    settings = load_settings(require_secrets=False)

    params = settings.filter.as_query_params()

    assert ("cities", "1") in params
    assert ("deal_types", "2") in params
    assert ("currency_id", "2") in params
    assert ("price_from", "300") in params
    assert ("price_to", "500") in params
    assert ("urbans[]", "47") in params


def test_missing_secrets_raise_only_when_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setattr("flats_georgia.config.load_dotenv", lambda *a, **k: False)

    # require_secrets=False -> no secrets, no error
    assert load_settings(require_secrets=False).secrets is None

    # require_secrets=True -> a clear error naming both vars
    with pytest.raises(ConfigError) as excinfo:
        load_settings(require_secrets=True)
    assert "TELEGRAM_BOT_TOKEN" in str(excinfo.value)
    assert "TELEGRAM_CHAT_ID" in str(excinfo.value)


def test_secrets_loaded_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("flats_georgia.config.load_dotenv", lambda *a, **k: False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")

    settings = load_settings(require_secrets=True)

    assert settings.secrets is not None
    assert settings.secrets.telegram_bot_token == "123:abc"
    assert settings.secrets.telegram_chat_id == "999"


def test_malformed_config_is_reported(tmp_path: Path) -> None:
    bad = tmp_path / "config.toml"
    bad.write_text(
        textwrap.dedent(
            """
            [filter]
            city = 1
            deal_type = 2
            real_estate_type = 1
            currency = 2
            price_from = 300
            price_to = 500
            # urbans missing on purpose

            [behaviour]
            request_delay_seconds = 1.5
            request_jitter_seconds = 1.0
            message_pause_seconds = 3.0
            max_pages_per_run = 10
            max_stored_ids = 20000
            timezone = "Asia/Tbilisi"
            daily_digest_hour = 11
            quiet_hours_local = [0, 1, 2]

            [source]
            api_url = "x"
            website_key = "myhome"
            search_page_url = "x"
            homepage_url = "x"
            listing_url_template = "x"
            user_agent = "x"
            """
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="urbans"):
        load_settings(bad, require_secrets=False)


def test_missing_config_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_settings(tmp_path / "nope.toml", require_secrets=False)
