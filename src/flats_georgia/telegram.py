"""Digest formatting and Telegram delivery.

The digest text is Russian - it is read only by the project owner. Messages are
sent as plain text (no parse mode), so no escaping is needed and listing URLs
stay clickable.
"""

from __future__ import annotations

import contextlib
from collections.abc import Sequence
from typing import Protocol

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from flats_georgia.models import Listing

MESSAGE_LIMIT = 4096
_API_TEMPLATE = "https://api.telegram.org/bot{token}/sendMessage"
_TIMEOUT = httpx.Timeout(15.0)

_METRO_RU: dict[int, str] = {
    1: "Государственный университет",
    2: "Важа-Пшавела",
    3: "Делиси",
    4: "Медицинский университет",
    5: "Технический университет",
}
_AREA_RU: dict[str, str] = {"Saburtalo": "Сабуртало"}


class TelegramError(RuntimeError):
    """The Telegram Bot API rejected a request in a way retries will not fix."""


class Sender(Protocol):
    def send_message(self, text: str) -> None: ...
    def send_error(self, text: str) -> None: ...


def _price(listing: Listing) -> str:
    if listing.price_usd is not None:
        gel = f" (₾{listing.price_gel})" if listing.price_gel is not None else ""
        return f"${listing.price_usd}{gel}"
    if listing.price_gel is not None:
        return f"₾{listing.price_gel}"
    return "цена не указана"


def _rooms(listing: Listing) -> str | None:
    if listing.rooms:
        return f"{listing.rooms}-комн."
    return None


def _area(listing: Listing) -> str | None:
    if listing.area_m2:
        return f"{listing.area_m2:g} м²"
    return None


def _floor(listing: Listing) -> str | None:
    if listing.floor is not None and listing.total_floors is not None:
        return f"{listing.floor}/{listing.total_floors} эт."
    if listing.floor is not None:
        return f"{listing.floor} эт."
    return None


def _place(listing: Listing) -> str:
    area = _AREA_RU.get(listing.area_name, listing.area_name) or "—"
    metro = _METRO_RU.get(listing.metro_station_id or -1)
    return f"{area}, метро {metro}" if metro else area


def format_listing(listing: Listing) -> str:
    line1 = " · ".join(
        part for part in (_price(listing), _rooms(listing), _area(listing), _floor(listing)) if part
    )
    who = "агентство" if listing.is_agency else "собственник"
    when = f" · {listing.posted_at:%d.%m %H:%M}" if listing.posted_at else ""
    line2 = f"{_place(listing)} · {who}{when}"
    return f"{line1}\n{line2}\n{listing.url}"


def build_messages(listings: Sequence[Listing], header: str) -> list[str]:
    """Group header + listing blocks into messages, each <= MESSAGE_LIMIT chars.

    A listing block is never split across messages.
    """
    blocks = [header, *(format_listing(listing) for listing in listings)]
    messages: list[str] = []
    current = ""
    for raw_block in blocks:
        block = (
            raw_block if len(raw_block) <= MESSAGE_LIMIT else raw_block[: MESSAGE_LIMIT - 1] + "…"
        )
        candidate = block if not current else f"{current}\n\n{block}"
        if len(candidate) <= MESSAGE_LIMIT:
            current = candidate
            continue
        if current:
            messages.append(current)
        current = block
    if current:
        messages.append(current)
    return messages


class _Retryable(Exception):
    pass


class TelegramSender:
    """Real Bot API sender."""

    def __init__(
        self,
        token: str,
        chat_id: str,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self._url = _API_TEMPLATE.format(token=token)
        self._chat_id = chat_id
        self._owns_client = client is None
        self._client = client or httpx.Client()

    @retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, max=15),
        retry=retry_if_exception_type(_Retryable),
    )
    def _post(self, text: str) -> None:
        try:
            resp = self._client.post(
                self._url,
                json={
                    "chat_id": self._chat_id,
                    "text": text,
                    "disable_web_page_preview": True,
                },
                timeout=_TIMEOUT,
            )
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            raise _Retryable(str(exc)) from exc
        if resp.status_code == 429 or resp.status_code >= 500:
            raise _Retryable(f"HTTP {resp.status_code}")
        if resp.status_code != 200:
            raise TelegramError(f"Telegram API HTTP {resp.status_code}: {resp.text[:200]}")

    def send_message(self, text: str) -> None:
        try:
            self._post(text)
        except _Retryable as exc:
            raise TelegramError(f"Telegram send kept failing: {exc}") from exc

    def send_error(self, text: str) -> None:
        """Best-effort: never raise from the failure-notification path."""
        with contextlib.suppress(Exception):
            self.send_message(f"⚠️ Flats Georgia: {text}")

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


class DryRunSender:
    """Prints instead of calling Telegram. Records everything it was asked to send."""

    def __init__(self) -> None:
        self.messages: list[str] = []
        self.errors: list[str] = []

    def send_message(self, text: str) -> None:
        self.messages.append(text)
        print(text)
        print("-" * 40)

    def send_error(self, text: str) -> None:
        self.errors.append(text)
        print(f"[dry-run error notice] {text}")
