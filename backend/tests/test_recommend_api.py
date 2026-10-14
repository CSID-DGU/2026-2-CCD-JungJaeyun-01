import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import get_travel_time_service
from app.services.travel_time import MockTravelTimeService, TravelTimeUnavailable
from app.config import load_travel_config

HONGDAE = {"name": "민지", "lat": 37.556871, "lng": 126.923779, "age_group": "20s"}
JAMSIL = {"name": "서준", "lat": 37.513311, "lng": 127.100231, "age_group": "20s"}
NOWON = {"name": "하윤", "lat": 37.656340, "lng": 127.063449, "age_group": "30s"}


@pytest.fixture
def client():
    app.dependency_overrides[get_travel_time_service] = lambda: MockTravelTimeService(
        load_travel_config().mock
    )
    yield TestClient(app)
    app.dependency_overrides.clear()


def post(client, participants, purpose="meal"):
    return client.post("/api/recommend/regions", json={"participants": participants, "purpose": purpose})


def test_returns_top3_with_evidence(client):
    r = post(client, [HONGDAE, JAMSIL, NOWON])
    assert r.status_code == 200
    body = r.json()
    assert [x["rank"] for x in body["regions"]] == [1, 2, 3]
    first = body["regions"][0]
    assert [p["name"] for p in first["participants"]] == ["민지", "서준", "하윤"]
    assert set(first["metrics"]) == {"avg_minutes", "max_minutes", "std_minutes"}
    assert set(first["normalized"]) == {"avg", "max", "std"}
    assert set(first["metric_ranks"]) == {"avg", "max", "std"}
    assert body["meta"]["candidate_count"] == 12
    assert body["meta"]["travel_source"] == "mock"
    scores = [x["score"] for x in body["regions"]]
    assert scores == sorted(scores, reverse=True)


def test_two_and_five_participants(client):
    assert post(client, [HONGDAE, JAMSIL]).status_code == 200
    five = [{**HONGDAE, "name": f"p{i}", "lat": 37.5 + i * 0.02} for i in range(5)]
    assert post(client, five).status_code == 200


@pytest.mark.parametrize("count", [0, 1, 6])
def test_participant_count_out_of_range(client, count):
    assert post(client, [{**HONGDAE, "name": f"p{i}"} for i in range(count)]).status_code == 422


def test_invalid_age_group_and_purpose(client):
    assert post(client, [HONGDAE, {**JAMSIL, "age_group": "70s"}]).status_code == 422
    assert post(client, [HONGDAE, JAMSIL], purpose="sports").status_code == 422


def test_coordinates_outside_korea_rejected(client):
    assert post(client, [HONGDAE, {**JAMSIL, "lat": 0.0}]).status_code == 422


def test_no_reachable_region_returns_503(client):
    class Unreachable:
        source = "mock"

        def get_minutes(self, origin, station):
            raise TravelTimeUnavailable("ODsay 429 Daily quota exceeded")

    app.dependency_overrides[get_travel_time_service] = Unreachable
    assert post(client, [HONGDAE, JAMSIL]).status_code == 503


def test_failed_station_is_excluded_with_reason(client):
    class FailsForOneStation(MockTravelTimeService):
        def get_minutes(self, origin, station):
            if station.name == "청량리역":
                raise TravelTimeUnavailable("ODsay 429 Daily quota exceeded (재시도 2회 후에도 실패)")
            return super().get_minutes(origin, station)

    app.dependency_overrides[get_travel_time_service] = lambda: FailsForOneStation(load_travel_config().mock)
    meta = post(client, [HONGDAE, JAMSIL, NOWON]).json()["meta"]
    assert meta["evaluated_count"] == 11
    assert meta["excluded_stations"] == [
        {"station": "청량리역", "reason": "민지 출발: ODsay 429 Daily quota exceeded (재시도 2회 후에도 실패)"}
    ]


# --------------------------------------------------------------------------- POST /api/recommend
from app.config import load_place_config  # noqa: E402
from app.services import get_place_service, get_rating_service  # noqa: E402
from app.services.place_search import MockPlaceService  # noqa: E402
from app.services.rating import MockRatingService, RatingResult, RatingService  # noqa: E402


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
