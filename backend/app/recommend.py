"""지역 추천 흐름: 후보 선정 → 이동시간 조회 → RegionScore → 응답 구성."""

from typing import Sequence

from app.config import RegionConfig, load_travel_config
from app.geo import Coord, centroid
from app.schemas import (
    EstimatedTravelOut,
    LatLng,
    MetricRanksOut,
    MetricsOut,
    NormalizedOut,
    ParticipantTravelOut,
    RegionOut,
    RegionRecommendMeta,
    RegionRecommendRequest,
    RegionRecommendResponse,
    RouteLegOut,
    RouteOut,
    StationOut,
    WeightsOut,
)
from app.scoring.region import RegionMetrics, RegionScore, score_regions
from app.services.route import Route
from app.services.travel_time import MockTravelTimeService, TravelTimeService, TravelTimeUnavailable
from app.stations import Station, nearest_stations

_METRIC_LABELS = {"avg": "평균 이동시간", "max": "최대 이동시간", "std": "이동시간 편차"}


def _rank_by(scores: Sequence[RegionScore], attr: str) -> dict[str, int]:
    ordered = sorted(scores, key=lambda r: (getattr(r.metrics, attr), r.region_id))
    return {r.region_id: i for i, r in enumerate(ordered, 1)}


def region_reason(rank: int, metrics: RegionMetrics, metric_ranks: dict[str, int], evaluated: int) -> str:
    """지역 선정 이유 한 문장. 후보 중 1위인 지표가 있으면 그것을, 없으면 균형을 강조한다."""
    detail = f"평균 {metrics.avg:.0f}분 · 최대 {metrics.max:.0f}분 · 편차 {metrics.std:.1f}분"
    best = [_METRIC_LABELS[a] for a in ("avg", "max", "std") if metric_ranks[a] == 1]
    if best:
        return f"후보 {evaluated}곳 중 {', '.join(best)} 부문에서 가장 유리해 {rank}위로 선정했어요 ({detail})."
    ranks = " · ".join(f"{_METRIC_LABELS[a]} {metric_ranks[a]}위" for a in ("avg", "max", "std"))
    return f"{ranks}로 세 지표가 고르게 좋아 {rank}위로 선정했어요 ({detail})."


def _route_out(route: Route) -> RouteOut:
    return RouteOut(
        total_minutes=route.total_minutes,
        transfers=route.transfers,
        legs=[
            RouteLegOut(
                kind=leg.kind, minutes=leg.minutes, distance_m=leg.distance_m, label=leg.label,
                color=leg.color, from_name=leg.from_name, to_name=leg.to_name,
                stop_count=leg.stop_count,
                path=[LatLng(lat=c.lat, lng=c.lng) for c in leg.path],
            )
            for leg in route.legs
        ],
    )


def _participant_travel(
    service: TravelTimeService, name: str, origin: Coord, station: Station,
    minutes: float, is_estimated: bool,
) -> ParticipantTravelOut:
    """참여자 한 명의 이동시간 + 지도용 경로. 가짜 경로는 만들지 않고, 없으면 이유를 남긴다."""
    base = dict(name=name, minutes=round(minutes, 1), is_estimated=is_estimated)
    if is_estimated:
        return ParticipantTravelOut(**base, route_note="추정 경로 (실제 경로 조회 실패)")
    try:
        route = service.get_route(origin, station)  # 저장된 경로를 쓰며, 없을 때만 API를 한 번 부른다
    except TravelTimeUnavailable as e:
        return ParticipantTravelOut(**base, route_note=f"추정 경로 (경로 상세 조회 실패: {e})")
    if route is None:
        note = ("추정 경로 (mock 모드라 실제 경로 데이터가 없어요)" if service.source == "mock"
                else "추정 경로 (경로 상세 정보를 받지 못했어요)")
        return ParticipantTravelOut(**base, route_note=note)
    return ParticipantTravelOut(**base, route=_route_out(route))


def recommend_regions(
    request: RegionRecommendRequest,
    service: TravelTimeService,
    stations: Sequence[Station],
    config: RegionConfig,
    fallback: TravelTimeService | None = None,
) -> RegionRecommendResponse:
    """service로 이동시간을 구하고, 실패한 출발지-역 조합은 fallback(기본: mock의 거리 기반 추정)으로 대체한다.

    대체한 값은 is_estimated=True로 표시하며 캐시되지 않는다 (캐시는 service 쪽 래퍼가 성공 결과만 저장).
    """
    fallback = fallback or MockTravelTimeService(load_travel_config().mock)
    origins = [Coord(p.lat, p.lng) for p in request.participants]
    center = centroid(origins)
    candidates = nearest_stations(stations, center, config.candidate_k)

    travel_minutes: dict[str, list[float]] = {}
    estimated: dict[str, list[bool]] = {}
    estimated_log: list[EstimatedTravelOut] = []
    for station in candidates:
        times: list[float] = []
        flags: list[bool] = []
        for participant, origin in zip(request.participants, origins):
            try:
                times.append(service.get_minutes(origin, station))
                flags.append(False)
            except TravelTimeUnavailable as e:
                times.append(fallback.get_minutes(origin, station))
                flags.append(True)
                estimated_log.append(
                    EstimatedTravelOut(station=station.name, participant=participant.name, reason=str(e))
                )
        travel_minutes[station.id] = times
        estimated[station.id] = flags

    scores = score_regions(travel_minutes, config.weights)
    ranks = {attr: _rank_by(scores, attr) for attr in ("avg", "max", "std")}
    by_id = {s.id: s for s in candidates}

    regions = []
    for i, r in enumerate(scores[: config.top_n], 1):
        st = by_id[r.region_id]
        metric_ranks = {a: ranks[a][r.region_id] for a in ranks}
        regions.append(RegionOut(
            rank=i,
            station=StationOut(
                id=st.id, name=st.name, lat=st.coord.lat, lng=st.coord.lng, lines=list(st.lines),
            ),
            score=round(r.score, 4),
            reason=region_reason(i, r.metrics, metric_ranks, len(scores)),
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
            metric_ranks=MetricRanksOut(**metric_ranks),
            participants=[
                _participant_travel(service, p.name, origin, st, m, est)
                for p, origin, m, est in zip(request.participants, origins, r.minutes, estimated[r.region_id])
            ],
        ))

    w = config.weights
    return RegionRecommendResponse(
        regions=regions,
        meta=RegionRecommendMeta(
            purpose=request.purpose,
            centroid=LatLng(lat=round(center.lat, 6), lng=round(center.lng, 6)),
            candidate_count=len(candidates),
            evaluated_count=len(travel_minutes),
            estimated_travel=estimated_log,
            weights=WeightsOut(avg=w.avg, max=w.max, std=w.std),
            travel_source=service.source,
        ),
    )
