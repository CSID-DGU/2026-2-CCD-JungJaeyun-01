"""ODsay 대중교통 프로바이더 (기본 비활성화: ROUTE_PROVIDER=odsay로 켠다).

기본값은 Google Routes(providers/google.py)다. 이 파일은 이전에 쓰던 ODsay 연동을 같은 RouteProvider 인터페이스로
옮겨 둔 것으로, 2단계 구조에서는 상위 후보 몇 곳의 (출발지, 도착역) 쌍만 호출한다.
- 요청은 순차적이고 호출 간 최소 간격을 둔다. 429는 1초·2초 대기 후 최대 2회 재시도하고,
  그래도 429면 한도 초과로 보고 일정 시간 HTTP 호출 없이 바로 실패시킨다.
- 응답의 subPath/passStopList를 공통 경로 스키마(app.route_model)로 변환한다.
"""

import logging
import re
import time
from dataclasses import dataclass
from typing import Callable, Sequence

import httpx2 as httpx

from app.config import TravelParams
from app.geo import Coord, haversine_km
from app.providers.base import MatrixResult, RouteProvider, RouteUnavailable
from app.providers.google import coord_key
from app.route_model import BUS, SUBWAY, WALK, Route, Segment, route_from_dict, route_to_dict
from app.services.routes_store import RoutesStore
from app.stations import Station

logger = logging.getLogger(__name__)

# 노선 색 (수도권). 없으면 None → 화면에서 참여자 색을 쓴다.
SUBWAY_COLORS = [
    ("1호선", "#0052A4"), ("2호선", "#00A84D"), ("3호선", "#EF7C1C"), ("4호선", "#00A5DE"),
    ("5호선", "#996CAC"), ("6호선", "#CD7C2F"), ("7호선", "#747F00"), ("8호선", "#E6186C"),
    ("9호선", "#BDB092"), ("신분당", "#D4003B"), ("수인분당", "#F5A200"), ("분당", "#F5A200"),
    ("경의중앙", "#77C4A3"), ("공항철도", "#0090D2"), ("경춘", "#0C8E72"), ("우이신설", "#B0CE18"),
    ("신림", "#6789CA"), ("경강", "#0054A6"), ("서해", "#81A914"), ("GTX-A", "#9A6292"),
]
BUS_COLORS = {11: "#3D5BAB", 12: "#5BB025", 13: "#F2B70A", 14: "#E60012", 3: "#53B332", 15: "#D6001C"}


@dataclass(frozen=True)
class TravelResult:
    minutes: float
    route: Route | None = None


def _subway_label(name: str) -> tuple[str, str | None]:
    short = re.sub(r"^(수도권|서울|인천|부산|대구|광주|대전)\s*", "", name).strip()
    if name.startswith("수도권"):
        for key, color in SUBWAY_COLORS:
            if key in short:
                return short, color
    return short, None


def _pt(x, y) -> tuple[float, float]:
    return (float(y), float(x))  # ODsay: x=경도, y=위도


def parse_odsay_route(path: dict, origin: Coord, destination: Coord) -> Route | None:
    """ODsay path 하나를 공통 Route로 변환한다. 형식이 예상과 다르면 None (가짜 경로를 만들지 않는다)."""
    try:
        subs = path["subPath"]
        segments: list[Segment] = []
        cursor = (origin.lat, origin.lng)
        for i, sp in enumerate(subs):
            code = sp["trafficType"]
            if code == 3:  # 도보: 좌표가 없어 앞뒤 구간의 끝점·시작점으로 잇는다
                nxt = next((s for s in subs[i + 1:] if s["trafficType"] in (1, 2)), None)
                end = _pt(nxt["startX"], nxt["startY"]) if nxt else (destination.lat, destination.lng)
                minutes, dist = int(sp.get("sectionTime", 0)), int(sp.get("distance", 0))
                if minutes > 0 or dist > 0:
                    segments.append(Segment(WALK, None, None, None, None, float(minutes), (cursor, end)))
                cursor = end
                continue
            stations = (sp.get("passStopList") or {}).get("stations") or []
            points = tuple(_pt(s["x"], s["y"]) for s in stations)
            if len(points) < 2:
                points = (_pt(sp["startX"], sp["startY"]), _pt(sp["endX"], sp["endY"]))
            lane = (sp.get("lane") or [{}])[0]
            if code == 1:
                name, color = _subway_label(lane.get("name", ""))
                mode, label = SUBWAY, name or None
            else:
                mode, label, color = BUS, (f"{lane['busNo']}번" if lane.get("busNo") else None), BUS_COLORS.get(lane.get("type"))
            segments.append(Segment(mode, label, color, sp.get("startName"), sp.get("endName"),
                                    float(sp.get("sectionTime", 0)), points))
            cursor = points[-1]
        transit = sum(1 for s in segments if s.mode != WALK)
        if transit == 0:
            return None
        return Route(int(path["info"]["totalTime"]), max(0, transit - 1), tuple(segments), "odsay")
    except (KeyError, TypeError, ValueError, IndexError) as e:
        logger.warning("ODsay 경로 파싱 실패: %s", type(e).__name__)
        return None


def _odsay_error(error: object) -> tuple[str, str]:
    item = error[0] if isinstance(error, list) and error else error
    if not isinstance(item, dict):
        return "", str(error)
    return str(item.get("code", "")), str(item.get("msg") or item.get("message") or "")


def _error_code(body: dict) -> str | None:
    return _odsay_error(body["error"])[0] if "error" in body else None


def _walking_minutes(straight_km: float, p: TravelParams) -> float:
    return straight_km * p.detour_factor / p.walk_speed_kmh * 60


