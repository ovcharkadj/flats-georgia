"""Patch 3 - seen-ids state store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flats_georgia.config import Settings
from flats_georgia.dedup import SeenStore, StateError
from tests.conftest import make_listing


def test_filter_new_returns_only_unseen_in_order(tmp_path: Path) -> None:
    store = SeenStore(tmp_path / "s.json", ids=[10, 11, 12, 13, 14], max_stored=100)
    listings = [make_listing(i) for i in (14, 20, 11, 21, 12, 22, 10, 23)]

    new = store.filter_new(listings)

    assert [listing.id for listing in new] == [20, 21, 22, 23]
    # non-mutating
    assert store.filter_new(listings) == new


def test_mark_and_save_persists_union(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    store = SeenStore(path, ids=[1, 2, 3], max_stored=100)
    store.mark_seen([make_listing(3), make_listing(4), make_listing(5)])
    store.save()

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["ids"] == [1, 2, 3, 4, 5]
    assert payload["updated_at"].endswith("Z")


def test_absent_file_means_everything_is_new(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "seen_ids.json"
    store = SeenStore.load(path, max_stored=100)
    assert store.is_empty

    listings = [make_listing(1), make_listing(2)]
    assert store.filter_new(listings) == listings

    store.mark_seen(listings)
    store.save()
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8"))["ids"] == [1, 2]


def test_save_caps_to_the_highest_ids(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    store = SeenStore(path, ids=[], max_stored=3)
    store.mark_seen([make_listing(i) for i in (5, 1, 9, 3, 7)])
    store.save()

    assert json.loads(path.read_text(encoding="utf-8"))["ids"] == [5, 7, 9]


def test_round_trip_load_after_save(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    store = SeenStore(path, ids=[100, 200, 300], max_stored=100)
    store.mark_digest_sent("2026-09-07")
    store.save()

    reloaded = SeenStore.load(path, max_stored=100)
    assert 200 in reloaded
    assert 999 not in reloaded
    assert len(reloaded) == 3
    assert reloaded.last_digest_date == "2026-09-07"


def test_last_digest_date_defaults_to_none_and_survives_old_files(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"ids": [1, 2], "updated_at": "x"}), encoding="utf-8")

    store = SeenStore.load(path, max_stored=100)
    assert store.last_digest_date is None

    store.mark_digest_sent("2026-09-07")
    store.save()
    assert json.loads(path.read_text(encoding="utf-8"))["last_digest_date"] == "2026-09-07"


def test_non_string_last_digest_date_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"ids": [1], "last_digest_date": 20260907}), encoding="utf-8")
    with pytest.raises(StateError, match="last_digest_date"):
        SeenStore.load(path, max_stored=100)


def test_malformed_json_raises_state_error(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(StateError, match="cannot read"):
        SeenStore.load(path, max_stored=100)


def test_wrong_shape_raises_state_error(tmp_path: Path) -> None:
    path = tmp_path / "s.json"
    path.write_text(json.dumps({"ids": ["a", "b"]}), encoding="utf-8")
    with pytest.raises(StateError, match="not a list of integers"):
        SeenStore.load(path, max_stored=100)

    path.write_text(json.dumps({"seen": [1, 2]}), encoding="utf-8")
    with pytest.raises(StateError, match="no 'ids' key"):
        SeenStore.load(path, max_stored=100)


def test_repo_state_file_matches_config(settings: Settings) -> None:
    """The committed state seed loads cleanly with the real config."""
    store = SeenStore.load(settings.state_path, max_stored=settings.behaviour.max_stored_ids)
    assert store.is_empty or len(store) > 0
