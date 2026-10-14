import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import load_region_config, load_travel_config
from app.geo import Coord
from app.main import app
from app.recommend import recommend_regions
from app.schemas import RegionRecommendRequest
from app.services import get_travel_time_service
from app.services.route import (
    BUS,
    SUBWAY,
    WALK,
    parse_odsay_route,
    route_from_dict,
    route_to_dict,
)
from app.services.travel_cache import CachedTravelTimeService, TravelTimeCache
from app.services.travel_time import (
    MockTravelTimeService,
    TravelResult,
    TravelTimeService,
    TravelTimeUnavailable,
)
from app.stations import Station, load_stations

ORIGIN = Coord(37.5569, 126.9238)
DEST = Coord(37.5663, 126.9910)


def stations(*pairs):
    return {"stations": [{"index": i, "stationName": n, "x": str(x), "y": str(y)} for i, (n, x, y) in enumerate(pairs)]}


def odsay_path(extra_subs=None, total=29):
    """ODsay searchPubTransPathT의 path 하나와 같은 구조 (좌표 x=경도, y=위도)."""
    subs = [
        {"trafficType": 3, "distance": 300, "sectionTime": 5},
        {"trafficType": 1, "distance": 4200, "sectionTime": 18, "stationCount": 4,
         "lane": [{"name": "수도권 6호선", "subwayCode": 6}],
         "startName": "합정", "startX": 126.9144, "startY": 37.5499,
         "endName": "신당", "endX": 127.0178, "endY": 37.5657,
         "passStopList": stations(("합정", 126.9144, 37.5499), ("상수", 126.9229, 37.5477),
                                   ("신당", 127.0178, 37.5657))},
        {"trafficType": 3, "distance": 50, "sectionTime": 1},
        {"trafficType": 1, "distance": 900, "sectionTime": 3, "stationCount": 1,
         "lane": [{"name": "수도권 2호선", "subwayCode": 2}],
         "startName": "신당", "startX": 127.0178, "startY": 37.5657,
         "endName": "을지로3가", "endX": 126.9910, "endY": 37.5663,
         "passStopList": stations(("신당", 127.0178, 37.5657), ("을지로3가", 126.9910, 37.5663))},
        {"trafficType": 3, "distance": 120, "sectionTime": 2},
    ]
    return {"info": {"totalTime": total}, "subPath": extra_subs or subs}


class TestParseRoute:
    def test_legs_in_order_with_labels_and_colors(self):
        route = parse_odsay_route(odsay_path(), ORIGIN, DEST)
        assert [leg.kind for leg in route.legs] == [WALK, SUBWAY, WALK, SUBWAY, WALK]
        assert [leg.label for leg in route.legs if leg.kind == SUBWAY] == ["6호선", "2호선"]
        assert [leg.color for leg in route.legs if leg.kind == SUBWAY] == ["#CD7C2F", "#00A84D"]
        assert (route.total_minutes, route.transfers) == (29, 1)

    def test_subway_path_uses_stop_coordinates_x_is_longitude(self):
        leg = parse_odsay_route(odsay_path(), ORIGIN, DEST).legs[1]
        assert leg.path[0] == Coord(lat=37.5499, lng=126.9144)
        assert len(leg.path) == 3 and (leg.from_name, leg.to_name, leg.stop_count) == ("합정", "신당", 4)

    def test_walk_legs_connect_origin_to_first_stop_and_last_stop_to_destination(self):
        route = parse_odsay_route(odsay_path(), ORIGIN, DEST)
        assert route.legs[0].path == (ORIGIN, Coord(37.5499, 126.9144))
        assert route.legs[-1].path == (Coord(37.5663, 126.9910), DEST)

    def test_zero_length_walk_between_transfers_is_dropped(self):
        subs = odsay_path()["subPath"]
        subs[2] = {"trafficType": 3, "distance": 0, "sectionTime": 0}
        assert [leg.kind for leg in parse_odsay_route(odsay_path(subs), ORIGIN, DEST).legs] == [
            WALK, SUBWAY, SUBWAY, WALK]

    def test_bus_leg_label_and_color(self):
        subs = [{"trafficType": 2, "distance": 3000, "sectionTime": 12, "stationCount": 6,
                 "lane": [{"busNo": "472", "type": 11}], "startName": "A", "startX": 126.93, "startY": 37.55,
                 "endName": "B", "endX": 126.98, "endY": 37.56,
                 "passStopList": stations(("A", 126.93, 37.55), ("B", 126.98, 37.56))}]
        leg = parse_odsay_route(odsay_path(subs, 12), ORIGIN, DEST).legs[0]
        assert (leg.kind, leg.label, leg.color) == (BUS, "472번", "#3D5BAB")

    def test_missing_stop_list_falls_back_to_start_and_end(self):
        subs = odsay_path()["subPath"]
        del subs[1]["passStopList"]
        leg = parse_odsay_route(odsay_path(subs), ORIGIN, DEST).legs[1]
        assert leg.path == (Coord(37.5499, 126.9144), Coord(37.5657, 127.0178))

    def test_line_outside_metropolitan_area_has_no_color(self):
        subs = odsay_path()["subPath"]
        subs[1]["lane"] = [{"name": "부산 1호선"}]
        assert parse_odsay_route(odsay_path(subs), ORIGIN, DEST).legs[1].color is None

    def test_walk_only_or_malformed_returns_none_instead_of_fake_route(self):
        assert parse_odsay_route(odsay_path([{"trafficType": 3, "distance": 100, "sectionTime": 2}]), ORIGIN, DEST) is None
        assert parse_odsay_route({"info": {"totalTime": 5}}, ORIGIN, DEST) is None
        assert parse_odsay_route({"info": {}, "subPath": [{"trafficType": 1}]}, ORIGIN, DEST) is None

    def test_dict_roundtrip(self):
        route = parse_odsay_route(odsay_path(), ORIGIN, DEST)
        assert route_from_dict(route_to_dict(route)) == route


