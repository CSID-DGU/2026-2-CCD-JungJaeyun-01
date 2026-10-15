"""타임라인용 데이터: 약속 시간 기준 경로 변환(시각·방면·정거장 수·배지 색)이 Google 응답과 일치하는지."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.geo import Coord
from app.main import app
from app.meeting import InvalidMeetingTime, default_meeting_time, resolve_meeting_time
from app.providers.google import convert_route
from app.route_model import BUS, SUBWAY, WALK, route_from_dict, route_to_dict
from app.services import get_route_provider
from app.stations import load_stations
from app.subway import enrich_route_stops, load_network
from tests.test_recommend_api import HONGDAE, JAMSIL, FakeProvider

FIXTURES = Path(__file__).parent / "fixtures"
KST = timezone(timedelta(hours=9))


def load(name):
    data = json.loads((FIXTURES / f"google_route_{name}.json").read_text(encoding="utf-8"))
    return data, Coord(*data["origin_latlng"]), Coord(*data["destination_latlng"])


def kst(utc_text: str) -> str:
    """Google의 UTC 시각을 KST ISO 문자열로 (응답과 직접 비교하기 위한 기준 계산)."""
    return datetime.fromisoformat(utc_text.replace("Z", "+00:00")).astimezone(KST).isoformat(timespec="seconds")


def close(a: str, b: datetime, seconds: float = 3.0) -> bool:
    """시각 문자열과 datetime이 초 단위 반올림 오차(기본 3초) 안에서 같은지."""
    return abs((datetime.fromisoformat(a) - b).total_seconds()) <= seconds


def google_transit_steps(response):
    return [s for s in response["routes"][0]["legs"][0]["steps"] if s.get("transitDetails")]


# --------------------------------------------------------------------------- 약속 시간
class TestMeetingTime:
    def test_default_is_the_next_saturday_6pm_kst(self):
        assert default_meeting_time(datetime(2026, 10, 15, 9, tzinfo=KST)) == datetime(2026, 10, 17, 18, tzinfo=KST)  # 목 → 토
        assert default_meeting_time(datetime(2026, 10, 17, 9, tzinfo=KST)) == datetime(2026, 10, 24, 18, tzinfo=KST)  # 토 → 다음 토
        assert default_meeting_time(datetime(2026, 10, 18, 9, tzinfo=KST)) == datetime(2026, 10, 24, 18, tzinfo=KST)  # 일 → 토

    def test_request_without_a_time_gets_the_default(self):
        now = datetime(2026, 10, 15, 9, tzinfo=KST)
        assert resolve_meeting_time(None, now) == datetime(2026, 10, 17, 18, tzinfo=KST)

    def test_naive_and_other_timezones_are_normalised_to_kst(self):
        now = datetime(2026, 10, 15, 9, tzinfo=KST)
        assert resolve_meeting_time(datetime(2026, 10, 17, 18, 0), now) == datetime(2026, 10, 17, 18, tzinfo=KST)
        utc = datetime(2026, 10, 17, 9, 0, tzinfo=timezone.utc)
        assert resolve_meeting_time(utc, now) == datetime(2026, 10, 17, 18, tzinfo=KST)

    def test_past_or_too_close_times_are_rejected(self):
        now = datetime(2026, 10, 15, 9, tzinfo=KST)
        with pytest.raises(InvalidMeetingTime):
            resolve_meeting_time(datetime(2026, 10, 14, 18, tzinfo=KST), now)
        with pytest.raises(InvalidMeetingTime):
            resolve_meeting_time(now + timedelta(minutes=10), now)

    def test_api_uses_the_default_and_echoes_the_meeting_time(self):
        provider = FakeProvider()
        app.dependency_overrides[get_route_provider] = lambda: provider
        try:
            body = TestClient(app).post("/api/recommend/regions", json={"participants": [HONGDAE, JAMSIL], "purpose": "meal"}).json()
        finally:
            app.dependency_overrides.clear()
        meeting = provider.meeting_times[0]
        assert (meeting.weekday(), meeting.hour, meeting.minute) == (5, 18, 0) and meeting > datetime.now(KST)  # 토요일 18시, 미래
        assert body["meta"]["meeting_time"] == meeting.isoformat(timespec="minutes")

    def test_api_passes_a_custom_meeting_time_and_rejects_a_past_one(self):
        provider = FakeProvider()
        app.dependency_overrides[get_route_provider] = lambda: provider
        client = TestClient(app)
        custom = (datetime.now(KST) + timedelta(days=3)).replace(hour=20, minute=30, second=0, microsecond=0)
        try:
            ok = client.post("/api/recommend/regions", json={"participants": [HONGDAE, JAMSIL], "purpose": "meal",
                                                              "meeting_time": custom.isoformat()})
            past = client.post("/api/recommend/regions", json={"participants": [HONGDAE, JAMSIL], "purpose": "meal",
                                                                "meeting_time": "2020-01-01T18:00:00+09:00"})
        finally:
            app.dependency_overrides.clear()
        assert ok.status_code == 200 and provider.meeting_times[0] == custom
        assert past.status_code == 422 and "약속 시간" in past.json()["detail"]


# --------------------------------------------------------------------------- Google 응답과의 일치 (실제 녹화)
class TestTimelineMatchesGoogle:
    def test_subway_segment_matches_google_exactly(self):
        data, origin, dest = load("arrive_hongdae_dongdaemun")
        steps = google_transit_steps(data["response"])
        route = convert_route(data["response"], origin, dest)
        seg = next(s for s in route.segments if s.mode == SUBWAY)
        td, line = steps[0]["transitDetails"], steps[0]["transitDetails"]["transitLine"]
        stops = td["stopDetails"]
        assert seg.line_name == line["nameShort"] == "2호선"
        assert seg.line_color == line["color"] == "#35b12b" and seg.line_text_color == line["textColor"] == "#ffffff"
        assert seg.headsign == td["headsign"] == "신도림역 방면"
        assert seg.stop_count == td["stopCount"] == 9
        assert (seg.from_name, seg.to_name) == (stops["departureStop"]["name"], stops["arrivalStop"]["name"])
        assert seg.departure_time == kst(stops["departureTime"]) and seg.arrival_time == kst(stops["arrivalTime"])
        assert seg.distance_m == steps[0]["distanceMeters"]

    def test_the_leave_time_is_the_boarding_time_minus_the_walk(self):
        data, origin, dest = load("arrive_hongdae_dongdaemun")
        route = convert_route(data["response"], origin, dest)
        walk, ride = route.segments[0], route.segments[1]
        assert walk.mode == WALK and ride.mode == SUBWAY
        assert walk.arrival_time == ride.departure_time                              # 걸어서 승차역에 도착하는 시각 = 승차 시각
        walk_start = datetime.fromisoformat(ride.departure_time) - timedelta(minutes=walk.minutes)
        assert abs((datetime.fromisoformat(route.departure_time) - walk_start).total_seconds()) <= 90  # 총 소요시간 기준이라 1분쯤 차이 가능
        # 출발 시각 = 도착 시각 - 총 소요시간: 어느 화면에서 재도 같은 소요시간이 나온다
        assert datetime.fromisoformat(route.arrival_time) - datetime.fromisoformat(route.departure_time) == timedelta(minutes=route.total_minutes)
        assert route.arrival_time == ride.arrival_time                               # 마지막이 대중교통이면 하차 시각이 도착 시각
        assert datetime.fromisoformat(route.arrival_time) <= datetime(2026, 10, 17, 18, 0, tzinfo=KST)  # 약속 시간 안에 도착
        assert route.walk_meters == walk.distance_m == 44 and route.walk_minutes == walk.minutes

    def test_bus_route_keeps_badge_colors_headsign_stop_count_and_trailing_walk_time(self):
        data, origin, dest = load("arrive_bus_naegok_gangnam")
        steps = google_transit_steps(data["response"])
        route = convert_route(data["response"], origin, dest)
        walk1, bus, walk2 = route.segments
        td = steps[0]["transitDetails"]
        assert (bus.mode, bus.line_name, bus.line_color, bus.line_text_color) == (BUS, "741", "#374ff2", "#ffffff")
        assert bus.headsign == td["headsign"] == "진관차고지" and bus.stop_count == td["stopCount"] == 10
        assert bus.departure_time == kst(td["stopDetails"]["departureTime"])
        assert walk1.arrival_time == bus.departure_time and walk2.departure_time == bus.arrival_time  # 앞뒤 도보가 이어진다
        assert close(walk2.arrival_time, datetime.fromisoformat(bus.arrival_time) + timedelta(minutes=walk2.minutes))
        assert close(route.arrival_time, datetime(2026, 10, 17, 18, 0, tzinfo=KST))  # 약속 시간(18:00)에 맞춰 도착
        assert route.arrival_time == walk2.arrival_time and route.walk_meters == walk1.distance_m + walk2.distance_m
        assert bus.intermediate_stops is None  # Google은 경유 정류장 이름을 주지 않는다

    def test_transfer_route_chains_times_through_the_transfer_walk(self):
        data, origin, dest = load("seouldae_anguk")  # 이전(출발 시각 기준) 녹화본: 2호선 → 환승 → 3호선
        route = convert_route(data["response"], origin, dest)
        first, walk, second = route.segments
        assert [s.mode for s in route.segments] == [SUBWAY, WALK, SUBWAY]
        assert (first.headsign, second.headsign) == ("외선순환 방면", "구파발역 방면")
        assert (first.stop_count, second.stop_count) == (5, 12)
        assert walk.departure_time == first.arrival_time                   # 하차 직후 환승 도보 시작
        # Google 데이터상 환승 도보(약 2.6분)와 열차 간격이 거의 같다 (이 응답은 도보가 34초 길다) → 분 단위로 보면 같은 시각
        assert abs((datetime.fromisoformat(walk.arrival_time) - datetime.fromisoformat(second.departure_time)).total_seconds()) < 60
        assert route.departure_time == first.departure_time and route.arrival_time == second.arrival_time

    def test_times_survive_the_cache_round_trip(self):
        data, origin, dest = load("arrive_bus_naegok_gangnam")
        route = convert_route(data["response"], origin, dest)
        assert route_from_dict(route_to_dict(route)) == route

    def test_entries_cached_before_the_new_fields_still_load(self):
        old = {"totalMinutes": 16, "transfers": 0, "source": "google", "segments": [
            {"mode": "SUBWAY", "lineName": "2호선", "lineColor": "#35b12b", "from": "합정", "to": "을지로3가",
             "minutes": 16.0, "path": [[37.5, 127.0], [37.6, 127.1]]}]}
        route = route_from_dict(old)
        assert route.departure_time is None and route.segments[0].headsign is None and route.segments[0].stop_count is None


# --------------------------------------------------------------------------- 경유 정거장 (노선도 데이터)
class TestIntermediateStops:
    def test_subway_stops_are_filled_when_the_stop_count_matches(self):
        data, origin, dest = load("arrive_hongdae_dongdaemun")
        route = enrich_route_stops(convert_route(data["response"], origin, dest), load_network())
        seg = next(s for s in route.segments if s.mode == SUBWAY)
        assert seg.intermediate_stops == ("신촌", "이대", "아현", "충정로", "시청", "을지로입구", "을지로3가", "을지로4가")
        assert len(seg.intermediate_stops) + 1 == seg.stop_count  # 중간 8곳 + 하차역 = 9개 정거장
        assert seg.intermediate_stops_source == "subway-map"

    def test_stops_are_left_empty_when_the_counts_disagree(self):
        data, origin, dest = load("arrive_hongdae_dongdaemun")
        route = convert_route(data["response"], origin, dest)
        wrong = route.__class__(**{**route.__dict__, "segments": tuple(
            s.__class__(**{**s.__dict__, "stop_count": 5}) if s.mode == SUBWAY else s for s in route.segments)})
        seg = next(s for s in enrich_route_stops(wrong, load_network()).segments if s.mode == SUBWAY)
        assert seg.intermediate_stops is None  # 틀린 목록을 보여주느니 비워 둔다

    def test_bus_segments_are_never_enriched(self):
        data, origin, dest = load("arrive_bus_naegok_gangnam")
        route = enrich_route_stops(convert_route(data["response"], origin, dest), load_network())
        assert all(s.intermediate_stops is None for s in route.segments)

    def test_route_endpoint_returns_the_stops_with_their_source(self):
        data, origin, dest = load("arrive_hongdae_dongdaemun")
        route = convert_route(data["response"], origin, dest)
        station = next(s for s in load_stations() if s.name == "동대문역사문화공원역")
        provider = FakeProvider(route=route)
        app.dependency_overrides[get_route_provider] = lambda: provider
        try:
            body = TestClient(app).post("/api/route", json={"lat": origin.lat, "lng": origin.lng, "station_id": station.id}).json()
        finally:
            app.dependency_overrides.clear()
        seg = next(s for s in body["route"]["segments"] if s["mode"] == "SUBWAY")
        assert seg["intermediateStops"][:3] == ["신촌", "이대", "아현"] and seg["intermediateStopsSource"] == "subway-map"
        assert body["route"]["departureTime"].endswith("+09:00") and seg["headsign"] == "내선순환 · 신촌 방면"
        assert provider.meeting_times[0].weekday() == 5  # 기본 약속 시간(토요일)으로 호출


class TestRingDirection:
    def test_hongdae_to_dongdaemun_is_the_inner_loop_toward_sinchon_not_sindorim(self):
        from app.subway import enrich_route_stops, load_network
        data, origin, dest = load("arrive_hongdae_dongdaemun")
        route = convert_route(data["response"], origin, dest)
        assert route.segments[1].headsign == "신도림역 방면"            # Google은 열차 종착역을 준다
        ride = enrich_route_stops(route, load_network()).segments[1]
        assert ride.headsign == "내선순환 · 신촌 방면"                  # 실제 진행 방향 (다음 역 기준)
        assert ride.realtime["headsign"] == "신도림역 방면"             # 실시간 매칭용 원본은 그대로 보관

    def test_ring_direction_helper(self):
        from app.subway import ring_direction
        assert ring_direction("2호선", "홍대입구", "신촌") == "내선"
        assert ring_direction("2호선", "홍대입구", "합정") == "외선"
        assert ring_direction("2호선", "충정로", "시청") == "내선"      # 순환 이음매
        assert ring_direction("2호선", "시청", "충정로") == "외선"
        assert ring_direction("3호선", "홍대입구", "신촌") is None
        assert ring_direction("2호선", "성수", "뚝섬") == "외선"
