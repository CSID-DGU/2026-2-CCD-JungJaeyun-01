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


class RegionRecommendMeta(BaseModel):
    purpose: Purpose
    centroid: LatLng
    candidate_count: int
    evaluated_count: int
    excluded_stations: list[str]
    weights: WeightsOut
    travel_source: str


class RegionRecommendResponse(BaseModel):
    regions: list[RegionOut]
    meta: RegionRecommendMeta
