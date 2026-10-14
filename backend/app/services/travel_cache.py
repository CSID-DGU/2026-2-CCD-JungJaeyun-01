"""이동시간 SQLite 캐시. 같은 (출발지, 역) 조합은 외부 API를 다시 호출하지 않는다.

캐시 키: (source, 출발지 위도·경도를 소수점 4자리로 반올림한 값, 역 id)
소수점 4자리 ≈ 11m 정밀도라 같은 장소에서의 미세한 좌표 차이는 같은 키가 된다.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.geo import Coord
from app.services.travel_time import TravelTimeService
from app.stations import Station

_SCHEMA = """
CREATE TABLE IF NOT EXISTS travel_time (
    source      TEXT NOT NULL,
    origin_lat  TEXT NOT NULL,
    origin_lng  TEXT NOT NULL,
    station_id  TEXT NOT NULL,
    minutes     REAL NOT NULL,
    created_at  TEXT NOT NULL,
    PRIMARY KEY (source, origin_lat, origin_lng, station_id)
)
"""


def cache_key(origin: Coord) -> tuple[str, str]:
    return f"{origin.lat:.4f}", f"{origin.lng:.4f}"


class TravelTimeCache:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def get(self, source: str, origin: Coord, station_id: str) -> float | None:
        lat, lng = cache_key(origin)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT minutes FROM travel_time "
                "WHERE source = ? AND origin_lat = ? AND origin_lng = ? AND station_id = ?",
                (source, lat, lng, station_id),
            ).fetchone()
        return row[0] if row else None

    def set(self, source: str, origin: Coord, station_id: str, minutes: float) -> None:
        lat, lng = cache_key(origin)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO travel_time VALUES (?, ?, ?, ?, ?, ?)",
                (source, lat, lng, station_id, minutes, datetime.now(timezone.utc).isoformat()),
            )

    def count(self, source: str) -> int:
        with self._connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM travel_time WHERE source = ?", (source,)
            ).fetchone()[0]


class CachedTravelTimeService(TravelTimeService):
    """다른 TravelTimeService를 감싸 결과를 캐시한다. 실패(None)는 캐시하지 않는다."""

    def __init__(self, inner: TravelTimeService, cache: TravelTimeCache):
        self.inner = inner
        self.cache = cache
        self.source = inner.source
        self.hits = 0
        self.misses = 0

    def is_cached(self, origin: Coord, station: Station) -> bool:
        return self.cache.get(self.source, origin, station.id) is not None

    def get_minutes(self, origin: Coord, station: Station) -> float | None:
        cached = self.cache.get(self.source, origin, station.id)
        if cached is not None:
            self.hits += 1
            return cached
        self.misses += 1
        minutes = self.inner.get_minutes(origin, station)
        if minutes is not None:
            self.cache.set(self.source, origin, station.id, minutes)
        return minutes
