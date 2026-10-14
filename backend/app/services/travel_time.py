"""이동시간 서비스: 인터페이스 + mock 구현 + ODsay 실제 구현."""

import logging
import time
from abc import ABC, abstractmethod
from typing import Callable, Sequence

import httpx2 as httpx

from app.config import TravelParams
from app.geo import Coord, haversine_km
from app.stations import Station

logger = logging.getLogger(__name__)


class TravelTimeUnavailable(Exception):
    """경로를 구하지 못했다. str(e)가 사용자에게 보여줄 사유다."""


class TravelTimeService(ABC):
    """출발지 → 역 대중교통 이동시간(분). 구하지 못하면 TravelTimeUnavailable."""

    source: str

    @abstractmethod
    def get_minutes(self, origin: Coord, station: Station) -> float: ...


def walking_minutes(straight_km: float, params: TravelParams) -> float:
    return straight_km * params.detour_factor / params.walk_speed_kmh * 60


def estimate_transit_minutes(straight_km: float, params: TravelParams) -> float:
    """직선거리 기반 대중교통 소요시간 추정: 접근시간 + 주행시간 + 환승 페널티."""
    if straight_km < params.walk_threshold_km:
        return walking_minutes(straight_km, params)
    route_km = straight_km * params.detour_factor
    transfers = min(params.max_transfers, int(route_km // params.transfer_every_km))
    return (params.access_minutes
            + route_km / params.transit_speed_kmh * 60
            + transfers * params.transfer_penalty_minutes)


class MockTravelTimeService(TravelTimeService):
    source = "mock"

    def __init__(self, params: TravelParams):
        self.params = params

    def get_minutes(self, origin: Coord, station: Station) -> float:
        return estimate_transit_minutes(haversine_km(origin, station.coord), self.params)


class OdsayTravelTimeService(TravelTimeService):
    """ODsay searchPubTransPathT. 검색된 경로 중 최단 totalTime을 사용한다.

    - 호출은 항상 순차적이며, 실제 HTTP 요청 사이에 min_interval 초 이상 간격을 둔다.
    - 429(일일 한도/요청 과다)는 retry_delays 만큼 대기하며 재시도한다 (기본 1초, 2초 → 최대 2회).
    - 그래도 실패하면 TravelTimeUnavailable. 호출자가 해당 역을 후보에서 뺀다.
    """

    source = "odsay"
    URL = "https://api.odsay.com/v1/api/searchPubTransPathT"
    # 출발지와 도착지가 700m 이내면 ODsay는 경로 대신 이 에러 코드를 준다 → 도보로 계산
    TOO_CLOSE_CODE = "-98"
    NO_RESULT_CODE = "-99"
    RATE_LIMIT_CODE = "429"

    def __init__(
        self,
        api_key: str,
        params: TravelParams,
        timeout: float = 10.0,
        client: httpx.Client | None = None,
        min_interval: float = 0.3,
        retry_delays: Sequence[float] = (1.0, 2.0),
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        if not api_key:
            raise ValueError("ODSAY_API_KEY가 설정되지 않았습니다.")
        self._api_key = api_key
        self.params = params
        self._client = client or httpx.Client(timeout=timeout)
        self._min_interval = min_interval
        self._retry_delays = tuple(retry_delays)
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: float | None = None
        self.http_calls = 0

    def get_minutes(self, origin: Coord, station: Station) -> float:
        body = self._request_with_retry(origin, station)

        if "error" in body:
            code, msg = _odsay_error(body["error"])
            if code == self.TOO_CLOSE_CODE:
                return walking_minutes(haversine_km(origin, station.coord), self.params)
            if code == self.NO_RESULT_CODE:
                raise TravelTimeUnavailable("ODsay: 검색 결과 없음")
            raise TravelTimeUnavailable(f"ODsay 에러 {code} {msg}".strip())

        paths = body.get("result", {}).get("path") or []
        if not paths:
            raise TravelTimeUnavailable("ODsay: 경로 없음")
        return float(min(p["info"]["totalTime"] for p in paths))

    def _request_with_retry(self, origin: Coord, station: Station) -> dict:
        body: dict = {}
        for attempt in range(len(self._retry_delays) + 1):
            body = self._request(origin, station)
            if _error_code(body) != self.RATE_LIMIT_CODE:
                return body
            if attempt < len(self._retry_delays):
                self._sleep(self._retry_delays[attempt])
        _, msg = _odsay_error(body["error"])
        raise TravelTimeUnavailable(
            f"ODsay 429 {msg} (재시도 {len(self._retry_delays)}회 후에도 실패)".replace("  ", " ")
        )

    def _request(self, origin: Coord, station: Station) -> dict:
        self._throttle()
        self.http_calls += 1
        try:
            r = self._client.get(self.URL, params={
                "SX": origin.lng, "SY": origin.lat,
                "EX": station.coord.lng, "EY": station.coord.lat,
                "apiKey": self._api_key,
            })
            if r.status_code == 429:
                return {"error": {"code": self.RATE_LIMIT_CODE, "msg": "HTTP 429"}}
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            # 예외 메시지에는 apiKey가 든 URL이 포함될 수 있으므로 타입만 남긴다.
            logger.warning("ODsay 요청 실패 (%s → %s): %s", origin, station.name, type(e).__name__)
            raise TravelTimeUnavailable(f"ODsay 요청 실패({type(e).__name__})") from None

    def _throttle(self) -> None:
        if self._last_request_at is not None:
            wait = self._min_interval - (self._clock() - self._last_request_at)
            if wait > 0:
                self._sleep(wait)
        self._last_request_at = self._clock()


def _odsay_error(error: object) -> tuple[str, str]:
    # ODsay는 {"code", "msg"} 객체 또는 [{"code", "message"}] 배열 두 형태로 에러를 준다.
    item = error[0] if isinstance(error, list) and error else error
    if not isinstance(item, dict):
        return "", str(error)
    return str(item.get("code", "")), str(item.get("msg") or item.get("message") or "")


def _error_code(body: dict) -> str | None:
    return _odsay_error(body["error"])[0] if "error" in body else None
