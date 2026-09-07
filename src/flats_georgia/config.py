"""Load ``config.toml`` and environment secrets into a typed, frozen ``Settings``."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CONFIG_PATH = _REPO_ROOT / "config.toml"


class ConfigError(RuntimeError):
    """Raised when configuration or required secrets are missing or malformed."""


@dataclass(frozen=True, slots=True)
class FilterConfig:
    city: int
    deal_type: int
    real_estate_type: int
    currency: int
    price_from: int
    price_to: int
    urbans: tuple[int, ...]

    def as_query_params(self) -> list[tuple[str, str]]:
        """Flatten to MyHome query parameters (``urbans[]`` repeated per id)."""
        params: list[tuple[str, str]] = [
            ("cities", str(self.city)),
            ("deal_types", str(self.deal_type)),
            ("real_estate_types", str(self.real_estate_type)),
            ("currency_id", str(self.currency)),
            ("price_from", str(self.price_from)),
            ("price_to", str(self.price_to)),
        ]
        params.extend(("urbans[]", str(u)) for u in self.urbans)
        return params


@dataclass(frozen=True, slots=True)
class BehaviourConfig:
    request_delay_seconds: float
    request_jitter_seconds: float
    message_pause_seconds: float
    max_pages_per_run: int
    max_stored_ids: int
    timezone: str
    always_send_hours_local: tuple[int, ...]
    quiet_hours_local: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SourceConfig:
    api_url: str
    website_key: str
    search_page_url: str
    homepage_url: str
    listing_url_template: str
    user_agent: str


@dataclass(frozen=True, slots=True)
class Secrets:
    telegram_bot_token: str
    telegram_chat_id: str


@dataclass(frozen=True, slots=True)
class Settings:
    filter: FilterConfig
    behaviour: BehaviourConfig
    source: SourceConfig
    state_path: Path
    secrets: Secrets | None


class _Table:
    """Thin typed accessor over one ``config.toml`` table."""

    def __init__(self, data: object, path: str) -> None:
        if not isinstance(data, dict):
            raise ConfigError(f"config.toml: [{path}] must be a table")
        self._data: dict[str, object] = data
        self._path = path

    def _get(self, key: str) -> object:
        if key not in self._data:
            raise ConfigError(f"config.toml: missing [{self._path}] key {key!r}")
        return self._data[key]

    def str_(self, key: str) -> str:
        value = self._get(key)
        if not isinstance(value, str):
            raise ConfigError(f"config.toml: [{self._path}] {key!r} must be a string")
        return value

    def int_(self, key: str) -> int:
        value = self._get(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"config.toml: [{self._path}] {key!r} must be an integer")
        return value

    def float_(self, key: str) -> float:
        value = self._get(key)
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ConfigError(f"config.toml: [{self._path}] {key!r} must be a number")
        return float(value)

    def int_tuple(self, key: str) -> tuple[int, ...]:
        value = self._get(key)
        if not isinstance(value, list) or not all(
            isinstance(v, int) and not isinstance(v, bool) for v in value
        ):
            raise ConfigError(f"config.toml: [{self._path}] {key!r} must be a list of integers")
        return tuple(int(v) for v in value)

    def str_or(self, key: str, default: str) -> str:
        return self.str_(key) if key in self._data else default


def load_settings(
    config_path: Path | None = None,
    *,
    require_secrets: bool = True,
) -> Settings:
    """Read config + env. With ``require_secrets`` the Telegram env vars must be set."""
    path = config_path or _DEFAULT_CONFIG_PATH
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")

    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    flt = _Table(raw.get("filter", {}), "filter")
    beh = _Table(raw.get("behaviour", {}), "behaviour")
    src = _Table(raw.get("source", {}), "source")
    state = _Table(raw.get("state", {}), "state")

    filter_config = FilterConfig(
        city=flt.int_("city"),
        deal_type=flt.int_("deal_type"),
        real_estate_type=flt.int_("real_estate_type"),
        currency=flt.int_("currency"),
        price_from=flt.int_("price_from"),
        price_to=flt.int_("price_to"),
        urbans=flt.int_tuple("urbans"),
    )

    behaviour_config = BehaviourConfig(
        request_delay_seconds=beh.float_("request_delay_seconds"),
        request_jitter_seconds=beh.float_("request_jitter_seconds"),
        message_pause_seconds=beh.float_("message_pause_seconds"),
        max_pages_per_run=beh.int_("max_pages_per_run"),
        max_stored_ids=beh.int_("max_stored_ids"),
        timezone=beh.str_("timezone"),
        always_send_hours_local=beh.int_tuple("always_send_hours_local"),
        quiet_hours_local=beh.int_tuple("quiet_hours_local"),
    )

    source_config = SourceConfig(
        api_url=src.str_("api_url"),
        website_key=src.str_("website_key"),
        search_page_url=src.str_("search_page_url"),
        homepage_url=src.str_("homepage_url"),
        listing_url_template=src.str_("listing_url_template"),
        user_agent=src.str_("user_agent"),
    )

    state_path = _REPO_ROOT / state.str_or("path", "state/seen_ids.json")

    return Settings(
        filter=filter_config,
        behaviour=behaviour_config,
        source=source_config,
        state_path=state_path,
        secrets=_load_secrets() if require_secrets else _try_load_secrets(),
    )


def _load_secrets() -> Secrets:
    load_dotenv(_REPO_ROOT / ".env")
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    missing = [
        name
        for name, value in (("TELEGRAM_BOT_TOKEN", token), ("TELEGRAM_CHAT_ID", chat_id))
        if not value
    ]
    if missing:
        raise ConfigError(
            "missing required secret(s): "
            + ", ".join(missing)
            + " - set them in .env locally or as GitHub Actions secrets "
            "(or pass --dry-run to run without sending)"
        )
    return Secrets(telegram_bot_token=token, telegram_chat_id=chat_id)


def _try_load_secrets() -> Secrets | None:
    try:
        return _load_secrets()
    except ConfigError:
        return None


if __name__ == "__main__":  # pragma: no cover - manual smoke check
    print(load_settings(require_secrets=False))
