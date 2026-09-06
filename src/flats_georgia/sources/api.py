"""Primary source: MyHome's internal JSON API (``api-statements.tnet.ge/v1/statements``)."""

from __future__ import annotations

import time
from collections.abc import Callable
from zoneinfo import ZoneInfo

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from flats_georgia.config import Settings
from flats_georgia.models import Listing, normalize_api
from flats_georgia.sources import SourceError

_TIMEOUT = httpx.Timeout(15.0)


class _Retryable(Exception):
    """Transient failure worth retrying (network blip, 5xx, 429)."""


def _headers(settings: Settings) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "X-Website-Key": settings.source.website_key,
        "locale": "en",
        "User-Agent": settings.source.user_agent,
    }


@retry(
    reraise=True,
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1, max=10),
    retry=retry_if_exception_type(_Retryable),
)
def _get_page(
    client: httpx.Client,
    url: str,
    params: list[tuple[str, str]],
    headers: dict[str, str],
    page: int,
) -> list[dict[str, object]]:
    try:
        resp = client.get(
            url,
            params=[*params, ("page", str(page))],
            headers=headers,
            timeout=_TIMEOUT,
        )
    except (httpx.TransportError, httpx.TimeoutException) as exc:
        raise _Retryable(str(exc)) from exc

    if resp.status_code == 429 or resp.status_code >= 500:
        raise _Retryable(f"HTTP {resp.status_code}")
    if resp.status_code != 200:
        raise SourceError(f"MyHome API returned HTTP {resp.status_code} for page {page}")

    try:
        body = resp.json()
    except ValueError as exc:
        raise SourceError("MyHome API returned a non-JSON body") from exc

    if not isinstance(body, dict) or body.get("result") is not True:
        raise SourceError(f"MyHome API result not ok: {str(body)[:200]}")

    data = body.get("data")
    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise SourceError("MyHome API response missing data.data list")

    return [item for item in items if isinstance(item, dict)]


def fetch_listings(
    settings: Settings,
    *,
    client: httpx.Client | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Listing]:
    """Fetch every matching listing, paging until an empty page or the page cap.

    Raises ``SourceError`` on an unrecoverable failure.
    """
    tz = ZoneInfo(settings.behaviour.timezone)
    headers = _headers(settings)
    params = settings.filter.as_query_params()
    template = settings.source.listing_url_template

    owns_client = client is None
    active = client or httpx.Client()
    listings: list[Listing] = []
    seen: set[int] = set()
    try:
        for page in range(1, settings.behaviour.max_pages_per_run + 1):
            if page > 1:
                sleep(settings.behaviour.request_delay_seconds)
            try:
                rows = _get_page(active, settings.source.api_url, params, headers, page)
            except _Retryable as exc:
                raise SourceError(f"MyHome API kept failing: {exc}") from exc
            if not rows:
                break
            for row in rows:
                try:
                    listing = normalize_api(row, listing_url_template=template, tz=tz)
                except ValueError:
                    continue
                if listing.id in seen:
                    continue
                seen.add(listing.id)
                listings.append(listing)
    finally:
        if owns_client:
            active.close()
    return listings
