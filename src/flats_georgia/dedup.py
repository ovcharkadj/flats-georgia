"""Persistent state: already-seen listing ids and the last daily-digest date.

The newness signal is the listing ``id`` (monotonically increasing on MyHome, and
unchanged when a listing is bumped), so a plain id set is enough. ``last_digest_date``
lets the pipeline send the once-a-day digest on the first run at/after the digest
hour even when GitHub skipped the exact scheduled slot.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from flats_georgia.models import Listing


class StateError(RuntimeError):
    """The state file exists but is not valid ``{"ids": [int, ...]}``."""


class SeenStore:
    """Load / query / persist the run state for one state file."""

    def __init__(
        self,
        path: Path,
        ids: Iterable[int],
        max_stored: int,
        last_digest_date: str | None = None,
    ) -> None:
        self._path = path
        self._ids: set[int] = {int(i) for i in ids}
        self._max_stored = max_stored
        self._last_digest_date = last_digest_date

    @classmethod
    def load(cls, path: Path, *, max_stored: int) -> SeenStore:
        if not path.is_file():
            return cls(path, (), max_stored)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise StateError(f"cannot read state file {path}: {exc}") from exc
        if not isinstance(raw, dict) or "ids" not in raw:
            raise StateError(f"state file {path} has no 'ids' key")
        ids = raw["ids"]
        if not isinstance(ids, list) or not all(
            isinstance(i, int) and not isinstance(i, bool) for i in ids
        ):
            raise StateError(f"state file {path} 'ids' is not a list of integers")
        last_digest_date = raw.get("last_digest_date")
        if last_digest_date is not None and not isinstance(last_digest_date, str):
            raise StateError(f"state file {path} 'last_digest_date' is not a string")
        return cls(path, ids, max_stored, last_digest_date)

    def __contains__(self, listing_id: int) -> bool:
        return listing_id in self._ids

    def __len__(self) -> int:
        return len(self._ids)

    @property
    def is_empty(self) -> bool:
        return not self._ids

    @property
    def last_digest_date(self) -> str | None:
        return self._last_digest_date

    def filter_new(self, listings: Sequence[Listing]) -> list[Listing]:
        """Listings whose id has not been seen, in the given order. Non-mutating."""
        return [listing for listing in listings if listing.id not in self._ids]

    def mark_seen(self, listings: Iterable[Listing]) -> None:
        self._ids.update(listing.id for listing in listings)

    def mark_digest_sent(self, date: str) -> None:
        self._last_digest_date = date

    def save(self) -> None:
        kept = sorted(self._ids)
        if len(kept) > self._max_stored:
            kept = kept[-self._max_stored :]
        self._ids = set(kept)
        payload = {
            "ids": kept,
            "last_digest_date": self._last_digest_date,
            "updated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
