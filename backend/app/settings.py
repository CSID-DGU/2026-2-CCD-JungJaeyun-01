"""환경변수 로딩. 루트의 .env를 읽는다."""

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")


def _as_bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


# mock은 pytest에서만 쓴다. 실제 실행에서 켜져 있으면 화면에 가짜 데이터가 섞이므로 시작을 막는다.
MOCK_PLACES: bool = _as_bool(os.getenv("MOCK_PLACES"), default=False)    # 장소 검색(카카오)
MOCK_RATINGS: bool = _as_bool(os.getenv("MOCK_RATINGS"), default=False)  # 평점(구글 Places)
MOCK_ROUTES: bool = _as_bool(os.getenv("MOCK_ROUTES"), default=False)    # 경로(구글 Routes): true면 저장본(fixtures)만 읽는다
_UNDER_PYTEST = "PYTEST_VERSION" in os.environ or "pytest" in sys.modules
if (MOCK_PLACES or MOCK_RATINGS or MOCK_ROUTES) and not _UNDER_PYTEST:
    raise RuntimeError("MOCK_PLACES / MOCK_RATINGS / MOCK_ROUTES는 pytest에서만 쓸 수 있어요. .env에서 false로 바꾸거나 지워 주세요.")
if os.getenv("USE_MOCK"):
    logging.getLogger(__name__).warning("USE_MOCK은 더 이상 쓰지 않아요. MOCK_PLACES / MOCK_RATINGS / MOCK_ROUTES로 나뉘었습니다.")
KAKAO_REST_API_KEY: str = os.getenv("KAKAO_REST_API_KEY", "")
# 카카오맵 JavaScript 키: 프론트가 직접 쓰는 키이며, 백엔드는 지도 로드 실패 원인 진단에만 쓴다.
KAKAO_JS_KEY: str = os.getenv("VITE_KAKAO_JS_KEY", "")
ODSAY_API_KEY: str = os.getenv("ODSAY_API_KEY", "")
GOOGLE_PLACES_API_KEY: str = os.getenv("GOOGLE_PLACES_API_KEY", "")

# 경로 API 선택과 호출 모드. 키는 백엔드에서만 쓴다.
ROUTE_PROVIDER: str = os.getenv("ROUTE_PROVIDER", "google").strip().lower()   # google | odsay (odsay는 기본 비활성화)
ROUTE_MODE: str = "replay" if MOCK_ROUTES else os.getenv("ROUTE_MODE", "live").strip().lower()             # live(기본: 캐시 우선, 없으면 호출 후 저장) | record | replay(테스트용)
GOOGLE_ROUTES_KEY: str = os.getenv("GOOGLE_ROUTES_KEY", "")

# 경로 응답 캐시와 하루 호출 수 집계(SQLite). .gitignore의 *.sqlite3 규칙으로 커밋되지 않는다.
ROUTES_DB_PATH: Path = ROOT_DIR / "backend" / "data" / "routes_cache.sqlite3"

# 장소 검색 결과(카카오), 평점(구글), 구글 일일 호출 수 캐시(SQLite).
PLACES_CACHE_PATH: Path = ROOT_DIR / "backend" / "data" / "places_cache.sqlite3"

# 카카오 로그인(REST API 인가 코드 방식). 토큰은 백엔드 세션에만 두고 프론트에는 내려주지 않는다.
KAKAO_CLIENT_SECRET: str = os.getenv("KAKAO_CLIENT_SECRET", "")     # 선택: 카카오 로그인 > 보안에서 켠 경우만
# 프론트 주소와 로그인 Redirect URI는 비워 두면 "지금 접속한 주소(요청 Host)"를 쓴다 (localhost, cloudflared 터널 모두 자동).
# 고정하고 싶을 때만 채운다. Redirect URI는 카카오 개발자 콘솔에 등록한 값과 글자 하나까지 같아야 한다.
FRONTEND_URL: str = os.getenv("FRONTEND_URL", "").rstrip("/")
KAKAO_REDIRECT_URI: str = os.getenv("KAKAO_REDIRECT_URI", "")

# 실시간 도착 정보 (백엔드 전용 키). 없으면 "실시간 정보 없음"으로 조용히 처리한다.
SEOUL_SUBWAY_API_KEY: str = os.getenv("SEOUL_SUBWAY_API_KEY", "")   # 서울 열린데이터광장 지하철 실시간 도착정보
SEOUL_BUS_API_KEY: str = os.getenv("SEOUL_BUS_API_KEY", "")         # 공공데이터포털 서울 버스 정류소·도착정보
REALTIME_TTL_SECONDS: float = float(os.getenv("REALTIME_TTL_SECONDS", "30"))
