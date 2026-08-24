from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .models import Listing


class ListingStore:
    def __init__(self, path: str | Path = "watch.db") -> None:
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS seen (
                source TEXT NOT NULL,
                article_id TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                PRIMARY KEY (source, article_id)
            )"""
        )
        self.connection.commit()

    @staticmethod
    def _payload_hash(listing: Listing) -> str:
        # Hash the normalized price fields as well as raw payload so price changes
        # remain detectable even when a source omits them from its raw dictionary.
        payload = {"price": listing.price, "rent": listing.rent, "raw": listing.raw}
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
        return hashlib.sha256(encoded).hexdigest()

    def is_empty(self) -> bool:
        row = self.connection.execute("SELECT 1 FROM seen LIMIT 1").fetchone()
        return row is None

    def mark_and_filter_new(self, listings: list[Listing]) -> tuple[list[Listing], list[Listing]]:
        new: list[Listing] = []
        price_changed: list[Listing] = []
        now = datetime.now(UTC).isoformat()
        with self.connection:
            for listing in listings:
                digest = self._payload_hash(listing)
                row = self.connection.execute(
                    "SELECT payload_hash FROM seen WHERE source=? AND article_id=?",
                    (listing.source, listing.article_id),
                ).fetchone()
                if row is None:
                    new.append(listing)
                    self.connection.execute(
                        "INSERT INTO seen VALUES (?, ?, ?, ?, ?)",
                        (listing.source, listing.article_id, digest, now, now),
                    )
                else:
                    if row[0] != digest:
                        price_changed.append(listing)
                    self.connection.execute(
                        "UPDATE seen SET payload_hash=?, last_seen=? WHERE source=? AND article_id=?",
                        (digest, now, listing.source, listing.article_id),
                    )
        return new, price_changed

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "ListingStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

