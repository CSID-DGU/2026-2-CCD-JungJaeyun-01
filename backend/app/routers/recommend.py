import logging

from fastapi import APIRouter, Depends, HTTPException

from app import settings
from app.config import PlaceConfig, RegionConfig, load_place_config, load_region_config
from app.geo import Coord
from app.place_recommend import recommend_with_places
from app.providers.base import RouteProvider, RouteUnavailable
from app.recommend import recommend_regions
from app.route_model import route_to_dict
from app.schemas import (
    RecommendResponse,
    RegionRecommendRequest,
    RegionRecommendResponse,
    RouteOut,
    RouteRequest,
    RouteResponse,
)
from app.services import get_estimator, get_place_service, get_rating_service, get_route_provider, get_routes_store
from app.services.place_search import PlaceService
from app.services.rating import RatingService
from app.services.routes_store import RoutesStore, today
from app.stations import Station, load_stations
from app.subway import TravelEstimator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/recommend", tags=["recommend"])
route_router = APIRouter(prefix="/api", tags=["route"])


def get_stations() -> tuple[Station, ...]:
    return load_stations()


@router.post("", response_model=RecommendResponse)
def post_recommend(
    request: RegionRecommendRequest,
    estimator: TravelEstimator = Depends(get_estimator),
    provider: RouteProvider = Depends(get_route_provider),
    place_service: PlaceService = Depends(get_place_service),
    rating_service: RatingService = Depends(get_rating_service),
    stations: tuple[Station, ...] = Depends(get_stations),
    region_config: RegionConfig = Depends(load_region_config),
    place_config: PlaceConfig = Depends(load_place_config),
) -> RecommendResponse:
    """1단계(추정, API 0회) → 상위 3곳만 2단계(경로 API, 최대 1회)로 확인한 지역 + 지역별 장소 5곳."""
    return recommend_with_places(request, estimator, provider, place_service, rating_service,
                                 stations, region_config, place_config)


@router.post("/regions", response_model=RegionRecommendResponse)
def post_recommend_regions(
    request: RegionRecommendRequest,
    estimator: TravelEstimator = Depends(get_estimator),
    provider: RouteProvider = Depends(get_route_provider),
    stations: tuple[Station, ...] = Depends(get_stations),
    config: RegionConfig = Depends(load_region_config),
) -> RegionRecommendResponse:
    """지역(역) 추천만 필요할 때."""
    return recommend_regions(request, estimator, provider, stations, config)


@route_router.post("/route", response_model=RouteResponse)
def post_route(
    request: RouteRequest,
    estimator: TravelEstimator = Depends(get_estimator),
    provider: RouteProvider = Depends(get_route_provider),
    stations: tuple[Station, ...] = Depends(get_stations),
) -> RouteResponse:
    """참여자 한 명의 상세 경로. 사용자가 이름을 눌렀을 때만 호출한다 (캐시됨).

    경로 API가 실패하면 지하철 그래프 추정 경로(source='estimate')를 돌려주고 note에 이유를 적는다.
    """
    station = next((s for s in stations if s.id == request.station_id), None)
    if station is None:
        raise HTTPException(status_code=404, detail="알 수 없는 도착역입니다.")
    origin = Coord(request.lat, request.lng)
    try:
        return RouteResponse(route=RouteOut.model_validate(route_to_dict(provider.route(origin, station))))
    except RouteUnavailable as e:
        logger.warning("상세 경로 조회 실패, 추정 경로로 대체: %s", e)
        estimate = estimator.estimate_route(origin, station)
        if estimate is None:
            raise HTTPException(status_code=503, detail=f"경로를 구하지 못했어요: {e}") from e
        return RouteResponse(route=RouteOut.model_validate(route_to_dict(estimate)),
                             note=f"실제 경로 조회에 실패해 추정 경로를 보여줘요 ({e})")


@route_router.get("/dev/usage")
def get_usage(store: RoutesStore = Depends(get_routes_store), provider: RouteProvider = Depends(get_route_provider)) -> dict:
    """개발용: 오늘 경로 API 호출 수 (화면 구석 표시용)."""
    return {
        "day": today(), "provider": provider.name, "mode": settings.ROUTE_MODE,
        "counters": store.usage(),  # matrix, route, cache_hit, replay_hit, replay_miss, error, odsay
    }
