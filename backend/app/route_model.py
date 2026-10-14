"""공통 경로 스키마. 어떤 경로 API(Google, ODsay, 지하철 그래프 추정)를 쓰든 프론트는 이 형식만 본다.

route = {totalMinutes, transfers, segments[{mode, lineName, lineColor, from, to, minutes, path[[lat,lng],...]}], source}
- mode: WALK | SUBWAY | BUS
- source: "google" | "estimate" (| "odsay")
"""

from dataclasses import dataclass

WALK, SUBWAY, BUS = "WALK", "SUBWAY", "BUS"

LatLngPair = tuple[float, float]


@dataclass(frozen=True)
class Segment:
    mode: str                       # WALK | SUBWAY | BUS
    line_name: str | None           # "2호선", "472번"
    line_color: str | None          # "#35b12b"
    from_name: str | None
    to_name: str | None
    minutes: float
    path: tuple[LatLngPair, ...]    # ((lat, lng), ...)


@dataclass(frozen=True)
class Route:
    total_minutes: int
    transfers: int
    segments: tuple[Segment, ...]
    source: str                     # "google" | "estimate" | "odsay"


def route_to_dict(route: Route) -> dict:
    """API 응답·캐시용 dict (camelCase)."""
    return {
        "totalMinutes": route.total_minutes,
        "transfers": route.transfers,
        "source": route.source,
        "segments": [
            {
                "mode": s.mode, "lineName": s.line_name, "lineColor": s.line_color,
                "from": s.from_name, "to": s.to_name, "minutes": s.minutes,
                "path": [[lat, lng] for lat, lng in s.path],
            }
            for s in route.segments
        ],
    }


def route_from_dict(d: dict) -> Route:
    return Route(
        total_minutes=d["totalMinutes"], transfers=d["transfers"], source=d["source"],
        segments=tuple(
            Segment(
                mode=s["mode"], line_name=s["lineName"], line_color=s["lineColor"],
                from_name=s["from"], to_name=s["to"], minutes=s["minutes"],
                path=tuple((p[0], p[1]) for p in s["path"]),
            )
            for s in d["segments"]
        ),
    )
