import pytest

from app.config import load_travel_config
from app.geo import Coord
from app.providers.base import RouteUnavailable
from app.providers.odsay import OdsayClient, OdsayRouteProvider, parse_odsay_route
from app.route_model import BUS, SUBWAY, WALK
from app.services.routes_store import RoutesStore
from app.stations import Station


def station(id_: str, lat: float, lng: float) -> Station:
    return Station(id=id_, name=f"{id_}역", coord=Coord(lat, lng))


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
        svc = OdsayClient(
            "dummy-key", self.params, client=FakeClient(*responses),
            min_interval=0.3, retry_delays=(1.0, 2.0), sleep=t.sleep, clock=t.clock,
            quota_cooldown=300.0,
        )
        return svc, t

    def test_takes_fastest_path(self):
        body = {"result": {"path": [{"info": {"totalTime": 52}}, {"info": {"totalTime": 40}}]}}
        svc, _ = self.service(body)
        assert svc.fetch(self.origin, self.st).minutes == 40.0

    def test_429_is_retried_with_1s_then_2s_wait(self):
        svc, t = self.service(QUOTA_BODY, QUOTA_BODY, OK_BODY)
        assert svc.fetch(self.origin, self.st).minutes == 40.0
        assert svc.http_calls == 3
        assert t.sleeps == [1.0, 2.0]

    def test_http_status_429_is_also_retried(self):
        svc, t = self.service(FakeResponse({}, status=429), OK_BODY)
        assert svc.fetch(self.origin, self.st).minutes == 40.0
        assert t.sleeps == [1.0]

    def test_gives_up_after_two_retries_with_reason(self):
        svc, t = self.service(QUOTA_BODY)
        with pytest.raises(RouteUnavailable, match="429.*Daily quota exceeded.*2회"):
            svc.fetch(self.origin, self.st)
        assert svc.http_calls == 3  # 최초 1회 + 재시도 2회
        assert t.sleeps == [1.0, 2.0]

    def test_after_quota_is_exhausted_further_calls_fail_fast_without_http(self):
        svc, t = self.service(QUOTA_BODY)
        with pytest.raises(RouteUnavailable):
            svc.fetch(self.origin, self.st)
        assert svc.http_calls == 3
        sleeps_before = list(t.sleeps)
        for _ in range(5):
            with pytest.raises(RouteUnavailable, match="호출 중단"):
                svc.fetch(self.origin, self.st)
        assert svc.http_calls == 3 and t.sleeps == sleeps_before  # 호출도 대기도 없다

    def test_calls_resume_after_the_cooldown(self):
        svc, t = self.service(QUOTA_BODY, QUOTA_BODY, QUOTA_BODY, OK_BODY)
        with pytest.raises(RouteUnavailable):
            svc.fetch(self.origin, self.st)
        t.now += 301
        assert svc.fetch(self.origin, self.st).minutes == 40.0
        assert svc.http_calls == 4

    def test_other_errors_do_not_trigger_the_cooldown(self):
        svc, _ = self.service({"error": {"code": "500", "msg": "x"}}, OK_BODY)
        with pytest.raises(RouteUnavailable):
            svc.fetch(self.origin, self.st)
        assert svc.fetch(self.origin, self.st).minutes == 40.0

    def test_other_errors_are_not_retried(self):
        svc, t = self.service({"error": {"code": "500", "msg": "서버 내부 오류"}})
        with pytest.raises(RouteUnavailable, match="500"):
            svc.fetch(self.origin, self.st)
        assert svc.http_calls == 1 and t.sleeps == []

    def test_waits_at_least_0_3s_between_requests(self):
        svc, t = self.service(OK_BODY)
        svc.fetch(self.origin, self.st)
        svc.fetch(self.origin, self.st)
        svc.fetch(self.origin, self.st)
        assert t.sleeps == pytest.approx([0.3, 0.3])  # 첫 호출 전에는 대기 없음

    def test_too_close_falls_back_to_walking(self):
        svc, _ = self.service({"error": [{"code": "-98", "message": "출, 도착지가 700m 이내입니다."}]})
        assert svc.fetch(self.origin, self.st).minutes > 0

    def test_requires_api_key(self):
        with pytest.raises(ValueError):
            OdsayClient("", self.params)

    def test_request_uses_lng_as_x(self):
        svc, _ = self.service(OK_BODY)
        svc.fetch(self.origin, self.st)
        sent = svc._client.requests[0]
        assert (sent["SX"], sent["SY"]) == (self.origin.lng, self.origin.lat)


# --------------------------------------------------------------------------- ODsay 응답 → 공통 경로 스키마
ORIGIN = Coord(37.5569, 126.9238)
DEST = Coord(37.5663, 126.9910)


def stations_list(*pairs):
    return {"stations": [{"index": i, "stationName": n, "x": str(x), "y": str(y)} for i, (n, x, y) in enumerate(pairs)]}


