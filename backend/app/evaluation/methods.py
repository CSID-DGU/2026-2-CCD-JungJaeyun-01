"""비교 방식(기존 방식)과 가중치 민감도 계산."""

from dataclasses import dataclass
from itertools import combinations
from statistics import fmean, pstdev
from typing import Mapping, Sequence

from app.geo import Coord, centroid, haversine_km
from app.scoring.region import RegionWeights, score_regions

Times = Mapping[str, Sequence[float]]  # 후보 id → 참여자별 이동시간(분)


@dataclass(frozen=True)
class GroupStats:
    """한 지역에 모였을 때 참여자 이동시간의 요약 (분)."""
    avg: float
    max: float
    min: float
    std: float

    @property
    def gap(self) -> float:
        """가장 오래 걸리는 사람과 가장 적게 걸리는 사람의 차이 (불공평 정도)."""
        return self.max - self.min


def group_stats(minutes: Sequence[float]) -> GroupStats:
    return GroupStats(avg=fmean(minutes), max=float(max(minutes)), min=float(min(minutes)), std=pstdev(minutes))


def rank_with_weights(times: Times, weights: RegionWeights) -> list[str]:
    """후보 id를 RegionScore 순서(좋은 순)로."""
    return [r.region_id for r in score_regions(times, weights)]


def midpoint_pick(stations: Mapping[str, Coord], origins: Sequence[Coord]) -> str:
    """기존 방식 1: 출발지들의 지리적 중간점에서 가장 가까운 역 (지도 앱의 '중간 지점 찾기'에 해당)."""
    mid = centroid(origins)
    return min(stations, key=lambda sid: (haversine_km(stations[sid], mid), sid))


def hub_pick(times: Times, hub_ids: Sequence[str]) -> str:
    """기존 방식 2: 사람들이 흔히 떠올리는 대표 번화가(허브) 중 평균 이동시간이 가장 짧은 곳.

    허브별 이동시간을 이미 아는 것처럼 가정하므로 이 방식에게 유리한(보수적인) 비교다.
    """
    hubs = [h for h in hub_ids if h in times]
    if not hubs:
        raise ValueError("후보에 허브가 없습니다.")
    return min(hubs, key=lambda h: (fmean(times[h]), h))


def pipeline_pick(estimates: Times, actual: Times, weights: RegionWeights, shortlist: int) -> str:
    """MeetPick 실제 흐름: 추정으로 shortlist곳을 뽑고, 그 안에서만 실제 시간으로 다시 점수를 매겨 1위를 고른다."""
    short = [r.region_id for r in score_regions(estimates, weights)[:shortlist]]
    return score_regions({sid: actual[sid] for sid in short if sid in actual}, weights)[0].region_id


def weight_grid(step: float = 0.1) -> list[tuple[float, float, float]]:
    """합이 1인 (avg, max, std) 가중치 격자. step=0.1이면 66가지."""
    n = round(1 / step)
    grid = []
    for a in range(n + 1):
        for m in range(n + 1 - a):
            grid.append((round(a * step, 6), round(m * step, 6), round((n - a - m) * step, 6)))
    return grid


def kendall_tau(order_a: Sequence[str], order_b: Sequence[str]) -> float:
    """두 순위의 일치도 (-1 ~ 1, 1이면 완전히 같은 순서). 같은 원소 집합이어야 한다."""
    pos_b = {x: i for i, x in enumerate(order_b)}
    pairs = list(combinations(order_a, 2))
    if not pairs:
        return 1.0
    agree = sum(1 for x, y in pairs if pos_b[x] < pos_b[y])
    return (2 * agree - len(pairs)) / len(pairs)


def sensitivity(times: Times, default: RegionWeights, step: float = 0.1, top_k: int = 3) -> dict:
    """가중치를 바꿨을 때 추천이 얼마나 달라지는지.

    반환: 기본 가중치 순위, 격자 전체에서 1위가 같은 비율, 상위 k곳이 같은 비율, 평균 켄들 타우,
    1위로 뽑힌 적 있는 지역과 그 비율.
    """
    base = rank_with_weights(times, default)
    grid = weight_grid(step)
    same_top1 = same_topk = 0
    taus: list[float] = []
    winners: dict[str, int] = {}
    for a, m, s in grid:
        order = rank_with_weights(times, RegionWeights(avg=a, max=m, std=s))
        winners[order[0]] = winners.get(order[0], 0) + 1
        same_top1 += order[0] == base[0]
        same_topk += set(order[:top_k]) == set(base[:top_k])
        taus.append(kendall_tau(base, order))
    n = len(grid)
    return {
        "default_order": base,
        "grid_size": n,
        "top1_same_ratio": same_top1 / n,
        "topk_same_ratio": same_topk / n,
        "mean_kendall_tau": fmean(taus),
        "winners": dict(sorted(winners.items(), key=lambda kv: -kv[1])),
    }
