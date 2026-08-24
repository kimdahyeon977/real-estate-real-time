from __future__ import annotations

from datetime import datetime, timedelta

from .config import WatchConfig
from .models import Listing

# 네이버 부동산 유형 코드 (fin.land 번들에 실린 코드표 기준)
SINGLE_FAMILY_CODES = {"C03", "C04", "C06"}  # 단독주택 / 전원주택 / 한옥

# "층간·벽간 소음이 없을 법한 구조" 판정에 쓰는 표현들.
TOP_FLOOR_WORDS = ("탑층", "최상층", "펜트", "팬트", "옥탑")
DUPLEX_WORDS = ("복층", "메자닌", "다락")
SINGLE_FAMILY_WORDS = ("단독주택", "전원주택", "단독", "주택", "한옥", "타운하우스")


def _text(listing: Listing) -> str:
    return " ".join((listing.title, listing.address, str(listing.raw))).lower()


def _too_old(listing: Listing, max_age_days: object) -> bool:
    """등록된 지 오래된 매물은 신규로 취급하지 않는다.

    매물이 많은 단지는 한 사이클에 전량을 훑지 못해, 목록 꼬리에 있는 오래된
    매물이 요청마다 들락거리며 가짜 '신규'로 잡힌다. 페이징을 늘려도 단지 규모에
    따라 한계가 있어, 등록일로 직접 막는 쪽이 확실하다.
    등록일을 주지 않는 소스(당근)는 이 조건을 건너뛴다.
    """
    if max_age_days is None or listing.posted_at is None:
        return False
    return listing.posted_at < datetime.now() - timedelta(days=int(max_age_days))


def _is_top_floor(listing: Listing) -> bool:
    """해당 층 == 총 층이면 확실한 탑층. 네이버가 '고/15'처럼 층을 뭉개서 줄 때는
    판정이 불가능하므로 매물 설명의 표현에 의존한다."""
    raw = listing.raw if isinstance(listing.raw, dict) else {}
    floor = (raw.get("articleDetail") or {}).get("floorDetailInfo") or {}
    target, total = str(floor.get("targetFloor") or ""), str(floor.get("totalFloor") or "")
    if target.isdigit() and total.isdigit() and int(target) == int(total) > 1:
        return True
    return any(word in _text(listing) for word in TOP_FLOOR_WORDS)


def _is_duplex(listing: Listing) -> bool:
    return any(word in _text(listing) for word in DUPLEX_WORDS)


def _is_single_family(listing: Listing) -> bool:
    raw = listing.raw if isinstance(listing.raw, dict) else {}
    if raw.get("realEstateType") in SINGLE_FAMILY_CODES:
        return True
    return any(word in _text(listing) for word in SINGLE_FAMILY_WORDS)


QUIET_STRUCTURES = {"탑층": _is_top_floor, "복층": _is_duplex, "단독주택": _is_single_family}


def _passes_structure(listing: Listing, required: object) -> bool:
    """요청한 구조 중 하나라도 해당하면 통과. 위아래·옆집 소음을 피하려는 조건이라
    셋 중 무엇이든 만족하면 되는 OR 조건이다."""
    if not required:
        return True
    checks = [QUIET_STRUCTURES[name] for name in required if name in QUIET_STRUCTURES]
    return any(check(listing) for check in checks) if checks else True


def _passes_price(listing: Listing, rules: object) -> bool:
    """거래유형마다 기준이 다르다(전세는 보증금, 월세는 월 임대료). 상한은 '미만'이다."""
    if not isinstance(rules, dict):
        return True
    rule = rules.get(listing.trade_type)
    if not isinstance(rule, dict):
        return True
    if "price_under" in rule and listing.price >= int(rule["price_under"]):
        return False
    if "rent_under" in rule and (listing.rent or 0) >= int(rule["rent_under"]):
        return False
    if "deposit_under" in rule and listing.price >= int(rule["deposit_under"]):
        return False
    return True


def matches(listing: Listing, watch: WatchConfig) -> bool:
    options = watch.options
    if _too_old(listing, options.get("max_age_days")):
        return False
    if options.get("trade_types") and listing.trade_type not in options["trade_types"]:
        return False
    if not _passes_price(listing, options.get("price_rules")):
        return False
    if not _passes_structure(listing, options.get("require_any_of")):
        return False
    if options.get("price_min") is not None and listing.price < int(options["price_min"]):
        return False
    if options.get("price_max") is not None and listing.price > int(options["price_max"]):
        return False
    if options.get("area_min_m2") is not None and (listing.area_m2 is None or listing.area_m2 < float(options["area_min_m2"])):
        return False
    if options.get("area_max_m2") is not None and (listing.area_m2 is None or listing.area_m2 > float(options["area_max_m2"])):
        return False
    excluded = options.get("exclude_keywords", [])
    haystack = _text(listing)
    return not any(str(keyword).lower() in haystack for keyword in excluded)


def filter_listings(listings: list[Listing], watch: WatchConfig) -> list[Listing]:
    return [listing for listing in listings if matches(listing, watch)]
