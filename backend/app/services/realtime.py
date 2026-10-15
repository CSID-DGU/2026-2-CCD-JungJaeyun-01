"""실시간 도착 정보: 서울 열린데이터광장 지하철 실시간 도착정보, 공공데이터포털 서울 버스 정류소·도착정보.

실패(키 없음·서울 밖·응답 오류·시간 초과)는 모두 `available=False`로 조용히 처리한다. 키는 로그·응답에 남기지 않는다.
"""

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import httpx2 as httpx

from app.subway import SubwayNetwork, _line_hops

logger = logging.getLogger(__name__)

SUBWAY_URL = "http://swopenapi.seoul.go.kr/api/subway/{key}/json/realtimeStationArrival/0/30/{station}"
BUS_POS_URL = "http://ws.bus.go.kr/api/rest/stationinfo/getStationByPos"
BUS_ARRIVAL_URL = "http://ws.bus.go.kr/api/rest/stationinfo/getStationByUid"

# 서울(+인접) 대략 범위. 밖이면 버스 API를 부르지 않는다.
SEOUL_BOUNDS = (37.41, 37.71, 126.76, 127.19)

SUBWAY_IDS = {
    "1호선": "1001", "2호선": "1002", "3호선": "1003", "4호선": "1004", "5호선": "1005", "6호선": "1006",
    "7호선": "1007", "8호선": "1008", "9호선": "1009", "경의중앙선": "1063", "공항철도": "1065",
    "경춘선": "1067", "수인분당선": "1075", "신분당선": "1077", "우이신설선": "1092",
}
MAX_ITEMS = 2  # 첫 번째·두 번째 열차/버스


@dataclass
class Arrival:
    seconds: int | None          # 도착까지 남은 시간(초). 모르면 None
    stops_away: int | None       # 몇 정거장 전. 모르면 None
    text: str                    # 원문 요약 ("곧 도착" 등)
    destination: str | None = None


@dataclass
class RealtimeResult:
    available: bool
    items: list[Arrival] = field(default_factory=list)
    updated_at: float = 0.0
    reason: str | None = None    # 개발자용 사유 (화면에는 "실시간 정보 없음"만 보인다)

    def to_dict(self) -> dict:
        return {"available": self.available,
                "items": [{"seconds": i.seconds, "stopsAway": i.stops_away, "text": i.text, "destination": i.destination} for i in self.items],
                "updatedAt": self.updated_at, "reason": self.reason}


def none(reason: str) -> RealtimeResult:
    return RealtimeResult(False, [], time.time(), reason)


def plain_station(name: str) -> str:
    return re.sub(r"\s+", "", name).removesuffix("역")


def in_seoul(lat: float, lng: float) -> bool:
    return SEOUL_BOUNDS[0] <= lat <= SEOUL_BOUNDS[1] and SEOUL_BOUNDS[2] <= lng <= SEOUL_BOUNDS[3]


class TtlCache:
    def __init__(self, ttl: float, clock: Callable[[], float] = time.monotonic):
        self.ttl, self._clock, self._items, self._lock = ttl, clock, {}, threading.Lock()

    def get(self, key: tuple, factory: Callable[[], Any]) -> Any:
        now = self._clock()
        with self._lock:
            hit = self._items.get(key)
            if hit and now - hit[0] < self.ttl:
                return hit[1]
        value = factory()
        with self._lock:
            self._items[key] = (self._clock(), value)
            if len(self._items) > 500:  # 오래된 항목 정리
                for k in [k for k, (t, _) in self._items.items() if now - t > self.ttl]:
                    self._items.pop(k, None)
        return value


def _get_json(http: httpx.Client, url: str, params: dict | None = None) -> Any:
    r = http.get(url, params=params)
    if r.status_code != 200:
        raise ValueError(f"HTTP {r.status_code}")
    return r.json()


