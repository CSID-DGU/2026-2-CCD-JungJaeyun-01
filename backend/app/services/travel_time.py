"""이동시간 서비스: 인터페이스 + mock 구현 + ODsay 실제 구현."""

import logging
from abc import ABC, abstractmethod

import httpx2 as httpx

from app.config import TravelParams
from app.geo import Coord, haversine_km
from app.stations import Station

logger = logging.getLogger(__name__)


class TravelTimeService(ABC):
    """출발지 → 역 대중교통 이동시간(분). 경로를 구할 수 없으면 None."""

    source: str

    @abstractmethod
    def get_minutes(self, origin: Coord, station: Station) -> float | None: ...


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

    def get_minutes(self, origin: Coord, station: Station) -> float | None:
        return estimate_transit_minutes(haversine_km(origin, station.coord), self.params)


class OdsayTravelTimeService(TravelTimeService):
    """ODsay searchPubTransPathT. 검색된 경로 중 최단 totalTime을 사용한다."""

    source = "odsay"
    URL = "https://api.odsay.com/v1/api/searchPubTransPathT"
    # 출발지와 도착지가 700m 이내면 ODsay는 경로 대신 이 에러 코드를 준다 → 도보로 계산
    TOO_CLOSE_CODE = "-98"

    def __init__(self, api_key: str, params: TravelParams, timeout: float = 10.0,
                 client: httpx.Client | None = None):
        if not api_key:
            raise ValueError("ODSAY_API_KEY가 설정되지 않았습니다.")
        self._api_key = api_key
        self.params = params
        self._client = client or httpx.Client(timeout=timeout)
        self.call_count = 0

    def get_minutes(self, origin: Coord, station: Station) -> float | None:
        self.call_count += 1
        try:
            r = self._client.get(self.URL, params={
                "SX": origin.lng, "SY": origin.lat,
                "EX": station.coord.lng, "EY": station.coord.lat,
                "apiKey": self._api_key,
            })
            r.raise_for_status()
            body = r.json()
        except (httpx.HTTPError, ValueError) as e:
            # 예외 메시지에는 apiKey가 든 URL이 포함될 수 있으므로 타입만 남긴다.
            logger.warning("ODsay 요청 실패 (%s → %s): %s", origin, station.name, type(e).__name__)
            return None

        if "error" in body:
            code, msg = _odsay_error(body["error"])
            if code == self.TOO_CLOSE_CODE:
                return walking_minutes(haversine_km(origin, station.coord), self.params)
            logger.warning("ODsay 에러 (%s → %s): %s %s", origin, station.name, code, msg)
            return None

        paths = body.get("result", {}).get("path") or []
        if not paths:
            return None
        return float(min(p["info"]["totalTime"] for p in paths))


def _odsay_error(error: object) -> tuple[str, str]:
    # ODsay는 {"code", "msg"} 객체 또는 [{"code", "message"}] 배열 두 형태로 에러를 준다.
    item = error[0] if isinstance(error, list) and error else error
    if not isinstance(item, dict):
        return "", str(error)
    return str(item.get("code", "")), str(item.get("msg") or item.get("message") or "")
