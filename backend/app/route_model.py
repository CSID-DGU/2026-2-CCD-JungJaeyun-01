"""공통 경로 스키마. 어떤 경로 API(Google, ODsay, 지하철 그래프 추정)를 쓰든 프론트는 이 형식만 본다.

route = {totalMinutes, transfers, segments[{mode, lineName, lineColor, from, to, minutes, path[[lat,lng],...], ...}], source, ...}
- mode: WALK | SUBWAY | BUS
- source: "google" | "estimate" (| "odsay")
- 시각은 모두 KST ISO 8601 문자열("2026-10-17T18:22:00+09:00"). 모르면 null.
"""

from dataclasses import dataclass

WALK, SUBWAY, BUS = "WALK", "SUBWAY", "BUS"

LatLngPair = tuple[float, float]


@dataclass(frozen=True)
class Segment:
    mode: str                       # WALK | SUBWAY | BUS
    line_name: str | None           # "2호선", "741"
    line_color: str | None          # "#35b12b"
    from_name: str | None
    to_name: str | None
    minutes: float
    path: tuple[LatLngPair, ...]    # ((lat, lng), ...)
    # --- 타임라인용 (없으면 None) ---
    distance_m: int | None = None
    departure_time: str | None = None
    arrival_time: str | None = None
    headsign: str | None = None            # "구파발역 방면"
    stop_count: int | None = None          # 정거장(정류장) 수
    line_text_color: str | None = None     # 노선 배지 글자색
    intermediate_stops: tuple[str, ...] | None = None  # 경유 정거장 이름 (출발·도착 제외)
    intermediate_stops_source: str | None = None       # "subway-map": 우리 노선도 데이터로 구한 값
    line_kind: str | None = None                       # 버스 종류 ("간선", "지선", "광역" ...)
    realtime: dict | None = None                       # 실시간 도착 정보를 붙일 때 쓸 승·하차 정류장/노선/방면 참조 (지금은 미사용)


@dataclass(frozen=True)
class Route:
    total_minutes: int
    transfers: int
    segments: tuple[Segment, ...]
    source: str                     # "google" | "estimate" | "odsay"
    departure_time: str | None = None   # 집을 나서는 시각
    arrival_time: str | None = None     # 도착지 도착 시각
    walk_minutes: float | None = None
    walk_meters: int | None = None


def route_to_dict(route: Route) -> dict:
    """API 응답·캐시용 dict (camelCase)."""
    return {
        "totalMinutes": route.total_minutes,
        "transfers": route.transfers,
        "source": route.source,
        "departureTime": route.departure_time,
        "arrivalTime": route.arrival_time,
        "walkMinutes": route.walk_minutes,
        "walkMeters": route.walk_meters,
        "segments": [
            {
                "mode": s.mode, "lineName": s.line_name, "lineColor": s.line_color,
                "from": s.from_name, "to": s.to_name, "minutes": s.minutes,
                "path": [[lat, lng] for lat, lng in s.path],
                "distanceMeters": s.distance_m, "departureTime": s.departure_time, "arrivalTime": s.arrival_time,
                "headsign": s.headsign, "stopCount": s.stop_count, "lineTextColor": s.line_text_color,
                "intermediateStops": list(s.intermediate_stops) if s.intermediate_stops is not None else None,
                "intermediateStopsSource": s.intermediate_stops_source,
                "lineKind": s.line_kind, "realtime": s.realtime,
            }
            for s in route.segments
        ],
    }


def route_from_dict(d: dict) -> Route:
    """캐시에서 읽을 때: 필드가 추가되기 전에 저장된 항목도 읽을 수 있게 .get을 쓴다."""
    return Route(
        total_minutes=d["totalMinutes"], transfers=d["transfers"], source=d["source"],
        departure_time=d.get("departureTime"), arrival_time=d.get("arrivalTime"),
        walk_minutes=d.get("walkMinutes"), walk_meters=d.get("walkMeters"),
        segments=tuple(
            Segment(
                mode=s["mode"], line_name=s["lineName"], line_color=s["lineColor"],
                from_name=s["from"], to_name=s["to"], minutes=s["minutes"],
                path=tuple((p[0], p[1]) for p in s["path"]),
                distance_m=s.get("distanceMeters"), departure_time=s.get("departureTime"),
                arrival_time=s.get("arrivalTime"), headsign=s.get("headsign"), stop_count=s.get("stopCount"),
                line_text_color=s.get("lineTextColor"),
                intermediate_stops=tuple(s["intermediateStops"]) if s.get("intermediateStops") is not None else None,
                intermediate_stops_source=s.get("intermediateStopsSource"),
                line_kind=s.get("lineKind"), realtime=s.get("realtime"),
            )
            for s in d["segments"]
        ),
    )
