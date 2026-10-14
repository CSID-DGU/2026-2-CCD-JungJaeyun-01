from functools import lru_cache

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app import settings
from app.services.kakao_map_check import KakaoMapDiagnostics

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])

# 헤더에 그대로 들어가므로 scheme://host[:port] 형태만 받는다.
ORIGIN_PATTERN = r"^https?://[A-Za-z0-9.\-]+(:\d{1,5})?$"


class MapDiagnosisOut(BaseModel):
    code: str
    message: str


@lru_cache
def get_map_diagnostics() -> KakaoMapDiagnostics:
    return KakaoMapDiagnostics(settings.KAKAO_JS_KEY)


@router.get("/kakao-map", response_model=MapDiagnosisOut)
def diagnose_kakao_map(
    origin: str = Query(pattern=ORIGIN_PATTERN, description="브라우저의 location.origin"),
    diagnostics: KakaoMapDiagnostics = Depends(get_map_diagnostics),
) -> MapDiagnosisOut:
    """지도 SDK 로드가 실패했을 때 원인(도메인 미등록/키 오류/카카오맵 미사용 설정 등)을 알려준다."""
    result = diagnostics.check(origin)
    return MapDiagnosisOut(code=result.code, message=result.message)
