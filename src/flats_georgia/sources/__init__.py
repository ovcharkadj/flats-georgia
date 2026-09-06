"""Listing sources for MyHome.ge.

The JSON API is the only source this round (MyHome's web pages 403 non-browser
clients - see SPEC). ``get_listings`` is the single seam callers use, so a
browser-based fallback could be slotted in later without touching them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from flats_georgia.sources.api import SourceError, fetch_listings

if TYPE_CHECKING:
    import httpx

    from flats_georgia.config import Settings
    from flats_georgia.models import Listing

__all__ = ["SourceError", "get_listings"]


def get_listings(
    settings: Settings,
    *,
    client: httpx.Client | None = None,
) -> list[Listing]:
    """Fetch every matching listing from the best available source."""
    return fetch_listings(settings, client=client)
