import pytest

from app.config import load_place_config
from app.geo import Coord
from app.services.place_search import CachedPlaceService, KakaoPlaceService, Place, PlaceService
from app.services.places_cache import PlacesCache
from app.services.rating import (
    STATUS_ERROR,
    STATUS_NO_KEY,
    STATUS_NOT_FOUND,
    STATUS_OK,
    STATUS_QUOTA,
    GoogleRatingService,
    names_match,
)
from app.stations import Station

PLACE = Place(id="1", name="포490베트남쌀국수 강남점", category_name="음식점 > 아시아음식",
              address="서울 강남구", lat=37.498, lng=127.0278, distance_m=22)
STATION = Station(id="s1", name="강남역", coord=Coord(37.498, 127.028))
GOOD = {"places": [{"displayName": {"text": "포490 베트남쌀국수 강남점"}, "rating": 4.4, "userRatingCount": 321}]}


class FakeResponse:
    def __init__(self, body, status=200):
        self._body, self.status_code, self.text = body, status, str(body)

    def json(self):
        return self._body


class FakeClient:
    def __init__(self, *responses):
        self.responses, self.requests = list(responses), []

    def _next(self, request):
        self.requests.append(request)
        return self.responses[min(len(self.requests) - 1, len(self.responses) - 1)]

    def post(self, url, headers=None, json=None):
        return self._next({"headers": headers, "json": json})

    def get(self, url, params=None, headers=None):
        return self._next({"params": params, "headers": headers})


def google(tmp_path, *responses, key="dummy", limit=100, day="2026-10-14"):
    client = FakeClient(*responses)
    svc = GoogleRatingService(key, PlacesCache(tmp_path / "p.sqlite3"), daily_limit=limit,
                              cache_ttl_days=30, match_radius_m=150, client=client, today=lambda: day)
    return svc, client


class TestGoogleRating:
    def test_ok_returns_rating_and_count(self, tmp_path):
        svc, _ = google(tmp_path, FakeResponse(GOOD))
        r = svc.get_rating(PLACE, STATION.name)
        assert (r.status, r.rating, r.review_count) == (STATUS_OK, 4.4, 321)

    def test_requests_only_the_minimal_field_mask(self, tmp_path):
        svc, client = google(tmp_path, FakeResponse(GOOD))
        svc.get_rating(PLACE, STATION.name)
        sent = client.requests[0]
        assert sent["headers"]["X-Goog-FieldMask"] == "places.displayName,places.rating,places.userRatingCount"
        assert sent["json"]["pageSize"] == 1

    def test_missing_key_makes_no_call(self, tmp_path):
        svc, client = google(tmp_path, FakeResponse(GOOD), key="")
        assert svc.get_rating(PLACE, STATION.name).status == STATUS_NO_KEY
        assert client.requests == []

    def test_http_error_is_not_cached(self, tmp_path):
        svc, client = google(tmp_path, FakeResponse({"error": {}}, status=403), FakeResponse(GOOD))
        assert svc.get_rating(PLACE, STATION.name).status == STATUS_ERROR
        assert svc.get_rating(PLACE, STATION.name).status == STATUS_OK  # 재시도하면 호출됨
        assert len(client.requests) == 2

    def test_result_is_cached(self, tmp_path):
        svc, client = google(tmp_path, FakeResponse(GOOD))
        svc.get_rating(PLACE, STATION.name)
        again = svc.get_rating(PLACE, STATION.name)
        assert again.rating == 4.4 and len(client.requests) == 1

    def test_not_found_is_cached_too(self, tmp_path):
        svc, client = google(tmp_path, FakeResponse({}))
        assert svc.get_rating(PLACE, STATION.name).status == STATUS_NOT_FOUND
        assert svc.get_rating(PLACE, STATION.name).status == STATUS_NOT_FOUND
        assert len(client.requests) == 1

    def test_different_place_name_is_rejected(self, tmp_path):
        other = {"places": [{"displayName": {"text": "맥도날드 역삼점"}, "rating": 3.9, "userRatingCount": 900}]}
        svc, _ = google(tmp_path, FakeResponse(other))
        assert svc.get_rating(PLACE, STATION.name).status == STATUS_NOT_FOUND

    def test_place_without_rating_is_not_found(self, tmp_path):
        no_rating = {"places": [{"displayName": {"text": PLACE.name}}]}
        svc, _ = google(tmp_path, FakeResponse(no_rating))
        assert svc.get_rating(PLACE, STATION.name).status == STATUS_NOT_FOUND

    def test_daily_limit_stops_calls(self, tmp_path):
        svc, client = google(tmp_path, FakeResponse(GOOD), limit=2)
        places = [Place(**{**PLACE.__dict__, "id": str(i)}) for i in range(4)]
        statuses = [svc.get_rating(p, STATION.name).status for p in places]
        assert statuses == [STATUS_OK, STATUS_OK, STATUS_QUOTA, STATUS_QUOTA]
        assert len(client.requests) == 2

    def test_limit_resets_next_day(self, tmp_path):
        day = ["2026-10-14"]
        client = FakeClient(FakeResponse(GOOD))
        svc = GoogleRatingService("k", PlacesCache(tmp_path / "p.sqlite3"), 1, 30, 150,
                                  client=client, today=lambda: day[0])
        p2 = Place(**{**PLACE.__dict__, "id": "2"})
        assert svc.get_rating(PLACE, "강남역").status == STATUS_OK
        assert svc.get_rating(p2, "강남역").status == STATUS_QUOTA
        day[0] = "2026-10-15"
        assert svc.get_rating(p2, "강남역").status == STATUS_OK


