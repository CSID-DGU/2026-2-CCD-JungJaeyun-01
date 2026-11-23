"""공정성과 장소 만족도가 갈릴 때의 추천 규칙 (순수 함수).

- 이동 공정성(사람 말): 가장 오래 걸리는 사람과 가장 적게 걸리는 사람의 차이(분)로 높음/보통/낮음을 나눈다.
- 두 가지 추천을 함께 낸다.
    공평 추천     = RegionScore 1위 (이동시간의 평균·최대·편차를 모두 고려)
    장소 만족 추천 = 공평 추천에서 크게 벗어나지 않는 지역 중, 장소 만족도(상위 장소들의 PlaceScore 평균)가 가장 높은 곳
  '크게 벗어나지 않는다'는 두 가지 한도로 정한다: RegionScore가 1위보다 tolerance_score 넘게 낮지 않고,
  최대 이동시간이 1위보다 max_extra_minutes 넘게 길지 않을 것. 즉 공정성이 하한(가드레일)이고 만족도는 그 안에서 최적화한다.
- 두 추천이 같으면 하나만 보여주고, 다르면 둘 다 보여줘 사용자가 고른다.
"""

from dataclasses import dataclass
from statistics import fmean
from typing import Sequence


@dataclass(frozen=True)
class FairnessLevels:
    high_gap_max: float   # 이 값 이하면 '높음'
    mid_gap_max: float    # 이 값 이하면 '보통', 넘으면 '낮음'


@dataclass(frozen=True)
class PickRules:
    tolerance_score: float
    max_extra_minutes: float
    quality_top_n: int


@dataclass(frozen=True)
class RegionForPick:
    rank: int
    score: float                 # RegionScore
    max_minutes: float
    quality: float | None        # 장소 만족도 (장소를 못 구했으면 None)


def fairness_level(gap_minutes: float, levels: FairnessLevels) -> str:
    """'high' | 'mid' | 'low'"""
    if gap_minutes <= levels.high_gap_max:
        return "high"
    return "mid" if gap_minutes <= levels.mid_gap_max else "low"


def place_quality(place_scores: Sequence[float], top_n: int) -> float | None:
    """지역의 장소 만족도 = 점수가 높은 상위 top_n곳의 PlaceScore 평균. 장소가 없으면 None."""
    best = sorted(place_scores, reverse=True)[:top_n]
    return fmean(best) if best else None


def choose_picks(regions: Sequence[RegionForPick], rules: PickRules) -> tuple[int, int]:
    """(공평 추천 순위, 장소 만족 추천 순위). regions는 RegionScore 순위 순서."""
    if not regions:
        raise ValueError("지역이 없습니다.")
    fair = min(regions, key=lambda r: r.rank)
    eligible = [
        r for r in regions
        if r.quality is not None
        and r.score >= fair.score - rules.tolerance_score
        and r.max_minutes <= fair.max_minutes + rules.max_extra_minutes
    ]
    if not eligible:
        return fair.rank, fair.rank
    best = max(eligible, key=lambda r: (r.quality, -r.rank))  # 만족도가 같으면 공정성 순위가 높은 쪽
    return fair.rank, best.rank
