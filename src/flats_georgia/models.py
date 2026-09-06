"""The ``Listing`` value object and normalization from MyHome's wire formats.

Everything downstream of ``sources/`` works on ``Listing`` and never touches raw
MyHome dicts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

_LAST_UPDATED_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass(frozen=True, slots=True)
class Listing:
    id: int
    url: str
    title: str
    price_usd: int | None
    price_gel: int | None
    area_m2: float | None
    rooms: str | None
    bedrooms: str | None
    floor: int | None
    total_floors: int | None
    area_name: str
    district: str
    metro_station_id: int | None
    posted_at: datetime | None
    is_agency: bool


def _as_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return None


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _as_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _price_total(price: object, currency_key: str) -> int | None:
    if not isinstance(price, dict):
        return None
    bucket = price.get(currency_key)
    if not isinstance(bucket, dict):
        return None
    return _as_int(bucket.get("price_total"))


def _parse_posted_at(raw: object, tz: ZoneInfo) -> datetime | None:
    text = _as_str(raw)
    if text is None:
        return None
    try:
        return datetime.strptime(text, _LAST_UPDATED_FORMAT).replace(tzinfo=tz)
    except ValueError:
        return None


def normalize_api(
    raw: dict[str, object],
    *,
    listing_url_template: str,
    tz: ZoneInfo,
) -> Listing:
    """Map one raw MyHome statement dict (API or embedded page JSON) to ``Listing``.

    Raises ``ValueError`` if the record has no usable integer ``id``.
    """
    listing_id = _as_int(raw.get("id"))
    if listing_id is None:
        raise ValueError(f"listing record has no usable id: {raw.get('id')!r}")

    user_type = raw.get("user_type")
    user_type_value = user_type.get("type") if isinstance(user_type, dict) else None
    is_agency = _as_str(user_type_value) not in (None, "physical")

    return Listing(
        id=listing_id,
        url=listing_url_template.format(id=listing_id),
        title=_as_str(raw.get("dynamic_title")) or f"Listing {listing_id}",
        price_usd=_price_total(raw.get("price"), "2"),
        price_gel=_price_total(raw.get("price"), "1"),
        area_m2=_as_float(raw.get("area")),
        rooms=_as_str(raw.get("room")),
        bedrooms=_as_str(raw.get("bedroom")),
        floor=_as_int(raw.get("floor")),
        total_floors=_as_int(raw.get("total_floors")),
        area_name=_as_str(raw.get("urban_name")) or "",
        district=_as_str(raw.get("district_name")) or "",
        metro_station_id=_as_int(raw.get("metro_station_id")),
        posted_at=_parse_posted_at(raw.get("last_updated"), tz),
        is_agency=is_agency,
    )
