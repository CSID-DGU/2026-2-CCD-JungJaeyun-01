from fastapi import APIRouter, Depends, HTTPException

from app.config import RegionConfig, load_region_config
from app.recommend import NoReachableRegionError, recommend_regions
from app.schemas import RegionRecommendRequest, RegionRecommendResponse
from app.services import get_travel_time_service
from app.services.travel_time import TravelTimeService
from app.stations import Station, load_stations

router = APIRouter(prefix="/api/recommend", tags=["recommend"])


def get_stations() -> tuple[Station, ...]:
    return load_stations()


@router.post("/regions", response_model=RegionRecommendResponse)
def post_recommend_regions(
    request: RegionRecommendRequest,
    service: TravelTimeService = Depends(get_travel_time_service),
    stations: tuple[Station, ...] = Depends(get_stations),
    config: RegionConfig = Depends(load_region_config),
) -> RegionRecommendResponse:
    try:
        return recommend_regions(request, service, stations, config)
    except NoReachableRegionError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
