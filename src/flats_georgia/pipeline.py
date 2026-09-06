"""Orchestration: fetch -> pick new -> send digest -> persist state."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from flats_georgia.config import Settings
from flats_georgia.dedup import SeenStore
from flats_georgia.sources import SourceError, get_listings
from flats_georgia.telegram import (
    DryRunSender,
    Sender,
    TelegramError,
    TelegramSender,
    build_messages,
)

log = logging.getLogger("flats_georgia.pipeline")

EXIT_OK = 0
EXIT_SOURCE_FAILED = 2
EXIT_SEND_FAILED = 3

_AREA_LABEL = "Сабуртало"  # single fixed filter this round


def _header(new_count: int, when: datetime) -> str:
    stamp = f"{when:%d.%m %H:%M}"
    if new_count == 0:
        return f"🏘 MyHome · {_AREA_LABEL} · {stamp}\nНовых объявлений нет."
    return f"🏘 MyHome · {_AREA_LABEL} · {stamp}\nНовых объявлений: {new_count}"


def _make_sender(settings: Settings, *, dry_run: bool) -> Sender:
    if dry_run:
        return DryRunSender()
    if settings.secrets is None:  # pragma: no cover - load_settings enforces this
        raise RuntimeError("Telegram secrets are required for a real run")
    return TelegramSender(settings.secrets.telegram_bot_token, settings.secrets.telegram_chat_id)


def run(
    settings: Settings,
    *,
    dry_run: bool = False,
    force_full: bool = False,
    always_send: bool = False,
    now: datetime | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Run one digest cycle. Returns a process exit code."""
    tz = ZoneInfo(settings.behaviour.timezone)
    moment = now or datetime.now(tz)
    sender = _make_sender(settings, dry_run=dry_run)
    try:
        try:
            listings = get_listings(settings)
        except SourceError as exc:
            log.error("source failed: %s", exc)
            sender.send_error(f"источник недоступен: {exc}")
            return EXIT_SOURCE_FAILED

        log.info("fetched %d listing(s)", len(listings))
        store = SeenStore.load(settings.state_path, max_stored=settings.behaviour.max_stored_ids)
        selected = listings if force_full else store.filter_new(listings)
        must_send = always_send or (moment.hour in settings.behaviour.always_send_hours_local)

        if not selected and not must_send:
            log.info("nothing new, no guaranteed slot - not sending")
            return EXIT_OK

        messages = build_messages(selected, _header(len(selected), moment))
        try:
            for index, message in enumerate(messages):
                if index:
                    sleep(settings.behaviour.message_pause_seconds)
                sender.send_message(message)
        except TelegramError as exc:
            log.error("send failed: %s", exc)
            sender.send_error(f"не удалось отправить сводку: {exc}")
            return EXIT_SEND_FAILED

        log.info("sent %d message(s) covering %d listing(s)", len(messages), len(selected))
        if not dry_run:
            store.mark_seen(listings)
            store.save()
        return EXIT_OK
    finally:
        if isinstance(sender, TelegramSender):
            sender.close()
