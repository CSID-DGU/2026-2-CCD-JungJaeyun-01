"""전체 추천 데모: 홍대입구·잠실·노원 3명 출발, 식사 → 상위 3개 지역 + 지역별 장소 + API별 호출 횟수.

실행 (backend 폴더에서):
    .venv\\Scripts\\python scripts/demo_recommend.py                  # .env의 USE_MOCK 값 사용
    $env:USE_MOCK="false"; .venv\\Scripts\\python scripts/demo_recommend.py

USE_MOCK=false이면 ODsay·카카오·구글을 실제로 호출한다. ODsay는 캐시에 없는 조합이
최악의 경우(전부 429 재시도) 쓰게 될 호출 수가 --max-calls(기본 50)를 넘으면 호출 전에 중단한다.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import settings  # noqa: E402
from app.config import load_place_config, load_region_config, load_travel_config  # noqa: E402
from app.geo import Coord, centroid  # noqa: E402
from app.place_recommend import recommend_with_places  # noqa: E402
from app.schemas import ParticipantIn, RegionRecommendRequest  # noqa: E402
from app.services import get_place_service, get_rating_service, get_travel_time_service  # noqa: E402
from app.services.travel_cache import CachedTravelTimeService  # noqa: E402
from app.stations import load_stations, nearest_stations  # noqa: E402

PARTICIPANTS = [
    ParticipantIn(name="홍대", lat=37.556871, lng=126.923779, age_group="20s"),   # 홍대입구역
    ParticipantIn(name="잠실", lat=37.513311, lng=127.100231, age_group="20s"),   # 잠실역
    ParticipantIn(name="노원", lat=37.656340, lng=127.063449, age_group="30s"),   # 노원역
]


def odsay_uncached(service, request) -> tuple[int, int]:
    """(캐시에 없는 출발지-역 조합 수, 전체 조합 수)"""
    origins = [Coord(p.lat, p.lng) for p in request.participants]
    candidates = nearest_stations(load_stations(), centroid(origins), load_region_config().candidate_k)
    total = len(candidates) * len(origins)
    if not isinstance(service, CachedTravelTimeService):
        return 0, total
    return sum(1 for st in candidates for o in origins if not service.is_cached(o, st)), total


def calls(service) -> int:
    inner = getattr(service, "inner", service)
    return getattr(inner, "http_calls", 0)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--purpose", default="meal", choices=["meal", "cafe", "drink"])
    parser.add_argument("--max-calls", type=int, default=50, help="ODsay 최악 호출 수 상한")
    args = parser.parse_args()

    travel, places, ratings = get_travel_time_service(), get_place_service(), get_rating_service()
    request = RegionRecommendRequest(participants=PARTICIPANTS, purpose=args.purpose)
    print(f"USE_MOCK={settings.USE_MOCK} | 이동시간 {type(travel).__name__} | 장소 {type(places).__name__} "
          f"| 평점 {type(ratings).__name__}")

    uncached, total = odsay_uncached(travel, request)
    attempts = 1 + len(load_travel_config().odsay_retry_delays_seconds)
    worst = uncached * attempts
    print(f"ODsay: 조합 {total}건 중 캐시에 없음 {uncached}건 → 최악의 경우 호출 {worst}건")
    if worst > args.max_calls:
        sys.exit(f"중단: 최악 호출 {worst}건이 상한 {args.max_calls}건을 넘습니다. 실행하지 않았습니다.")

    response = recommend_with_places(request, travel, places, ratings, load_stations(),
                                     load_region_config(), load_place_config())
    meta = response.meta

    print(f"\n가중치(지역) 평균 {meta.weights.avg}/최대 {meta.weights.max}/편차 {meta.weights.std} | "
          f"후보 {meta.candidate_count}개 중 {meta.evaluated_count}개 평가")
    for ex in meta.estimated_travel:
        print(f"  추정치 대체: {ex.station} / {ex.participant} ← {ex.reason}")
    print(f"연령대 선호도: source={meta.age_preference.source} (임의값 {meta.age_preference.is_assumed})")

    for r in response.regions:
        m = r.metrics
        times = "/".join(f"{p.minutes:.0f}" for p in r.participants)
        print(f"\n{r.rank}위 {r.station.name} 점수 {r.score:.3f} | 이동 {times}분 "
              f"(평균 {m.avg_minutes} 최대 {m.max_minutes} 편차 {m.std_minutes})")
        for p in r.places:
            print(f"   {p.rank}. {p.name} [{p.score:.3f}] {p.reason}")
    for w in meta.place_warnings:
        print(f"경고: {w}")

    g_used = ""
    if hasattr(ratings, "cache"):
        from datetime import date
        g_used = f" (오늘 누적 {ratings.cache.usage(date.today().isoformat())}/{load_place_config().google.daily_limit})"
    print("\n===== API별 실제 호출 횟수 =====")
    print(f"ODsay : {calls(travel)}건")
    print(f"카카오 : {calls(places)}건 (캐시 적중 {getattr(places, 'hits', 0)} / 미적중 {getattr(places, 'misses', 0)})")
    print(f"구글   : {calls(ratings)}건{g_used} | 평점 조회 결과 {meta.ratings.status_counts}")


if __name__ == "__main__":
    main()
