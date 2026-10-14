"""후보 지역(지하철역) 데이터. 원본은 scripts/fetch_stations.py로 생성한 data/stations.json."""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Sequence

from app.geo import Coord, haversine_km

STATIONS_PATH = Path(__file__).resolve().parents[1] / "data" / "stations.json"


@dataclass(frozen=True)
class Station:
    id: str
    name: str
    coord: Coord
    lines: tuple[str, ...] = ()
    address: str = ""


@lru_cache
def load_stations(path: Path = STATIONS_PATH) -> tuple[Station, ...]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return tuple(
        Station(
            id=s["id"],
            name=s["name"],
            coord=Coord(lat=s["lat"], lng=s["lng"]),
            lines=tuple(s.get("lines", [])),
            address=s.get("address", ""),
        )
        for s in raw
    )


def nearest_stations(stations: Sequence[Station], center: Coord, k: int) -> list[Station]:
    """center에서 가까운 순으로 k개. 거리가 같으면 id 순으로 정렬해 결과를 고정한다."""
    if k <= 0:
        raise ValueError("k는 1 이상이어야 합니다.")
    return sorted(stations, key=lambda s: (haversine_km(center, s.coord), s.id))[:k]
