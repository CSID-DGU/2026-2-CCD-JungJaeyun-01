import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx2 as httpx
import pytest

from app.geo import Coord
from app.providers.base import RouteUnavailable, SingleFlight
from app.providers.google import (
    MATRIX_FIELD_MASK,
    MATRIX_URL,
    ROUTES_FIELD_MASK,
    ROUTES_URL,
    GoogleClient,
    GoogleRouteProvider,
    GoogleSettings,
    classify_failure,
    convert_route,
    next_departure,
    time_band,
)
from app.route_model import BUS, SUBWAY, WALK
from app.services.polyline import decode_polyline
from app.services.routes_store import RoutesStore
from app.stations import Station

FIXTURES = Path(__file__).parent / "fixtures"
KST = timezone(timedelta(hours=9))
SETTINGS = GoogleSettings(departure_hour=18, utc_offset_hours=9, cache_ttl_days=7, max_retries=1,
                          backoff_seconds=0, timeout_seconds=5, cooldown_seconds=120)
NOW = lambda: datetime(2026, 10, 15, 12, 0, tzinfo=KST)  # noqa: E731  (목요일)
HAPJEONG = Coord(37.54991, 126.91445)
EULJIRO = Station(id="s-eulji", name="을지로3가역", coord=Coord(37.56629, 126.99098))
ANGUK = Station(id="s-anguk", name="안국역", coord=Coord(37.57650, 126.98542))


def load(name):
    data = json.loads((FIXTURES / f"google_route_{name}.json").read_text(encoding="utf-8"))
    return data["response"], Coord(*data["origin_latlng"]), Coord(*data["destination_latlng"])


# --------------------------------------------------------------------------- 폴리라인·시각
def test_polyline_decoder_matches_the_documented_example():
    # 구글 문서의 예: _p~iF~ps|U_ulLnnqC_mqNvxq`@
    pts = decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
    assert pts == [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]


def test_departure_is_the_next_weekday_at_6pm_kst():
    assert next_departure(datetime(2026, 10, 15, 9, 0, tzinfo=KST), 18, 9) == datetime(2026, 10, 16, 18, tzinfo=KST)  # 목→금
    assert next_departure(datetime(2026, 10, 16, 9, 0, tzinfo=KST), 18, 9) == datetime(2026, 10, 19, 18, tzinfo=KST)  # 금→월
    assert next_departure(datetime(2026, 10, 17, 9, 0, tzinfo=KST), 18, 9) == datetime(2026, 10, 19, 18, tzinfo=KST)  # 토→월


def test_time_band_separates_weekday_and_weekend():
    assert time_band(datetime(2026, 10, 16, 18, tzinfo=KST)) == "weekday-18"
    assert time_band(datetime(2026, 10, 17, 18, tzinfo=KST)) == "weekend-18"


