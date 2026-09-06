"""Patch 4 - digest formatting and Telegram delivery."""

from __future__ import annotations

import json

import pytest
from pytest_httpx import HTTPXMock

from flats_georgia.config import load_settings
from flats_georgia.telegram import (
    MESSAGE_LIMIT,
    DryRunSender,
    TelegramError,
    TelegramSender,
    build_messages,
    format_listing,
)
from tests.conftest import make_listing


def test_format_listing_has_the_essentials() -> None:
    listing = make_listing(25801515, price_usd=420, price_gel=1100, area_m2=40.0, rooms="1")

    text = format_listing(listing)

    assert "$420" in text
    assert "₾1100" in text
    assert "40 м²" in text
    assert "1-комн." in text
    assert "3/8 эт." in text
    assert "метро Важа-Пшавела" in text
    assert "собственник" in text
    assert text.strip().endswith("https://www.myhome.ge/en/pr/25801515/")


def test_format_listing_marks_agency_and_survives_missing_fields() -> None:
    listing = make_listing(
        1,
        is_agency=True,
        floor=None,
        total_floors=None,
        metro_station_id=None,
        posted_at=None,
        area_m2=None,
        rooms=None,
        price_usd=None,
        price_gel=None,
    )

    text = format_listing(listing)

    assert "агентство" in text
    assert "цена не указана" in text
    assert "Сабуртало" in text
    assert text.endswith("/1/")


def test_build_messages_keeps_header_first_and_one_message_when_small() -> None:
    listings = [make_listing(i) for i in range(5)]

    messages = build_messages(listings, header="HEAD")

    assert len(messages) == 1
    assert messages[0].startswith("HEAD\n\n")
    for listing in listings:
        assert listing.url in messages[0]


def test_build_messages_chunks_without_splitting_blocks() -> None:
    listings = [make_listing(1000 + i) for i in range(80)]

    messages = build_messages(listings, header="HEAD")

    assert len(messages) > 1
    assert all(len(message) <= MESSAGE_LIMIT for message in messages)
    # every listing lands in exactly one message, whole
    for listing in listings:
        hits = [m for m in messages if listing.url in m]
        assert len(hits) == 1
        assert format_listing(listing) in hits[0]


def test_build_messages_truncates_an_oversized_block() -> None:
    huge = make_listing(1, title="x" * (MESSAGE_LIMIT * 2))
    messages = build_messages([huge], header="HEAD")
    assert all(len(message) <= MESSAGE_LIMIT for message in messages)


def test_sender_posts_expected_payload(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://api.telegram.org/bot123:abc/sendMessage", json={"ok": True}
    )
    sender = TelegramSender("123:abc", "999")

    sender.send_message("hello")

    request = httpx_mock.get_requests()[0]
    assert request.method == "POST"
    body = json.loads(request.content)
    assert body == {"chat_id": "999", "text": "hello", "disable_web_page_preview": True}


def test_sender_raises_on_client_error(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(status_code=400, json={"ok": False, "description": "chat not found"})
    sender = TelegramSender("123:abc", "bad")

    with pytest.raises(TelegramError, match="400"):
        sender.send_message("hi")


def test_sender_retries_429_then_succeeds(
    httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(TelegramSender._post.retry, "sleep", lambda *_a, **_k: None)
    httpx_mock.add_response(status_code=429, json={"ok": False})
    httpx_mock.add_response(json={"ok": True})
    sender = TelegramSender("123:abc", "999")

    sender.send_message("hi")

    assert len(httpx_mock.get_requests()) == 2


def test_send_error_never_raises(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(status_code=401, json={"ok": False}, is_reusable=True)
    sender = TelegramSender("123:abc", "999")

    sender.send_error("source is down")  # must not raise


def test_dry_run_sender_records_and_makes_no_http_calls(httpx_mock: HTTPXMock) -> None:
    sender = DryRunSender()

    sender.send_message("digest body")
    sender.send_error("oops")

    assert sender.messages == ["digest body"]
    assert sender.errors == ["oops"]
    assert httpx_mock.get_requests() == []


@pytest.mark.live
def test_live_send_to_configured_chat() -> None:
    settings = load_settings(require_secrets=True)
    assert settings.secrets is not None
    sender = TelegramSender(settings.secrets.telegram_bot_token, settings.secrets.telegram_chat_id)
    sender.send_message("Flats Georgia: live delivery test ✅")
    sender.close()