class OdsayClient:
    """ODsay searchPubTransPathT 호출. 순차 호출 + 429 재시도 + 한도 초과 시 일정 시간 호출 중단."""

    URL = "https://api.odsay.com/v1/api/searchPubTransPathT"
    TOO_CLOSE_CODE, NO_RESULT_CODE, RATE_LIMIT_CODE = "-98", "-99", "429"

    def __init__(self, api_key: str, params: TravelParams, timeout: float = 10.0, client: httpx.Client | None = None,
                 min_interval: float = 0.3, retry_delays: Sequence[float] = (1.0, 2.0),
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                 quota_cooldown: float = 300.0):
        if not api_key:
            raise ValueError("ODSAY_API_KEY가 설정되지 않았습니다.")
        self._api_key, self.params = api_key, params
        self._client = client or httpx.Client(timeout=timeout)
        self._min_interval, self._retry_delays = min_interval, tuple(retry_delays)
        self._sleep, self._clock = sleep, clock
        self._last_request_at: float | None = None
        self._quota_cooldown = quota_cooldown
        self._blocked_until: float | None = None
        self._blocked_reason = ""
        self.http_calls = 0

    def fetch(self, origin: Coord, station: Station) -> TravelResult:
        body = self._request_with_retry(origin, station)
        if "error" in body:
            code, msg = _odsay_error(body["error"])
            if code == self.TOO_CLOSE_CODE:  # 700m 이내: 경로 대신 도보 거리 응답
                km = haversine_km(origin, station.coord)
                minutes = _walking_minutes(km, self.params)
                walk = Segment(WALK, None, None, None, station.name, float(max(1, round(minutes))),
                               ((origin.lat, origin.lng), (station.coord.lat, station.coord.lng)))
                return TravelResult(minutes, Route(max(1, round(minutes)), 0, (walk,), "odsay"))
            if code == self.NO_RESULT_CODE:
                raise RouteUnavailable("ODsay: 검색 결과 없음")
            raise RouteUnavailable(f"ODsay 에러 {code} {msg}".strip())
        paths = body.get("result", {}).get("path") or []
        if not paths:
            raise RouteUnavailable("ODsay: 경로 없음")
        best = min(paths, key=lambda p: p["info"]["totalTime"])
        return TravelResult(float(best["info"]["totalTime"]), parse_odsay_route(best, origin, station.coord))

    def _request_with_retry(self, origin: Coord, station: Station) -> dict:
        if self._blocked_until is not None:
            if self._clock() < self._blocked_until:
                raise RouteUnavailable(self._blocked_reason)
            self._blocked_until = None
        body: dict = {}
        for attempt in range(len(self._retry_delays) + 1):
            body = self._request(origin, station)
            if _error_code(body) != self.RATE_LIMIT_CODE:
                return body
            if attempt < len(self._retry_delays):
                self._sleep(self._retry_delays[attempt])
        _, msg = _odsay_error(body["error"])
        reason = f"ODsay 429 {msg} (재시도 {len(self._retry_delays)}회 후에도 실패)".replace("  ", " ")
        self._blocked_until = self._clock() + self._quota_cooldown
        self._blocked_reason = f"{reason}, 이후 {int(self._quota_cooldown)}초간 호출 중단"
        raise RouteUnavailable(reason)

    def _request(self, origin: Coord, station: Station) -> dict:
        self._throttle()
        self.http_calls += 1
        try:
            r = self._client.get(self.URL, params={"SX": origin.lng, "SY": origin.lat, "EX": station.coord.lng,
                                                   "EY": station.coord.lat, "apiKey": self._api_key})
            if r.status_code == 429:
                return {"error": {"code": self.RATE_LIMIT_CODE, "msg": "HTTP 429"}}
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            logger.warning("ODsay 요청 실패 (%s): %s", station.name, type(e).__name__)
            raise RouteUnavailable(f"ODsay 요청 실패({type(e).__name__})") from None

    def _throttle(self) -> None:
        if self._last_request_at is not None:
            wait = self._min_interval - (self._clock() - self._last_request_at)
            if wait > 0:
                self._sleep(wait)
        self._last_request_at = self._clock()


class OdsayRouteProvider(RouteProvider):
    name = "odsay"

    def __init__(self, client: OdsayClient, store: RoutesStore, cache_ttl_days: int = 7):
        self.client, self.store, self.ttl = client, store, cache_ttl_days

    def _key(self, origin: Coord, station: Station) -> str:
        return f"odsay|{coord_key(origin)}|{station.id}"

    def _lookup(self, origin: Coord, station: Station) -> TravelResult:
        key = self._key(origin, station)
        hit = self.store.get(key, self.ttl)
        if hit is not None:
            self.store.add_usage("cache_hit")
            return TravelResult(hit["minutes"], route_from_dict(hit["route"]) if hit.get("route") else None)
        result = self.client.fetch(origin, station)
        self.store.add_usage("odsay")
        self.store.put(key, {"minutes": result.minutes, "route": route_to_dict(result.route) if result.route else None})
        return result

    def matrix(self, origins: Sequence[Coord], destinations: Sequence[Station], meeting_time=None) -> MatrixResult:
        result = MatrixResult(minutes=[[None] * len(destinations) for _ in origins])
        before = self.client.http_calls
        for i, o in enumerate(origins):
            for j, d in enumerate(destinations):
                try:
                    result.minutes[i][j] = self._lookup(o, d).minutes
                except RouteUnavailable as e:
                    result.error = str(e)
        result.api_calls = self.client.http_calls - before
        return result

    def route(self, origin: Coord, destination: Station, meeting_time=None) -> Route:
        route = self._lookup(origin, destination).route
        if route is None:
            raise RouteUnavailable("ODsay: 경로 상세 정보를 받지 못했어요")
        return route