# --------------------------------------------------------------------------- Google 응답 → 공통 스키마 (실제 녹화 응답)
class TestConvertRoute:
    def test_direct_subway_route(self):
        resp, origin, dest = load("hapjeong_euljiro3ga")
        route = convert_route(resp, origin, dest)
        assert (route.source, route.total_minutes, route.transfers) == ("google", 16, 0)
        seg = route.segments[0]
        assert (seg.mode, seg.line_name, seg.line_color) == (SUBWAY, "2호선", "#35b12b")
        assert (seg.from_name, seg.to_name, seg.minutes) == ("합정", "을지로3가", 16.0)
        assert len(seg.path) > 20 and all(isinstance(p, tuple) and len(p) == 2 for p in seg.path)
        assert 37.0 < seg.path[0][0] < 38.0 and 126.0 < seg.path[0][1] < 127.5  # (lat, lng) 순서

    def test_transfer_route_merges_fragmented_walking_steps(self):
        resp, origin, dest = load("seouldae_anguk")
        route = convert_route(resp, origin, dest)
        assert (route.total_minutes, route.transfers) == (38, 1)
        assert [s.mode for s in route.segments] == [SUBWAY, WALK, SUBWAY]  # 잘게 쪼개진 도보 step 10여 개가 하나로
        first, walk, second = route.segments
        assert (first.line_name, first.line_color) == ("2호선", "#35b12b")
        assert (second.line_name, second.line_color) == ("3호선", "#f25c2b")
        assert (first.to_name, second.from_name) == ("교대", "교대")
        assert 2.0 <= walk.minutes <= 4.0
        assert walk.path[0] == first.path[-1] and walk.path[-1] == second.path[0]  # 도보가 앞뒤 구간과 이어진다

    def test_segments_are_continuous_and_have_drawable_paths(self):
        for name in ("hapjeong_euljiro3ga", "seouldae_anguk", "suwon_jonggak"):
            resp, origin, dest = load(name)
            route = convert_route(resp, origin, dest)
            assert all(len(s.path) >= 2 for s in route.segments), name
            for a, b in zip(route.segments, route.segments[1:]):
                if b.mode == WALK:
                    assert b.path[0] == a.path[-1], name
                if a.mode == WALK:
                    assert a.path[-1] == b.path[0], name

    def test_intercity_train_without_short_name_or_color_is_still_converted(self):
        resp, origin, dest = load("suwon_jonggak")  # 코레일 장거리열차(노선명 '전라', 색 없음) + 1호선
        route = convert_route(resp, origin, dest)
        transit = [s for s in route.segments if s.mode != WALK]
        assert [s.line_name for s in transit] == ["전라", "1호선"]
        assert transit[0].line_color is None and transit[1].line_color == "#003499"
        assert all(s.mode == SUBWAY for s in transit) and route.transfers == 1

    def test_bus_vehicle_maps_to_bus(self):
        resp = {"routes": [{"duration": "600s", "legs": [{"steps": [{
            "travelMode": "TRANSIT", "staticDuration": "600s",
            "transitDetails": {"transitLine": {"nameShort": "472", "color": "#3d5bab", "vehicle": {"type": "BUS"}},
                               "stopDetails": {"departureStop": {"name": "A"}, "arrivalStop": {"name": "B"}}}}]}]}]}
        seg = convert_route(resp, Coord(37.5, 127.0), Coord(37.51, 127.01)).segments[0]
        assert (seg.mode, seg.line_name, seg.from_name, seg.to_name) == (BUS, "472", "A", "B")

    def test_no_routes_raises_unavailable(self):
        with pytest.raises(RouteUnavailable):
            convert_route({}, HAPJEONG, EULJIRO.coord)


