"""지역 추천 흐름 (2단계).

1단계 (API 호출 0): 후보 역 K곳에 대해 지하철 그래프로 참여자별 이동시간을 추정하고 RegionScore로 상위 3곳을 고른다.
2단계 (검색당 최대 1회 호출): 상위 3곳까지의 실제 소요시간을 경로 API(computeRouteMatrix)로 한 번에 받아
                            상위 3곳의 평균·최대·편차와 순위를 다시 계산한다. 실패한 칸은 1단계 추정값을 쓰고 '추정'으로 표시한다.
상세 경로(computeRoutes)는 여기서 부르지 않는다: 사용자가 참여자 이름을 누를 때만 /api/route에서 호출한다.
"""

import logging
from typing import Sequence

from app.config import RegionConfig
from app.geo import Coord, centroid
from app.providers.base import MatrixResult, RouteProvider
from app.schemas import (
    AccuracyOut,
    AccuracyPairOut,
    LatLng,
    MetricRanksOut,
    MetricsOut,
    NormalizedOut,
    ParticipantTravelOut,
    Phase2Out,
    RegionOut,
    RegionRecommendMeta,
    RegionRecommendRequest,
    RegionRecommendResponse,
    StationOut,
    WeightsOut,
)
from app.scoring.region import RegionMetrics, RegionScore, score_regions
from app.stations import Station, nearest_stations
from app.subway import TravelEstimator

logger = logging.getLogger(__name__)

_METRIC_LABELS = {"avg": "평균 이동시간", "max": "최대 이동시간", "std": "이동시간 편차"}


def _rank_by(scores: Sequence[RegionScore], attr: str) -> dict[str, int]:
    ordered = sorted(scores, key=lambda r: (getattr(r.metrics, attr), r.region_id))
    return {r.region_id: i for i, r in enumerate(ordered, 1)}


def region_reason(rank: int, metrics: RegionMetrics, metric_ranks: dict[str, int], pool: str) -> str:
    """지역 선정 이유 한 문장. 1위인 지표가 있으면 그것을, 없으면 균형을 강조한다. pool: 비교 대상 설명."""
    detail = f"평균 {metrics.avg:.0f}분 · 최대 {metrics.max:.0f}분 · 편차 {metrics.std:.1f}분"
    best = [_METRIC_LABELS[a] for a in ("avg", "max", "std") if metric_ranks[a] == 1]
    if best:
        return f"{pool} {', '.join(best)} 부문에서 가장 유리해 {rank}위로 선정했어요 ({detail})."
    ranks = " · ".join(f"{_METRIC_LABELS[a]} {metric_ranks[a]}위" for a in ("avg", "max", "std"))
    return f"{ranks}로 세 지표가 고르게 좋아 {rank}위로 선정했어요 ({detail})."


def _accuracy(pairs: list[AccuracyPairOut]) -> AccuracyOut | None:
    if not pairs:
        return None
    diffs = [p.diff_minutes for p in pairs]
    return AccuracyOut(
        mae_minutes=round(sum(abs(d) for d in diffs) / len(diffs), 1),
        bias_minutes=round(sum(diffs) / len(diffs), 1),
        pairs=pairs,
    )


