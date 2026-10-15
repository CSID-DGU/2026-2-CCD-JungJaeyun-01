from functools import lru_cache
from typing import Literal

import httpx2 as httpx
from fastapi import APIRouter, Depends, Query

from app import settings
from app.services.realtime import BusRealtime, RealtimeResult, SubwayRealtime, TtlCache, none
from app.subway import load_network

router = APIRouter(prefix="/api", tags=["realtime"])


@lru_cache
def get_realtime() -> tuple[SubwayRealtime, BusRealtime]:
    cache = TtlCache(settings.REALTIME_TTL_SECONDS)  # 같은 요청은 30초 동안 한 번만 호출
    http = httpx.Client(timeout=4)
    return (SubwayRealtime(settings.SEOUL_SUBWAY_API_KEY, http, cache, load_network()),
            BusRealtime(settings.SEOUL_BUS_API_KEY, http, cache))


@router.get("/realtime")
def get_arrivals(
    type: Literal["subway", "bus"],
    station: str | None = Query(None, max_length=40, description="subway: 승차역 이름"),
    line: str | None = Query(None, max_length=20, description="subway: 호선(2호선) / bus: 노선 번호(741)"),
    headsign: str | None = Query(None, max_length=40, description="subway: 방면(종착역)"),
    next: str | None = Query(None, max_length=40, description="subway: 승차역 다음 역 (순환선 방향 구분용)"),
    lat: float | None = None, lng: float | None = None,
    stop: str | None = Query(None, max_length=40, description="bus: 정류소 이름"),
    services: tuple[SubwayRealtime, BusRealtime] = Depends(get_realtime),
) -> dict:
    """다음 열차/버스 도착 정보(최대 2개). 실패·서울 밖·키 없음은 오류가 아니라 available=false로 돌려준다."""
    subway, bus = services
    result: RealtimeResult
    try:
        if type == "subway":
            result = subway.arrivals(station, line, headsign, next) if station and line else none("파라미터 부족")
        else:
            result = bus.arrivals(lat, lng, stop, line) if None not in (lat, lng, stop, line) else none("파라미터 부족")
    except Exception:  # noqa: BLE001 - 실시간은 부가 기능이라 어떤 실패도 화면을 깨지 않는다
        result = none("내부 오류")
    return result.to_dict()
