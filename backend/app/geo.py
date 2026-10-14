"""좌표 계산 유틸 (순수 함수)."""

import math
from dataclasses import dataclass
from typing import Sequence

EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class Coord:
    lat: float
    lng: float


def haversine_km(a: Coord, b: Coord) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (a.lat, a.lng, b.lat, b.lng))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def centroid(coords: Sequence[Coord]) -> Coord:
    """출발지 좌표의 산술 평균. 수도권 범위에서는 구면 보정 없이 충분히 정확하다."""
    if not coords:
        raise ValueError("좌표가 비어 있습니다.")
    return Coord(
        lat=sum(c.lat for c in coords) / len(coords),
        lng=sum(c.lng for c in coords) / len(coords),
    )
