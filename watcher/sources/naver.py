from __future__ import annotations

import time
from datetime import datetime

from ..config import WatchConfig
from ..models import Listing
from .base import Source
from .http import BrowserLikeClient

# Verified against fin.land.naver.com's shipped request schemas (zod, bundled in
# the client JS). new.land.naver.com is rate-limited per source IP and returns a
# blanket HTTP 429 from datacenter ranges, so fin.land is the endpoint used here.
FRONT_API = "https://fin.land.naver.com/front-api/v1"
COMPLEX_LIST_BY_CORTAR = "https://m.land.naver.com/complex/ajax/complexListByCortarNo"
ARTICLE_URL = "https://fin.land.naver.com/articles/{article_number}"

TRADE_TYPES = {"매매": "A1", "전세": "B1", "월세": "B2", "단기임대": "B3"}
TRADE_TYPE_NAMES = {code: name for name, code in TRADE_TYPES.items()}
REAL_ESTATE_TYPES = {"아파트": "A01", "오피스텔": "A02", "재건축": "A04"}

# fin.land's articlePagingRequest schema: size is required and capped at 30.
PAGE_SIZE = 30
# 목록은 반드시 끝까지 훑는다. 중간에 끊으면 매 사이클 다른 표본을 보게 되어
# 오래된 매물이 가짜 신규로 잡힌다(대단지는 1,000건이 넘는다). 이 값은 폭주
# 방지용 안전판이지 정상 동작 시의 상한이 아니다.
MAX_PAGES_HARD = 80
# 가격 변동은 매물 수를 바꾸지 않으므로, 카운트가 그대로여도 가끔은 전량을 다시 읽는다.
DEFAULT_FULL_REFRESH_SECONDS = 900


class NaverSource(Source):
    """네이버 부동산(fin.land) 신규 매물 조회.

    감시 단위는 단지(complexNumber)다. `complex_numbers`를 직접 주거나,
    `cortar_no`(법정동코드)를 주면 해당 동의 단지 목록을 먼저 조회해 순회한다.
    정렬은 DATE_DESC 고정이되, 동점 정렬이 흔들려 오탐이 나므로 커서로 전량을 훑는다.
    """

    def __init__(self) -> None:
        self.client = BrowserLikeClient(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "ko-KR,ko;q=0.9",
                "Origin": "https://fin.land.naver.com",
                "Referer": "https://fin.land.naver.com/",
            },
            timeout=15.0,
        )
        self._primed = False
        # complexNumber -> (마지막으로 본 매물 수, 마지막 전량 조회 시각)
        self._complex_state: dict[int, tuple[tuple[int, ...], float]] = {}

    def _complex_numbers(self, watch: WatchConfig) -> list[int]:
        configured = watch.options.get("complex_numbers")
        if configured:
            return [int(number) for number in configured]
        cortar_no = str(watch.options["cortar_no"])
        payload = self.client.get_json(COMPLEX_LIST_BY_CORTAR, {"cortarNo": cortar_no})
        wanted = {
            REAL_ESTATE_TYPES[name]
            for name in watch.options.get("real_estate_types", [])
            if name in REAL_ESTATE_TYPES
        }
        numbers = []
        for complex_info in payload.get("result") or []:
            if wanted and complex_info.get("hscpTypeCd") not in wanted:
                continue
            numbers.append(int(complex_info["hscpNo"]))
        return numbers

    def _ensure_primed(self, complex_number: int) -> None:
        """API는 페이지 방문으로 발급되는 쿠키가 없으면 429를 준다. 첫 호출 전에 받아둔다."""
        if self._primed:
            return
        self.client.prime(f"https://fin.land.naver.com/complexes/{complex_number}?tab=article")
        self._primed = True

    def _counts(self, complex_number: int) -> tuple[int, ...]:
        self._ensure_primed(complex_number)
        body = self.client.get_json(
            f"{FRONT_API}/complex/article/count", {"complexNumber": complex_number}
        )
        result = body.get("result") or {}
        return tuple(
            int(result.get(key) or 0)
            for key in ("dealCount", "leaseDepositCount", "leaseMonthlyCount", "leaseShortTerm")
        )

    def _articles(self, complex_number: int, trade_codes: list[str]) -> list[dict]:
        self._ensure_primed(complex_number)
        entries: list[dict] = []
        seed: str | None = None
        last_info: list = []
        # 등록일이 같은 매물끼리는 정렬 순서가 요청마다 흔들린다. 서버가 준
        # seed/lastInfo 커서를 그대로 물려 마지막 페이지까지 이어 읽는다.
        for _ in range(MAX_PAGES_HARD):
            payload = {
                "complexNumber": complex_number,
                "tradeTypes": trade_codes,
                "size": PAGE_SIZE,
                "userChannelType": "PC",
                "articleSortType": "DATE_DESC",
            }
            if seed is not None:
                payload["seed"] = seed
                payload["lastInfo"] = last_info
            body = self.client.post_json(f"{FRONT_API}/complex/article/list", payload)
            if not body.get("isSuccess"):
                raise RuntimeError(f"naver article list failed: {body.get('detailCode')}")
            result = body.get("result") or {}
            entries.extend(result.get("list") or [])
            if not result.get("hasNextPage"):
                break
            seed, last_info = result.get("seed"), result.get("lastInfo") or []
        return entries

    def fetch(self, watch: WatchConfig) -> list[Listing]:
        trade_codes = [
            TRADE_TYPES[name] for name in watch.options.get("trade_types", []) if name in TRADE_TYPES
        ] or list(TRADE_TYPES.values())
        refresh_after = float(
            watch.options.get("full_refresh_seconds", DEFAULT_FULL_REFRESH_SECONDS)
        )
        listings: dict[str, Listing] = {}
        for complex_number in self._complex_numbers(watch):
            # 대단지는 전량 조회가 40페이지에 달한다. 매물 수가 그대로면 요청 한 번으로
            # 건너뛰고, 가격 변동을 놓치지 않도록 주기적으로는 강제로 다시 읽는다.
            counts = self._counts(complex_number)
            seen_counts, refreshed_at = self._complex_state.get(complex_number, (None, 0.0))
            if counts == seen_counts and time.monotonic() - refreshed_at < refresh_after:
                continue
            self._complex_state[complex_number] = (counts, time.monotonic())
            for entry in self._articles(complex_number, trade_codes):
                article = entry.get("representativeArticleInfo")
                if article:
                    listing = _to_listing(article)
                    listings[listing.article_id] = listing
        return list(listings.values())


