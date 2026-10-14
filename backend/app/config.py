"""backend/config/*.yaml 로딩. 점수 계산 함수에는 여기서 읽은 값을 인자로 넘긴다."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

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
    )
