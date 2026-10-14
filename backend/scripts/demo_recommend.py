"""지역 추천 데모: 홍대입구·잠실·노원 3명 출발 → 상위 3개 지역 출력.

실행 (backend 폴더에서):
    .venv\\Scripts\\python scripts/demo_recommend.py                  # .env의 USE_MOCK 값 사용
    $env:USE_MOCK="false"; .venv\\Scripts\\python scripts/demo_recommend.py --repeat 2

USE_MOCK=false이면 ODsay를 실제로 호출한다. 캐시에 없는 조합 수가 --max-calls(기본 50)를
넘으면 호출하기 전에 중단한다. --repeat 2는 같은 입력을 한 번 더 돌려 캐시 동작을 보여준다.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import settings  # noqa: E402
from app.config import load_region_config  # noqa: E402
from app.geo import Coord, centroid  # noqa: E402
from app.recommend import recommend_regions  # noqa: E402
from app.schemas import ParticipantIn, RegionRecommendRequest  # noqa: E402
from app.services import get_travel_time_service  # noqa: E402
from app.services.travel_cache import CachedTravelTimeService  # noqa: E402
from app.services.travel_time import OdsayTravelTimeService  # noqa: E402
from app.stations import load_stations, nearest_stations  # noqa: E402

PARTICIPANTS = [
    ParticipantIn(name="홍대", lat=37.556871, lng=126.923779, age_group="20s"),   # 홍대입구역
    ParticipantIn(name="잠실", lat=37.513311, lng=127.100231, age_group="20s"),   # 잠실역
    ParticipantIn(name="노원", lat=37.656340, lng=127.063449, age_group="30s"),   # 노원역
]


def count_uncached_calls(service, request: RegionRecommendRequest) -> tuple[int, int]:
    """(캐시에 없어 API를 호출해야 하는 조합 수, 전체 조합 수)"""
    config = load_region_config()
    origins = [Coord(p.lat, p.lng) for p in request.participants]
    candidates = nearest_stations(load_stations(), centroid(origins), config.candidate_k)
    total = len(candidates) * len(origins)
    if not isinstance(service, CachedTravelTimeService):
        return 0, total
    uncached = sum(1 for st in candidates for o in origins if not service.is_cached(o, st))
    return uncached, total


def print_result(response) -> None:
    meta = response.meta
    print(f"\n이동시간 소스: {meta.travel_source} | 후보 {meta.candidate_count}개 중 "
          f"{meta.evaluated_count}개 평가 | 중심점 ({meta.centroid.lat}, {meta.centroid.lng})")
    print(f"가중치: 평균 {meta.weights.avg} / 최대 {meta.weights.max} / 편차 {meta.weights.std}")
    if meta.excluded_stations:
        print(f"경로를 못 구해 제외된 역: {', '.join(meta.excluded_stations)}")
    names = [p.name for p in response.regions[0].participants]
    head = " ".join(f"{n:>5}" for n in names)
    print(f"\n{'순위':<4}{'역':<10}{'점수':>7}  {head}  {'평균':>6}{'최대':>6}{'편차':>6}")
    for r in response.regions:
        times = " ".join(f"{p.minutes:>5.0f}" for p in r.participants)
        m = r.metrics
        print(f"{r.rank:<4}{r.station.name:<10}{r.score:>7.3f}  {times}  "
              f"{m.avg_minutes:>6.1f}{m.max_minutes:>6.1f}{m.std_minutes:>6.1f}")
    print("\n지표 순위(후보 중, 1=최상): " + " | ".join(
        f"{r.station.name} 평균 {r.metric_ranks.avg}위·최대 {r.metric_ranks.max}위·편차 {r.metric_ranks.std}위"
        for r in response.regions))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=1, help="같은 입력을 N번 실행(캐시 확인용)")
    parser.add_argument("--max-calls", type=int, default=50, help="실제 API 호출 상한")
    args = parser.parse_args()

    service = get_travel_time_service()
    request = RegionRecommendRequest(participants=PARTICIPANTS, purpose="meal")
    config = load_region_config()
    print(f"USE_MOCK={settings.USE_MOCK} → {type(service).__name__}")

    for run in range(1, args.repeat + 1):
        uncached, total = count_uncached_calls(service, request)
        print(f"\n===== 실행 {run}/{args.repeat} =====")
        print(f"조합 {total}건 (참여자 {len(PARTICIPANTS)}명 × 후보 {config.candidate_k}개), "
              f"캐시 없음 → 실제 호출 예정 {uncached}건")
        if uncached > args.max_calls:
            sys.exit(f"중단: 호출 예정 {uncached}건이 상한 {args.max_calls}건을 넘습니다. 실행하지 않았습니다.")

        hits_before = getattr(service, "hits", 0)
        misses_before = getattr(service, "misses", 0)
        response = recommend_regions(request, service, load_stations(), config)
        print_result(response)

        if isinstance(service, CachedTravelTimeService):
            inner = service.inner
            print(f"\n[캐시] 이번 실행 적중 {service.hits - hits_before}건 / 미적중 {service.misses - misses_before}건")
            if isinstance(inner, OdsayTravelTimeService):
                print(f"[ODsay] 누적 실제 호출 {inner.call_count}건 | "
                      f"캐시 DB 저장 {service.cache.count('odsay')}건")


if __name__ == "__main__":
    main()