def _price_manwon(price_info: dict, key: str) -> int:
    """네이버는 가격을 원 단위로 준다. 만원 단위로 정규화한다."""
    return int(price_info.get(key) or 0) // 10000


def _posted_at(article: dict) -> datetime | None:
    verification = article.get("verificationInfo") or {}
    raw = verification.get("exposureStartDate") or verification.get("articleConfirmDate")
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return None


def _to_listing(article: dict) -> Listing:
    price_info = article.get("priceInfo") or {}
    space = article.get("spaceInfo") or {}
    detail = article.get("articleDetail") or {}
    broker = article.get("brokerInfo") or {}
    address = article.get("address") or {}
    trade_code = article.get("tradeType", "")

    # 매매는 매매가, 전월세는 보증금이 기준가. 월세만 rent에 따로 담는다.
    deposit = _price_manwon(price_info, "dealPrice" if trade_code == "A1" else "warrantyPrice")
    rent = _price_manwon(price_info, "rentPrice") or None

    return Listing(
        source="naver",
        article_id=str(article["articleNumber"]),
        title=" ".join(
            part
            for part in (
                article.get("complexName"),
                space.get("supplySpaceName"),
                detail.get("articleFeatureDescription"),
            )
            if part
        ),
        trade_type=TRADE_TYPE_NAMES.get(trade_code, trade_code),
        price=deposit,
        rent=rent,
        area_m2=space.get("exclusiveSpace"),
        floor=detail.get("floorInfo"),
        address=" ".join(
            part
            for part in (address.get("city"), address.get("division"), address.get("sector"))
            if part
        ),
        url=ARTICLE_URL.format(article_number=article["articleNumber"]),
        agent=broker.get("brokerageName"),
        posted_at=_posted_at(article),
        raw=article,
    )
