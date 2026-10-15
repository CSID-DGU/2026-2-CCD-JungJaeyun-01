"""API 요청·응답 스키마."""

from datetime import datetime
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
    # 약속 시간. 없으면 다음 토요일 오후 6시(KST). 이 시각에 도착하는 기준으로 경로를 구한다.
    meeting_time: datetime | None = None


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
    is_estimated: bool = False   # True면 경로 API 확인에 실패해 1단계 추정값을 쓴 것 ("추정" 표시)
    estimate_minutes: float | None = None  # 1단계 추정값 (참고용)


class RegionOut(BaseModel):
    rank: int
    station: StationOut
    score: float
    reason: str
    stage1_rank: int          # 1단계(그래프 추정) 순위. 최종 순위와 다르면 실제 경로(버스 포함)가 순위를 바꾼 것
    metrics: MetricsOut
    normalized: NormalizedOut
    metric_ranks: MetricRanksOut
    participants: list[ParticipantTravelOut]


class WeightsOut(BaseModel):
    avg: float
    max: float
    std: float


class AccuracyPairOut(BaseModel):
    participant: str
    station: str
    estimate_minutes: float
    actual_minutes: float
    diff_minutes: float      # 추정 - 실제


class AccuracyOut(BaseModel):
    """1단계 추정과 2단계 실제값의 차이 (추정 정확도 확인용)."""

    mae_minutes: float
    bias_minutes: float
    pairs: list[AccuracyPairOut]


class Phase2Out(BaseModel):
    status: Literal["ok", "failed", "skipped"]
    reason: str | None
    provider: str | None
    api_calls: int
    cache_hits: int
    candidates: int = 0      # 경로 API로 확인한 후보 수 (SHORTLIST_SIZE)


class RegionRecommendMeta(BaseModel):
    purpose: Purpose
    centroid: LatLng
    candidate_count: int
    evaluated_count: int
    weights: WeightsOut
    travel_source: str       # 최종 지역 이동시간의 출처: "google" | "odsay" | "estimate"
    meeting_time: str        # 실제로 쓴 약속 시간 (KST ISO 8601)
    phase2: Phase2Out
    estimate_accuracy: AccuracyOut | None


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
    weights_used: dict[str, float]  # 실제 적용된 가중치
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


# --------------------------------------------------------------------------- 상세 경로 (공통 스키마)
class RouteSegmentOut(BaseModel):
    mode: Literal["WALK", "SUBWAY", "BUS"]
    lineName: str | None
    lineColor: str | None
    from_: str | None = Field(default=None, alias="from")
    to: str | None
    minutes: float
    path: list[list[float]]   # [[lat, lng], ...]
    # 타임라인용 (없으면 null)
    distanceMeters: int | None = None
    departureTime: str | None = None
    arrivalTime: str | None = None
    headsign: str | None = None
    stopCount: int | None = None
    lineTextColor: str | None = None
    intermediateStops: list[str] | None = None
    intermediateStopsSource: str | None = None
    lineKind: str | None = None
    realtime: dict | None = None   # 실시간 도착 정보용 참조 (승·하차 정류장, 노선, 방면, 정류소 ID 자리)

    model_config = {"populate_by_name": True}


class RouteOut(BaseModel):
    totalMinutes: int
    transfers: int
    segments: list[RouteSegmentOut]
    source: Literal["google", "estimate", "odsay"]
    departureTime: str | None = None   # 집을 나서는 시각
    arrivalTime: str | None = None     # 도착지 도착 시각
    walkMinutes: float | None = None
    walkMeters: int | None = None


class RouteRequest(BaseModel):
    lat: float = Field(ge=33.0, le=39.0)
    lng: float = Field(ge=124.0, le=132.0)
    station_id: str
    meeting_time: datetime | None = None   # 없으면 기본 약속 시간


class RouteResponse(BaseModel):
    route: RouteOut
    note: str | None = None   # 추정 경로일 때 이유 등
