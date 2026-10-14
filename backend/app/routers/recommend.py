from fastapi import APIRouter, Depends

from app.config import PlaceConfig, RegionConfig, load_place_config, load_region_config
from app.place_recommend import recommend_with_places
from app.recommend import recommend_regions
from app.schemas import (
    RecommendResponse,
    RegionRecommendRequest,
    RegionRecommendResponse,
)
from app.services import get_place_service, get_rating_service, get_travel_time_service
from app.services.place_search import PlaceService
from app.services.rating import RatingService
from app.services.travel_time import TravelTimeService
from app.stations import Station, load_stations

router = APIRouter(prefix="/api/recommend", tags=["recommend"])


def get_stations() -> tuple[Station, ...]:
    return load_stations()


@router.post("", response_model=RecommendResponse)
def post_recommend(
    request: RegionRecommendRequest,
    travel_service: TravelTimeService = Depends(get_travel_time_service),
    place_service: PlaceService = Depends(get_place_service),
    rating_service: RatingService = Depends(get_rating_service),
    stations: tuple[Station, ...] = Depends(get_stations),
    region_config: RegionConfig = Depends(load_region_config),
    place_config: PlaceConfig = Depends(load_place_config),
) -> RecommendResponse:
    """상위 3개 지역 + 지역별 이동시간 지표 + 지역별 상위 5개 장소를 한 번에 반환한다."""
    return recommend_with_places(request, travel_service, place_service, rating_service,
                                 stations, region_config, place_config)


@router.post("/regions", response_model=RegionRecommendResponse)
def post_recommend_regions(
    request: RegionRecommendRequest,
    service: TravelTimeService = Depends(get_travel_time_service),
    stations: tuple[Station, ...] = Depends(get_stations),
    config: RegionConfig = Depends(load_region_config),
) -> RegionRecommendResponse:
    """지역(역) 추천만 필요할 때."""
    return recommend_regions(request, service, stations, config)
