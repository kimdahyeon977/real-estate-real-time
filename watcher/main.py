from __future__ import annotations

import argparse
import random
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .config import Config, ConfigError, WatchConfig, load_config
from .filters import filter_listings
from .notify.discord import DiscordNotifier
from .sources.base import Source
from .sources.fake import FakeSource
from .sources.karrot import KarrotSource
from .sources.naver import NaverSource
from .store import ListingStore


@dataclass
class SourceState:
    failures: int = 0
    next_attempt: float = 0.0
    deadman_sent: bool = False


SOURCES: dict[str, type[Source]] = {"fake": FakeSource, "naver": NaverSource, "karrot": KarrotSource}
STOP = False


def _stop(*_: object) -> None:
    global STOP
    STOP = True


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="네이버/당근 매물 감시 봇")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--db", default="watch.db")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--source", choices=tuple(SOURCES))
    parser.add_argument("--test-notify", action="store_true")
    return parser


def _selected_watches(config: Config, selected: str | None) -> list[WatchConfig]:
    if selected == "fake":
        watches = [watch for watch in config.watches if watch.source == "fake"]
        return watches or [WatchConfig("fake E2E", "fake", {})]
    return [watch for watch in config.watches if selected is None or watch.source == selected]


def _notify(notifier: DiscordNotifier, listings: list, changed: list, dry_run: bool) -> None:
    if dry_run:
        for label, items in (("NEW", listings), ("PRICE_CHANGED", changed)):
            for item in items:
                print(f"[{label}] {item.source}/{item.article_id} {item.trade_type} {item.price:,}만원 {item.title}")
        return
    notifier.send_listings(listings)
    notifier.send_listings(changed, price_changed=True)


def run_cycle(
    config: Config,
    watches: list[WatchConfig],
    sources: dict[str, Source],
    states: dict[str, SourceState],
    store: ListingStore,
    notifier: DiscordNotifier,
    dry_run: bool,
    initial_empty: bool,
) -> None:
    now = time.monotonic()
    total_new = total_changed = 0
    for watch in watches:
        state = states.setdefault(watch.source, SourceState())
        if now < state.next_attempt:
            continue
        try:
            fetched = sources[watch.source].fetch(watch)
            filtered = filter_listings(fetched, watch)
            new, changed = store.mark_and_filter_new(filtered)
            silent = initial_empty and config.notify.cold_start_silent
            if not silent:
                _notify(notifier, new, changed, dry_run)
            elif new or changed:
                print(f"[COLD_START] {watch.name}: {len(new)}건 기준선 저장 (알림 생략)")
            total_new += len(new)
            total_changed += len(changed)
            state.failures = 0
            state.next_attempt = 0
            state.deadman_sent = False
            print(f"[OK] {watch.name}: fetched={len(fetched)} matched={len(filtered)} new={len(new)} changed={len(changed)}")
        except Exception as exc:  # exception isolation is deliberately per watch/source
            state.failures += 1
            delay = min(config.poll.interval_seconds * (2 ** state.failures), 900)
            state.next_attempt = time.monotonic() + delay
            print(f"[ERROR] {watch.name}: {exc} (failures={state.failures}, backoff={delay}s)", file=sys.stderr)
            if state.failures >= config.notify.deadman_failures and not state.deadman_sent:
                if dry_run:
                    print(f"[DEADMAN] {watch.source}: 연속 {state.failures}회 실패", file=sys.stderr)
                else:
                    try:
                        notifier.send_alert("감시 중단됨", f"{watch.source} 소스가 연속 {state.failures}회 실패했습니다.\n마지막 오류: {exc}")
                    except Exception as notify_exc:
                        print(f"[ERROR] deadman notification failed: {notify_exc}", file=sys.stderr)
                state.deadman_sent = True
    print(f"[SUMMARY] new={total_new} changed={total_changed}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    notifier = DiscordNotifier(config.notify.discord_webhook)
    if args.test_notify:
        try:
            notifier.send_test()
        except Exception as exc:
            print(f"test notification failed: {exc}", file=sys.stderr)
            return 1
        print("test notification sent")
        return 0
    watches = _selected_watches(config, args.source)
    if not watches:
        print("no matching watches configured", file=sys.stderr)
        return 2
    sources = {name: cls() for name, cls in SOURCES.items() if any(w.source == name for w in watches)}
    states: dict[str, SourceState] = {}
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    db_path = Path(args.db)
    with ListingStore(db_path) as store:
        initial_empty = store.is_empty()
        while not STOP:
            run_cycle(config, watches, sources, states, store, notifier, args.dry_run, initial_empty)
            initial_empty = False
            if args.once:
                break
            wait = config.poll.interval_seconds + random.uniform(0, config.poll.jitter_seconds)
            deadline = time.monotonic() + wait
            while not STOP and time.monotonic() < deadline:
                time.sleep(min(0.5, deadline - time.monotonic()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

