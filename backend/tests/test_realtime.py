import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers.realtime import get_realtime
from app.services.realtime import BusRealtime, SubwayRealtime, TtlCache, parse_bus, parse_subway, pick_station
from app.subway import load_network

SUBWAY_PAYLOAD = {"realtimeArrivalList": [
    # 2호선 외선(성수행, 합정방면) — 신촌에서 오는 중 (홍대입구 다음 역이 합정이 아니라 신촌인 내선과 구분돼야 함)
    {"subwayId": "1002", "updnLine": "외선", "trainLineNm": "성수행 - 합정방면", "arvlMsg2": "3분 50초 후", "arvlMsg3": "아현", "barvlDt": "230", "arvlCd": "99"},
    {"subwayId": "1002", "updnLine": "내선", "trainLineNm": "신도림행 - 신촌방면", "arvlMsg2": "[2]번째 전역 (합정)", "arvlMsg3": "합정", "barvlDt": "300", "arvlCd": "99"},
    {"subwayId": "1002", "updnLine": "내선", "trainLineNm": "신도림행 - 신촌방면", "arvlMsg2": "전역 도착", "arvlMsg3": "합정", "barvlDt": "120", "arvlCd": "5"},
    {"subwayId": "1002", "updnLine": "내선", "trainLineNm": "신도림행 - 신촌방면", "arvlMsg2": "홍대입구 출발", "arvlMsg3": "홍대입구", "barvlDt": "0", "arvlCd": "2"},
    {"subwayId": "1065", "updnLine": "상행", "trainLineNm": "검암행 - 디지털미디어시티방면", "arvlMsg2": "곧", "arvlMsg3": "x", "barvlDt": "60", "arvlCd": "99"},
]}


def test_subway_filters_by_line_and_direction_and_sorts_by_time():
    got = parse_subway(SUBWAY_PAYLOAD, "2호선", "홍대입구", "신도림역 방면", "신촌")
    assert [(a.seconds, a.stops_away) for a in got] == [(120, 1), (300, 2)]  # 출발한 열차·반대 방향·다른 호선 제외, 최대 2개


def test_subway_matches_by_next_station_when_headsign_is_not_the_terminal():
    got = parse_subway(SUBWAY_PAYLOAD, "2호선", "홍대입구", "엉뚱한역 방면", "합정")
    assert [a.seconds for a in got] == [230]


def test_subway_stops_away_is_computed_from_the_line_map_when_the_message_has_no_count():
    got = parse_subway(SUBWAY_PAYLOAD, "2호선", "홍대입구", "성수역 방면", None, load_network())
    assert got[0].seconds == 230 and got[0].stops_away == 3  # 아현→이대→신촌→홍대입구 (노선도로 계산)


def test_subway_unknown_line_returns_nothing():
    assert parse_subway(SUBWAY_PAYLOAD, "99호선", "홍대입구", "신도림역 방면", "신촌") == []


BUS_POS = {"msgHeader": {"headerCd": "0"}, "msgBody": {"itemList": [
    {"arsId": "14001", "stationNm": "다른정류장", "dist": "20"}, {"arsId": "14002", "stationNm": "홍대입구역", "dist": "90"}]}}
BUS_ARR = {"msgHeader": {"headerCd": "0"}, "msgBody": {"itemList": [
    {"rtNm": "741", "arrmsg1": "3분10초후[2번째 전]", "arrmsg2": "12분5초후[7번째 전]", "traTime1": "190", "traTime2": "725", "adirection": "강남"},
    {"rtNm": "7011", "arrmsg1": "곧 도착", "arrmsg2": "운행종료"},
]}}


def test_bus_picks_the_same_named_station_then_filters_the_route():
    assert pick_station(BUS_POS, "홍대입구역") == "14002"
    got = parse_bus(BUS_ARR, "741")
    assert [(a.seconds, a.stops_away) for a in got] == [(190, 2), (725, 7)]
    assert parse_bus(BUS_ARR, "7011")[0].seconds == 30 and len(parse_bus(BUS_ARR, "7011")) == 1  # 운행종료는 제외
    assert parse_bus(BUS_ARR, "999") == []