# --------------------------------------------------------------------------- 오류 분류
@pytest.mark.parametrize("status, body, kind, retryable, blocks", [
    (None, None, "network", True, False),
    (503, {}, "server", True, False),
    (429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded for quota metric"}}, "quota", False, True),
    (403, {"error": {"status": "PERMISSION_DENIED", "message": "Routes API has not been used in project"}}, "api_disabled", False, True),
    (403, {"error": {"status": "PERMISSION_DENIED", "message": "Requests from this IP are blocked"}}, "key_restricted", False, True),
    (400, {"error": {"status": "INVALID_ARGUMENT", "message": "bad"}}, "bad_request", False, False),
])
def test_failure_classification(status, body, kind, retryable, blocks):
    f = classify_failure(status, body)
    assert (f.kind, f.retryable, f.blocks) == (kind, retryable, blocks) and f.message


# --------------------------------------------------------------------------- 호출 보호 (가짜 HTTP)
class Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._body, self.content = status, body if body is not None else {}, b"x"

    def json(self):
        return self._body


class ScriptedHttp:
    """응답(또는 예외)을 순서대로 돌려준다. 마지막 항목은 반복."""

    def __init__(self, *script, delay=0.0):
        self.script, self.requests, self.delay = list(script), [], delay
        self.lock = threading.Lock()

    def post(self, url, json=None, headers=None):
        with self.lock:
            self.requests.append({"url": url, "json": json, "headers": headers})
            item = self.script[min(len(self.requests) - 1, len(self.script) - 1)]
        time.sleep(self.delay)
        if isinstance(item, Exception):
            raise item
        return item


ROUTE_OK = Resp(200, load("hapjeong_euljiro3ga")[0])


def matrix_ok(n_o, n_d, minutes=20):
    return Resp(200, [{"originIndex": i, "destinationIndex": j, "duration": f"{minutes * 60}s", "condition": "ROUTE_EXISTS"}
                      for i in range(n_o) for j in range(n_d)])


def provider(tmp_path, http, mode="live", key="secret-key", clock=None, fixtures=None):
    store = RoutesStore(tmp_path / "r.sqlite3")
    kwargs = {"fixtures_dir": fixtures} if fixtures else {}
    if clock:
        kwargs["clock"] = clock
    client = GoogleClient(key, mode, store, SETTINGS, http=http, sleep=lambda s: None, **kwargs)
    return GoogleRouteProvider(client, SETTINGS, now=NOW), store, http


def test_matrix_request_uses_transit_future_departure_and_minimal_field_mask(tmp_path):
    p, _, http = provider(tmp_path, ScriptedHttp(matrix_ok(2, 2)))
    p.matrix([HAPJEONG, Coord(37.51, 127.10)], [EULJIRO, ANGUK])
    (req,) = http.requests
    assert req["url"] == MATRIX_URL
    assert req["headers"]["X-Goog-FieldMask"] == MATRIX_FIELD_MASK == "originIndex,destinationIndex,duration,condition,status"
    assert req["json"]["travelMode"] == "TRANSIT" and req["json"]["departureTime"] == "2026-10-16T09:00:00Z"  # 금 18시 KST
    assert len(req["json"]["origins"]) == 2 and len(req["json"]["destinations"]) == 2


def test_route_request_uses_the_minimal_field_mask(tmp_path):
    p, _, http = provider(tmp_path, ScriptedHttp(ROUTE_OK))
    p.route(HAPJEONG, EULJIRO)
    assert http.requests[0]["url"] == ROUTES_URL and http.requests[0]["headers"]["X-Goog-FieldMask"] == ROUTES_FIELD_MASK
    assert "distanceMeters" not in ROUTES_FIELD_MASK  # 쓰지 않는 필드는 요청하지 않는다


def test_matrix_maps_cells_and_leaves_failed_cells_empty(tmp_path):
    body = [{"originIndex": 0, "destinationIndex": 0, "duration": "1200s", "condition": "ROUTE_EXISTS"},
            {"originIndex": 0, "destinationIndex": 1, "condition": "ROUTE_NOT_FOUND"},
            {"originIndex": 1, "destinationIndex": 0, "duration": "600s", "condition": "ROUTE_EXISTS", "status": {"code": 13}}]
    p, _, _ = provider(tmp_path, ScriptedHttp(Resp(200, body)))
    result = p.matrix([HAPJEONG, Coord(37.51, 127.1)], [EULJIRO, ANGUK])
    assert result.minutes == [[20.0, None], [None, None]]


def test_live_mode_caches_matrix_and_route_by_coordinates_station_and_time_band(tmp_path):
    p, store, http = provider(tmp_path, ScriptedHttp(matrix_ok(1, 1), ROUTE_OK))
    p.matrix([Coord(37.549912, 126.914412)], [EULJIRO])
    again = p.matrix([Coord(37.549949, 126.914449)], [EULJIRO])  # 소수 4자리로 반올림하면 같은 출발지 (37.5499, 126.9144)
    assert len(http.requests) == 1 and again.api_calls == 0 and again.cache_hits == 1
    p.route(HAPJEONG, EULJIRO)
    p.route(HAPJEONG, EULJIRO)
    assert [r["url"] for r in http.requests] == [MATRIX_URL, ROUTES_URL]
    assert store.usage()["cache_hit"] >= 2


def test_cache_is_scoped_per_destination(tmp_path):
    p, _, http = provider(tmp_path, ScriptedHttp(ROUTE_OK))
    p.route(HAPJEONG, EULJIRO)
    p.route(HAPJEONG, ANGUK)
    assert len(http.requests) == 2


def test_concurrent_identical_requests_make_one_call(tmp_path):
    p, _, http = provider(tmp_path, ScriptedHttp(ROUTE_OK, delay=0.15))
    results, errors = [], []

    def click():
        try:
            results.append(p.route(HAPJEONG, EULJIRO))
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=click) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == [] and len(results) == 8 and len(http.requests) == 1


def test_single_flight_propagates_the_leaders_error_to_waiters():
    flight, started, errs = SingleFlight(), threading.Event(), []

    def slow_fail():
        started.set()
        time.sleep(0.1)
        raise RouteUnavailable("boom")

    def run():
        try:
            flight.do("k", slow_fail)
        except RouteUnavailable as e:
            errs.append(str(e))

    t1 = threading.Thread(target=run)
    t1.start()
    started.wait()
    t2 = threading.Thread(target=run)
    t2.start()
    t1.join()
    t2.join()
    assert errs == ["boom", "boom"]


def test_transient_error_is_retried_once_then_succeeds(tmp_path):
    p, store, http = provider(tmp_path, ScriptedHttp(Resp(503, {}), ROUTE_OK))
    assert p.route(HAPJEONG, EULJIRO).total_minutes == 16
    assert len(http.requests) == 2 and store.usage()["route"] == 2  # 시도마다 센다


def test_network_error_is_retried_only_once(tmp_path):
    p, _, http = provider(tmp_path, ScriptedHttp(httpx.ConnectError("down")))
    with pytest.raises(RouteUnavailable, match="네트워크"):
        p.route(HAPJEONG, EULJIRO)
    assert len(http.requests) == 2  # 최초 1회 + 재시도 1회까지만


