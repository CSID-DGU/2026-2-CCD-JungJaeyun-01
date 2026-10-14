"""RegionScore 계산 (순수 함수).

RegionScore = 1 - (w_avg * 평균 + w_max * 최대 + w_std * 표준편차)
- 세 지표는 후보 지역들 사이에서 min-max 정규화한 값이다 (0 = 가장 좋음, 1 = 가장 나쁨).
- 가중치 합이 1이므로 점수는 0~1이며 높을수록 좋다.
"""

import math
from dataclasses import dataclass
from statistics import fmean, pstdev
from typing import Mapping, Sequence


@dataclass(frozen=True)
class RegionWeights:
    avg: float
    max: float
    std: float

    def __post_init__(self) -> None:
        if min(self.avg, self.max, self.std) < 0:
            raise ValueError("가중치는 0 이상이어야 합니다.")
        if not math.isclose(self.avg + self.max + self.std, 1.0, abs_tol=1e-9):
            raise ValueError("가중치 합은 1이어야 합니다.")


@dataclass(frozen=True)
class RegionMetrics:
    avg: float
    max: float
    std: float


@dataclass(frozen=True)
class RegionScore:
    region_id: str
    minutes: tuple[float, ...]  # 참여자별 이동시간 (입력 순서 유지)
    metrics: RegionMetrics      # 원래 단위(분)
    normalized: RegionMetrics   # 0~1, 낮을수록 좋음
    score: float


def compute_metrics(minutes: Sequence[float]) -> RegionMetrics:
    """참여자별 이동시간 → 평균, 최대, 모표준편차."""
    if not minutes:
        raise ValueError("이동시간이 비어 있습니다.")
    return RegionMetrics(avg=fmean(minutes), max=float(max(minutes)), std=pstdev(minutes))


def min_max_normalize(values: Sequence[float]) -> list[float]:
    """최솟값 0, 최댓값 1로 변환. 모든 값이 같으면 차이가 없으므로 전부 0."""
    if not values:
        return []
    lo, hi = min(values), max(values)
    if math.isclose(lo, hi):
        return [0.0] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def score_regions(
    travel_minutes: Mapping[str, Sequence[float]],
    weights: RegionWeights,
) -> list[RegionScore]:
    """지역 id → 참여자별 이동시간을 받아 RegionScore 내림차순으로 반환한다.

    동점이면 평균 이동시간, 최대 이동시간, 지역 id 순으로 정렬한다.
    """
    ids = sorted(travel_minutes)
    metrics = [compute_metrics(travel_minutes[i]) for i in ids]
    n_avg = min_max_normalize([m.avg for m in metrics])
    n_max = min_max_normalize([m.max for m in metrics])
    n_std = min_max_normalize([m.std for m in metrics])

    results = [
        RegionScore(
            region_id=region_id,
            minutes=tuple(travel_minutes[region_id]),
            metrics=m,
            normalized=RegionMetrics(avg=a, max=x, std=s),
            score=1 - (weights.avg * a + weights.max * x + weights.std * s),
        )
        for region_id, m, a, x, s in zip(ids, metrics, n_avg, n_max, n_std)
    ]
    return sorted(results, key=lambda r: (-r.score, r.metrics.avg, r.metrics.max, r.region_id))


def top_regions(
    travel_minutes: Mapping[str, Sequence[float]],
    weights: RegionWeights,
    top_n: int,
) -> list[RegionScore]:
    return score_regions(travel_minutes, weights)[:top_n]
