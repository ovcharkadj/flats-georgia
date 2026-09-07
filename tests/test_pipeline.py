"""Patch 5 - pipeline orchestration."""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from flats_georgia import pipeline
from flats_georgia.config import Settings, load_settings
from flats_georgia.dedup import SeenStore
from flats_georgia.sources import SourceError
from flats_georgia.telegram import TelegramError
from tests.conftest import make_listing

TZ = ZoneInfo("Asia/Tbilisi")
AFTERNOON = datetime(2026, 9, 6, 15, 0, tzinfo=TZ)  # awake, past the daily-digest hour
MORNING = datetime(2026, 9, 6, 11, 20, tzinfo=TZ)  # just past the daily-digest hour
LATE_MORNING = datetime(2026, 9, 6, 12, 37, tzinfo=TZ)  # a missed-1100-slot catch-up
NIGHT = datetime(2026, 9, 7, 1, 9, tzinfo=TZ)  # inside quiet_hours_local (the 01:09 incident)


class RecordingSender:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.errors: list[str] = []

    def send_message(self, text: str) -> None:
        self.messages.append(text)

    def send_error(self, text: str) -> None:
        self.errors.append(text)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Settings, RecordingSender]:
    settings = dataclasses.replace(
        load_settings(require_secrets=False), state_path=tmp_path / "seen_ids.json"
    )
    sender = RecordingSender()
    monkeypatch.setattr(pipeline, "_make_sender", lambda *a, **k: sender)
    return settings, sender


def _patch_source(monkeypatch: pytest.MonkeyPatch, listings: object) -> None:
    def fake_get_listings(_settings: Settings, **_kw: object) -> object:
        if isinstance(listings, Exception):
            raise listings
        return listings

    monkeypatch.setattr(pipeline, "get_listings", fake_get_listings)


