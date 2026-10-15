"""수도권 지하철 그래프와 1단계 이동시간 추정 (외부 API 호출 없음).

데이터: data/subway/network.json (scripts/build_subway_network.py로 생성, 출처는 data/subway/README.md)
- 노드 = (노선, 역). 같은 노선의 인접 역은 '탑승' 간선, 같은 역의 다른 노선은 '환승' 간선으로 이어진다.
- 이동시간 = 출발지 → 가까운 역 도보 + 첫 승차 대기 + 다익스트라 최단 시간 + 도착역 출구.
"""

import heapq
import json
import math
import re
from collections import deque
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Sequence

from app.geo import Coord, haversine_km
from app.route_model import SUBWAY, WALK, Route, Segment
from app.stations import Station

NETWORK_PATH = Path(__file__).resolve().parents[1] / "data" / "subway" / "network.json"


@dataclass(frozen=True)
class EstimateParams:
    walk_speed_kmh: float
    detour_factor: float
    boarding_wait_minutes: float
    egress_minutes: float
    nearest_station_k: int
    fallback_transit_speed_kmh: float
    fallback_access_minutes: float


@dataclass(frozen=True)
class Node:
    id: str
    line: str
    name: str
    coord: Coord


@dataclass(frozen=True)
class Edge:
    to: str
    minutes: float
    transfer: bool