# --------------------------------------------------------------------------- 지하철
def _subway_stops_away(item: dict, line: str, station: str, network: SubwayNetwork | None) -> int | None:
    msg = item.get("arvlMsg2") or ""
    if m := re.search(r"\[(\d+)\]번째 전역", msg):
        return int(m.group(1))
    if "전역" in msg:
        return 1
    if network and (current := plain_station(item.get("arvlMsg3") or "")) and current != station:
        hops = _line_hops(network, line, current, station)
        if hops:
            return len(hops) - 1
    return 0 if item.get("arvlCd") in ("0", "1") else None


def parse_subway(payload: dict, line: str, station: str, headsign: str | None, next_stop: str | None,
                 network: SubwayNetwork | None = None) -> list[Arrival]:
    subway_id = SUBWAY_IDS.get(line)
    if subway_id is None:  # 모르는 노선은 엉뚱한 열차를 보여주지 않는다
        return []
    terminal = plain_station((headsign or "").removesuffix("방면"))
    nxt = plain_station(next_stop or "")
    rows: list[tuple[float, Arrival]] = []
    for it in payload.get("realtimeArrivalList") or []:
        if it.get("subwayId") != subway_id:
            continue
        if it.get("arvlCd") == "2":  # 이미 출발한 열차
            continue
        name = re.sub(r"\s+", "", it.get("trainLineNm") or "")
        head, _, towards = name.partition("-")
        # 방면(진행 방향)이 맞는 열차만: 종착역이 같거나, 다음 정차역 방면이 같을 때
        if not ((terminal and head.removesuffix("행") == terminal) or (nxt and towards.startswith(f"{nxt}방면"))):
            continue
        seconds = int(it["barvlDt"]) if str(it.get("barvlDt") or "0").isdigit() and int(it["barvlDt"]) > 0 else None
        stops = _subway_stops_away(it, line, station, network)
        if seconds is None and stops is None:
            continue
        key = seconds if seconds is not None else (stops or 0) * 120
        rows.append((key, Arrival(seconds, stops, it.get("arvlMsg2") or "", head.removesuffix("행") or None)))
    return [a for _, a in sorted(rows, key=lambda r: r[0])][:MAX_ITEMS]


class SubwayRealtime:
    def __init__(self, key: str, http: httpx.Client, cache: TtlCache, network: SubwayNetwork | None = None):
        self.key, self.http, self.cache, self.network = key, http, cache, network

    def arrivals(self, station: str, line: str, headsign: str | None, next_stop: str | None) -> RealtimeResult:
        if not self.key:
            return none("SEOUL_SUBWAY_API_KEY 없음")
        name = plain_station(station)
        # 같은 역은 방면과 무관하게 한 번만 부른다 (30초 캐시). 실패도 캐시해서 연타를 막는다.
        payload, error = self.cache.get(("subway", name), lambda: self._fetch(name))
        if payload is None:
            return none(error)
        items = parse_subway(payload, line, name, headsign, next_stop, self.network)
        return RealtimeResult(bool(items), items, time.time(), None if items else "해당 열차 없음")

    def _fetch(self, name: str) -> tuple[dict | None, str]:
        try:
            payload = _get_json(self.http, SUBWAY_URL.format(key=self.key, station=name))
        except Exception as e:  # noqa: BLE001 - 어떤 실패든 "실시간 정보 없음"으로 처리
            logger.warning("지하철 실시간 조회 실패(%s)", type(e).__name__)
            return None, f"요청 실패({type(e).__name__})"
        if not isinstance(payload, dict) or not payload.get("realtimeArrivalList"):
            return None, "응답에 도착 정보 없음"
        return payload, ""


# --------------------------------------------------------------------------- 버스
def _items(payload: dict) -> list[dict]:
    body = payload.get("msgBody") or {}
    items = body.get("itemList") or []
    return [items] if isinstance(items, dict) else list(items)


def _header_ok(payload: dict) -> bool:
    return str((payload.get("msgHeader") or {}).get("headerCd", "0")) in ("0", "4")  # 4: 결과 없음