def test_permanent_error_is_not_retried_and_pauses_further_calls(tmp_path):
    now = [100.0]
    forbidden = Resp(403, {"error": {"status": "PERMISSION_DENIED", "message": "Routes API has not been used"}})
    p, _, http = provider(tmp_path, ScriptedHttp(forbidden), clock=lambda: now[0])
    with pytest.raises(RouteUnavailable, match="Routes API"):
        p.route(HAPJEONG, EULJIRO)
    assert len(http.requests) == 1  # 재시도 없음
    with pytest.raises(RouteUnavailable, match="중단"):
        p.route(HAPJEONG, ANGUK)
    assert len(http.requests) == 1  # 쿨다운 동안 호출 없음
    now[0] += 121
    http.script = [ROUTE_OK]
    assert p.route(HAPJEONG, ANGUK).total_minutes == 16 and len(http.requests) == 2


def test_matrix_failure_is_reported_instead_of_raised(tmp_path):
    p, _, _ = provider(tmp_path, ScriptedHttp(Resp(403, {"error": {"message": "Requests from this IP are blocked"}})))
    result = p.matrix([HAPJEONG], [EULJIRO])
    assert result.minutes == [[None]] and "키 제한" in result.error


def test_missing_key_never_calls_google(tmp_path):
    p, _, http = provider(tmp_path, ScriptedHttp(ROUTE_OK), key="")
    with pytest.raises(RouteUnavailable, match="GOOGLE_ROUTES_KEY"):
        p.route(HAPJEONG, EULJIRO)
    assert http.requests == []


def test_api_key_is_never_leaked_in_errors_or_logs(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    p, _, _ = provider(tmp_path, ScriptedHttp(httpx.ConnectError("https://x?key=secret-key failed")))
    with pytest.raises(RouteUnavailable) as e:
        p.route(HAPJEONG, EULJIRO)
    assert "secret-key" not in str(e.value) and "secret-key" not in caplog.text


# --------------------------------------------------------------------------- ROUTE_MODE: live | record | replay
def test_replay_mode_never_calls_google_and_fails_clearly_without_a_recording(tmp_path):
    p, store, http = provider(tmp_path, ScriptedHttp(ROUTE_OK), mode="replay", fixtures=tmp_path / "fx")
    with pytest.raises(RouteUnavailable, match="저장된 응답이 없어요"):
        p.route(HAPJEONG, EULJIRO)
    assert http.requests == [] and store.usage()["replay_miss"] == 1
    assert p.matrix([HAPJEONG], [EULJIRO]).error  # 매트릭스도 호출 없이 실패로 보고


def test_record_mode_saves_real_responses_and_replay_reads_them_with_zero_calls(tmp_path):
    fx = tmp_path / "fx"
    rec, _, rec_http = provider(tmp_path, ScriptedHttp(matrix_ok(1, 1, minutes=18), ROUTE_OK), mode="record", fixtures=fx)
    assert rec.matrix([HAPJEONG], [EULJIRO]).minutes == [[18.0]]
    assert rec.route(HAPJEONG, EULJIRO).total_minutes == 16
    assert len(rec_http.requests) == 2 and len(list(fx.glob("*.json"))) == 2
    saved = json.loads(next(fx.glob("route-*.json")).read_text(encoding="utf-8"))
    assert saved["kind"] == "route" and "routes" in saved["response"] and "secret-key" not in json.dumps(saved)

    rep, store, rep_http = provider(tmp_path / "other", ScriptedHttp(), mode="replay", fixtures=fx) if (tmp_path / "other").mkdir() is None else (None, None, None)
    assert rep.matrix([HAPJEONG], [EULJIRO]).minutes == [[18.0]]
    assert rep.route(HAPJEONG, EULJIRO).segments[0].line_name == "2호선"
    assert rep_http.requests == [] and store.usage()["replay_hit"] == 2


def test_record_mode_always_calls_even_if_the_cache_has_the_answer(tmp_path):
    p, _, http = provider(tmp_path, ScriptedHttp(ROUTE_OK), mode="record", fixtures=tmp_path / "fx")
    p.route(HAPJEONG, EULJIRO)
    p.route(HAPJEONG, EULJIRO)
    assert len(http.requests) == 2  # 녹화는 캐시를 쓰지 않는다 (live만 캐시)


def test_invalid_mode_is_rejected(tmp_path):
    with pytest.raises(ValueError):
        GoogleClient("k", "turbo", RoutesStore(tmp_path / "r.sqlite3"), SETTINGS)
