import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import load_place_config
from app.main import app
from app.providers.base import MatrixResult, RouteProvider, RouteUnavailable
from app.providers.google import MATRIX_URL, ROUTES_URL, GoogleClient, GoogleRouteProvider, GoogleSettings
from app.routers.search import get_place_lookup_service
from app.services import get_place_service, get_rating_service, get_route_provider, get_routes_store
from app.services.place_lookup import KakaoPlaceLookupService, PlaceHit, PlaceLookupError
from app.services.place_search import MockPlaceService
from app.services.rating import MockRatingService, RatingResult, RatingService
from app.services.routes_store import RoutesStore
from app.stations import load_stations

FIXTURES = Path(__file__).parent / "fixtures"
HONGDAE = {"name": "민지", "lat": 37.556871, "lng": 126.923779, "age_group": "20s"}
JAMSIL = {"name": "서준", "lat": 37.513311, "lng": 127.100231, "age_group": "20s"}
NOWON = {"name": "하윤", "lat": 37.656340, "lng": 127.063449, "age_group": "30s"}


class FakeProvider(RouteProvider):
    """경로 API 없이 호출 내용만 기록하는 가짜. minutes(origin_index, dest_index) → 분 또는 None."""

    name = "google"

    def __init__(self, minutes=lambda i, j: 30.0, error=None, route=None, route_error=None):
        self.minutes, self.error, self.route_value, self.route_error = minutes, error, route, route_error
        self.matrix_calls: list[tuple] = []
        self.route_calls: list[tuple] = []

    def matrix(self, origins, destinations):
        self.matrix_calls.append((list(origins), [d.name for d in destinations]))
        if self.error:
            return MatrixResult(minutes=[[None] * len(destinations) for _ in origins], error=self.error)
        grid = [[self.minutes(i, j) for j in range(len(destinations))] for i in range(len(origins))]
        return MatrixResult(minutes=grid, api_calls=1)

    def route(self, origin, destination):
        self.route_calls.append((origin, destination.name))
        if self.route_error:
            raise RouteUnavailable(self.route_error)
        return self.route_value


@pytest.fixture
def client():
    """기본: 경로 API가 실패하는 상황(추정값만 사용). 개별 테스트가 provider를 바꿔 끼운다."""
    app.dependency_overrides[get_route_provider] = lambda: FakeProvider(error="테스트: 경로 API 없음")
    yield TestClient(app)
    app.dependency_overrides.clear()


def use(provider):
    app.dependency_overrides[get_route_provider] = lambda: provider
    return provider


def post(client, participants, purpose="meal"):
    return client.post("/api/recommend/regions", json={"participants": participants, "purpose": purpose})


# --------------------------------------------------------------------------- 1단계: 추정만으로 (API 0회)
def test_stage1_alone_returns_top3_with_evidence(client):
    body = post(client, [HONGDAE, JAMSIL, NOWON]).json()
    assert [r["rank"] for r in body["regions"]] == [1, 2, 3]
    first = body["regions"][0]
    assert [p["name"] for p in first["participants"]] == ["민지", "서준", "하윤"]
    assert set(first["metrics"]) == {"avg_minutes", "max_minutes", "std_minutes"}
    assert set(first["normalized"]) == {"avg", "max", "std"} and set(first["metric_ranks"]) == {"avg", "max", "std"}
    assert body["meta"]["candidate_count"] == 20  # config의 K. 후보가 몇 개든 API 호출은 늘지 않는다
    scores = [r["score"] for r in body["regions"]]
    assert scores == sorted(scores, reverse=True)


def test_when_the_route_api_fails_everything_is_marked_as_estimate(client):
    body = post(client, [HONGDAE, JAMSIL]).json()
    assert body["meta"]["phase2"]["status"] == "failed" and "테스트" in body["meta"]["phase2"]["reason"]
    assert body["meta"]["travel_source"] == "estimate"
    assert all(p["is_estimated"] for r in body["regions"] for p in r["participants"])
    assert len(body["regions"]) == 3


@pytest.mark.parametrize("count", [0, 1, 6])
def test_participant_count_out_of_range(client, count):
    assert post(client, [{**HONGDAE, "name": f"p{i}"} for i in range(count)]).status_code == 422


