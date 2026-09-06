"""Persistent set of already-seen listing ids (``state/seen_ids.json``).

The newness signal is the listing ``id`` (monotonically increasing on MyHome, and
unchanged when a listing is bumped), so a plain id set is enough.
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
    """Load / query / persist the seen-id set for one state file."""

    def __init__(self, path: Path, ids: Iterable[int], max_stored: int) -> None:
        self._path = path
        self._ids: set[int] = {int(i) for i in ids}
        self._max_stored = max_stored

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
        return cls(path, ids, max_stored)

    def __contains__(self, listing_id: int) -> bool:
        return listing_id in self._ids

    def __len__(self) -> int:
        return len(self._ids)

    @property
    def is_empty(self) -> bool:
        return not self._ids

    def filter_new(self, listings: Sequence[Listing]) -> list[Listing]:
        """Listings whose id has not been seen, in the given order. Non-mutating."""
        return [listing for listing in listings if listing.id not in self._ids]

    def mark_seen(self, listings: Iterable[Listing]) -> None:
        self._ids.update(listing.id for listing in listings)

    def save(self) -> None:
        kept = sorted(self._ids)
        if len(kept) > self._max_stored:
            kept = kept[-self._max_stored :]
        self._ids = set(kept)
        payload = {
            "ids": kept,
            "updated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
