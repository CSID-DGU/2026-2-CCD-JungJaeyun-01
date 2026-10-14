"""PlaceScore 계산 (순수 함수).

PlaceScore = Σ (가중치 × 항목 점수), 각 항목은 0~1.
  접근성   : 1 - 역에서 거리 / 검색 반경
  평점     : 리뷰 수를 반영한 베이지안 평균을 [rating_floor, 5] → [0, 1]로 변환
  인기도   : log(1 + 리뷰 수) / log(1 + popularity_cap)
  목적 적합성 / 연령대 적합성 : category_name 키워드 기반 (값은 config에서 주입)

평점 데이터가 없으면 평점·인기도 항목을 빼고 남은 가중치를 합이 1이 되도록 재정규화한다.
"""

import math
from dataclasses import dataclass
from typing import Collection, Mapping, Sequence

COMPONENTS = ("accessibility", "rating", "popularity", "purpose", "age")
RATING_COMPONENTS = ("rating", "popularity")  # 외부 평점 데이터가 있어야 계산되는 항목


@dataclass(frozen=True)
class PlaceWeights:
    accessibility: float
    rating: float
    popularity: float
    purpose: float
    age: float

    def __post_init__(self) -> None:
        values = self.as_dict().values()
        if min(values) < 0:
            raise ValueError("가중치는 0 이상이어야 합니다.")
        if not math.isclose(sum(values), 1.0, abs_tol=1e-9):
            raise ValueError("가중치 합은 1이어야 합니다.")

    def as_dict(self) -> dict[str, float]:
        return {name: getattr(self, name) for name in COMPONENTS}


@dataclass(frozen=True)
class PlaceScoringParams:
    radius_m: float
    prior_mean: float
    prior_weight: float
    rating_floor: float
    popularity_cap: int
    walk_m_per_min: float


@dataclass(frozen=True)
class AgeGroupPreference:
    default: float
    keywords: Mapping[str, float]


@dataclass(frozen=True)
class PlaceFeatures:
    distance_m: float
    purpose_fit: float            # 0~1
    age_fit: float                # 0~1
    rating: float | None = None   # 1~5
    review_count: int | None = None


@dataclass(frozen=True)
class PlaceScoreResult:
    score: float
    components: Mapping[str, float | None]  # 값을 구하지 못한 항목은 None
    weights_used: Mapping[str, float]       # 재정규화 후 실제 적용된 가중치 (합 1)
    rating_used: bool


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def accessibility_score(distance_m: float, radius_m: float) -> float:
    return clamp01(1 - distance_m / radius_m)


def bayesian_rating(rating: float, review_count: int, prior_mean: float, prior_weight: float) -> float:
    """리뷰가 적을수록 사전 평균(prior_mean) 쪽으로 끌어당긴 평점."""
    return (review_count * rating + prior_weight * prior_mean) / (review_count + prior_weight)


def rating_score(rating: float, review_count: int, params: PlaceScoringParams) -> float:
    adjusted = bayesian_rating(rating, review_count, params.prior_mean, params.prior_weight)
    return clamp01((adjusted - params.rating_floor) / (5.0 - params.rating_floor))


def popularity_score(review_count: int, cap: int) -> float:
    return clamp01(math.log1p(review_count) / math.log1p(cap))


def keyword_fit(category_name: str, keywords: Mapping[str, float], default: float) -> float:
    """category_name에 포함된 키워드 중 가장 높은 값. 하나도 없으면 default."""
    matched = [score for keyword, score in keywords.items() if keyword in category_name]
    return max(matched) if matched else default


def age_fit(
    category_name: str,
    age_groups: Sequence[str],
    preferences: Mapping[str, AgeGroupPreference],
) -> float:
    """참여자 연령대별 적합성의 평균."""
    fits = [
        keyword_fit(category_name, preferences[g].keywords, preferences[g].default)
        for g in age_groups
    ]
    return sum(fits) / len(fits)


def renormalize_weights(weights: Mapping[str, float], available: Collection[str]) -> dict[str, float]:
    """available 항목만 남기고 합이 1이 되도록 비례 조정. 남은 가중치가 전부 0이면 균등 분배."""
    kept = {k: v for k, v in weights.items() if k in available}
    if not kept:
        raise ValueError("사용 가능한 항목이 없습니다.")
    total = sum(kept.values())
    if total <= 0:
        return {k: 1 / len(kept) for k in kept}
    return {k: v / total for k, v in kept.items()}


def score_place(
    features: PlaceFeatures,
    weights: PlaceWeights,
    params: PlaceScoringParams,
) -> PlaceScoreResult:
    has_rating = features.rating is not None and features.review_count is not None
    components: dict[str, float | None] = {
        "accessibility": accessibility_score(features.distance_m, params.radius_m),
        "rating": (rating_score(features.rating, features.review_count, params)
                   if has_rating else None),
        "popularity": (popularity_score(features.review_count, params.popularity_cap)
                       if has_rating else None),
        "purpose": clamp01(features.purpose_fit),
        "age": clamp01(features.age_fit),
    }
    available = [name for name, value in components.items() if value is not None]
    used = renormalize_weights(weights.as_dict(), available)
    score = sum(used[name] * components[name] for name in used)
    return PlaceScoreResult(score=score, components=components, weights_used=used, rating_used=has_rating)


def walking_minutes(distance_m: float, walk_m_per_min: float) -> int:
    return max(1, round(distance_m / walk_m_per_min))


def reason_line(
    distance_m: float,
    rating: float | None,
    review_count: int | None,
    walk_m_per_min: float,
) -> str:
    """장소 선정 이유 한 줄. 예: "역에서 도보 3분, 평점 4.5(리뷰 320개)"."""
    walk = f"역에서 도보 {walking_minutes(distance_m, walk_m_per_min)}분"
    if rating is None or review_count is None:
        return f"{walk}, 평점 정보 없음"
    return f"{walk}, 평점 {rating:.1f}(리뷰 {review_count:,}개)"
