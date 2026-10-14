"""지역 추천 흐름: 후보 선정 → 이동시간 조회 → RegionScore → 응답 구성."""

from typing import Sequence

from app.config import RegionConfig
from app.geo import Coord, centroid
from app.schemas import (
    ExcludedStationOut,
    LatLng,
    MetricRanksOut,
    MetricsOut,
    NormalizedOut,
    ParticipantTravelOut,
    RegionOut,
    RegionRecommendMeta,
    RegionRecommendRequest,
    RegionRecommendResponse,
    StationOut,
    WeightsOut,
)
from app.scoring.region import RegionScore, score_regions
from app.services.travel_time import TravelTimeService, TravelTimeUnavailable
from app.stations import Station, nearest_stations


class NoReachableRegionError(Exception):
    """모든 후보 역에 대해 이동시간을 구하지 못했을 때."""


def _rank_by(scores: Sequence[RegionScore], attr: str) -> dict[str, int]:
    ordered = sorted(scores, key=lambda r: (getattr(r.metrics, attr), r.region_id))
    return {r.region_id: i for i, r in enumerate(ordered, 1)}


def recommend_regions(
    request: RegionRecommendRequest,
    service: TravelTimeService,
    stations: Sequence[Station],
    config: RegionConfig,
) -> RegionRecommendResponse:
    origins = [Coord(p.lat, p.lng) for p in request.participants]
    center = centroid(origins)
    candidates = nearest_stations(stations, center, config.candidate_k)

    travel_minutes: dict[str, list[float]] = {}
    excluded: list[ExcludedStationOut] = []
    for station in candidates:
        times: list[float] = []
        reason: str | None = None
        for participant, origin in zip(request.participants, origins):
            try:
                times.append(service.get_minutes(origin, station))
            except TravelTimeUnavailable as e:
                # 한 명이라도 경로가 없으면 남은 호출을 아끼고 이 역을 후보에서 뺀다.
                reason = f"{participant.name} 출발: {e}"
                break
        if reason is None:
            travel_minutes[station.id] = times
        else:
            excluded.append(ExcludedStationOut(station=station.name, reason=reason))

    if not travel_minutes:
        raise NoReachableRegionError("이동시간을 계산할 수 있는 후보 지역이 없습니다.")

    scores = score_regions(travel_minutes, config.weights)
    ranks = {attr: _rank_by(scores, attr) for attr in ("avg", "max", "std")}
    by_id = {s.id: s for s in candidates}

    regions = [
        RegionOut(
            rank=i,
            station=StationOut(
                id=st.id, name=st.name, lat=st.coord.lat, lng=st.coord.lng, lines=list(st.lines),
            ),
            score=round(r.score, 4),
            metrics=MetricsOut(
                avg_minutes=round(r.metrics.avg, 1),
                max_minutes=round(r.metrics.max, 1),
                std_minutes=round(r.metrics.std, 1),
            ),
            normalized=NormalizedOut(
                avg=round(r.normalized.avg, 4),
                max=round(r.normalized.max, 4),
                std=round(r.normalized.std, 4),
            ),
            metric_ranks=MetricRanksOut(**{a: ranks[a][r.region_id] for a in ranks}),
            participants=[
                ParticipantTravelOut(name=p.name, minutes=round(m, 1))
                for p, m in zip(request.participants, r.minutes)
            ],
        )
        for i, r in enumerate(scores[: config.top_n], 1)
        for st in [by_id[r.region_id]]
    ]

    w = config.weights
    return RegionRecommendResponse(
        regions=regions,
        meta=RegionRecommendMeta(
            purpose=request.purpose,
            centroid=LatLng(lat=round(center.lat, 6), lng=round(center.lng, 6)),
            candidate_count=len(candidates),
            evaluated_count=len(travel_minutes),
            excluded_stations=excluded,
            weights=WeightsOut(avg=w.avg, max=w.max, std=w.std),
            travel_source=service.source,
        ),
    )