def test_new_listings_are_sent_and_state_written(
    env: tuple[Settings, RecordingSender], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, sender = env
    _patch_source(monkeypatch, [make_listing(1), make_listing(2), make_listing(3)])

    code = pipeline.run(settings, now=AFTERNOON)

    assert code == pipeline.EXIT_OK
    assert sender.messages
    assert "Новых объявлений: 3" in sender.messages[0]
    stored = json.loads(settings.state_path.read_text(encoding="utf-8"))["ids"]
    assert stored == [1, 2, 3]


def test_second_run_sends_nothing(
    env: tuple[Settings, RecordingSender], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, sender = env
    listings = [make_listing(1), make_listing(2)]
    _patch_source(monkeypatch, listings)

    assert pipeline.run(settings, now=AFTERNOON) == pipeline.EXIT_OK
    sender.messages.clear()

    assert pipeline.run(settings, now=AFTERNOON) == pipeline.EXIT_OK
    assert sender.messages == []


def test_daily_digest_is_sent_once_per_day_even_with_nothing_new(
    env: tuple[Settings, RecordingSender], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, sender = env
    # id 1 already seen, and no digest has gone out today
    SeenStore(settings.state_path, ids=[1], max_stored=100).save()
    _patch_source(monkeypatch, [make_listing(1)])

    assert pipeline.run(settings, now=MORNING) == pipeline.EXIT_OK
    assert len(sender.messages) == 1
    assert "Новых объявлений нет." in sender.messages[0]

    sender.messages.clear()
    assert pipeline.run(settings, now=AFTERNOON) == pipeline.EXIT_OK
    assert sender.messages == []  # already done today


def test_daily_digest_catches_up_after_a_missed_1100_slot(
    env: tuple[Settings, RecordingSender], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, sender = env
    SeenStore(settings.state_path, ids=[1], max_stored=100).save()
    _patch_source(monkeypatch, [make_listing(1)])

    # first run of the day happens at 12:37 because GitHub skipped 11:xx
    assert pipeline.run(settings, now=LATE_MORNING) == pipeline.EXIT_OK
    assert len(sender.messages) == 1

    stored = json.loads(settings.state_path.read_text(encoding="utf-8"))
    assert stored["last_digest_date"] == "2026-09-06"


def test_dry_run_sends_but_writes_no_state(
    env: tuple[Settings, RecordingSender], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, sender = env
    _patch_source(monkeypatch, [make_listing(1), make_listing(2)])

    code = pipeline.run(settings, dry_run=True, now=AFTERNOON)

    assert code == pipeline.EXIT_OK
    assert sender.messages
    assert not settings.state_path.exists()


def test_force_full_resends_everything(
    env: tuple[Settings, RecordingSender], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, sender = env
    _patch_source(monkeypatch, [make_listing(1), make_listing(2)])
    pipeline.run(settings, now=AFTERNOON)
    sender.messages.clear()

    code = pipeline.run(settings, force_full=True, now=AFTERNOON)

    assert code == pipeline.EXIT_OK
    assert "Новых объявлений: 2" in sender.messages[0]


def test_source_failure_notifies_and_returns_nonzero(
    env: tuple[Settings, RecordingSender], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, sender = env
    _patch_source(monkeypatch, SourceError("API 403"))

    code = pipeline.run(settings, now=AFTERNOON)

    assert code == pipeline.EXIT_SOURCE_FAILED
    assert len(sender.errors) == 1
    assert sender.messages == []


def test_send_failure_returns_nonzero(
    env: tuple[Settings, RecordingSender], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, sender = env
    _patch_source(monkeypatch, [make_listing(1)])

    def boom(_text: str) -> None:
        raise TelegramError("chat not found")

    monkeypatch.setattr(sender, "send_message", boom)

    code = pipeline.run(settings, now=AFTERNOON)

    assert code == pipeline.EXIT_SEND_FAILED
    assert len(sender.errors) == 1
    # state not advanced on a failed send
    assert not settings.state_path.exists()


def test_quiet_hours_suppress_everything(
    env: tuple[Settings, RecordingSender], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, sender = env

    def fail_if_called(*_a: object, **_k: object) -> object:
        raise AssertionError("source must not be hit during quiet hours")

    monkeypatch.setattr(pipeline, "get_listings", fail_if_called)

    code = pipeline.run(settings, always_send=True, now=NIGHT)

    assert code == pipeline.EXIT_OK
    assert sender.messages == []
    assert sender.errors == []
    assert not settings.state_path.exists()


def test_force_full_still_runs_during_quiet_hours(
    env: tuple[Settings, RecordingSender], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, sender = env
    _patch_source(monkeypatch, [make_listing(1)])

    code = pipeline.run(settings, force_full=True, now=NIGHT)

    assert code == pipeline.EXIT_OK
    assert sender.messages


def test_digest_is_ordered_most_expensive_first(
    env: tuple[Settings, RecordingSender], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, sender = env
    _patch_source(
        monkeypatch,
        [
            make_listing(1, price_usd=350),
            make_listing(2, price_usd=500),
            make_listing(3, price_usd=None),
            make_listing(4, price_usd=420),
        ],
    )

    pipeline.run(settings, now=AFTERNOON)

    body = "\n".join(sender.messages)
    positions = [body.index(f"/{i}/") for i in (2, 4, 1, 3)]
    assert positions == sorted(positions)  # 500, 420, 350, then no-price


def test_messages_are_paced(
    env: tuple[Settings, RecordingSender], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, sender = env
    _patch_source(monkeypatch, [make_listing(1000 + i) for i in range(120)])
    pauses: list[float] = []

    pipeline.run(settings, now=AFTERNOON, sleep=pauses.append)

    assert len(sender.messages) > 1
    assert len(pauses) == len(sender.messages) - 1
    assert all(p == settings.behaviour.message_pause_seconds for p in pauses)


@pytest.mark.live
def test_live_dry_run_end_to_end() -> None:
    settings = load_settings(require_secrets=False)
    assert pipeline.run(settings, dry_run=True, always_send=True) == pipeline.EXIT_OK