def test_bus_single_item_dict_response_is_handled():
    payload = {"msgHeader": {"headerCd": "0"}, "msgBody": {"itemList": {"rtNm": "741", "arrmsg1": "5분후[3번째 전]"}}}
    assert parse_bus(payload, "741")[0].seconds == 300


class Counting:
    def __init__(self, routes):
        self.calls = []
        self.routes = routes

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(str(request.url))
        for needle, (status, body) in self.routes.items():
            if needle in str(request.url):
                return httpx.Response(status, json=body)
        return httpx.Response(404, json={})


def services(routes, subway_key="sk", bus_key="bk"):
    t = Counting(routes)
    http = httpx.Client(transport=httpx.MockTransport(t))
    cache = TtlCache(30)
    return (SubwayRealtime(subway_key, http, cache), BusRealtime(bus_key, http, cache)), t


@pytest.fixture
def client():
    yield TestClient(app)
    app.dependency_overrides.clear()


SUBWAY_Q = "/api/realtime?type=subway&station=홍대입구역&line=2호선&headsign=신도림역 방면&next=신촌"
BUS_Q = "/api/realtime?type=bus&lat=37.5569&lng=126.9238&stop=홍대입구역&line=741"


def test_endpoint_returns_arrivals_and_caches_for_30_seconds(client):
    svc, t = services({"realtimeStationArrival": (200, SUBWAY_PAYLOAD)})
    app.dependency_overrides[get_realtime] = lambda: svc
    first = client.get(SUBWAY_Q).json()
    assert first["available"] and len(first["items"]) == 2 and first["items"][0]["seconds"] == 120
    client.get(SUBWAY_Q)
    client.get(SUBWAY_Q.replace("신촌", "합정"))  # 같은 역이면 방면이 달라도 호출은 한 번
    assert len(t.calls) == 1
    from urllib.parse import unquote
    assert "/sk/" in t.calls[0] and unquote(t.calls[0]).endswith("/홍대입구")  # 역 접미사 제거


def test_endpoint_bus_flow_uses_station_lookup_then_arrival(client):
    svc, t = services({"getStationByPos": (200, BUS_POS), "getStationByUid": (200, BUS_ARR)})
    app.dependency_overrides[get_realtime] = lambda: svc
    body = client.get(BUS_Q).json()
    assert body["available"] and body["items"][0]["stopsAway"] == 2
    client.get(BUS_Q)
    assert len(t.calls) == 2  # 정류소 조회 1 + 도착 조회 1, 이후는 캐시
    assert "arsId=14002" in t.calls[1]


@pytest.mark.parametrize("query", [SUBWAY_Q, BUS_Q])
def test_no_keys_means_quiet_unavailable(client, query):
    svc, t = services({}, subway_key="", bus_key="")
    app.dependency_overrides[get_realtime] = lambda: svc
    r = client.get(query)
    assert r.status_code == 200 and r.json()["available"] is False and t.calls == []


@pytest.mark.parametrize("query", [SUBWAY_Q, BUS_Q])
def test_upstream_errors_are_quiet(client, query):
    svc, _ = services({"realtimeStationArrival": (500, {}), "getStationByPos": (401, {"error": "x"})})
    app.dependency_overrides[get_realtime] = lambda: svc
    r = client.get(query)
    assert r.status_code == 200 and r.json()["available"] is False and "sk" not in r.text and "bk" not in r.text


def test_outside_seoul_bus_makes_no_call(client):
    svc, t = services({})
    app.dependency_overrides[get_realtime] = lambda: svc
    r = client.get("/api/realtime?type=bus&lat=35.1796&lng=129.0756&stop=서면&line=1001").json()
    assert r["available"] is False and t.calls == []
