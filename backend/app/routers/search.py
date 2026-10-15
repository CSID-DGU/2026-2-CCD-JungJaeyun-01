from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app import settings
from app.services.place_lookup import (
    KakaoPlaceLookupService,
    PlaceLookupError,
    PlaceLookupService,
)

router = APIRouter(prefix="/api/search", tags=["search"])


class PlaceHitOut(BaseModel):
    id: str
    name: str
    address: str
    category: str
    lat: float
    lng: float


@lru_cache
def get_place_lookup_service() -> PlaceLookupService:
    # mock 없이 항상 실제 카카오 API를 사용한다.
    return KakaoPlaceLookupService(settings.KAKAO_REST_API_KEY)


@router.get("/places", response_model=list[PlaceHitOut])
def search_places(
    query: str = Query(min_length=1, max_length=50, description="출발지 검색어"),
    service: PlaceLookupService = Depends(get_place_lookup_service),
) -> list[PlaceHitOut]:
    """출발지 자동완성: 카카오 키워드 검색 프록시 (키는 서버에만 둔다)."""
    query = query.strip()
    if not query:
        return []
    try:
        return [PlaceHitOut(**hit.__dict__) for hit in service.search(query)]
    except PlaceLookupError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