class FakeRouteService(TravelTimeService):
    """get_route 호출을 기록하는 가짜. 이동시간은 mock 추정값을 쓴다."""

    source = "odsay"

    def __init__(self, route=None, error=None):
        self.mock = MockTravelTimeService(load_travel_config().mock)
        self.route, self.error, self.route_calls = route, error, []

    def get_minutes(self, origin, station):
        return self.mock.get_minutes(origin, station)

    def get_route(self, origin, station):
        self.route_calls.append((origin, station.name))
        if self.error:
            raise self.error
        return self.route


P = [
    {"name": "민지", "lat": 37.556871, "lng": 126.923779, "age_group": "20s"},
    {"name": "서준", "lat": 37.513311, "lng": 127.100231, "age_group": "20s"},
]


def recommend(service):
    return recommend_regions(RegionRecommendRequest(participants=P, purpose="meal"), service,
                             load_stations(), load_region_config())


class TestRecommendRoutes:
    def test_routes_are_attached_only_for_top_regions_and_use_stored_data(self):
        route = parse_odsay_route(odsay_path(), ORIGIN, DEST)
        service = FakeRouteService(route=route)
        result = recommend(service)
        assert len(service.route_calls) == 3 * 2  # 상위 3개 지역 × 참여자 2명 (후보 12곳 전체가 아님)
        p = result.regions[0].participants[0]
        assert p.route_note is None and p.route.transfers == 1
        assert [leg.kind for leg in p.route.legs] == ["walk", "subway", "walk", "subway", "walk"]
        assert p.route.legs[1].path[0].lat == pytest.approx(37.5499)

    def test_estimated_pair_gets_no_route_and_a_clear_note(self):
        class FailsForFirst(FakeRouteService):
            def get_minutes(self, origin, station):
                if origin.lat == pytest.approx(P[0]["lat"]):
                    raise TravelTimeUnavailable("ODsay 429")
                return super().get_minutes(origin, station)

        service = FailsForFirst(route=parse_odsay_route(odsay_path(), ORIGIN, DEST))
        first, second = recommend(service).regions[0].participants
        assert first.is_estimated and first.route is None
        assert first.route_note == "추정 경로 (실제 경로 조회 실패)"
        assert second.route is not None
        assert all(call[0].lat != pytest.approx(P[0]["lat"]) for call in service.route_calls)  # 추정 건은 조회 안 함

    def test_mock_mode_says_there_is_no_real_route(self):
        p = recommend(MockTravelTimeService(load_travel_config().mock)).regions[0].participants[0]
        assert p.route is None and "mock" in p.route_note and not p.is_estimated

    def test_route_lookup_failure_is_reported_not_faked(self):
        p = recommend(FakeRouteService(error=TravelTimeUnavailable("ODsay 429"))).regions[0].participants[0]
        assert p.route is None and "ODsay 429" in p.route_note

    def test_api_response_contains_route_fields(self):
        route = parse_odsay_route(odsay_path(), ORIGIN, DEST)
        app.dependency_overrides[get_travel_time_service] = lambda: FakeRouteService(route=route)
        try:
            body = TestClient(app).post("/api/recommend/regions", json={"participants": P, "purpose": "meal"}).json()
        finally:
            app.dependency_overrides.clear()
        leg = body["regions"][0]["participants"][0]["route"]["legs"][1]
        assert leg["label"] == "6호선" and leg["color"] == "#CD7C2F"
        assert leg["path"][0] == {"lat": 37.5499, "lng": 126.9144}


