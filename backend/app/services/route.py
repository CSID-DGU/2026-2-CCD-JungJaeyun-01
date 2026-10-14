"""대중교통 경로 모델과 ODsay searchPubTransPathT 응답 파서.

ODsay 응답에서 이미 받은 subPath / passStopList를 그대로 재사용한다 (추가 API 호출 없음).
- trafficType 1 = 지하철, 2 = 버스, 3 = 도보
- 도보 구간에는 좌표가 없어서 앞뒤 구간의 끝점/시작점(또는 출발지·도착역)으로 선을 잇는다.
- 지하철·버스 구간은 passStopList.stations의 정류장 좌표(x=경도, y=위도)를 이어서 그린다.
"""

import logging
import re
from dataclasses import asdict, dataclass

from app.geo import Coord

logger = logging.getLogger(__name__)

SUBWAY, BUS, WALK = "subway", "bus", "walk"

# 노선 색 (수도권). 없으면 None → 화면에서 참여자 색을 쓴다.
SUBWAY_COLORS = [
    ("1호선", "#0052A4"), ("2호선", "#00A84D"), ("3호선", "#EF7C1C"), ("4호선", "#00A5DE"),
    ("5호선", "#996CAC"), ("6호선", "#CD7C2F"), ("7호선", "#747F00"), ("8호선", "#E6186C"),
    ("9호선", "#BDB092"), ("신분당", "#D4003B"), ("수인분당", "#F5A200"), ("분당", "#F5A200"),
    ("경의중앙", "#77C4A3"), ("공항철도", "#0090D2"), ("경춘", "#0C8E72"), ("우이신설", "#B0CE18"),
    ("신림", "#6789CA"), ("경강", "#0054A6"), ("서해", "#81A914"), ("GTX-A", "#9A6292"),
    ("의정부", "#FDA600"), ("용인", "#44A41D"), ("김포", "#A17800"),
]
# ODsay 버스 type → 서울 버스 색
BUS_COLORS = {11: "#3D5BAB", 12: "#5BB025", 13: "#F2B70A", 14: "#E60012", 3: "#53B332", 15: "#D6001C"}


@dataclass(frozen=True)
class RouteLeg:
    kind: str                   # walk | subway | bus
    minutes: int
    distance_m: int
    label: str | None           # "6호선", "472번"
    color: str | None
    from_name: str | None
    to_name: str | None
    stop_count: int | None
    path: tuple[Coord, ...]     # 지도에 그릴 좌표 (출발 → 도착 순)


@dataclass(frozen=True)
class Route:
    total_minutes: int
    transfers: int
    legs: tuple[RouteLeg, ...]


def route_to_dict(route: Route) -> dict:
    return asdict(route)


def route_from_dict(d: dict) -> Route:
    legs = tuple(
        RouteLeg(**{**leg, "path": tuple(Coord(**p) for p in leg["path"])}) for leg in d["legs"]
    )
    return Route(total_minutes=d["total_minutes"], transfers=d["transfers"], legs=legs)


def walking_route(origin: Coord, destination: Coord, minutes: float, distance_m: float) -> Route:
    """출발지와 역이 가까워 ODsay가 경로 대신 '도보 거리' 응답을 줄 때의 단일 도보 구간."""
    leg = RouteLeg(WALK, max(1, round(minutes)), round(distance_m), None, None, None, None, None,
                   (origin, destination))
    return Route(total_minutes=leg.minutes, transfers=0, legs=(leg,))


def _subway_label(name: str) -> tuple[str, str | None]:
    """("수도권 6호선") → ("6호선", 색). 수도권이 아닌 노선은 색 없음."""
    short = re.sub(r"^(수도권|서울|인천|부산|대구|광주|대전)\s*", "", name).strip()
    if name.startswith("수도권"):
        for key, color in SUBWAY_COLORS:
            if key in short:
                return short, color
    return short, None


def _coord(x: str | float, y: str | float) -> Coord:
    return Coord(lat=float(y), lng=float(x))


def parse_odsay_route(path: dict, origin: Coord, destination: Coord) -> Route | None:
    """ODsay path 하나를 Route로 변환한다. 형식이 예상과 다르면 None (호출자는 경로 없이 진행)."""
    try:
        subs = path["subPath"]
        legs: list[RouteLeg] = []
        cursor = origin
        for i, sp in enumerate(subs):
            kind_code = sp["trafficType"]
            if kind_code == 3:
                nxt = next((s for s in subs[i + 1:] if s["trafficType"] in (1, 2)), None)
                end = _coord(nxt["startX"], nxt["startY"]) if nxt else destination
                minutes, dist = int(sp.get("sectionTime", 0)), int(sp.get("distance", 0))
                if minutes > 0 or dist > 0:  # 같은 역 안 환승처럼 0분·0m인 도보는 생략
                    legs.append(RouteLeg(WALK, minutes, dist, None, None, None, None, None, (cursor, end)))
                cursor = end
                continue

            stations = (sp.get("passStopList") or {}).get("stations") or []
            points = tuple(_coord(s["x"], s["y"]) for s in stations)
            if len(points) < 2:
                points = (_coord(sp["startX"], sp["startY"]), _coord(sp["endX"], sp["endY"]))
            lane = (sp.get("lane") or [{}])[0]
            if kind_code == 1:
                kind = SUBWAY
                label, color = _subway_label(lane.get("name", ""))
                label = label or None
            else:
                kind = BUS
                label = f"{lane['busNo']}번" if lane.get("busNo") else None
                color = BUS_COLORS.get(lane.get("type"))
            legs.append(RouteLeg(
                kind, int(sp.get("sectionTime", 0)), int(sp.get("distance", 0)), label, color,
                sp.get("startName"), sp.get("endName"), sp.get("stationCount"), points,
            ))
            cursor = points[-1]

        transit = sum(1 for leg in legs if leg.kind != WALK)
        if not legs or transit == 0:
            return None
        return Route(total_minutes=int(path["info"]["totalTime"]), transfers=max(0, transit - 1),
                     legs=tuple(legs))
    except (KeyError, TypeError, ValueError, IndexError) as e:
        logger.warning("ODsay 경로 파싱 실패: %s", type(e).__name__)
        return None
