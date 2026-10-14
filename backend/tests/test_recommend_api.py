import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import get_travel_time_service
from app.services.travel_time import MockTravelTimeService
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
            return None

    app.dependency_overrides[get_travel_time_service] = Unreachable
    assert post(client, [HONGDAE, JAMSIL]).status_code == 503