class CountingFetcher(TravelTimeService):
    source = "odsay"

    def __init__(self, route):
        self.calls, self.route = 0, route

    def get_minutes(self, origin, station):
        return self.fetch(origin, station).minutes

    def fetch(self, origin, station):
        self.calls += 1
        return TravelResult(25.0, self.route)


STATION = Station(id="s1", name="신당역", coord=DEST)


class TestRouteCache:
    def route(self):
        return parse_odsay_route(odsay_path(), ORIGIN, DEST)

    def test_first_lookup_stores_route_and_second_reads_it_without_calling_api(self, tmp_path):
        inner = CountingFetcher(self.route())
        cached = CachedTravelTimeService(inner, TravelTimeCache(tmp_path / "t.sqlite3"))
        assert cached.get_minutes(ORIGIN, STATION) == 25.0
        assert cached.get_route(ORIGIN, STATION) == self.route()
        assert cached.fetch(ORIGIN, STATION).route == self.route()
        assert inner.calls == 1 and cached.route_backfills == 0

    def test_legacy_rows_without_route_are_migrated_and_backfilled_once(self, tmp_path):
        db = tmp_path / "t.sqlite3"
        with sqlite3.connect(db) as conn:  # 경로 저장 도입 전 스키마
            conn.execute("CREATE TABLE travel_time (source TEXT NOT NULL, origin_lat TEXT NOT NULL, "
                         "origin_lng TEXT NOT NULL, station_id TEXT NOT NULL, minutes REAL NOT NULL, "
                         "created_at TEXT NOT NULL, PRIMARY KEY (source, origin_lat, origin_lng, station_id))")
            conn.execute("INSERT INTO travel_time VALUES ('odsay', '37.5569', '126.9238', 's1', 31.0, 'x')")
        inner = CountingFetcher(self.route())
        cached = CachedTravelTimeService(inner, TravelTimeCache(db))

        assert cached.get_minutes(ORIGIN, STATION) == 31.0 and inner.calls == 0  # 이동시간은 캐시 그대로
        assert cached.get_route(ORIGIN, STATION) == self.route()                 # 경로만 한 번 채운다
        assert inner.calls == 1 and cached.route_backfills == 1
        cached.get_route(ORIGIN, STATION)
        assert inner.calls == 1                                                  # 이후에는 API 호출 없음

    def test_failed_backfill_keeps_the_legacy_row(self, tmp_path):
        cache = TravelTimeCache(tmp_path / "t.sqlite3")
        cache.set("odsay", ORIGIN, "s1", 31.0)
        with sqlite3.connect(cache.path) as conn:
            conn.execute("UPDATE travel_time SET route_json = NULL")

        class Failing(CountingFetcher):
            def fetch(self, origin, station):
                raise TravelTimeUnavailable("ODsay 429")

        cached = CachedTravelTimeService(Failing(None), cache)
        with pytest.raises(TravelTimeUnavailable):
            cached.get_route(ORIGIN, STATION)
        entry = cache.get_entry("odsay", ORIGIN, "s1")
        assert entry.minutes == 31.0 and entry.route_known is False

    def test_route_less_result_is_remembered_so_it_is_not_refetched(self, tmp_path):
        inner = CountingFetcher(None)
        cached = CachedTravelTimeService(inner, TravelTimeCache(tmp_path / "t.sqlite3"))
        cached.get_minutes(ORIGIN, STATION)
        assert cached.get_route(ORIGIN, STATION) is None and inner.calls == 1
