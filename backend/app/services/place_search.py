"""장소 검색 서비스: 인터페이스 + mock + 카카오 카테고리 검색 + SQLite 캐시 래퍼."""

import logging
import math
import random
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass

import httpx2 as httpx

from app.services.places_cache import PlacesCache
from app.stations import Station

logger = logging.getLogger(__name__)


class PlaceSearchError(Exception):
    """장소 검색 실패. str(e)가 사유."""


@dataclass(frozen=True)
class Place:
    id: str
    name: str
    category_name: str
    address: str
    lat: float
    lng: float
    distance_m: float  # 역(검색 중심)에서의 거리
    url: str = ""
    phone: str = ""


class PlaceService(ABC):
    source: str

    @abstractmethod
    def search_nearby(self, station: Station, category_code: str) -> list[Place]:
        """역 반경 내 장소를 가까운 순으로 반환한다 (최대 max_results개)."""


# --------------------------------------------------------------------------- mock
_MOCK_FOOD = [
    ("음식점 > 한식 > 육류,고기", "고깃집"), ("음식점 > 한식 > 국밥", "국밥"), ("음식점 > 한식 > 찌개,전골", "찌개집"),
    ("음식점 > 일식 > 초밥,롤", "스시"), ("음식점 > 일식 > 돈까스,우동", "돈카츠"), ("음식점 > 양식 > 이탈리안", "파스타"),
    ("음식점 > 양식 > 햄버거", "버거"), ("음식점 > 중식", "중화요리"), ("음식점 > 분식", "분식"),
    ("음식점 > 아시아음식 > 동남아음식 > 베트남음식", "쌀국수"), ("음식점 > 패스트푸드 > 맥도날드", "패스트푸드"),
    ("음식점 > 술집 > 호프,통닭", "호프"), ("음식점 > 술집 > 일본식주점", "이자카야"), ("음식점 > 술집 > 실내포장마차", "포차"),
]
_MOCK_CAFE = [
    ("음식점 > 카페 > 커피전문점", "커피"), ("음식점 > 카페 > 커피전문점 > 스타벅스", "스타벅스"),
    ("음식점 > 카페 > 디저트카페", "디저트"), ("음식점 > 카페 > 테마카페 > 보드카페", "보드카페"),
    ("음식점 > 간식 > 제과,베이커리", "베이커리"),
]


class MockPlaceService(PlaceService):
    """API 키 없이 쓰는 고정 데이터. 같은 (역, 카테고리)에는 항상 같은 장소를 만든다."""

    source = "mock"

    def __init__(self, radius_m: float, max_results: int):
        self.radius_m = radius_m
        self.max_results = max_results

    def search_nearby(self, station: Station, category_code: str) -> list[Place]:
        rng = random.Random(f"{station.id}:{category_code}")
        kinds = _MOCK_CAFE if category_code == "CE7" else _MOCK_FOOD
        places = []
        for i in range(self.max_results):
            category, label = rng.choice(kinds)
            distance = rng.uniform(15, self.radius_m)
            bearing = rng.uniform(0, 2 * math.pi)
            lat = station.coord.lat + distance * math.cos(bearing) / 111_320
            lng = station.coord.lng + distance * math.sin(bearing) / (111_320 * math.cos(math.radians(station.coord.lat)))
            pid = f"mock-{station.id}-{category_code}-{i}"
            places.append(Place(
                id=pid, name=f"{station.name[:-1]} {label} {i + 1}호점", category_name=category,
                address=f"{station.address or station.name} 인근", lat=lat, lng=lng,
                distance_m=round(distance), url=f"https://place.map.kakao.com/{pid}",
            ))
        return sorted(places, key=lambda p: (p.distance_m, p.id))


# --------------------------------------------------------------------------- kakao
class KakaoPlaceService(PlaceService):
    """카카오 로컬 카테고리 검색. 한 페이지 15개, 최대 3페이지(45개)."""

    source = "kakao"
    URL = "https://dapi.kakao.com/v2/local/search/category.json"
    PAGE_SIZE = 15
    MAX_PAGES = 3  # 카카오 API의 페이지 상한

    def __init__(self, api_key: str, radius_m: float, max_results: int,
                 timeout: float = 10.0, client: httpx.Client | None = None):
        if not api_key:
            raise ValueError("KAKAO_REST_API_KEY가 설정되지 않았습니다.")
        self._api_key = api_key
        self.radius_m = radius_m
        self.max_results = max_results
        self._client = client or httpx.Client(timeout=timeout)
        self.http_calls = 0

    def search_nearby(self, station: Station, category_code: str) -> list[Place]:
        places: list[Place] = []
        pages = min(self.MAX_PAGES, math.ceil(self.max_results / self.PAGE_SIZE))
        for page in range(1, pages + 1):
            body = self._get_page(station, category_code, page)
            places.extend(_parse_kakao(d) for d in body.get("documents", []))
            if body.get("meta", {}).get("is_end", True):
                break
        return places[: self.max_results]

    def _get_page(self, station: Station, category_code: str, page: int) -> dict:
        self.http_calls += 1
        try:
            r = self._client.get(
                self.URL,
                params={"category_group_code": category_code, "x": station.coord.lng,
                        "y": station.coord.lat, "radius": int(self.radius_m),
                        "size": self.PAGE_SIZE, "page": page, "sort": "distance"},
                headers={"Authorization": f"KakaoAK {self._api_key}"},
            )
        except httpx.HTTPError as e:
            raise PlaceSearchError(f"카카오 요청 실패({type(e).__name__})") from None
        if r.status_code != 200:
            raise PlaceSearchError(f"카카오 HTTP {r.status_code}: {r.text[:120]}")
        return r.json()


def _parse_kakao(d: dict) -> Place:
    return Place(
        id=d["id"], name=d["place_name"], category_name=d.get("category_name", ""),
        address=d.get("road_address_name") or d.get("address_name", ""),
        lat=float(d["y"]), lng=float(d["x"]), distance_m=float(d.get("distance") or 0),
        url=d.get("place_url", ""), phone=d.get("phone", ""),
    )


# --------------------------------------------------------------------------- cache
class CachedPlaceService(PlaceService):
    """같은 (역, 카테고리, 반경, 최대 개수)는 SQLite에서 읽고 API를 다시 부르지 않는다."""

    def __init__(self, inner: PlaceService, cache: PlacesCache, radius_m: float,
                 max_results: int, ttl_days: int):
        self.inner, self.cache = inner, cache
        self.source = inner.source
        self._key = (int(radius_m), max_results)
        self._ttl_days = ttl_days
        self.hits = 0
        self.misses = 0

    def search_nearby(self, station: Station, category_code: str) -> list[Place]:
        cached = self.cache.get_places(station.id, category_code, *self._key, self._ttl_days)
        if cached is not None:
            self.hits += 1
            return [Place(**d) for d in cached]
        self.misses += 1
        places = self.inner.search_nearby(station, category_code)  # 실패는 전파 → 캐시 안 함
        self.cache.set_places(station.id, category_code, *self._key, [asdict(p) for p in places])
        return places
