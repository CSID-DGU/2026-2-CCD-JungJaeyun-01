"""Google Routes API 프로바이더 (computeRouteMatrix / computeRoutes, TRANSIT).

호출 구조
- matrix(): 검색당 최대 1회. 상위 후보 역 몇 곳까지의 실제 소요시간만 구한다.
- route():  사용자가 참여자 이름을 눌렀을 때만 호출하고 결과를 캐시한다.
보호 장치
- 디스크 캐시: (출발지 좌표 소수 4자리, 도착역, 요일·시간대) 키, 7일 (live 모드)
- 동시에 같은 요청이 오면 한 번만 호출 (SingleFlight)
- 일시 오류(네트워크·5xx·429)만 1회 재시도, 키 제한·API 미사용·할당량 오류는 일정 시간 호출을 멈춘다 (추정값으로 대체)
- FieldMask로 필요한 필드만 요청
- ROUTE_MODE: live(실제 호출 + 캐시) | record(실제 호출 + backend/fixtures/google/에 저장) | replay(저장본만 사용, 호출 0)
키는 백엔드에서만 쓰며 로그·응답에 남기지 않는다.
"""

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

import httpx2 as httpx

from app.geo import Coord
from app.providers.base import MatrixResult, RouteProvider, RouteUnavailable, SingleFlight
from app.route_model import BUS, SUBWAY, WALK, Route, Segment, route_from_dict, route_to_dict
from app.services.polyline import decode_polyline
from app.services.routes_store import RoutesStore
from app.stations import Station

logger = logging.getLogger(__name__)

MATRIX_URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
MATRIX_FIELD_MASK = "originIndex,destinationIndex,duration,condition,status"
ROUTES_FIELD_MASK = ",".join([
    "routes.duration",
    "routes.legs.steps.travelMode",
    "routes.legs.steps.staticDuration",
    "routes.legs.steps.distanceMeters",
    "routes.legs.steps.polyline.encodedPolyline",
    "routes.legs.steps.transitDetails",
])
BUS_VEHICLES = {"BUS", "INTERCITY_BUS", "TROLLEYBUS"}

MODES = ("live", "record", "replay")
FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "google"


@dataclass(frozen=True)
class GoogleSettings:
    utc_offset_hours: int
    cache_ttl_days: int
    max_retries: int
    backoff_seconds: float
    timeout_seconds: float
    cooldown_seconds: float
    transit_modes: tuple[str, ...] = ("BUS", "SUBWAY", "TRAIN", "LIGHT_RAIL")  # 허용할 대중교통 수단 (버스 포함)


# ----------------------------------------------------------------------------- 시각·키
_DOW = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def time_band(meeting_time: datetime) -> str:
    """캐시 키의 요일·시간대. 약속이 토요일 18시면 'sat-18' (같은 요일·시간대면 날짜가 달라도 같은 키)."""
    return f"{_DOW[meeting_time.weekday()]}-{meeting_time.hour:02d}"


def coord_key(c: Coord) -> str:
    return f"{c.lat:.4f},{c.lng:.4f}"