def test_names_match():
    assert names_match("포490베트남쌀국수 강남점", "포490 베트남쌀국수 강남점")
    assert names_match("스타벅스 강남역점", "스타벅스")
    assert not names_match("포490베트남쌀국수 강남점", "맥도날드 역삼점")
    assert not names_match("레코드피자 을지로3가점", "레코드피자 힙지로점")  # 지점이 다른 같은 브랜드


class TestKakaoPlaces:
    def page(self, n, is_end):
        docs = [{"id": f"{n}-{i}", "place_name": f"p{n}-{i}", "category_name": "음식점 > 한식",
                 "road_address_name": "주소", "x": "127.0", "y": "37.5", "distance": str(i * 10)}
                for i in range(15)]
        return FakeResponse({"documents": docs, "meta": {"is_end": is_end}})

    def test_collects_up_to_45_over_three_pages(self):
        client = FakeClient(self.page(1, False), self.page(2, False), self.page(3, False), self.page(4, False))
        svc = KakaoPlaceService("k", 500, 45, client=client)
        assert len(svc.search_nearby(STATION, "FD6")) == 45
        assert svc.http_calls == 3

    def test_stops_when_last_page(self):
        svc = KakaoPlaceService("k", 500, 45, client=FakeClient(self.page(1, True)))
        assert len(svc.search_nearby(STATION, "FD6")) == 15
        assert svc.http_calls == 1

    def test_second_search_is_served_from_sqlite(self, tmp_path):
        inner = KakaoPlaceService("k", 500, 45, client=FakeClient(self.page(1, True)))
        cached = CachedPlaceService(inner, PlacesCache(tmp_path / "p.sqlite3"), 500, 45, ttl_days=7)
        first = cached.search_nearby(STATION, "FD6")
        second = cached.search_nearby(STATION, "FD6")
        assert first == second and inner.http_calls == 1
        assert (cached.hits, cached.misses) == (1, 1)


def test_purpose_mapping_in_config():
    purposes = load_place_config().purposes
    assert purposes["meal"].category_code == "FD6"
    assert purposes["cafe"].category_code == "CE7"
    assert (purposes["drink"].category_code, purposes["drink"].category_name_contains) == ("FD6", "술집")
    assert load_place_config().age.is_assumed is True
