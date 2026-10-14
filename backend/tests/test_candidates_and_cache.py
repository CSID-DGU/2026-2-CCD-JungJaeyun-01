import pytest

from app.config import load_travel_config
from app.geo import Coord, centroid, haversine_km
from app.services.travel_cache import CachedTravelTimeService, TravelTimeCache, cache_key
from app.services.travel_time import (
    MockTravelTimeService,
    OdsayTravelTimeService,
    TravelTimeService,
    TravelTimeUnavailable,
    estimate_transit_minutes,
)
from app.stations import Station, load_stations, nearest_stations


def station(id_: str, lat: float, lng: float) -> Station:
    return Station(id=id_, name=f"{id_}역", coord=Coord(lat, lng))


class TestGeo:
    def test_haversine_known_distance(self):
        # 강남역 ↔ 홍대입구역 직선거리 약 12km
        gangnam, hongdae = Coord(37.498086, 127.028001), Coord(37.556871, 126.923779)
        assert haversine_km(gangnam, hongdae) == pytest.approx(11.0, abs=1.5)

    def test_centroid(self):
        c = centroid([Coord(37.0, 127.0), Coord(38.0, 128.0)])
        assert (c.lat, c.lng) == (37.5, 127.5)

    def test_centroid_empty(self):
        with pytest.raises(ValueError):
            centroid([])


class TestNearestStations:
    def test_returns_k_closest_in_order(self):
        stations = [station("far", 37.9, 127.0), station("near", 37.5, 127.0), station("mid", 37.6, 127.0)]
        result = nearest_stations(stations, Coord(37.5, 127.0), 2)
        assert [s.id for s in result] == ["near", "mid"]

    def test_k_larger_than_stations(self):
        assert len(nearest_stations([station("a", 37.5, 127.0)], Coord(37.5, 127.0), 12)) == 1

    def test_invalid_k(self):
        with pytest.raises(ValueError):
            nearest_stations([], Coord(0, 0), 0)

    def test_real_data_loads(self):
        stations = load_stations()
        assert len(stations) >= 55
        assert all(33 < s.coord.lat < 39 and 124 < s.coord.lng < 132 for s in stations)
        assert len({s.id for s in stations}) == len(stations)


class TestMockTravelTime:
    params = load_travel_config().mock

    def test_farther_takes_longer(self):
        assert estimate_transit_minutes(15, self.params) > estimate_transit_minutes(5, self.params)

    def test_short_distance_is_walking(self):
        assert estimate_transit_minutes(0.3, self.params) < self.params.access_minutes + 5

    def test_transfer_penalty_applies(self):
        # 환승 기준거리를 넘으면 단순 거리 비례보다 커진다
        p = self.params
        km = 20
        base = p.access_minutes + km * p.detour_factor / p.transit_speed_kmh * 60
        assert estimate_transit_minutes(km, p) > base

    def test_service_uses_station_coordinates(self):
        service = MockTravelTimeService(self.params)
        origin = Coord(37.5, 127.0)
        assert service.get_minutes(origin, station("near", 37.51, 127.0)) < service.get_minutes(
            origin, station("far", 37.7, 127.0)
        )


class CountingService(TravelTimeService):
    source = "counting"

    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail

    def get_minutes(self, origin, station):
        self.calls += 1
        if self.fail:
            raise TravelTimeUnavailable("테스트 실패")
        return 25.0


class TestCache:
    def test_key_rounds_to_4_decimals(self):
        assert cache_key(Coord(37.55687149, 126.92377851)) == ("37.5569", "126.9238")

    def test_second_call_is_cache_hit(self, tmp_path):
        inner = CountingService()
        cached = CachedTravelTimeService(inner, TravelTimeCache(tmp_path / "c.sqlite3"))
        st, origin = station("a", 37.5, 127.0), Coord(37.5569, 126.9238)
        assert cached.get_minutes(origin, st) == 25.0
        assert cached.get_minutes(origin, st) == 25.0
        assert inner.calls == 1
        assert (cached.hits, cached.misses) == (1, 1)

    def test_nearby_coordinates_share_key(self, tmp_path):
        inner = CountingService()
        cached = CachedTravelTimeService(inner, TravelTimeCache(tmp_path / "c.sqlite3"))
        st = station("a", 37.5, 127.0)
        cached.get_minutes(Coord(37.55687, 126.92377), st)
        cached.get_minutes(Coord(37.55689, 126.92381), st)  # 4자리 반올림하면 동일
        assert inner.calls == 1

    def test_different_station_or_origin_misses(self, tmp_path):
        inner = CountingService()
        cached = CachedTravelTimeService(inner, TravelTimeCache(tmp_path / "c.sqlite3"))
        origin = Coord(37.5569, 126.9238)
        cached.get_minutes(origin, station("a", 37.5, 127.0))
        cached.get_minutes(origin, station("b", 37.6, 127.0))
        cached.get_minutes(Coord(37.6, 127.1), station("a", 37.5, 127.0))
        assert inner.calls == 3

    def test_persists_across_instances(self, tmp_path):
        path = tmp_path / "c.sqlite3"
        st, origin = station("a", 37.5, 127.0), Coord(37.5569, 126.9238)
        CachedTravelTimeService(CountingService(), TravelTimeCache(path)).get_minutes(origin, st)
        inner = CountingService()
        CachedTravelTimeService(inner, TravelTimeCache(path)).get_minutes(origin, st)
        assert inner.calls == 0

    def test_failures_are_not_cached(self, tmp_path):
        inner = CountingService(fail=True)
        cached = CachedTravelTimeService(inner, TravelTimeCache(tmp_path / "c.sqlite3"))
        st, origin = station("a", 37.5, 127.0), Coord(37.5569, 126.9238)
        for _ in range(2):
            with pytest.raises(TravelTimeUnavailable):
                cached.get_minutes(origin, st)
        assert inner.calls == 2


