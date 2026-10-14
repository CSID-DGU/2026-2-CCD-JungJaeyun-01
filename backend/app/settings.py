"""환경변수 로딩. 루트의 .env를 읽는다."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


USE_MOCK: bool = _as_bool(os.getenv("USE_MOCK"), default=True)
KAKAO_REST_API_KEY: str = os.getenv("KAKAO_REST_API_KEY", "")
# 카카오맵 JavaScript 키: 프론트가 직접 쓰는 키이며, 백엔드는 지도 로드 실패 원인 진단에만 쓴다.
KAKAO_JS_KEY: str = os.getenv("VITE_KAKAO_JS_KEY", "")
ODSAY_API_KEY: str = os.getenv("ODSAY_API_KEY", "")
GOOGLE_PLACES_API_KEY: str = os.getenv("GOOGLE_PLACES_API_KEY", "")

# 이동시간 캐시(SQLite). .gitignore의 *.sqlite3 규칙으로 커밋되지 않는다.
TRAVEL_CACHE_PATH: Path = ROOT_DIR / "backend" / "data" / "travel_cache.sqlite3"

# 장소 검색 결과(카카오), 평점(구글), 구글 일일 호출 수 캐시(SQLite).
PLACES_CACHE_PATH: Path = ROOT_DIR / "backend" / "data" / "places_cache.sqlite3"