def recommend_regions(
    request: RegionRecommendRequest,
    estimator: TravelEstimator,
    provider: RouteProvider | None,
    stations: Sequence[Station],
    config: RegionConfig,
) -> RegionRecommendResponse:
    participants = request.participants
    origins = [Coord(p.lat, p.lng) for p in participants]
    center = centroid(origins)
    candidates = nearest_stations(stations, center, config.candidate_k)
    by_id = {s.id: s for s in candidates}

    # --- 1단계: 그래프 추정만으로 후보 전체를 점수화 (API 호출 0) -----------------------
    per_participant = [estimator.estimate(o, candidates) for o in origins]
    estimates = {st.id: [per_participant[i][st.id] for i in range(len(origins))] for st in candidates}
    stage1 = score_regions(estimates, config.weights)[: config.top_n]
    top = [by_id[r.region_id] for r in stage1]

    # --- 2단계: 상위 후보까지의 실제 소요시간 (검색당 최대 1회 호출) -----------------------
    matrix = MatrixResult(minutes=[[None] * len(top) for _ in origins])
    if provider is not None:
        matrix = provider.matrix(origins, top)
    final: dict[str, list[float]] = {}
    estimated_flags: dict[str, list[bool]] = {}
    pairs: list[AccuracyPairOut] = []
    for j, st in enumerate(top):
        times, flags = [], []
        for i, p in enumerate(participants):
            actual = matrix.minutes[i][j]
            if actual is None:
                times.append(estimates[st.id][i])
                flags.append(True)
            else:
                times.append(actual)
                flags.append(False)
                diff = estimates[st.id][i] - actual
                pairs.append(AccuracyPairOut(participant=p.name, station=st.name,
                                             estimate_minutes=round(estimates[st.id][i], 1),
                                             actual_minutes=round(actual, 1), diff_minutes=round(diff, 1)))
                logger.info("이동시간 추정 vs 실제 | %s→%s | 추정 %.1f분, 실제 %.1f분, 차이 %+.1f분",
                            p.name, st.name, estimates[st.id][i], actual, diff)
        final[st.id] = times
        estimated_flags[st.id] = flags
    used_actual = any(not f for flags in estimated_flags.values() for f in flags)
    accuracy = _accuracy(pairs)
    if accuracy:
        logger.info("1단계 추정 정확도 | 평균절대오차 %.1f분, 편향 %+.1f분 (%d건)",
                    accuracy.mae_minutes, accuracy.bias_minutes, len(pairs))

    scores = score_regions(final, config.weights)  # 상위 후보끼리 다시 정규화·순위
    ranks = {attr: _rank_by(scores, attr) for attr in ("avg", "max", "std")}
    pool = f"실제 경로 기준 상위 {len(scores)}곳 중" if used_actual else f"추정 기준 후보 {len(candidates)}곳 중"

    regions = []
    for i, r in enumerate(scores, 1):
        st = by_id[r.region_id]
        metric_ranks = {a: ranks[a][r.region_id] for a in ranks}
        regions.append(RegionOut(
            rank=i,
            station=StationOut(id=st.id, name=st.name, lat=st.coord.lat, lng=st.coord.lng, lines=list(st.lines)),
            score=round(r.score, 4),
            reason=region_reason(i, r.metrics, metric_ranks, pool),
            metrics=MetricsOut(avg_minutes=round(r.metrics.avg, 1), max_minutes=round(r.metrics.max, 1),
                               std_minutes=round(r.metrics.std, 1)),
            normalized=NormalizedOut(avg=round(r.normalized.avg, 4), max=round(r.normalized.max, 4),
                                     std=round(r.normalized.std, 4)),
            metric_ranks=MetricRanksOut(**metric_ranks),
            participants=[
                ParticipantTravelOut(name=p.name, minutes=round(m, 1), is_estimated=est,
                                     estimate_minutes=round(estimates[st.id][k], 1))
                for k, (p, m, est) in enumerate(zip(participants, r.minutes, estimated_flags[st.id]))
            ],
        ))

    if provider is None:
        status, reason = "skipped", "경로 API를 쓰지 않아 추정값으로 표시해요"
    elif not used_actual:
        status, reason = "failed", matrix.error or "경로 API가 이동시간을 돌려주지 않았어요"
    else:
        status, reason = "ok", matrix.error

    w = config.weights
    return RegionRecommendResponse(
        regions=regions,
        meta=RegionRecommendMeta(
            purpose=request.purpose,
            centroid=LatLng(lat=round(center.lat, 6), lng=round(center.lng, 6)),
            candidate_count=len(candidates),
            evaluated_count=len(candidates),
            weights=WeightsOut(avg=w.avg, max=w.max, std=w.std),
            travel_source=(provider.name if provider is not None and used_actual else "estimate"),
            phase2=Phase2Out(status=status, reason=reason, provider=provider.name if provider else None,
                             api_calls=matrix.api_calls, cache_hits=matrix.cache_hits),
            estimate_accuracy=accuracy,
        ),
    )
