"""backend/config/*.yaml 로딩. 점수 계산 함수에는 여기서 읽은 값을 인자로 넘긴다."""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping

import yaml

from app.scoring.place import AgeGroupPreference, PlaceScoringParams, PlaceWeights
from app.scoring.region import RegionWeights

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


@dataclass(frozen=True)
class RegionConfig:
    weights: RegionWeights
    candidate_k: int
    top_n: int


@dataclass(frozen=True)
class TravelParams:
    detour_factor: float
    transit_speed_kmh: float
    access_minutes: float
    transfer_every_km: float
    transfer_penalty_minutes: float
    max_transfers: int
    walk_speed_kmh: float
    walk_threshold_km: float


@dataclass(frozen=True)
class TravelConfig:
    mock: TravelParams
    odsay_timeout_seconds: float
    odsay_min_interval_seconds: float
    odsay_retry_delays_seconds: tuple[float, ...]
    odsay_quota_cooldown_seconds: float


def _read_yaml(name: str) -> dict:
    return yaml.safe_load((CONFIG_DIR / name).read_text(encoding="utf-8"))


@lru_cache
def load_region_config() -> RegionConfig:
    raw = _read_yaml("region.yaml")
    return RegionConfig(
        weights=RegionWeights(**raw["weights"]),
        candidate_k=int(raw["candidate_k"]),
        top_n=int(raw["top_n"]),
    )


@lru_cache
def load_travel_config() -> TravelConfig:
    raw = _read_yaml("travel.yaml")
    return TravelConfig(
        mock=TravelParams(**raw["mock"]),
        odsay_timeout_seconds=float(raw["odsay"]["timeout_seconds"]),
        odsay_min_interval_seconds=float(raw["odsay"]["min_interval_seconds"]),
        odsay_retry_delays_seconds=tuple(float(x) for x in raw["odsay"]["retry_delays_seconds"]),
        odsay_quota_cooldown_seconds=float(raw["odsay"]["quota_cooldown_seconds"]),
    )


AGE_GROUPS = ("10s", "20s", "30s", "40s", "50s+")


@dataclass(frozen=True)
class PurposeRule:
    category_code: str
    category_name_contains: str | None
    fit_default: float
    fit_keywords: Mapping[str, float]


@dataclass(frozen=True)
class AgePreferences:
    source: str  # "assumed" = 임의값, 실제 데이터로 교체하면 다른 값으로 바꾼다
    note: str
    groups: Mapping[str, AgeGroupPreference]

    @property
    def is_assumed(self) -> bool:
        return self.source == "assumed"


@dataclass(frozen=True)
class GoogleConfig:
    daily_limit: int
    cache_ttl_days: int
    match_radius_m: float


@dataclass(frozen=True)
class PlaceConfig:
    weights: PlaceWeights
    params: PlaceScoringParams
    radius_m: float
    max_results: int
    cache_ttl_days: int
    top_n: int
    purposes: Mapping[str, PurposeRule]
    google: GoogleConfig
    age: AgePreferences


@lru_cache
def load_age_preferences() -> AgePreferences:
    raw = json.loads((CONFIG_DIR / "age_preferences.json").read_text(encoding="utf-8"))
    groups = {
        name: AgeGroupPreference(default=float(g["default"]), keywords=dict(g["keywords"]))
        for name, g in raw["groups"].items()
    }
    missing = set(AGE_GROUPS) - set(groups)
    if missing:
        raise ValueError(f"age_preferences.json에 연령대가 없습니다: {sorted(missing)}")
    return AgePreferences(source=raw["source"], note=raw.get("note", ""), groups=groups)


@lru_cache
def load_place_config() -> PlaceConfig:
    raw = _read_yaml("place.yaml")
    search, scoring = raw["search"], raw["scoring"]
    return PlaceConfig(
        weights=PlaceWeights(**raw["weights"]),
        params=PlaceScoringParams(
            radius_m=float(search["radius_m"]),
            prior_mean=float(scoring["prior_mean"]),
            prior_weight=float(scoring["prior_weight"]),
            rating_floor=float(scoring["rating_floor"]),
            popularity_cap=int(scoring["popularity_cap"]),
            walk_m_per_min=float(scoring["walk_m_per_min"]),
        ),
        radius_m=float(search["radius_m"]),
        max_results=int(search["max_results"]),
        cache_ttl_days=int(search["cache_ttl_days"]),
        top_n=int(search["top_n"]),
        purposes={
            name: PurposeRule(
                category_code=p["category_code"],
                category_name_contains=p.get("category_name_contains"),
                fit_default=float(p["fit_default"]),
                fit_keywords=dict(p["fit_keywords"]),
            )
            for name, p in raw["purposes"].items()
        },
        google=GoogleConfig(
            daily_limit=int(raw["google"]["daily_limit"]),
            cache_ttl_days=int(raw["google"]["cache_ttl_days"]),
            match_radius_m=float(raw["google"]["match_radius_m"]),
        ),
        age=load_age_preferences(),
    )