def test_two_and_five_participants(client):
    assert post(client, [HONGDAE, JAMSIL]).status_code == 200
    five = [{**HONGDAE, "name": f"p{i}", "lat": 37.5 + i * 0.02} for i in range(5)]
    assert post(client, five).status_code == 200


def test_invalid_inputs_are_rejected(client):
    assert post(client, [HONGDAE, {**JAMSIL, "age_group": "70s"}]).status_code == 422
    assert post(client, [HONGDAE, JAMSIL], purpose="sports").status_code == 422
    assert post(client, [HONGDAE, {**JAMSIL, "lat": 0.0}]).status_code == 422


# --------------------------------------------------------------------------- 2단계: 상위 3곳만 확인
def test_stage2_calls_matrix_once_with_only_the_top_three(client):
    provider = use(FakeProvider())
    body = post(client, [HONGDAE, JAMSIL, NOWON]).json()
    assert len(provider.matrix_calls) == 1
    origins, destinations = provider.matrix_calls[0]
    assert len(origins) == 3 and len(destinations) == 3  # 후보 20곳이 아니라 상위 3곳
    assert provider.route_calls == []                     # 상세 경로는 이름을 눌렀을 때만
    assert body["meta"]["phase2"]["status"] == "ok" and body["meta"]["travel_source"] == "google"
    assert all(not p["is_estimated"] for r in body["regions"] for p in r["participants"])


def test_actual_minutes_replace_estimates_and_reorder_the_top_three(client):
    stage1_top = post(client, [HONGDAE, JAMSIL]).json()["regions"][0]["station"]["name"]
    top_index = {}

    class Skewed(FakeProvider):
        def matrix(self, origins, destinations):
            top_index["j"] = [d.name for d in destinations].index(stage1_top)
            return super().matrix(origins, destinations)

    # 1단계 1위가 실제로는 한 명에게 매우 먼 곳이었던 상황 (추정이 틀림)
    use(Skewed(minutes=lambda i, j: 90.0 if (i == 0 and j == top_index.get("j", 0)) else 25.0))
    regions = post(client, [HONGDAE, JAMSIL]).json()["regions"]
    assert regions[0]["station"]["name"] != stage1_top
    moved = next(r for r in regions if r["station"]["name"] == stage1_top)
    assert moved["participants"][0]["minutes"] == 90.0 and moved["rank"] > 1


def test_estimate_accuracy_is_reported(client):
    use(FakeProvider(minutes=lambda i, j: 30.0))
    acc = post(client, [HONGDAE, JAMSIL, NOWON]).json()["meta"]["estimate_accuracy"]
    assert len(acc["pairs"]) == 9
    diffs = [p["diff_minutes"] for p in acc["pairs"]]
    assert acc["mae_minutes"] == pytest.approx(sum(abs(d) for d in diffs) / 9, abs=0.15)
    assert all(p["actual_minutes"] == 30.0 for p in acc["pairs"])


def test_missing_matrix_cells_fall_back_to_estimates_only_for_those(client):
    use(FakeProvider(minutes=lambda i, j: None if (i == 1 and j == 0) else 30.0))
    regions = post(client, [HONGDAE, JAMSIL]).json()["regions"]
    assert sum(p["is_estimated"] for r in regions for p in r["participants"]) == 1


# --------------------------------------------------------------------------- 실제 Google 프로바이더 + 가짜 HTTP: 호출 횟수
SETTINGS = GoogleSettings(departure_hour=18, utc_offset_hours=9, cache_ttl_days=7, max_retries=1,
                          backoff_seconds=0, timeout_seconds=5, cooldown_seconds=120)


class FakeResp:
    def __init__(self, status, body):
        self.status_code, self._body, self.content = status, body, b"x"

    def json(self):
        return self._body


