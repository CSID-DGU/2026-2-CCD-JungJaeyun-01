"""외부 API 연동 계층.

각 외부 API(ODsay, 카카오 로컬 등)는 이 패키지 아래에
인터페이스 + mock 구현 + 실제 구현으로 분리하고,
settings.USE_MOCK 값으로 어떤 구현을 쓸지 선택한다.
"""

from functools import lru_cache

from app import settings
from app.config import load_estimate_params, load_google_settings, load_place_config, load_travel_config
from app.services.place_search import (
    CachedPlaceService,
    KakaoPlaceService,
    MockPlaceService,
    PlaceService,
)
from app.services.places_cache import PlacesCache
from app.services.rating import GoogleRatingService, MockRatingService, RatingService
from app.services.routes_store import RoutesStore
from app.subway import TravelEstimator, load_network


@lru_cache
def get_routes_store() -> RoutesStore:
    return RoutesStore(settings.ROUTES_DB_PATH)


@lru_cache
def get_estimator() -> TravelEstimator:
    """1단계 이동시간 추정기 (지하철 그래프, API 호출 없음)."""
    return TravelEstimator(load_network(), load_estimate_params())


@lru_cache
def get_route_provider():
    """ROUTE_PROVIDER=google(기본) | odsay(기본 비활성화). Google은 ROUTE_MODE=live(기본)|record|replay(테스트용)를 따른다."""
    from app.providers.google import GoogleClient, GoogleRouteProvider
    from app.providers.odsay import OdsayClient, OdsayRouteProvider

    store = get_routes_store()
    if settings.ROUTE_PROVIDER == "odsay":
        travel = load_travel_config()
        client = OdsayClient(
            settings.ODSAY_API_KEY, travel.mock, timeout=travel.odsay_timeout_seconds,
            min_interval=travel.odsay_min_interval_seconds, retry_delays=travel.odsay_retry_delays_seconds,
            quota_cooldown=travel.odsay_quota_cooldown_seconds,
        )
        return OdsayRouteProvider(client, store)
    gs = load_google_settings()
    return GoogleRouteProvider(GoogleClient(settings.GOOGLE_ROUTES_KEY, settings.ROUTE_MODE, store, gs), gs)


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