def odsay_path(subs=None, total=29):
    default = [
        {"trafficType": 3, "distance": 300, "sectionTime": 5},
        {"trafficType": 1, "distance": 4200, "sectionTime": 18, "stationCount": 4,
         "lane": [{"name": "수도권 6호선", "subwayCode": 6}], "startName": "합정", "startX": 126.9144, "startY": 37.5499,
         "endName": "신당", "endX": 127.0178, "endY": 37.5657,
         "passStopList": stations_list(("합정", 126.9144, 37.5499), ("상수", 126.9229, 37.5477), ("신당", 127.0178, 37.5657))},
        {"trafficType": 3, "distance": 50, "sectionTime": 1},
        {"trafficType": 1, "distance": 900, "sectionTime": 3, "stationCount": 1,
         "lane": [{"name": "수도권 2호선", "subwayCode": 2}], "startName": "신당", "startX": 127.0178, "startY": 37.5657,
         "endName": "을지로3가", "endX": 126.9910, "endY": 37.5663,
         "passStopList": stations_list(("신당", 127.0178, 37.5657), ("을지로3가", 126.9910, 37.5663))},
        {"trafficType": 3, "distance": 120, "sectionTime": 2},
    ]
    return {"info": {"totalTime": total}, "subPath": subs or default}


class TestParseOdsayRoute:
    def test_segments_use_the_common_schema(self):
        route = parse_odsay_route(odsay_path(), ORIGIN, DEST)
        assert route.source == "odsay" and (route.total_minutes, route.transfers) == (29, 1)
        assert [s.mode for s in route.segments] == [WALK, SUBWAY, WALK, SUBWAY, WALK]
        subway = [s for s in route.segments if s.mode == SUBWAY]
        assert [(s.line_name, s.line_color) for s in subway] == [("6호선", "#CD7C2F"), ("2호선", "#00A84D")]
        assert (subway[0].from_name, subway[0].to_name) == ("합정", "신당")

    def test_path_uses_lat_lng_order_and_stop_coordinates(self):
        seg = parse_odsay_route(odsay_path(), ORIGIN, DEST).segments[1]
        assert seg.path[0] == (37.5499, 126.9144) and len(seg.path) == 3  # ODsay x=경도, y=위도

    def test_walks_connect_origin_and_destination(self):
        route = parse_odsay_route(odsay_path(), ORIGIN, DEST)
        assert route.segments[0].path == ((ORIGIN.lat, ORIGIN.lng), (37.5499, 126.9144))
        assert route.segments[-1].path[-1] == (DEST.lat, DEST.lng)

    def test_bus_leg_label_and_color(self):
        subs = [{"trafficType": 2, "distance": 3000, "sectionTime": 12, "stationCount": 6, "lane": [{"busNo": "472", "type": 11}],
                 "startName": "A", "startX": 126.93, "startY": 37.55, "endName": "B", "endX": 126.98, "endY": 37.56,
                 "passStopList": stations_list(("A", 126.93, 37.55), ("B", 126.98, 37.56))}]
        seg = parse_odsay_route(odsay_path(subs, 12), ORIGIN, DEST).segments[0]
        assert (seg.mode, seg.line_name, seg.line_color) == (BUS, "472번", "#3D5BAB")

    def test_walk_only_or_malformed_returns_none_instead_of_a_fake_route(self):
        assert parse_odsay_route(odsay_path([{"trafficType": 3, "distance": 100, "sectionTime": 2}]), ORIGIN, DEST) is None
        assert parse_odsay_route({"info": {"totalTime": 5}}, ORIGIN, DEST) is None


class TestOdsayProvider:
    """2단계 구조에서의 ODsay: 상위 후보의 (출발지, 도착역) 쌍만 호출하고 결과를 캐시한다."""

    params = load_travel_config().mock

    def provider(self, tmp_path, *responses):
        t = FakeTime()
        client = OdsayClient("dummy", self.params, client=FakeClient(*responses), min_interval=0, retry_delays=(),
                             sleep=t.sleep, clock=t.clock)
        return OdsayRouteProvider(client, RoutesStore(tmp_path / "r.sqlite3")), client

    def test_matrix_calls_each_pair_once_and_caches(self, tmp_path):
        provider, client = self.provider(tmp_path, {"result": {"path": [odsay_path()]}})
        dests = [station("a", 37.56, 126.99), station("b", 37.50, 127.03)]
        first = provider.matrix([ORIGIN, Coord(37.51, 127.10)], dests)
        assert client.http_calls == 4 and first.api_calls == 4 and first.minutes[0][0] == 29.0
        second = provider.matrix([ORIGIN, Coord(37.51, 127.10)], dests)
        assert client.http_calls == 4 and second.api_calls == 0

    def test_route_returns_the_common_schema_from_the_cached_response(self, tmp_path):
        provider, client = self.provider(tmp_path, {"result": {"path": [odsay_path()]}})
        st = station("a", DEST.lat, DEST.lng)
        provider.matrix([ORIGIN], [st])
        route = provider.route(ORIGIN, st)
        assert route.source == "odsay" and route.segments[1].line_name == "6호선"
        assert client.http_calls == 1  # 이미 받은 응답을 재사용
