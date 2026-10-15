"""출발지 자동완성용 키워드 검색 (카카오 로컬 키워드 검색).

다른 서비스와 달리 mock 구현을 두지 않는다: 자동완성은 항상 실제 카카오 API를 쓴다.
테스트에서는 의존성을 가짜 구현으로 교체한다.
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx2 as httpx

logger = logging.getLogger(__name__)


class PlaceLookupError(Exception):
    """검색 실패. str(e)가 사용자에게 보여줄 사유."""


@dataclass(frozen=True)
class PlaceHit:
    id: str
    name: str
    address: str
    category: str
    lat: float
    lng: float


class PlaceLookupService(ABC):
    @abstractmethod
    def search(self, query: str) -> list[PlaceHit]: ...


class KakaoPlaceLookupService(PlaceLookupService):
    URL = "https://dapi.kakao.com/v2/local/search/keyword.json"

    def __init__(self, api_key: str, size: int = 8, timeout: float = 5.0,
                 client: httpx.Client | None = None):
        self._api_key = api_key
        self._size = size
        self._client = client or httpx.Client(timeout=timeout)

    def search(self, query: str) -> list[PlaceHit]:
        if not self._api_key:
            raise PlaceLookupError("KAKAO_REST_API_KEY가 설정되지 않았습니다.")
        try:
            r = self._client.get(
                self.URL,
                params={"query": query, "size": self._size},
                headers={"Authorization": f"KakaoAK {self._api_key}"},
            )
        except httpx.HTTPError as e:
            logger.warning("카카오 키워드 검색 요청 실패: %s", type(e).__name__)
            raise PlaceLookupError("카카오 검색에 연결하지 못했습니다.") from None
        if r.status_code != 200:
            logger.warning("카카오 키워드 검색 HTTP %s", r.status_code)
            raise PlaceLookupError(f"카카오 검색 오류(HTTP {r.status_code})")
        return [
            PlaceHit(
                id=d["id"], name=d["place_name"],
                address=d.get("road_address_name") or d.get("address_name", ""),
                category=d.get("category_name", ""), lat=float(d["y"]), lng=float(d["x"]),
            )
            for d in r.json().get("documents", [])
        ]
