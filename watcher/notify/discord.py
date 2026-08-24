from __future__ import annotations

import time
from collections.abc import Iterable

import requests

from ..models import Listing


class DiscordNotifier:
    def __init__(self, webhook_url: str, timeout: float = 10.0) -> None:
        self.webhook_url = webhook_url
        self.timeout = timeout
        self.session = requests.Session()

    @staticmethod
    def _embed(listing: Listing, price_changed: bool = False) -> dict:
        price = f"{listing.price:,}만원"
        if listing.rent is not None:
            price += f" / 월 {listing.rent:,}만원"
        fields = [
            {"name": "거래/가격", "value": f"{listing.trade_type} · {price}", "inline": True},
            {"name": "면적/층", "value": f"{listing.area_m2 or '-'}㎡ · {listing.floor or '-'}", "inline": True},
            {"name": "주소", "value": listing.address or "-", "inline": False},
        ]
        return {
            "title": ("가격 변동 · " if price_changed else "신규 · ") + listing.title,
            "url": listing.url,
            "color": 0xF39C12 if price_changed else 0x2ECC71,
            "fields": fields,
            "footer": {"text": f"{listing.source} · {listing.article_id}"},
        }

    def _post(self, payload: dict) -> None:
        for attempt in range(4):
            response = self.session.post(self.webhook_url, json=payload, timeout=self.timeout)
            if response.status_code != 429:
                response.raise_for_status()
                return
            try:
                retry_after = float(response.json().get("retry_after", 1))
            except (ValueError, TypeError):
                retry_after = float(response.headers.get("Retry-After", 1))
            # Discord JSON uses seconds (occasionally fractional). A very large
            # value is defensively interpreted as milliseconds.
            if retry_after > 100:
                retry_after /= 1000
            time.sleep(max(retry_after, 0.05))
        raise RuntimeError("Discord webhook remained rate limited after retries")

    def send_listings(self, listings: Iterable[Listing], price_changed: bool = False) -> None:
        embeds = [self._embed(item, price_changed) for item in listings]
        # Discord accepts at most 10 embeds per webhook request. Bundling also
        # keeps bursts comfortably below the per-webhook request rate limit.
        for offset in range(0, len(embeds), 10):
            self._post({"embeds": embeds[offset : offset + 10]})

    def send_alert(self, title: str, description: str) -> None:
        self._post({"embeds": [{"title": title, "description": description, "color": 0xE74C3C}]})

    def send_test(self) -> None:
        self._post({"embeds": [{"title": "Realty Watch 테스트", "description": "Discord 알림 경로가 정상입니다.", "color": 0x3498DB}]})

