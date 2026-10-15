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

# 경로 API 선택과 호출 모드. 키는 백엔드에서만 쓴다.
ROUTE_PROVIDER: str = os.getenv("ROUTE_PROVIDER", "google").strip().lower()   # google | odsay (odsay는 기본 비활성화)
ROUTE_MODE: str = os.getenv("ROUTE_MODE", "live").strip().lower()             # live(기본: 캐시 우선, 없으면 호출 후 저장) | record | replay(테스트용)
GOOGLE_ROUTES_KEY: str = os.getenv("GOOGLE_ROUTES_KEY", "")

# 경로 응답 캐시와 하루 호출 수 집계(SQLite). .gitignore의 *.sqlite3 규칙으로 커밋되지 않는다.
ROUTES_DB_PATH: Path = ROOT_DIR / "backend" / "data" / "routes_cache.sqlite3"

# 장소 검색 결과(카카오), 평점(구글), 구글 일일 호출 수 캐시(SQLite).
PLACES_CACHE_PATH: Path = ROOT_DIR / "backend" / "data" / "places_cache.sqlite3"

# 카카오 로그인(REST API 인가 코드 방식). 토큰은 백엔드 세션에만 두고 프론트에는 내려주지 않는다.
KAKAO_CLIENT_SECRET: str = os.getenv("KAKAO_CLIENT_SECRET", "")     # 선택: 카카오 로그인 > 보안에서 켠 경우만
FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")
# 카카오 개발자 콘솔의 Redirect URI와 글자 하나까지 같아야 한다. 프론트 개발 서버의 /auth 프록시를 거친다.
KAKAO_REDIRECT_URI: str = os.getenv("KAKAO_REDIRECT_URI", f"{FRONTEND_URL}/auth/kakao/callback")
