"""전체 추천 흐름: 지역 추천(RegionScore) → 지역별 장소 수집 → 상위 5곳 평점 조회 → PlaceScore."""

import logging
from collections import Counter
from typing import Sequence

from app.config import PlaceConfig, RegionConfig
from app.recommend import recommend_regions
from app.schemas import (
    AgePreferenceMeta,
    PlaceComponentsOut,
    PlaceOut,
    PlaceWeightsOut,
    RatingMeta,
    RecommendMeta,
    RecommendResponse,
    RegionRecommendRequest,
    RegionWithPlacesOut,
)
from app.scoring.place import (
    PlaceFeatures,
    PlaceScoreResult,
    age_fit,
    keyword_fit,
    reason_line,
    score_place,
)
from app.services.place_search import Place, PlaceSearchError, PlaceService
from app.services.rating import RatingResult, RatingService
from app.services.travel_time import TravelTimeService
from app.stations import Station

logger = logging.getLogger(__name__)


def _features(place: Place, purpose_fit: float, age: float, rating: RatingResult | None) -> PlaceFeatures:
    return PlaceFeatures(
        distance_m=place.distance_m, purpose_fit=purpose_fit, age_fit=age,
        rating=rating.rating if rating else None,
        review_count=rating.review_count if rating else None,
    )


def _sort_key(item: tuple[Place, PlaceScoreResult, object]):
    place, result, _ = item
    return (-result.score, place.distance_m, place.id)


def rank_places(
    places: Sequence[Place],
    station: Station,
    request: RegionRecommendRequest,
    place_config: PlaceConfig,
    rating_service: RatingService,
    rating_counts: Counter,
) -> list[PlaceOut]:
    """후보 장소를 평점 없이 1차 점수화 → 상위 N곳만 평점 조회 → 평점 포함 최종 점수로 정렬."""
    rule = place_config.purposes[request.purpose]
    if rule.category_name_contains:
        places = [p for p in places if rule.category_name_contains in p.category_name]

    ages = [p.age_group for p in request.participants]
    fits = {
        p.id: (
            keyword_fit(p.category_name, rule.fit_keywords, rule.fit_default),
            age_fit(p.category_name, ages, place_config.age.groups),
        )
        for p in places
    }
    weights, params = place_config.weights, place_config.params

    # 1차: 평점 없이 점수를 매겨 평점을 조회할 상위 N곳을 고른다 (구글 호출은 이 N곳뿐).
    first_pass = [
        (p, score_place(_features(p, *fits[p.id], None), weights, params), None) for p in places
    ]
    shortlist = [p for p, _, _ in sorted(first_pass, key=_sort_key)[: place_config.top_n]]

    final = []
    for place in shortlist:
        rating = rating_service.get_rating(place, station.name)
        rating_counts[rating.status] += 1
        result = score_place(_features(place, *fits[place.id], rating), weights, params)
        final.append((place, result, rating))

    out = []
    for rank, (place, result, rating) in enumerate(sorted(final, key=_sort_key), 1):
        out.append(PlaceOut(
            rank=rank, id=place.id, name=place.name, category=place.category_name,
            address=place.address, lat=place.lat, lng=place.lng, distance_m=place.distance_m,
            url=place.url, phone=place.phone, score=round(result.score, 4),
            components=PlaceComponentsOut(**{
                k: (round(v, 4) if v is not None else None) for k, v in result.components.items()
            }),
            weights_used={k: round(v, 4) for k, v in result.weights_used.items()},
            rating=rating.rating, review_count=rating.review_count, rating_status=rating.status,
            age_fit_assumed=place_config.age.is_assumed,
            reason=reason_line(place.distance_m, rating.rating, rating.review_count,
                               params.walk_m_per_min),
        ))
    return out


def recommend_with_places(
    request: RegionRecommendRequest,
    travel_service: TravelTimeService,
    place_service: PlaceService,
    rating_service: RatingService,
    stations: Sequence[Station],
    region_config: RegionConfig,
    place_config: PlaceConfig,
) -> RecommendResponse:
    base = recommend_regions(request, travel_service, stations, region_config)
    by_id = {s.id: s for s in stations}
    rule = place_config.purposes[request.purpose]

    rating_counts: Counter = Counter()
    warnings: list[str] = []
    regions = []
    for region in base.regions:
        station = by_id[region.station.id]
        try:
            places = place_service.search_nearby(station, rule.category_code)
            ranked = rank_places(places, station, request, place_config, rating_service, rating_counts)
            if not ranked:
                warnings.append(f"{station.name}: 조건에 맞는 장소가 없습니다.")
        except PlaceSearchError as e:
            warnings.append(f"{station.name}: 장소 검색 실패 - {e}")
            ranked = []
        regions.append(RegionWithPlacesOut(**region.model_dump(), places=ranked))

    age = place_config.age
    return RecommendResponse(
        regions=regions,
        meta=RecommendMeta(
            **base.meta.model_dump(),
            place_source=place_service.source,
            place_weights=PlaceWeightsOut(**place_config.weights.as_dict()),
            age_preference=AgePreferenceMeta(source=age.source, is_assumed=age.is_assumed, note=age.note),
            ratings=RatingMeta(
                source=rating_service.source, requested=sum(rating_counts.values()),
                status_counts=dict(rating_counts),
            ),
            place_warnings=warnings,
        ),
    )
