from __future__ import annotations

import json
import re
from urllib.parse import quote

from ..config import WatchConfig
from ..models import Listing
from .base import Source
from .http import BrowserLikeClient

# 당근부동산은 Remix SSR이라 별도 JSON API가 노출되지 않는다. 대신 동 지도
# 페이지가 schema.org JSON-LD(`#dong-articles`)로 최신 매물 목록을 실어 보낸다.
MAP_URL = "https://realty.daangn.com/map/{path}"
ARTICLE_URL = "https://realty.daangn.com/articles/{article_id}"
DONG_ARTICLES_ANCHOR = "#dong-articles"

LD_JSON_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
AREA_RE = re.compile(r"([\d.]+)\s*m²")
TRADE_RE = re.compile(r"(매매|전세|월세|단기임대)")
ARTICLE_ID_RE = re.compile(r"/articles/(\d+)")


class KarrotSource(Source):
    """당근부동산 동 단위 신규 매물 조회 (JSON-LD 파싱).

    `region_path`는 지도 페이지 경로 그대로 쓴다. 예: "경기도/안양시 만안구/석수동".
    """

    def __init__(self) -> None:
        self.client = BrowserLikeClient(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ko-KR,ko;q=0.9",
            },
            timeout=20.0,
        )

    @staticmethod
    def _region_paths(watch: WatchConfig) -> list[str]:
        paths = watch.options.get("region_paths")
        if paths:
            return [str(path) for path in paths]
        return [str(watch.options.get("region_path") or watch.options["region_id"])]

    def fetch(self, watch: WatchConfig) -> list[Listing]:
        # 동마다 별도 페이지라 순회한다. 인접 동은 매물이 겹치므로 id로 중복을 없앤다.
        listings: dict[str, Listing] = {}
        for region_path in self._region_paths(watch):
            url = MAP_URL.format(path="/".join(quote(part) for part in region_path.split("/")))
            for item in _dong_articles(self.client.get_text(url)):
                listing = _to_listing(item, region_path)
                if listing is not None:
                    listings.setdefault(listing.article_id, listing)
        return list(listings.values())


def _dong_articles(html: str) -> list[dict]:
    for block in LD_JSON_RE.findall(html):
        try:
            document = json.loads(block)
        except json.JSONDecodeError:
            continue
        for node in document.get("@graph", [document]):
            if node.get("@type") == "ItemList" and str(node.get("@id", "")).endswith(
                DONG_ARTICLES_ANCHOR
            ):
                return node.get("itemListElement") or []
    return []


def _to_manwon(text: str) -> int:
    """'3억 5,000만원' / '8억' / '4,000' 을 만원 단위 정수로 정규화한다."""
    cleaned = text.replace(",", "").strip()
    total = 0
    eok = re.search(r"(\d+)\s*억", cleaned)
    if eok:
        total += int(eok.group(1)) * 10000
        cleaned = cleaned[eok.end() :]
    man = re.search(r"(\d+)", cleaned)
    if man:
        total += int(man.group(1))
    return total


def _split_price(price_text: str) -> tuple[int, int | None]:
    """월세는 '보증금 / 월세', 매매·전세는 단일 금액."""
    if "/" in price_text:
        deposit, _, monthly = price_text.partition("/")
        return _to_manwon(deposit), _to_manwon(monthly) or None
    return _to_manwon(price_text), None


def _to_listing(item: dict, region_path: str) -> Listing | None:
    url = str(item.get("url") or "")
    match = ARTICLE_ID_RE.search(url)
    name = str(item.get("name") or "")
    trade = TRADE_RE.search(name)
    if match is None or trade is None:
        return None

    # "석수동 원룸 월세 1,000 / 50만원 26m² 매물" 에서 거래유형 뒤 금액 구간만 잘라낸다.
    tail = name[trade.end() :].removesuffix("매물").strip()
    area = AREA_RE.search(tail)
    price_text = tail[: area.start()] if area else tail
    deposit, rent = _split_price(price_text)

    return Listing(
        source="karrot",
        article_id=match.group(1),
        title=name.removesuffix("매물").strip(),
        trade_type=trade.group(1),
        price=deposit,
        rent=rent,
        area_m2=float(area.group(1)) if area else None,
        floor=None,
        address=region_path.replace("/", " "),
        url=ARTICLE_URL.format(article_id=match.group(1)),
        agent=None,
        posted_at=None,
        raw=item,
    )
