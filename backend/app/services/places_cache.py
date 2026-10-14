"""장소 검색 결과, 구글 평점, 구글 일일 호출 수를 저장하는 SQLite 캐시."""

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS kakao_places (
    station_id    TEXT NOT NULL,
    category_code TEXT NOT NULL,
    radius_m      INTEGER NOT NULL,
    max_results   INTEGER NOT NULL,
    places_json   TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    PRIMARY KEY (station_id, category_code, radius_m, max_results)
);
CREATE TABLE IF NOT EXISTS google_ratings (
    place_id     TEXT PRIMARY KEY,   -- 카카오 장소 id
    rating       REAL,               -- NULL = 구글에서 찾지 못함/평점 없음 (이것도 캐시)
    review_count INTEGER,
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS google_usage (
    day   TEXT PRIMARY KEY,
    count INTEGER NOT NULL
);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fresh(created_at: str, max_age_days: int) -> bool:
    return _now() - datetime.fromisoformat(created_at) <= timedelta(days=max_age_days)


class PlacesCache:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    # --- 카카오 장소 검색 -------------------------------------------------
    def get_places(self, station_id: str, category_code: str, radius_m: int,
                   max_results: int, max_age_days: int) -> list[dict] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT places_json, created_at FROM kakao_places "
                "WHERE station_id = ? AND category_code = ? AND radius_m = ? AND max_results = ?",
                (station_id, category_code, radius_m, max_results),
            ).fetchone()
        if row is None or not _fresh(row[1], max_age_days):
            return None
        return json.loads(row[0])

    def set_places(self, station_id: str, category_code: str, radius_m: int,
                   max_results: int, places: list[dict]) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO kakao_places VALUES (?, ?, ?, ?, ?, ?)",
                (station_id, category_code, radius_m, max_results,
                 json.dumps(places, ensure_ascii=False), _now().isoformat()),
            )

    # --- 구글 평점 --------------------------------------------------------
    def get_rating(self, place_id: str, max_age_days: int) -> tuple[float | None, int | None] | None:
        """캐시 적중이면 (rating, review_count) — 둘 다 None이면 '찾지 못함'. 미적중/만료는 None."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT rating, review_count, created_at FROM google_ratings WHERE place_id = ?",
                (place_id,),
            ).fetchone()
        if row is None or not _fresh(row[2], max_age_days):
            return None
        return row[0], row[1]

    def set_rating(self, place_id: str, rating: float | None, review_count: int | None) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO google_ratings VALUES (?, ?, ?, ?)",
                (place_id, rating, review_count, _now().isoformat()),
            )

    # --- 구글 일일 호출 수 -------------------------------------------------
    def usage(self, day: str) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT count FROM google_usage WHERE day = ?", (day,)).fetchone()
        return row[0] if row else 0

    def add_usage(self, day: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO google_usage VALUES (?, 1) "
                "ON CONFLICT(day) DO UPDATE SET count = count + 1",
                (day,),
            )
