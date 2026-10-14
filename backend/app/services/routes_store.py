"""경로 응답 디스크 캐시(SQLite)와 하루 호출 수 집계."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

KST = timezone(timedelta(hours=9))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS route_cache (
    key        TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS route_usage (
    day     TEXT NOT NULL,
    counter TEXT NOT NULL,
    count   INTEGER NOT NULL,
    PRIMARY KEY (day, counter)
);
"""


def today() -> str:
    return datetime.now(KST).date().isoformat()


class RoutesStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def get(self, key: str, ttl_days: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload, created_at FROM route_cache WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        if datetime.now(timezone.utc) - datetime.fromisoformat(row[1]) > timedelta(days=ttl_days):
            return None
        return json.loads(row[0])

    def put(self, key: str, payload: dict) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO route_cache VALUES (?, ?, ?)",
                (key, json.dumps(payload, ensure_ascii=False), datetime.now(timezone.utc).isoformat()),
            )

    def add_usage(self, counter: str, n: int = 1, day: str | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO route_usage VALUES (?, ?, ?) ON CONFLICT(day, counter) DO UPDATE SET count = count + ?",
                (day or today(), counter, n, n),
            )

    def usage(self, day: str | None = None) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute("SELECT counter, count FROM route_usage WHERE day = ?", (day or today(),)).fetchall()
        return dict(rows)
