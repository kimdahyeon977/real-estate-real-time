from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Listing:
    source: str
    article_id: str
    title: str
    trade_type: str
    price: int
    rent: int | None
    area_m2: float | None
    floor: str | None
    address: str
    url: str
    agent: str | None
    posted_at: datetime | None
    raw: dict

