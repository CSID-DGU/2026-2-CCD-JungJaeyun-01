"""전체 추천 데모: 홍대입구·잠실·노원 3명 출발, 식사 → 상위 3개 지역 + 지역별 장소.

실행 (backend 폴더에서):
    .venv\\Scripts\\python scripts/demo_recommend.py

경로 API는 ROUTE_PROVIDER / ROUTE_MODE(.env)를 따른다. 기본 ROUTE_MODE=replay는 저장본이 없으면 1단계 추정값만 쓴다.
장소·평점은 USE_MOCK 값을 따른다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import settings  # noqa: E402
from app.config import load_place_config, load_region_config  # noqa: E402
from app.place_recommend import recommend_with_places  # noqa: E402
from app.schemas import ParticipantIn, RegionRecommendRequest  # noqa: E402
from app.services import get_estimator, get_place_service, get_rating_service, get_route_provider, get_routes_store  # noqa: E402
from app.stations import load_stations  # noqa: E402

PARTICIPANTS = [
    ParticipantIn(name="홍대", lat=37.556871, lng=126.923779, age_group="20s"),   # 홍대입구역
    ParticipantIn(name="잠실", lat=37.513311, lng=127.100231, age_group="20s"),   # 잠실역
    ParticipantIn(name="노원", lat=37.656340, lng=127.063449, age_group="30s"),   # 노원역
]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    provider = get_route_provider()
    print(f"USE_MOCK={settings.USE_MOCK} | 경로 {provider.name}/{settings.ROUTE_MODE}")
    response = recommend_with_places(
        RegionRecommendRequest(participants=PARTICIPANTS, purpose="meal"),
        get_estimator(), provider, get_place_service(), get_rating_service(),
        load_stations(), load_region_config(), load_place_config(),
    )
    meta = response.meta
    print(f"이동시간 출처: {meta.travel_source} | 2단계: {meta.phase2.status} (API {meta.phase2.api_calls}회, 캐시 {meta.phase2.cache_hits}칸)"
          + (f" - {meta.phase2.reason}" if meta.phase2.reason else ""))
    if meta.estimate_accuracy:
        acc = meta.estimate_accuracy
        print(f"1단계 추정 오차: 평균 {acc.mae_minutes}분, 편향 {acc.bias_minutes:+}분 ({len(acc.pairs)}건)")
    for r in response.regions:
        times = " / ".join(f"{p.minutes:.0f}{'*' if p.is_estimated else ''}" for p in r.participants)
        print(f"\n{r.rank}위 {r.station.name} 점수 {r.score:.3f} | {times}분 (*=추정) | {r.reason}")
        for p in r.places:
            print(f"   {p.rank}. {p.name} [{p.score:.3f}] {p.reason}")
    print("\n오늘 경로 API 호출 수:", get_routes_store().usage())


if __name__ == "__main__":
    main()
