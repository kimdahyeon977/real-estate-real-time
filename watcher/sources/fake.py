from __future__ import annotations

from datetime import UTC, datetime

from ..config import WatchConfig
from ..models import Listing
from .base import Source


class FakeSource(Source):
    def fetch(self, watch: WatchConfig) -> list[Listing]:
        return [
            Listing("fake", "fake-001", "정자동 역세권 전세", "전세", 55000, None, 84.9, "8/20", "성남시 분당구 정자동", "https://example.invalid/fake-001", "가짜중개", datetime.now(UTC), {"price": 55000}),
            Listing("fake", "fake-002", "서현동 월세", "월세", 5000, 120, 59.8, "5/15", "성남시 분당구 서현동", "https://example.invalid/fake-002", None, datetime.now(UTC), {"price": 5000, "rent": 120}),
            Listing("fake", "fake-filtered", "반지하 전세", "전세", 20000, None, 45.0, "B1/4", "성남시 분당구", "https://example.invalid/fake-filtered", None, datetime.now(UTC), {"price": 20000}),
        ]
