"""평점 서비스: 인터페이스 + mock + 구글 Places API (New) Text Search.

구글은 비용이 들기 때문에 호출 전에 반드시 (1) 캐시 (2) 하루 호출 상한을 확인한다.
키가 없거나 실패하거나 상한을 넘으면 예외 대신 status로 알리고, 호출자는 평점 항목을 빼고 점수를 계산한다.
"""

import logging
import random
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
from typing import Callable

import httpx2 as httpx

from app.services.place_search import Place
from app.services.places_cache import PlacesCache

logger = logging.getLogger(__name__)

STATUS_OK = "ok"
STATUS_NOT_FOUND = "not_found"          # 구글에서 같은 장소를 못 찾았거나 평점이 없음
STATUS_NO_KEY = "no_key"
STATUS_QUOTA = "quota_exceeded"         # 하루 호출 상한 초과
STATUS_ERROR = "error"                  # HTTP/네트워크 오류


@dataclass(frozen=True)
class RatingResult:
    rating: float | None
    review_count: int | None
    status: str


class RatingService(ABC):
    source: str

    @abstractmethod
    def get_rating(self, place: Place, station_name: str) -> RatingResult: ...


class MockRatingService(RatingService):
    """장소 id로 값을 정하는 가짜 평점. 약 10%는 평점 없음으로 만들어 해당 경로도 거치게 한다."""

    source = "mock"

    def get_rating(self, place: Place, station_name: str) -> RatingResult:
        rng = random.Random(place.id)
        if rng.random() < 0.1:
            return RatingResult(None, None, STATUS_NOT_FOUND)
        return RatingResult(round(3.4 + rng.random() * 1.5, 1), int(5 + rng.random() ** 2 * 1200), STATUS_OK)


def names_match(a: str, b: str) -> bool:
    """카카오 장소명과 구글 장소명이 같은 곳인지 판단 (공백·기호 무시, 한쪽이 다른 쪽을 포함하거나 유사도 0.85 이상).

    지점명만 다른 장소(예: 레코드피자 힙지로점 / 을지로3가점)를 같은 곳으로 보지 않도록 기준을 엄격하게 둔다.
    """
    na, nb = (re.sub(r"[\W_]+", "", s.lower()) for s in (a, b))
    if not na or not nb:
        return False
    return na in nb or nb in na or SequenceMatcher(None, na, nb).ratio() >= 0.85


class GoogleRatingService(RatingService):
    source = "google"
    URL = "https://places.googleapis.com/v1/places:searchText"
    # 필요한 필드만 요청해 비용을 최소화한다 (rating, userRatingCount만 있어도 최상위 등급 요금이 적용됨).
    FIELD_MASK = "places.displayName,places.rating,places.userRatingCount"

    def __init__(
        self,
        api_key: str,
        cache: PlacesCache,
        daily_limit: int,
        cache_ttl_days: int,
        match_radius_m: float,
        timeout: float = 10.0,
        client: httpx.Client | None = None,
        today: Callable[[], str] = lambda: date.today().isoformat(),
    ):
        self._api_key = api_key
        self.cache = cache
        self.daily_limit = daily_limit
        self.cache_ttl_days = cache_ttl_days
        self.match_radius_m = match_radius_m
        self._client = client or httpx.Client(timeout=timeout)
        self._today = today
        self.http_calls = 0

    def get_rating(self, place: Place, station_name: str) -> RatingResult:
        if not self._api_key:
            return RatingResult(None, None, STATUS_NO_KEY)

        cached = self.cache.get_rating(place.id, self.cache_ttl_days)
        if cached is not None:
            return _result(*cached)

        day = self._today()
        if self.cache.usage(day) >= self.daily_limit:
            return RatingResult(None, None, STATUS_QUOTA)
        self.cache.add_usage(day)  # 요청 전에 센다: 실패해도 과금될 수 있으므로 상한을 넘기지 않게

        self.http_calls += 1
        try:
            r = self._client.post(
                self.URL,
                headers={"X-Goog-Api-Key": self._api_key, "X-Goog-FieldMask": self.FIELD_MASK,
                         "Content-Type": "application/json"},
                json={"textQuery": f"{place.name} {station_name}", "pageSize": 1,
                      "languageCode": "ko", "regionCode": "KR",
                      "locationBias": {"circle": {
                          "center": {"latitude": place.lat, "longitude": place.lng},
                          "radius": self.match_radius_m}}},
            )
        except httpx.HTTPError as e:
            logger.warning("Google Places 요청 실패(%s): %s", place.name, type(e).__name__)
            return RatingResult(None, None, STATUS_ERROR)
        if r.status_code != 200:
            logger.warning("Google Places HTTP %s (%s)", r.status_code, place.name)
            return RatingResult(None, None, STATUS_ERROR)

        found = (r.json().get("places") or [None])[0]
        rating = count = None
        if found and names_match(place.name, (found.get("displayName") or {}).get("text", "")):
            rating, count = found.get("rating"), found.get("userRatingCount")
        if rating is None or count is None:
            rating = count = None
        self.cache.set_rating(place.id, rating, count)  # '못 찾음'도 캐시해 같은 장소를 다시 조회하지 않는다
        return _result(rating, count)


def _result(rating: float | None, count: int | None) -> RatingResult:
    if rating is None or count is None:
        return RatingResult(None, None, STATUS_NOT_FOUND)
    return RatingResult(float(rating), int(count), STATUS_OK)
