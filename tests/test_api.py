"""Patch 2 - MyHome JSON API client."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

from flats_georgia.config import Settings, load_settings
from flats_georgia.sources import SourceError
from flats_georgia.sources import api as api_source
from tests.conftest import load_fixture_json

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.toml"


def no_sleep(_seconds: float) -> None:
    return None


def paginated_handler(
    pages: dict[str, object], empty: object
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page", "1")
        body = pages.get(page, empty)
        return httpx.Response(200, json=body)

    return handler


def test_fetch_paginates_until_empty_and_normalizes(
    settings: Settings, httpx_mock: HTTPXMock
) -> None:
    page1 = load_fixture_json("api_page1.json")
    page2 = load_fixture_json("api_page2.json")
    empty = load_fixture_json("api_page_empty.json")
    httpx_mock.add_callback(paginated_handler({"1": page1, "2": page2}, empty), is_reusable=True)

    listings = api_source.fetch_listings(settings, sleep=no_sleep)

    assert len(listings) == 40
    assert len({listing.id for listing in listings}) == 40
    assert all(isinstance(listing.id, int) and listing.id > 0 for listing in listings)
    assert all(listing.url.endswith(f"/{listing.id}/") for listing in listings)

    raw_first = page1["data"]["data"][0]
    got = next(listing for listing in listings if listing.id == raw_first["id"])
    assert got.price_usd == raw_first["price"]["2"]["price_total"]
    assert got.price_gel == raw_first["price"]["1"]["price_total"]
    assert got.area_m2 == float(raw_first["area"])
    assert got.rooms == str(raw_first["room"])
    assert got.area_name == raw_first["urban_name"]
    assert got.is_agency is (raw_first["user_type"]["type"] != "physical")


def test_empty_first_page_yields_no_listings(settings: Settings, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(json=load_fixture_json("api_page_empty.json"), is_reusable=True)

    assert api_source.fetch_listings(settings, sleep=no_sleep) == []


def test_page_cap_is_respected(httpx_mock: HTTPXMock, tmp_path: Path) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        CONFIG_PATH.read_text(encoding="utf-8").replace(
            "max_pages_per_run = 10", "max_pages_per_run = 2"
        ),
        encoding="utf-8",
    )
    settings = load_settings(cfg, require_secrets=False)
    httpx_mock.add_response(json=load_fixture_json("api_page1.json"), is_reusable=True)

    listings = api_source.fetch_listings(settings, sleep=no_sleep)

    assert len(listings) == 20
    assert len(httpx_mock.get_requests()) == 2


def test_client_error_raises_source_error(settings: Settings, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(status_code=403, json={"message": "nope"}, is_reusable=True)

    with pytest.raises(SourceError, match="403"):
        api_source.fetch_listings(settings, sleep=no_sleep)


def test_non_json_body_raises_source_error(settings: Settings, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(text="<html>maintenance</html>", is_reusable=True)

    with pytest.raises(SourceError, match="non-JSON"):
        api_source.fetch_listings(settings, sleep=no_sleep)


def test_result_false_body_raises_source_error(settings: Settings, httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        json={"result": False, "data": [], "errors": {"message": ["X-Website-Key is required"]}},
        is_reusable=True,
    )

    with pytest.raises(SourceError, match="result not ok"):
        api_source.fetch_listings(settings, sleep=no_sleep)


def test_transient_5xx_is_retried_then_succeeds(
    settings: Settings, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api_source._get_page.retry, "sleep", lambda *_a, **_k: None)
    httpx_mock.add_response(status_code=503, json={"message": "busy"})
    httpx_mock.add_response(status_code=503, json={"message": "busy"})
    httpx_mock.add_response(json=load_fixture_json("api_page_empty.json"))

    assert api_source.fetch_listings(settings, sleep=no_sleep) == []
    assert len(httpx_mock.get_requests()) == 3


def test_request_delay_includes_jitter_within_bounds(
    settings: Settings, httpx_mock: HTTPXMock
) -> None:
    # a reusable full page never returns empty, so all pages run and sleep between them
    httpx_mock.add_response(json=load_fixture_json("api_page1.json"), is_reusable=True)
    waits: list[float] = []

    api_source.fetch_listings(settings, sleep=waits.append)

    assert waits
    low = settings.behaviour.request_delay_seconds
    high = low + settings.behaviour.request_jitter_seconds
    assert all(low <= wait <= high for wait in waits)


@pytest.mark.live
def test_live_api_returns_in_band_listings() -> None:
    settings = load_settings(require_secrets=False)
    listings = api_source.fetch_listings(settings)
    assert listings
    assert all(listing.id > 0 for listing in listings)
    assert all(300 <= (listing.price_usd or 0) <= 500 for listing in listings)
