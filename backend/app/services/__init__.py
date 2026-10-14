"""외부 API 연동 계층.

각 외부 API(ODsay, 카카오 로컬 등)는 이 패키지 아래에
인터페이스 + mock 구현 + 실제 구현으로 분리하고,
settings.USE_MOCK 값으로 어떤 구현을 쓸지 선택한다.
"""

from functools import lru_cache

from app import settings
from app.config import load_place_config, load_travel_config
from app.services.place_search import (
    CachedPlaceService,
    KakaoPlaceService,
    MockPlaceService,
    PlaceService,
)
from app.services.places_cache import PlacesCache
from app.services.rating import GoogleRatingService, MockRatingService, RatingService
from app.services.travel_cache import CachedTravelTimeService, TravelTimeCache
from app.services.travel_time import (
    MockTravelTimeService,
    OdsayTravelTimeService,
    TravelTimeService,
)


@lru_cache
def get_travel_time_service() -> TravelTimeService:
    """USE_MOCK=true면 직선거리 추정, false면 ODsay + SQLite 캐시."""
    config = load_travel_config()
    if settings.USE_MOCK:
        return MockTravelTimeService(config.mock)
    odsay = OdsayTravelTimeService(
        api_key=settings.ODSAY_API_KEY,
        params=config.mock,
        timeout=config.odsay_timeout_seconds,
        min_interval=config.odsay_min_interval_seconds,
        retry_delays=config.odsay_retry_delays_seconds,
    )
    return CachedTravelTimeService(odsay, TravelTimeCache(settings.TRAVEL_CACHE_PATH))


@lru_cache
def get_place_service() -> PlaceService:
    """USE_MOCK=true면 고정 장소 데이터, false면 카카오 카테고리 검색 + SQLite 캐시."""
    cfg = load_place_config()
    if settings.USE_MOCK:
        return MockPlaceService(cfg.radius_m, cfg.max_results)
    kakao = KakaoPlaceService(settings.KAKAO_REST_API_KEY, cfg.radius_m, cfg.max_results)
    return CachedPlaceService(kakao, PlacesCache(settings.PLACES_CACHE_PATH),
                              cfg.radius_m, cfg.max_results, cfg.cache_ttl_days)


@lru_cache
def get_rating_service() -> RatingService:
    """USE_MOCK=true면 가짜 평점, false면 구글 Places(캐시 + 일일 호출 상한)."""
    if settings.USE_MOCK:
        return MockRatingService()
    g = load_place_config().google
    return GoogleRatingService(
        api_key=settings.GOOGLE_PLACES_API_KEY,
        cache=PlacesCache(settings.PLACES_CACHE_PATH),
        daily_limit=g.daily_limit,
        cache_ttl_days=g.cache_ttl_days,
        match_radius_m=g.match_radius_m,
    )
