from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class PollConfig:
    interval_seconds: int
    jitter_seconds: int


@dataclass(frozen=True)
class NotifyConfig:
    discord_webhook: str
    cold_start_silent: bool
    deadman_failures: int


@dataclass(frozen=True)
class WatchConfig:
    name: str
    source: str
    options: dict[str, Any]


@dataclass(frozen=True)
class Config:
    poll: PollConfig
    notify: NotifyConfig
    watches: tuple[WatchConfig, ...]


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{path} must be a mapping")
    return value


def _integer(value: Any, path: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConfigError(f"{path} must be an integer >= {minimum}")
    return value


def load_config(path: str | Path = "config.yaml") -> Config:
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"config not found: {config_path}")
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {config_path}: {exc}") from exc
    root = _mapping(data, "config")
    poll = _mapping(root.get("poll"), "poll")
    notify = _mapping(root.get("notify"), "notify")
    interval = _integer(poll.get("interval_seconds"), "poll.interval_seconds", 30)
    jitter = _integer(poll.get("jitter_seconds", 0), "poll.jitter_seconds")
    webhook = notify.get("discord_webhook")
    if not isinstance(webhook, str) or not webhook.strip():
        raise ConfigError("notify.discord_webhook must be a non-empty string")
    cold_start = notify.get("cold_start_silent", True)
    if not isinstance(cold_start, bool):
        raise ConfigError("notify.cold_start_silent must be a boolean")
    deadman = _integer(notify.get("deadman_failures", 5), "notify.deadman_failures", 1)
    raw_watches = root.get("watches")
    if not isinstance(raw_watches, list) or not raw_watches:
        raise ConfigError("watches must be a non-empty list")
    watches: list[WatchConfig] = []
    for index, raw in enumerate(raw_watches):
        item = _mapping(raw, f"watches[{index}]")
        name, source = item.get("name"), item.get("source")
        if not isinstance(name, str) or not name:
            raise ConfigError(f"watches[{index}].name must be a non-empty string")
        if source not in {"fake", "naver", "karrot"}:
            raise ConfigError(f"watches[{index}].source must be fake, naver, or karrot")
        if source == "naver" and not (item.get("cortar_no") or item.get("complex_numbers")):
            raise ConfigError(f"watches[{index}] requires cortar_no or complex_numbers for naver")
        if source == "karrot" and not (
            item.get("region_paths") or item.get("region_path") or item.get("region_id")
        ):
            raise ConfigError(f"watches[{index}].region_paths is required for karrot")
        watches.append(WatchConfig(name, source, {k: v for k, v in item.items() if k not in {"name", "source"}}))
    return Config(PollConfig(interval, jitter), NotifyConfig(webhook, cold_start, deadman), tuple(watches))