class FakeHttp:
    """Google 서버 흉내. URL별 호출을 기록한다."""

    def __init__(self, route_fixture="google_route_hapjeong_euljiro3ga.json"):
        self.calls: list[str] = []
        self.route_response = json.loads((FIXTURES / route_fixture).read_text(encoding="utf-8"))["response"]
        self.lock = threading.Lock()

    def post(self, url, json=None, headers=None):
        with self.lock:
            self.calls.append(url)
        if url == MATRIX_URL:
            elements = [{"originIndex": i, "destinationIndex": j, "duration": f"{(20 + 5 * j + 3 * i) * 60}s",
                         "condition": "ROUTE_EXISTS"}
                        for i in range(len(json["origins"])) for j in range(len(json["destinations"]))]
            return FakeResp(200, elements)
        return FakeResp(200, self.route_response)

    def count(self, url):
        return self.calls.count(url)


@pytest.fixture
def google(tmp_path):
    http = FakeHttp()
    store = RoutesStore(tmp_path / "routes.sqlite3")
    provider = GoogleRouteProvider(GoogleClient("test-key", "live", store, SETTINGS, http=http), SETTINGS)
    app.dependency_overrides[get_route_provider] = lambda: provider
    app.dependency_overrides[get_routes_store] = lambda: store
    yield http, provider, store
    app.dependency_overrides.clear()


def test_one_search_makes_at_most_one_google_matrix_call_and_no_route_calls(google):
    http, _, _ = google
    c = TestClient(app)
    payload = {"participants": [HONGDAE, JAMSIL, NOWON], "purpose": "meal"}
    first = c.post("/api/recommend/regions", json=payload).json()
    assert http.count(MATRIX_URL) == 1 and http.count(ROUTES_URL) == 0
    assert first["meta"]["phase2"]["api_calls"] == 1 and first["meta"]["travel_source"] == "google"
    again = c.post("/api/recommend/regions", json=payload).json()
    assert http.count(MATRIX_URL) == 1  # 같은 검색은 캐시 → 호출 0
    assert again["meta"]["phase2"]["api_calls"] == 0 and again["meta"]["phase2"]["cache_hits"] == 9


def test_route_detail_is_requested_only_when_asked_and_then_cached(google):
    http, _, _ = google
    c = TestClient(app)
    station = next(s for s in load_stations() if s.name == "을지로3가역")
    body = {"lat": 37.54991, "lng": 126.91445, "station_id": station.id}
    r = c.post("/api/route", json=body).json()
    assert http.count(ROUTES_URL) == 1 and r["note"] is None
    route = r["route"]
    assert set(route) == {"totalMinutes", "transfers", "segments", "source"} and route["source"] == "google"
    seg = route["segments"][0]
    assert set(seg) == {"mode", "lineName", "lineColor", "from", "to", "minutes", "path"}
    assert (seg["mode"], seg["lineName"], seg["lineColor"]) == ("SUBWAY", "2호선", "#35b12b")
    assert seg["path"][0][0] == pytest.approx(37.5499, abs=0.01)  # [lat, lng] 순서
    c.post("/api/route", json=body)
    assert http.count(ROUTES_URL) == 1  # 두 번째 클릭은 캐시


def test_route_failure_falls_back_to_a_labelled_estimate_route(client):
    use(FakeProvider(route_error="Google 할당량을 초과했어요"))
    station = next(s for s in load_stations() if s.name == "을지로3가역")
    r = client.post("/api/route", json={"lat": 37.54991, "lng": 126.91445, "station_id": station.id}).json()
    assert r["route"]["source"] == "estimate" and "추정 경로" in r["note"] and "할당량" in r["note"]
    assert r["route"]["segments"][0]["mode"] == "WALK" and any(s["mode"] == "SUBWAY" for s in r["route"]["segments"])


def test_unknown_station_is_404(client):
    assert client.post("/api/route", json={"lat": 37.5, "lng": 127.0, "station_id": "nope"}).status_code == 404


def test_dev_usage_shows_todays_counters(google):
    c = TestClient(app)
    c.post("/api/recommend/regions", json={"participants": [HONGDAE, JAMSIL], "purpose": "meal"})
    usage = c.get("/api/dev/usage").json()
    assert usage["provider"] == "google" and usage["counters"]["matrix"] == 1