class FakeResponse:
    def __init__(self, body, status=200):
        self._body, self.status_code = body, status

    def raise_for_status(self):
        pass

    def json(self):
        return self._body


class FakeClient:
    """응답을 순서대로 돌려주고, 마지막 응답은 반복한다."""

    def __init__(self, *responses):
        self.responses = [r if isinstance(r, FakeResponse) else FakeResponse(r) for r in responses]
        self.requests = []

    def get(self, url, params=None):
        self.requests.append(params)
        return self.responses[min(len(self.requests) - 1, len(self.responses) - 1)]


class FakeTime:
    """sleep을 기록하고 시계를 그만큼 앞으로 보낸다 (실제로 기다리지 않음)."""

    def __init__(self):
        self.now, self.sleeps = 100.0, []

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def clock(self):
        return self.now


OK_BODY = {"result": {"path": [{"info": {"totalTime": 40}}]}}
QUOTA_BODY = {"error": {"code": "429", "msg": "Daily quota exceeded"}}


class TestOdsay:
    params = load_travel_config().mock
    origin, st = Coord(37.5569, 126.9238), station("a", 37.4981, 127.0280)

    def service(self, *responses):
        t = FakeTime()
        svc = OdsayTravelTimeService(
            "dummy-key", self.params, client=FakeClient(*responses),
            min_interval=0.3, retry_delays=(1.0, 2.0), sleep=t.sleep, clock=t.clock,
            quota_cooldown=300.0,
        )
        return svc, t

    def test_takes_fastest_path(self):
        body = {"result": {"path": [{"info": {"totalTime": 52}}, {"info": {"totalTime": 40}}]}}
        svc, _ = self.service(body)
        assert svc.get_minutes(self.origin, self.st) == 40.0

    def test_429_is_retried_with_1s_then_2s_wait(self):
        svc, t = self.service(QUOTA_BODY, QUOTA_BODY, OK_BODY)
        assert svc.get_minutes(self.origin, self.st) == 40.0
        assert svc.http_calls == 3
        assert t.sleeps == [1.0, 2.0]

    def test_http_status_429_is_also_retried(self):
        svc, t = self.service(FakeResponse({}, status=429), OK_BODY)
        assert svc.get_minutes(self.origin, self.st) == 40.0
        assert t.sleeps == [1.0]

    def test_gives_up_after_two_retries_with_reason(self):
        svc, t = self.service(QUOTA_BODY)
        with pytest.raises(TravelTimeUnavailable, match="429.*Daily quota exceeded.*2회"):
            svc.get_minutes(self.origin, self.st)
        assert svc.http_calls == 3  # 최초 1회 + 재시도 2회
        assert t.sleeps == [1.0, 2.0]

    def test_after_quota_is_exhausted_further_calls_fail_fast_without_http(self):
        svc, t = self.service(QUOTA_BODY)
        with pytest.raises(TravelTimeUnavailable):
            svc.get_minutes(self.origin, self.st)
        assert svc.http_calls == 3
        sleeps_before = list(t.sleeps)
        for _ in range(5):
            with pytest.raises(TravelTimeUnavailable, match="호출 중단"):
                svc.get_minutes(self.origin, self.st)
        assert svc.http_calls == 3 and t.sleeps == sleeps_before  # 호출도 대기도 없다

    def test_calls_resume_after_the_cooldown(self):
        svc, t = self.service(QUOTA_BODY, QUOTA_BODY, QUOTA_BODY, OK_BODY)
        with pytest.raises(TravelTimeUnavailable):
            svc.get_minutes(self.origin, self.st)
        t.now += 301
        assert svc.get_minutes(self.origin, self.st) == 40.0
        assert svc.http_calls == 4

    def test_other_errors_do_not_trigger_the_cooldown(self):
        svc, _ = self.service({"error": {"code": "500", "msg": "x"}}, OK_BODY)
        with pytest.raises(TravelTimeUnavailable):
            svc.get_minutes(self.origin, self.st)
        assert svc.get_minutes(self.origin, self.st) == 40.0

    def test_other_errors_are_not_retried(self):
        svc, t = self.service({"error": {"code": "500", "msg": "서버 내부 오류"}})
        with pytest.raises(TravelTimeUnavailable, match="500"):
            svc.get_minutes(self.origin, self.st)
        assert svc.http_calls == 1 and t.sleeps == []

    def test_waits_at_least_0_3s_between_requests(self):
        svc, t = self.service(OK_BODY)
        svc.get_minutes(self.origin, self.st)
        svc.get_minutes(self.origin, self.st)
        svc.get_minutes(self.origin, self.st)
        assert t.sleeps == pytest.approx([0.3, 0.3])  # 첫 호출 전에는 대기 없음

    def test_too_close_falls_back_to_walking(self):
        svc, _ = self.service({"error": [{"code": "-98", "message": "출, 도착지가 700m 이내입니다."}]})
        assert svc.get_minutes(self.origin, self.st) > 0

    def test_requires_api_key(self):
        with pytest.raises(ValueError):
            OdsayTravelTimeService("", self.params)

    def test_request_uses_lng_as_x(self):
        svc, _ = self.service(OK_BODY)
        svc.get_minutes(self.origin, self.st)
        sent = svc._client.requests[0]
        assert (sent["SX"], sent["SY"]) == (self.origin.lng, self.origin.lat)
