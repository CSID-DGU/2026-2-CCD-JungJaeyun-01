"""이동시간 SQLite 캐시. 같은 (출발지, 역) 조합은 외부 API를 다시 호출하지 않는다.

캐시 키: (source, 출발지 위도·경도를 소수점 4자리로 반올림한 값, 역 id)
소수점 4자리 ≈ 11m 정밀도라 같은 장소에서의 미세한 좌표 차이는 같은 키가 된다.

이동시간과 함께 지도에 그릴 경로(route_json)도 저장한다.
route_json 값: NULL = 경로 저장 기능 도입 전 행(경로를 아직 모름), 'null' = 조회했지만 경로 상세 없음.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.geo import Coord
from app.services.route import Route, route_from_dict, route_to_dict
from app.services.travel_time import TravelResult, TravelTimeService
from app.stations import Station

_SCHEMA = """
CREATE TABLE IF NOT EXISTS travel_time (
    source      TEXT NOT NULL,
    origin_lat  TEXT NOT NULL,
    origin_lng  TEXT NOT NULL,
    station_id  TEXT NOT NULL,
    minutes     REAL NOT NULL,
    created_at  TEXT NOT NULL,
    route_json  TEXT,
    PRIMARY KEY (source, origin_lat, origin_lng, station_id)
)
"""


def cache_key(origin: Coord) -> tuple[str, str]:
    return f"{origin.lat:.4f}", f"{origin.lng:.4f}"


@dataclass(frozen=True)
class CacheEntry:
    minutes: float
    route: Route | None
    route_known: bool  # False: 경로 저장 도입 전에 저장된 행


class TravelTimeCache:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(_SCHEMA)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(travel_time)")}
            if "route_json" not in columns:  # 이전 버전 DB 마이그레이션
                conn.execute("ALTER TABLE travel_time ADD COLUMN route_json TEXT")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def get_entry(self, source: str, origin: Coord, station_id: str) -> CacheEntry | None:
        lat, lng = cache_key(origin)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT minutes, route_json FROM travel_time "
                "WHERE source = ? AND origin_lat = ? AND origin_lng = ? AND station_id = ?",
                (source, lat, lng, station_id),
            ).fetchone()
        if row is None:
            return None
        minutes, raw = row
        if raw is None:
            return CacheEntry(minutes, None, route_known=False)
        data = json.loads(raw)
        return CacheEntry(minutes, route_from_dict(data) if data else None, route_known=True)

    def get(self, source: str, origin: Coord, station_id: str) -> float | None:
        entry = self.get_entry(source, origin, station_id)
        return entry.minutes if entry else None

    def set(self, source: str, origin: Coord, station_id: str, minutes: float,
            route: Route | None = None) -> None:
        lat, lng = cache_key(origin)
        route_json = json.dumps(route_to_dict(route) if route else None, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO travel_time VALUES (?, ?, ?, ?, ?, ?, ?)",
                (source, lat, lng, station_id, minutes, datetime.now(timezone.utc).isoformat(), route_json),
            )

    def count(self, source: str) -> int:
        with self._connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM travel_time WHERE source = ?", (source,)
            ).fetchone()[0]


class CachedTravelTimeService(TravelTimeService):
    """다른 TravelTimeService를 감싸 결과를 캐시한다. 실패는 캐시하지 않는다."""

    def __init__(self, inner: TravelTimeService, cache: TravelTimeCache):
        self.inner = inner
        self.cache = cache
        self.source = inner.source
        self.hits = 0
        self.misses = 0
        self.route_backfills = 0  # 경로 저장 도입 전 행에 경로를 채우려고 API를 다시 부른 횟수

    def is_cached(self, origin: Coord, station: Station) -> bool:
        return self.cache.get(self.source, origin, station.id) is not None

    def _fetch_and_store(self, origin: Coord, station: Station) -> TravelResult:
        result = self.inner.fetch(origin, station)  # 실패(TravelTimeUnavailable)는 전파 → 캐시 안 함
        self.cache.set(self.source, origin, station.id, result.minutes, result.route)
        return result

    def get_minutes(self, origin: Coord, station: Station) -> float:
        entry = self.cache.get_entry(self.source, origin, station.id)
        if entry is not None:
            self.hits += 1
            return entry.minutes
        self.misses += 1
        return self._fetch_and_store(origin, station).minutes

    def fetch(self, origin: Coord, station: Station) -> TravelResult:
        entry = self.cache.get_entry(self.source, origin, station.id)
        if entry is not None and entry.route_known:
            self.hits += 1
            return TravelResult(entry.minutes, entry.route)
        self.misses += 1
        return self._fetch_and_store(origin, station)

    def get_route(self, origin: Coord, station: Station) -> Route | None:
        entry = self.cache.get_entry(self.source, origin, station.id)
        if entry is not None and entry.route_known:
            return entry.route  # 저장된 경로를 그대로 쓴다 (API 호출 없음)
        # 경로 저장 도입 전에 저장된 행: 추천 요청 중 상위 지역에 한해 한 번만 채운다.
        self.route_backfills += 1
        return self._fetch_and_store(origin, station).route