def _digest(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


# ----------------------------------------------------------------------------- 오류 분류
class ApiFailure(Exception):
    """Google 호출 실패의 분류. kind: network | server | rate_limit | key_restricted | api_disabled | quota | bad_request | unknown"""

    def __init__(self, kind: str, message: str, retryable: bool, blocks: bool):
        super().__init__(message)
        self.kind, self.message, self.retryable = kind, message, retryable
        self.blocks = blocks  # True면 잠시 호출을 멈춘다


def classify_failure(status: int | None, body: dict | None) -> ApiFailure:
    err = (body or {}).get("error", {}) if isinstance(body, dict) else {}
    text = f"{err.get('status', '')} {err.get('message', '')}".lower()
    if status is None:
        return ApiFailure("network", "Google에 연결하지 못했어요 (네트워크 오류)", True, False)
    if status >= 500:
        return ApiFailure("server", f"Google 서버 오류 (HTTP {status})", True, False)
    if status == 429 or "resource_exhausted" in text or "quota" in text:
        daily = "quota" in text and "per minute" not in text
        return ApiFailure("quota" if daily else "rate_limit",
                          "Google 할당량을 초과했어요" if daily else "Google 요청이 너무 많아요 (잠시 후 재시도)",
                          not daily, daily)
    if status == 403 or status == 401:
        if "has not been used" in text or "disabled" in text or "service_disabled" in text or "api_key_service_blocked" in text:
            return ApiFailure("api_disabled", "Routes API가 켜져 있지 않거나 이 키로 쓸 수 없어요 (Cloud Console에서 Routes API 사용 설정·키 API 제한 확인)", False, True)
        return ApiFailure("key_restricted", "API 키 제한 때문에 거부됐어요 (IP·앱 제한, 결제 설정 확인)", False, True)
    if status == 400:
        return ApiFailure("bad_request", f"요청 형식 오류: {str(err.get('message', ''))[:120]}", False, False)
    return ApiFailure("unknown", f"Google 오류 (HTTP {status})", False, False)


# ----------------------------------------------------------------------------- 변환: Google → 공통 스키마
def _seconds(value: str | None) -> float:
    return int(value.rstrip("s")) / 60 if value else 0.0


def _latlng(stop: dict) -> tuple[float, float] | None:
    ll = (stop.get("location") or {}).get("latLng")
    return (ll["latitude"], ll["longitude"]) if ll else None


def _parse_time(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text.replace("Z", "+00:00")) if text else None


def convert_route(response: dict, origin: Coord, destination: Coord, utc_offset_hours: int = 9) -> Route:
    """computeRoutes 응답 → 공통 Route. 잘게 쪼개진 연속 도보 step은 하나로 합치고, 시각·방면·정거장 수를 채운다."""
    routes = response.get("routes") or []
    if not routes:
        raise RouteUnavailable("Google이 경로를 찾지 못했어요")
    route = routes[0]
    tz = timezone(timedelta(hours=utc_offset_hours))
    raw: list[dict] = []
    for leg in route.get("legs", []):
        for step in leg.get("steps", []):
            points = [tuple(p) for p in decode_polyline((step.get("polyline") or {}).get("encodedPolyline", ""))]
            minutes = _seconds(step.get("staticDuration"))
            meters = int(step.get("distanceMeters") or 0)
            td = step.get("transitDetails")
            if not td:
                if raw and raw[-1]["mode"] == WALK:  # 연속 도보 병합
                    raw[-1]["minutes"] += minutes
                    raw[-1]["meters"] += meters
                    raw[-1]["path"].extend(points)
                else:
                    raw.append({"mode": WALK, "minutes": minutes, "meters": meters, "path": list(points)})
                continue
            line = td.get("transitLine") or {}
            stops = td.get("stopDetails") or {}
            dep, arr = stops.get("departureStop") or {}, stops.get("arrivalStop") or {}
            if len(points) < 2:
                points = [p for p in (_latlng(dep), _latlng(arr)) if p]
            vehicle = ((line.get("vehicle") or {}).get("type")) or ""
            raw.append({
                "mode": BUS if vehicle in BUS_VEHICLES else SUBWAY,
                "minutes": minutes, "meters": meters, "path": list(points),
                "line_name": line.get("nameShort") or line.get("name"),
                "line_color": line.get("color"), "line_text_color": line.get("textColor"),
                "from": dep.get("name"), "to": arr.get("name"),
                "headsign": td.get("headsign"), "stop_count": td.get("stopCount"),
                "dep": _parse_time(stops.get("departureTime")), "arr": _parse_time(stops.get("arrivalTime")),
            })

    # 시각: 대중교통 구간은 Google이 준 값, 도보는 앞뒤 구간에서 이어서 계산한다.
    n = len(raw)
    dep_t: list[datetime | None] = [r.get("dep") for r in raw]
    arr_t: list[datetime | None] = [r.get("arr") for r in raw]
    first = next((i for i, r in enumerate(raw) if r["mode"] != WALK and dep_t[i] and arr_t[i]), None)
    if first is not None:
        t = dep_t[first]
        for i in range(first - 1, -1, -1):          # 첫 승차 전 도보: 승차 시각에서 거꾸로
            arr_t[i], dep_t[i] = t, t - timedelta(minutes=raw[i]["minutes"])
            t = dep_t[i]
        t = arr_t[first]
        for i in range(first + 1, n):               # 이후: 앞 구간 도착 시각에서 이어서
            if raw[i]["mode"] == WALK:
                dep_t[i], arr_t[i] = t, t + timedelta(minutes=raw[i]["minutes"])
            t = arr_t[i] if arr_t[i] else t

    def iso(value: datetime | None) -> str | None:
        return value.astimezone(tz).isoformat(timespec="seconds") if value else None

    # 도보 구간은 앞뒤 구간과 이어지도록 시작·끝 점을 맞춘다 (출발지/도착지 포함).
    start, end = (origin.lat, origin.lng), (destination.lat, destination.lng)
    segments: list[Segment] = []
    for i, r in enumerate(raw):
        path = [p for k, p in enumerate(r["path"]) if k == 0 or p != r["path"][k - 1]]
        if r["mode"] == WALK:
            before = raw[i - 1]["path"][-1] if i > 0 and raw[i - 1]["path"] else start
            after = raw[i + 1]["path"][0] if i + 1 < n and raw[i + 1]["path"] else end
            path = [before, *path, after]
            path = [p for k, p in enumerate(path) if k == 0 or p != path[k - 1]]
            if len(path) < 2:
                path = [before, after]
        segments.append(Segment(
            mode=r["mode"], line_name=r.get("line_name"), line_color=r.get("line_color"),
            from_name=r.get("from"), to_name=r.get("to"), minutes=round(r["minutes"], 1), path=tuple(path),
            distance_m=r["meters"] or None, departure_time=iso(dep_t[i]), arrival_time=iso(arr_t[i]),
            headsign=r.get("headsign"), stop_count=r.get("stop_count"), line_text_color=r.get("line_text_color"),
        ))
    transit = sum(1 for s in segments if s.mode != WALK)
    walks = [s for s in segments if s.mode == WALK]
    return Route(
        total_minutes=round(_seconds(route.get("duration"))), transfers=max(0, transit - 1),
        segments=tuple(segments), source="google",
        departure_time=segments[0].departure_time if segments else None,
        arrival_time=segments[-1].arrival_time if segments else None,
        walk_minutes=round(sum(s.minutes for s in walks), 1), walk_meters=sum(s.distance_m or 0 for s in walks),
    )


# ----------------------------------------------------------------------------- 저수준 클라이언트
class GoogleClient:
    """HTTP 호출 + 모드(live/record/replay) 처리. 호출 횟수는 시도마다 센다 (실패해도 과금될 수 있다)."""

    def __init__(self, api_key: str, mode: str, store: RoutesStore, settings: GoogleSettings,
                 fixtures_dir: Path = FIXTURES_DIR, http: httpx.Client | None = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        if mode not in MODES:
            raise ValueError(f"ROUTE_MODE는 {MODES} 중 하나여야 합니다: {mode!r}")
        self.api_key, self.mode, self.store, self.s = api_key, mode, store, settings
        self.fixtures_dir = fixtures_dir
        self._http = http or httpx.Client(timeout=settings.timeout_seconds)
        self._sleep, self._clock = sleep, clock
        self._blocked_until = 0.0
        self._blocked_reason = ""
        self._lock = threading.Lock()

    def fixture_path(self, kind: str, key: str) -> Path:
        return self.fixtures_dir / f"{kind}-{_digest(key)}.json"

    def call(self, kind: str, key: str, url: str, body: dict, field_mask: str) -> Any:
        """kind: 'matrix' | 'route'. replay는 저장본만, live/record는 실제 호출. 실패하면 RouteUnavailable."""
        if self.mode == "replay":
            path = self.fixture_path(kind, key)
            if not path.exists():
                self.store.add_usage("replay_miss")
                raise RouteUnavailable("replay 모드: 이 요청의 저장된 응답이 없어요 (ROUTE_MODE=record로 녹화하세요)")
            self.store.add_usage("replay_hit")
            return json.loads(path.read_text(encoding="utf-8"))["response"]

        if not self.api_key:
            raise RouteUnavailable("GOOGLE_ROUTES_KEY가 설정되지 않았어요")
        with self._lock:
            if self._clock() < self._blocked_until:
                raise RouteUnavailable(self._blocked_reason)

        attempts = 1 + self.s.max_retries
        failure: ApiFailure | None = None
        for attempt in range(attempts):
            self.store.add_usage(kind)  # 시도마다 센다
            try:
                response = self._post(url, body, field_mask)
            except ApiFailure as f:
                failure = f
                self.store.add_usage("error")
                logger.warning("Google Routes %s 실패(%s): %s [시도 %d/%d]", kind, f.kind, f.message, attempt + 1, attempts)
                if f.blocks:
                    with self._lock:
                        self._blocked_until = self._clock() + self.s.cooldown_seconds
                        self._blocked_reason = f"{f.message} (이후 {int(self.s.cooldown_seconds)}초간 Google 호출 중단)"
                if not f.retryable or attempt == attempts - 1:
                    break
                self._sleep(self.s.backoff_seconds)
                continue
            if self.mode == "record":
                self._save_fixture(kind, key, body, response)
            return response
        raise RouteUnavailable(failure.message if failure else "알 수 없는 오류")

    def _post(self, url: str, body: dict, field_mask: str) -> Any:
        try:
            r = self._http.post(url, json=body, headers={
                "X-Goog-Api-Key": self.api_key, "X-Goog-FieldMask": field_mask, "Content-Type": "application/json"})
        except httpx.HTTPError:
            raise classify_failure(None, None) from None  # 예외 메시지에 키가 든 URL이 섞일 수 있어 버린다
        try:
            data = r.json() if r.content else {}
        except ValueError:
            data = {}
        if r.status_code != 200:
            raise classify_failure(r.status_code, data if isinstance(data, dict) else {})
        return data

    def _save_fixture(self, kind: str, key: str, body: dict, response: Any) -> None:
        self.fixtures_dir.mkdir(parents=True, exist_ok=True)
        payload = {"kind": kind, "key": key, "recordedAt": datetime.now(timezone.utc).isoformat(),
                   "request": {k: v for k, v in body.items() if k != "key"}, "response": response}
        self.fixture_path(kind, key).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


# ----------------------------------------------------------------------------- 프로바이더
def _waypoint(c: Coord) -> dict:
    return {"waypoint": {"location": {"latLng": {"latitude": c.lat, "longitude": c.lng}}}}


class GoogleRouteProvider(RouteProvider):
    name = "google"

    def __init__(self, client: GoogleClient, settings: GoogleSettings):
        self.client, self.s = client, settings
        self._flight = SingleFlight()

    @property
    def mode(self) -> str:
        return self.client.mode

    def _body(self, meeting_time: datetime) -> dict:
        """약속 시간에 도착하는 기준(arrivalTime)으로 요청한다. 그래야 참여자별 출발 시각이 나온다."""
        return {"travelMode": "TRANSIT", "regionCode": "KR",
                "arrivalTime": meeting_time.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "transitPreferences": {"allowedTravelModes": list(self.s.transit_modes)}}

    # --- 1단계 확인용: 상위 후보까지의 실제 소요시간 (검색당 최대 1회) -----------------
    def matrix(self, origins: Sequence[Coord], destinations: Sequence[Station], meeting_time: datetime) -> MatrixResult:
        band = time_band(meeting_time)
        result = MatrixResult(minutes=[[None] * len(destinations) for _ in origins])
        pair_keys = [[f"m|{coord_key(o)}|{d.id}|{band}" for d in destinations] for o in origins]
        use_cache = self.client.mode == "live"

        if use_cache:  # 모든 칸이 캐시에 있으면 호출하지 않는다
            cached = [[self.client.store.get(k, self.s.cache_ttl_days) for k in row] for row in pair_keys]
            if all(c is not None for row in cached for c in row):
                for i, row in enumerate(cached):
                    for j, c in enumerate(row):
                        result.minutes[i][j] = c["minutes"]
                result.cache_hits = len(origins) * len(destinations)
                self.client.store.add_usage("cache_hit", result.cache_hits)
                return result

        request_key = "matrix|" + ";".join(coord_key(o) for o in origins) + "|" + ",".join(d.id for d in destinations) + "|" + band
        body = {**self._body(meeting_time), "origins": [_waypoint(o) for o in origins],
                "destinations": [_waypoint(d.coord) for d in destinations]}

        def fetch() -> Any:
            return self.client.call("matrix", request_key, MATRIX_URL, body, MATRIX_FIELD_MASK)

        calls_before = self.client.store.usage().get("matrix", 0)
        try:
            elements = self._flight.do(request_key, fetch)
        except RouteUnavailable as e:
            result.error = str(e)
            return result
        result.api_calls = max(0, self.client.store.usage().get("matrix", 0) - calls_before) if self.client.mode != "replay" else 0

        for el in elements if isinstance(elements, list) else []:
            i, j = el.get("originIndex", 0), el.get("destinationIndex", 0)
            ok = el.get("condition") == "ROUTE_EXISTS" and el.get("duration") and not (el.get("status") or {}).get("code")
            if not ok or i >= len(origins) or j >= len(destinations):
                continue
            minutes = _seconds(el["duration"])
            result.minutes[i][j] = minutes
            if use_cache:
                self.client.store.put(pair_keys[i][j], {"minutes": minutes})
        return result

    # --- 참여자 이름을 눌렀을 때: 상세 경로 -------------------------------------------
    def route(self, origin: Coord, destination: Station, meeting_time: datetime) -> Route:
        key = f"r|{coord_key(origin)}|{destination.id}|{time_band(meeting_time)}"
        use_cache = self.client.mode == "live"

        def fetch() -> Route:
            if use_cache:
                hit = self.client.store.get(key, self.s.cache_ttl_days)
                if hit is not None:
                    self.client.store.add_usage("cache_hit")
                    return route_from_dict(hit)
            body = {**self._body(meeting_time), "origin": _waypoint(origin)["waypoint"],
                    "destination": _waypoint(destination.coord)["waypoint"], "languageCode": "ko"}
            response = self.client.call("route", key, ROUTES_URL, body, ROUTES_FIELD_MASK)
            route = convert_route(response, origin, destination.coord, self.s.utc_offset_hours)
            if use_cache:
                self.client.store.put(key, route_to_dict(route))
            return route

        return self._flight.do(key, fetch)
