# CLAUDE.md

맞춤형 모임 장소 추천 웹서비스 (캡스톤디자인). 전체 요구사항은 [docs/spec.md](docs/spec.md)를 따른다.

## 폴더 구조

```
meetup-recommender/
├── backend/            # Python FastAPI
│   ├── app/
│   │   ├── main.py     # FastAPI 앱, 라우터 등록
│   │   ├── settings.py # 환경변수 로딩 (루트 .env)
│   │   ├── services/   # 외부 API 인터페이스 + mock/실제 구현
│   │   └── scoring/    # RegionScore, PlaceScore 순수 함수
│   ├── config/         # region.yaml, travel.yaml, place.yaml, age_preferences.json
│   ├── data/           # stations.json (후보 역 좌표), *.sqlite3 캐시 (gitignore)
│   ├── scripts/        # test_apis.py, fetch_stations.py, demo_recommend.py
│   ├── tests/          # pytest
│   └── requirements.txt
├── frontend/           # React + Vite + TypeScript
├── docs/               # 개요서, 설계 문서, 보고서 자료
├── .env.example
└── CLAUDE.md
```

## 규칙

### API 키
- 외부 API 키는 **백엔드에서만** 사용한다. 프론트에서 외부 API(ODsay, 카카오 로컬, Google Places 등)를 직접 호출하지 않고 반드시 백엔드를 거친다.
- 예외: **카카오맵 JavaScript 키(`VITE_KAKAO_JS_KEY`)만** 프론트에서 사용한다.
  - `frontend/vite.config.ts`의 `envPrefix: ['VITE_KAKAO_JS_']` 때문에 이 키만 프론트 번들에 노출된다. prefix를 넓히거나 다른 키를 프론트에 추가하지 않는다.
- API 키는 루트의 `.env`로 관리한다. `.env`는 `.gitignore`에 포함되어 있으며 절대 커밋하지 않는다.
- 새 환경변수를 추가하면 `.env.example`에도 빈 값과 설명을 함께 추가한다.

### 외부 API 호출 분리
- 외부 API 호출은 `backend/app/services/` 아래에 **인터페이스(추상 클래스 또는 Protocol)** 로 정의한다.
- 각 인터페이스마다 **mock 구현**과 **실제 구현**을 둔다.
  - 예: `TransitService` → `MockTransitService`, `OdsayTransitService`
  - 예: `PlaceService` → `MockPlaceService`, `KakaoPlaceService`
- 환경변수 `USE_MOCK=true/false`로 구현을 전환한다 (`app.settings.USE_MOCK`). 라우터·점수 계산 코드는 구현체가 아니라 인터페이스에만 의존한다.
- mock 구현은 API 키 없이도 전체 흐름이 동작하도록 현실적인 고정 데이터를 반환한다.
- 예외: 출발지 자동완성 `GET /api/search/places`(`services/place_lookup.py`)는 mock 없이 `USE_MOCK`과 관계없이 항상 실제 카카오 키워드 검색을 쓴다.
- ODsay 조회가 재시도 후에도 실패한 출발지-역 조합은 후보에서 빼지 않고 mock의 거리 기반 추정치로 대체하며, 응답에 `is_estimated`로 표시한다 (추정치는 캐시하지 않는다).
- 참여자 이동 경로(`subPath`/`passStopList`의 정류장 좌표)는 추천 요청 중 받은 ODsay 응답에서 파싱해 이동시간과 함께 SQLite 캐시(`route_json`)에 저장한다. 지도에서 경로를 보여줄 때는 저장된 값만 쓰고 추가 API 호출을 하지 않는다. 경로 저장 도입 전 캐시 행은 상위 지역에 한해 한 번만 채운다.
- 실제 경로가 없는 참여자(추정치 대체, mock, 조회 실패)는 가짜 경로를 만들지 않는다. 응답의 `route`는 null, `route_note`에 이유를 담고, 화면은 출발지→도착역 점선 직선과 "추정 경로"로 표시한다.
- ODsay가 재시도 후에도 429면 한도 초과로 보고 `travel.yaml`의 `quota_cooldown_seconds`(기본 300초) 동안 HTTP 호출 없이 바로 실패 처리한다.
- 지도 연출은 App이 동작(검색/지역 탭/장소 카드/경로/전체 보기)마다 `motion` id를 올려 MapView가 이동 → 연출 순서로 한 번 실행한다. `prefers-reduced-motion`이면 즉시 이동·표시한다.
- 카카오맵 SDK는 카카오 개발자 콘솔의 Web 플랫폼에 `http://localhost:5173`이 등록되어 있어야 로드된다.

### 점수 계산
- RegionScore, PlaceScore의 **가중치는 `backend/config/` 아래 설정 파일로 분리**한다. 코드에 가중치를 하드코딩하지 않는다.
  - RegionScore: 평균 이동시간(효율성), 최대 이동시간(과도한 부담 방지), 이동시간 편차(공정성) — 각각 정규화 후 가중치 적용
  - PlaceScore: 접근성, 평점, 리뷰 수, 모임 목적 적합성, 연령대 선호도
- 점수 계산 함수(`backend/app/scoring/`)는 **순수 함수**로 작성한다: 입력(이동시간, 장소 정보, 가중치)만 받아 결과를 반환하고, 외부 API 호출·파일 읽기·전역 상태 변경을 하지 않는다. 가중치도 인자로 전달받는다.
- 점수 계산 함수를 추가·수정할 때는 `backend/tests/`에 **pytest 테스트를 함께 작성**한다 (정규화 경계값, 동점, 참여자 2명/5명 등).
- 연령대 가중치는 실제 데이터 기반인지 사전 정의 가중치인지 구분할 수 있게 구현한다. 현재 `config/age_preferences.json`은 `"source": "assumed"`(임의값)이며 API 응답에도 `age_preference.is_assumed`로 표시된다.
- 구글 평점을 못 받으면(키 없음/실패/일일 상한 초과) 평점·인기도 항목을 빼고 나머지 가중치를 재정규화한다. 구글은 지역별 상위 5곳만 조회하고, 캐시와 하루 호출 상한(`place.yaml`의 `google.daily_limit`)을 지킨다.

## 실행 방법

처음 한 번: 루트에서 `.env.example`을 `.env`로 복사하고 키를 채운다 (`USE_MOCK=true`면 키 없이 실행 가능).

### 백엔드 (http://localhost:8000)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

- 헬스체크: http://localhost:8000/health
- API 문서: http://localhost:8000/docs
- 테스트: `cd backend && pytest`
- 추천 호출: `POST /api/recommend` (상위 3개 지역 + 지역별 장소 5곳), 지역만: `POST /api/recommend/regions`
- 후보 역 좌표 재생성(카카오 키워드 검색): `python scripts/fetch_stations.py`
- 추천 데모: `python scripts/demo_recommend.py` (`USE_MOCK=false`면 ODsay·카카오·구글 실제 호출, API별 호출 수 출력. ODsay 최악 호출이 50건 초과면 중단)

### 프론트엔드 (http://localhost:5173)

```bash
cd frontend
npm install
npm run dev
```

- 개발 서버에서 `/api/*` 요청은 경로 그대로 백엔드(`localhost:8000`)로 프록시된다. 예: `fetch('/api/health')`
- 빌드: `npm run build`
