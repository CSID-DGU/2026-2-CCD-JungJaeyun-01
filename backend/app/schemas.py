"""API 요청·응답 스키마."""

from typing import Literal

from pydantic import BaseModel, Field

AgeGroup = Literal["10s", "20s", "30s", "40s", "50s+"]
Purpose = Literal["meal", "cafe", "drink"]  # 식사, 카페, 술자리


class ParticipantIn(BaseModel):
    name: str = Field(min_length=1, max_length=20)
    lat: float = Field(ge=33.0, le=39.0, description="출발지 위도")
    lng: float = Field(ge=124.0, le=132.0, description="출발지 경도")
    age_group: AgeGroup


class RegionRecommendRequest(BaseModel):
    participants: list[ParticipantIn] = Field(min_length=2, max_length=5)
    purpose: Purpose


class LatLng(BaseModel):
    lat: float
    lng: float


class StationOut(BaseModel):
    id: str
    name: str
    lat: float
    lng: float
    lines: list[str]


class MetricsOut(BaseModel):
    avg_minutes: float
    max_minutes: float
    std_minutes: float


class NormalizedOut(BaseModel):
    """후보 지역 간 min-max 정규화 값. 0 = 후보 중 가장 좋음, 1 = 가장 나쁨."""

    avg: float
    max: float
    std: float


class MetricRanksOut(BaseModel):
    """평가한 후보 지역 중 각 지표의 순위 (1 = 가장 좋음)."""

    avg: int
    max: int
    std: int


class ParticipantTravelOut(BaseModel):
    name: str
    minutes: float


class RegionOut(BaseModel):
    rank: int
    station: StationOut
    score: float
    metrics: MetricsOut
    normalized: NormalizedOut
    metric_ranks: MetricRanksOut
    participants: list[ParticipantTravelOut]


class WeightsOut(BaseModel):
    avg: float
    max: float
    std: float


class ExcludedStationOut(BaseModel):
    station: str
    reason: str


class RegionRecommendMeta(BaseModel):
    purpose: Purpose
    centroid: LatLng
    candidate_count: int
    evaluated_count: int
    excluded_stations: list[ExcludedStationOut]
    weights: WeightsOut
    travel_source: str


class RegionRecommendResponse(BaseModel):
    regions: list[RegionOut]
    meta: RegionRecommendMeta


# --------------------------------------------------------------------------- 장소 추천
class PlaceComponentsOut(BaseModel):
    """PlaceScore 항목별 점수(0~1). 평점 데이터가 없으면 rating·popularity는 null."""

    accessibility: float
    rating: float | None
    popularity: float | None
    purpose: float
    age: float


class PlaceWeightsOut(BaseModel):
    accessibility: float
    rating: float
    popularity: float
    purpose: float
    age: float


class PlaceOut(BaseModel):
    rank: int
    id: str
    name: str
    category: str
    address: str
    lat: float
    lng: float
    distance_m: float
    url: str
    phone: str
    score: float
    components: PlaceComponentsOut
    weights_used: dict[str, float]  # 재정규화 후 실제 적용된 가중치
    rating: float | None
    review_count: int | None
    rating_status: str
    age_fit_assumed: bool           # 연령대 적합성이 임의값 기반인지
    reason: str


class RegionWithPlacesOut(RegionOut):
    places: list[PlaceOut]


class AgePreferenceMeta(BaseModel):
    source: str
    is_assumed: bool
    note: str


class RatingMeta(BaseModel):
    source: str
    requested: int
    status_counts: dict[str, int]


class RecommendMeta(RegionRecommendMeta):
    place_source: str
    place_weights: PlaceWeightsOut
    age_preference: AgePreferenceMeta
    ratings: RatingMeta
    place_warnings: list[str]


class RecommendResponse(BaseModel):
    regions: list[RegionWithPlacesOut]
    meta: RecommendMeta