class SubwayNetwork:
    def __init__(self, nodes: Mapping[str, Node], edges: Mapping[str, Sequence[Edge]], line_colors: Mapping[str, str]):
        self.nodes = dict(nodes)
        self.edges = {k: list(v) for k, v in edges.items()}
        self.line_colors = dict(line_colors)
        self.groups: dict[str, list[str]] = {}
        for node in self.nodes.values():
            self.groups.setdefault(node.name, []).append(node.id)
        self.group_coord = {
            name: Coord(
                lat=sum(self.nodes[i].coord.lat for i in ids) / len(ids),
                lng=sum(self.nodes[i].coord.lng for i in ids) / len(ids),
            )
            for name, ids in self.groups.items()
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SubwayNetwork":
        nodes = {s["id"]: Node(s["id"], s["line"], s["name"], Coord(s["lat"], s["lng"])) for s in data["stations"]}
        edges: dict[str, list[Edge]] = {i: [] for i in nodes}
        for e in data["edges"]:
            edges[e["a"]].append(Edge(e["b"], e["minutes"], False))
            edges[e["b"]].append(Edge(e["a"], e["minutes"], False))
        for t in data["transfers"]:
            edges[t["a"]].append(Edge(t["b"], t["minutes"], True))
            edges[t["b"]].append(Edge(t["a"], t["minutes"], True))
        return cls(nodes, edges, {k: v["color"] for k, v in data["lines"].items()})

    def has_station(self, name: str) -> bool:
        return name in self.groups

    def nearest_groups(self, point: Coord, k: int) -> list[tuple[str, float]]:
        """point에서 가까운 역(역명 단위) k개와 직선거리(m)."""
        ranked = sorted(((name, haversine_km(point, c) * 1000) for name, c in self.group_coord.items()),
                        key=lambda x: (x[1], x[0]))
        return ranked[:k]

    def shortest(self, sources: Mapping[str, float]) -> tuple[dict[str, float], dict[str, tuple[str, Edge | None]]]:
        """다중 출발 다익스트라. 반환: (노드별 최단 시간, 이전 노드와 사용한 간선)."""
        dist: dict[str, float] = {}
        prev: dict[str, tuple[str, Edge | None]] = {}
        heap: list[tuple[float, str]] = []
        for node_id, cost in sources.items():
            dist[node_id] = cost
            prev[node_id] = ("", None)
            heapq.heappush(heap, (cost, node_id))
        while heap:
            d, u = heapq.heappop(heap)
            if d > dist.get(u, math.inf):
                continue
            for edge in self.edges[u]:
                nd = d + edge.minutes
                if nd < dist.get(edge.to, math.inf):
                    dist[edge.to] = nd
                    prev[edge.to] = (u, edge)
                    heapq.heappush(heap, (nd, edge.to))
        return dist, prev


@lru_cache
def load_network(path: Path = NETWORK_PATH) -> SubwayNetwork:
    return SubwayNetwork.from_dict(json.loads(path.read_text(encoding="utf-8")))


def station_key(station: Station) -> str:
    """후보 역 이름('강남역') → 네트워크 역명('강남')."""
    return station.name.removesuffix("역")


class TravelEstimator:
    """출발지 → 후보 역 이동시간 추정과 추정 경로."""

    def __init__(self, network: SubwayNetwork, params: EstimateParams):
        self.network = network
        self.params = params

    def _walk_minutes(self, meters: float) -> float:
        return meters * self.params.detour_factor / (self.params.walk_speed_kmh * 1000 / 60)

    def _search(self, origin: Coord):
        """출발지에서 가까운 역 k개를 시작점으로 한 최단 시간 탐색. 반환: (dist, prev, 시작 노드별 도보 시간)."""
        p = self.params
        sources: dict[str, float] = {}
        walk_to: dict[str, float] = {}
        for name, meters in self.network.nearest_groups(origin, p.nearest_station_k):
            walk = self._walk_minutes(meters)
            for node_id in self.network.groups[name]:
                sources[node_id] = walk + p.boarding_wait_minutes
                walk_to[node_id] = walk
        dist, prev = self.network.shortest(sources)
        return dist, prev, walk_to

    def _fallback(self, origin: Coord, station: Station) -> float:
        p = self.params
        km = haversine_km(origin, station.coord) * p.detour_factor
        return p.fallback_access_minutes + km / p.fallback_transit_speed_kmh * 60

    def _best_dest_node(self, dist: Mapping[str, float], station: Station) -> str | None:
        ids = self.network.groups.get(station_key(station), [])
        reachable = [i for i in ids if i in dist]
        return min(reachable, key=lambda i: dist[i]) if reachable else None

    def estimate(self, origin: Coord, stations: Sequence[Station]) -> dict[str, float]:
        """후보 역 id → 추정 이동시간(분). 한 번의 탐색으로 모든 후보를 계산하므로 후보가 몇 개든 비용이 거의 같다."""
        dist, _, _ = self._search(origin)
        result: dict[str, float] = {}
        for st in stations:
            node = self._best_dest_node(dist, st)
            minutes = dist[node] + self.params.egress_minutes if node else self._fallback(origin, st)
            direct = self._walk_minutes(haversine_km(origin, st.coord) * 1000)
            result[st.id] = min(minutes, direct) if direct <= 15 else minutes  # 15분 이내 도보 거리면 걷는 편이 빠르다
        return result

    def estimate_route(self, origin: Coord, station: Station) -> Route | None:
        """추정 경로(source='estimate'). 도착역이 그래프에 없으면 None."""
        dist, prev, walk_to = self._search(origin)
        end = self._best_dest_node(dist, station)
        if end is None:
            return None
        # 도착 노드에서 시작 노드까지 거슬러 올라간다.
        chain: list[tuple[str, Edge | None]] = []
        cur = end
        while cur:
            parent, edge = prev[cur]
            chain.append((cur, edge))
            cur = parent
        chain.reverse()  # [(시작 노드, None), (다음 노드, 사용한 간선), ...]

        nodes = self.network.nodes
        first = nodes[chain[0][0]]
        segments: list[Segment] = [Segment(
            WALK, None, None, None, first.name, round(walk_to[first.id], 1),
            ((origin.lat, origin.lng), (first.coord.lat, first.coord.lng)),
        )]
        transfers = 0
        run: list[Node] = [first]
        run_minutes = 0.0

        def flush() -> None:
            nonlocal run, run_minutes
            if len(run) >= 2:
                line = run[0].line
                segments.append(Segment(
                    SUBWAY, line, self.network.line_colors.get(line), run[0].name, run[-1].name,
                    round(run_minutes, 1), tuple((n.coord.lat, n.coord.lng) for n in run),
                ))
            run, run_minutes = [], 0.0

        for node_id, edge in chain[1:]:
            node = nodes[node_id]
            if edge is not None and edge.transfer:
                flush()
                transfers += 1
                prev_node = nodes[chain[[c[0] for c in chain].index(node_id) - 1][0]]
                segments.append(Segment(
                    WALK, None, None, prev_node.name, node.name, round(edge.minutes, 1),
                    ((prev_node.coord.lat, prev_node.coord.lng), (node.coord.lat, node.coord.lng)),
                ))
                run = [node]
            else:
                run.append(node)
                run_minutes += edge.minutes if edge else 0.0
        flush()
        last = nodes[end]
        segments.append(Segment(
            WALK, None, None, last.name, station.name, self.params.egress_minutes,
            ((last.coord.lat, last.coord.lng), (station.coord.lat, station.coord.lng)),
        ))
        total = dist[end] + self.params.egress_minutes
        return Route(total_minutes=round(total), transfers=transfers, segments=tuple(segments), source="estimate")


def _plain(name: str | None) -> str:
    """Google 정류장 이름('서울대입구 (관악구청)', '합정역') → 노선도 역명('서울대입구', '합정')."""
    return re.sub(r"\s*\(.*?\)", "", name or "").strip().removesuffix("역")


def _line_hops(network: SubwayNetwork, line: str, start: str, end: str) -> list[str] | None:
    """같은 노선 안에서 start → end로 가는 최소 환승 없는 역 순서 (이름 목록). 없으면 None."""
    first, last = f"{line}|{start}", f"{line}|{end}"
    if first not in network.nodes or last not in network.nodes:
        return None
    prev: dict[str, str | None] = {first: None}
    queue = deque([first])
    while queue:
        cur = queue.popleft()
        if cur == last:
            break
        for edge in network.edges[cur]:
            if edge.transfer or edge.to in prev or not edge.to.startswith(f"{line}|"):
                continue
            prev[edge.to] = cur
            queue.append(edge.to)
    if last not in prev:
        return None
    path, cur = [], last
    while cur:
        path.append(network.nodes[cur].name)
        cur = prev[cur]
    return path[::-1]


# 2호선 순환선 본선(내선순환 진행 순서). 지선(성수·신정)은 포함하지 않는다.
RING_2 = ("시청", "을지로입구", "을지로3가", "을지로4가", "동대문역사문화공원", "신당", "상왕십리", "왕십리", "한양대", "뚝섬",
          "성수", "건대입구", "구의", "강변", "잠실나루", "잠실", "잠실새내", "종합운동장", "삼성", "선릉", "역삼", "강남",
          "교대", "서초", "방배", "사당", "낙성대", "서울대입구", "봉천", "신림", "신대방", "구로디지털단지", "대림", "신도림",
          "문래", "영등포구청", "당산", "합정", "홍대입구", "신촌", "이대", "아현", "충정로")


def ring_direction(line: str, start: str, nxt: str) -> str | None:
    """2호선 순환선에서 start → nxt가 내선순환이면 '내선', 외선순환이면 '외선'. 순환선 밖이면 None."""
    if line != "2호선" or start not in RING_2 or nxt not in RING_2:
        return None
    i, j, n = RING_2.index(start), RING_2.index(nxt), len(RING_2)
    if (i + 1) % n == j:
        return "내선"
    if (i - 1) % n == j:
        return "외선"
    return None


def direction_headsign(seg: Segment, path: list[str]) -> str | None:
    """승차 후 첫 정차역 기준의 실제 진행 방향 문구. Google의 headsign은 열차 종착역이라 순환선에서는 방향을 오해하게 한다."""
    if len(path) < 2:
        return None
    ring = ring_direction(seg.line_name or "", _plain(path[0]), _plain(path[1]))
    return f"{ring}순환 · {_plain(path[1])} 방면" if ring else None


def enrich_route_stops(route: Route, network: SubwayNetwork) -> Route:
    """지하철 구간의 경유 정거장 목록을 우리 노선도 데이터로 채운다.

    Google Routes API는 경유 정거장 이름을 주지 않는다. 노선도(network.json)에서 구한 정거장 수가
    Google의 stopCount와 같을 때만 채우고, 다르면(급행·지선 등) 틀린 목록을 보여주지 않으려고 비워 둔다.
    """
    segments = []
    for seg in route.segments:
        if seg.mode == SUBWAY and seg.line_name and seg.stop_count and seg.from_name and seg.to_name:
            path = _line_hops(network, seg.line_name, _plain(seg.from_name), _plain(seg.to_name))
            if path and len(path) - 1 == seg.stop_count:
                seg = replace(seg, intermediate_stops=tuple(path[1:-1]), intermediate_stops_source="subway-map",
                              headsign=direction_headsign(seg, path) or seg.headsign)
        segments.append(seg)
    return replace(route, segments=tuple(segments))