# --------------------------------------------------------------------------- POST /api/recommend (장소 포함)
@pytest.fixture
def full_client(client):
    cfg = load_place_config()
    app.dependency_overrides[get_place_service] = lambda: MockPlaceService(cfg.radius_m, cfg.max_results)
    app.dependency_overrides[get_rating_service] = MockRatingService
    return client


def post_full(client, purpose="meal", participants=None):
    return client.post("/api/recommend", json={"participants": participants or [HONGDAE, JAMSIL, NOWON],
                                                "purpose": purpose})


def test_full_response_has_three_regions_with_five_places(full_client):
    body = post_full(full_client).json()
    assert len(body["regions"]) == 3
    for region in body["regions"]:
        assert region["metrics"] and region["participants"]
        assert len(region["places"]) == 5
        assert [p["rank"] for p in region["places"]] == [1, 2, 3, 4, 5]
        assert all(p["reason"].startswith("역에서 도보") for p in region["places"])
        scores = [p["score"] for p in region["places"]]
        assert scores == sorted(scores, reverse=True)


def test_age_preferences_are_flagged_as_assumed(full_client):
    body = post_full(full_client).json()
    assert body["meta"]["age_preference"]["source"] == "assumed"
    assert body["meta"]["age_preference"]["is_assumed"] is True
    assert all(p["age_fit_assumed"] for r in body["regions"] for p in r["places"])


def test_drink_purpose_only_returns_sul_jip(full_client):
    body = post_full(full_client, purpose="drink").json()
    places = [p for r in body["regions"] for p in r["places"]]
    assert places and all("술집" in p["category"] for p in places)


def test_cafe_purpose_uses_cafe_category(full_client):
    body = post_full(full_client, purpose="cafe").json()
    assert all(p["category"].startswith("음식점 > 카페") or "제과" in p["category"]
               for r in body["regions"] for p in r["places"])


def test_ratings_unavailable_still_returns_places_with_renormalized_weights(full_client):
    class NoRatings(RatingService):
        source = "google"

        def get_rating(self, place, station_name):
            return RatingResult(None, None, "quota_exceeded")

    app.dependency_overrides[get_rating_service] = NoRatings
    body = post_full(full_client).json()
    assert body["meta"]["ratings"]["status_counts"] == {"quota_exceeded": 15}
    place = body["regions"][0]["places"][0]
    assert place["rating"] is None and place["components"]["rating"] is None
    assert set(place["weights_used"]) == {"accessibility", "purpose", "age"}
    assert sum(place["weights_used"].values()) == pytest.approx(1.0, abs=1e-3)
    assert place["reason"].endswith("평점 정보 없음")


def test_ratings_are_requested_only_for_top_five_per_region(full_client):
    calls = []

    class Spy(MockRatingService):
        def get_rating(self, place, station_name):
            calls.append(place.id)
            return super().get_rating(place, station_name)

    app.dependency_overrides[get_rating_service] = Spy
    post_full(full_client)
    assert len(calls) == 15  # 지역 3곳 × 5곳, 후보 45곳 전체가 아님


# --------------------------------------------------------------------------- GET /api/search/places
def test_search_places_returns_hits(client):
    class Fake:
        def search(self, query):
            return [PlaceHit("1", f"{query}역 2호선", "서울 마포구", "교통 > 지하철", 37.55, 126.92)]

    app.dependency_overrides[get_place_lookup_service] = Fake
    r = client.get("/api/search/places", params={"query": "홍대입구"})
    assert r.status_code == 200
    assert r.json() == [{"id": "1", "name": "홍대입구역 2호선", "address": "서울 마포구",
                         "category": "교통 > 지하철", "lat": 37.55, "lng": 126.92}]


def test_search_places_requires_query_and_maps_errors(client):
    assert client.get("/api/search/places").status_code == 422

    class Broken:
        def search(self, query):
            raise PlaceLookupError("카카오 검색 오류(HTTP 403)")

    app.dependency_overrides[get_place_lookup_service] = Broken
    r = client.get("/api/search/places", params={"query": "강남"})
    assert (r.status_code, r.json()["detail"]) == (502, "카카오 검색 오류(HTTP 403)")


def test_search_places_without_key_fails_cleanly():
    with pytest.raises(PlaceLookupError):
        KakaoPlaceLookupService("").search("강남")