def _parse_bus_message(msg: str, sec: Any) -> Arrival | None:
    if not msg or any(w in msg for w in ("운행종료", "출발대기", "회차대기")):
        return None
    stops = re.search(r"\[(\d+)번째 전\]", msg)
    seconds = int(sec) if str(sec or "").isdigit() and int(sec) > 0 else None
    if seconds is None:
        mm, ss = re.search(r"(\d+)분", msg), re.search(r"(\d+)초", msg)
        if mm or ss:
            seconds = (int(mm.group(1)) * 60 if mm else 0) + (int(ss.group(1)) if ss else 0)
        elif "곧" in msg:
            seconds = 30
    if seconds is None and not stops:
        return None
    return Arrival(seconds, int(stops.group(1)) if stops else None, re.sub(r"\[.*?\]", "", msg).strip())


def parse_bus(payload: dict, route: str) -> list[Arrival]:
    out: list[Arrival] = []
    for it in _items(payload):
        if str(it.get("rtNm", "")).strip() != route.strip():
            continue
        for n in ("1", "2"):
            if a := _parse_bus_message(it.get(f"arrmsg{n}", ""), it.get(f"traTime{n}")):
                a.destination = it.get("adirection") or None
                out.append(a)
    return sorted(out, key=lambda a: a.seconds if a.seconds is not None else 10**6)[:MAX_ITEMS]


def pick_station(payload: dict, name: str) -> str | None:
    """반경 안 정류소 중 이름이 같은 것(없으면 가장 가까운 것)의 arsId."""
    items = _items(payload)
    if not items:
        return None
    norm = re.sub(r"\s+", "", name)
    same = [i for i in items if re.sub(r"\s+", "", str(i.get("stationNm", ""))) == norm]
    best = min(same or items, key=lambda i: float(i.get("dist") or 1e9))
    ars = str(best.get("arsId", "")).strip()
    return ars if ars and ars != "0" else None


class BusRealtime:
    def __init__(self, key: str, http: httpx.Client, cache: TtlCache):
        self.key, self.http, self.cache = key, http, cache

    def arrivals(self, lat: float, lng: float, stop: str, route: str) -> RealtimeResult:
        if not self.key:
            return none("SEOUL_BUS_API_KEY 없음")
        if not in_seoul(lat, lng):
            return none("서울 밖")
        ars, error = self.cache.get(("bus-stop", round(lat, 4), round(lng, 4), stop), lambda: self._station(lat, lng, stop))
        if ars is None:
            return none(error)
        payload, error = self.cache.get(("bus-arr", ars), lambda: self._fetch(ars))
        if payload is None:
            return none(error)
        items = parse_bus(payload, route)
        return RealtimeResult(bool(items), items, time.time(), None if items else "해당 노선 도착 정보 없음")

    def _params(self, **extra: Any) -> dict:
        return {"serviceKey": self.key, "resultType": "json", **extra}

    def _station(self, lat: float, lng: float, stop: str) -> tuple[str | None, str]:
        try:
            payload = _get_json(self.http, BUS_POS_URL, self._params(tmX=lng, tmY=lat, radius=120))
        except Exception as e:  # noqa: BLE001
            logger.warning("버스 정류소 조회 실패(%s)", type(e).__name__)
            return None, f"정류소 조회 실패({type(e).__name__})"
        if not isinstance(payload, dict) or not _header_ok(payload):
            return None, "정류소 조회 거절"
        ars = pick_station(payload, stop)
        return (ars, "") if ars else (None, "근처에 정류소 없음")

    def _fetch(self, ars_id: str) -> tuple[dict | None, str]:
        try:
            payload = _get_json(self.http, BUS_ARRIVAL_URL, self._params(arsId=ars_id))
        except Exception as e:  # noqa: BLE001
            logger.warning("버스 도착정보 조회 실패(%s)", type(e).__name__)
            return None, f"도착정보 조회 실패({type(e).__name__})"
        if not isinstance(payload, dict) or not _header_ok(payload):
            return None, "도착정보 조회 거절"
        return payload, ""
