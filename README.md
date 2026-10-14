# Meetup Recommender

이동 편의성과 연령대별 트렌드를 고려한 맞춤형 모임 장소 추천 서비스 (캡스톤디자인).

여러 명의 출발지를 입력하면 **실제 대중교통 이동시간**의 평균·최대·편차를 점수화(RegionScore)해 모두에게 공평한 지역(지하철역) 상위 3곳을 고르고, 각 지역에서 목적에 맞는 장소 상위 5곳을 PlaceScore로 추천합니다.

- 요구사항: [docs/spec.md](docs/spec.md)
- 개발 규칙: [CLAUDE.md](CLAUDE.md)

## 구성

| 폴더 | 내용 |
|---|---|
| `backend/` | Python FastAPI. 점수 계산(`app/scoring`), 외부 API 연동(`app/services`), 가중치 설정(`config/`) |
| `frontend/` | React + Vite + TypeScript. 입력 화면, 결과 화면, 카카오맵 |
| `docs/` | 개요서 등 문서 |

## 설치

필요한 것: **Python 3.11 이상**, **Node.js 20 이상**

```bash
# 백엔드
cd backend
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

# 프론트엔드 (새 터미널)
cd frontend
npm install
```

## 환경변수 (.env)

루트에서 `.env.example`을 `.env`로 복사하고 값을 채웁니다. `.env`는 git에 올라가지 않습니다.

```bash
cp .env.example .env
```

| 변수 | 용도 | 발급처 |
|---|---|---|
| `KAKAO_REST_API_KEY` | 장소 검색, 출발지 자동완성 (백엔드 전용) | [Kakao Developers](https://developers.kakao.com) → 내 애플리케이션 → 앱 키 → **REST API 키** |
| `VITE_KAKAO_JS_KEY` | 지도 표시 (프론트에서 쓰는 유일한 키) | 같은 화면의 **JavaScript 키** |
| `ODSAY_API_KEY` | 대중교통 이동시간 (백엔드 전용) | [ODsay LAB](https://lab.odsay.com) → 회원가입 후 애플리케이션 등록 → API 키 |
| `GOOGLE_PLACES_API_KEY` | (선택) 평점·리뷰 수 (백엔드 전용) | [Google Cloud Console](https://console.cloud.google.com) → **Places API (New)** 사용 설정 → 사용자 인증 정보 → API 키 |
| `USE_MOCK` | `true`: ODsay·장소 검색·평점을 가짜 데이터로 대체 / `false`: 실제 API 호출 | - |

카카오 설정에서 꼭 확인할 것:

1. 앱의 **카카오맵** 사용 설정을 ON으로 바꿉니다 (꺼져 있으면 장소 검색이 403).
2. 앱의 **플랫폼 → Web 사이트 도메인**에 `http://localhost:5173`을 등록합니다 (없으면 지도가 뜨지 않음). `http://127.0.0.1:5173`으로 접속하려면 이것도 등록하고 프론트를 `npm run dev -- --host 127.0.0.1`로 실행하세요.

지도가 뜨지 않으면 화면에 원인(도메인 미등록 / 키 오류 / REST 키 사용 / 카카오맵 미사용 설정)이 표시됩니다. `.env`를 바꾼 뒤에는 프론트 개발 서버를 다시 시작해야 합니다.

참고:

- 구글 Places는 결제 계정 연결이 필요하고 호출마다 과금됩니다. 키가 없으면 평점 없이 동작하며(평점 항목을 빼고 가중치 재정규화), 하루 호출 상한은 `backend/config/place.yaml`의 `google.daily_limit`(기본 100)입니다.
- `USE_MOCK=true`여도 출발지 자동완성(`GET /api/search/places`)은 항상 실제 카카오 API를 사용하므로 `KAKAO_REST_API_KEY`가 필요합니다.
- ODsay 키는 발급 시 사용할 플랫폼(서버 IP 등) 등록이 필요할 수 있습니다.

## 실행

백엔드 (http://localhost:8000):

```bash
cd backend
.venv\Scripts\activate
uvicorn app.main:app --reload --port 8000
```

프론트엔드 (http://localhost:5173):

```bash
cd frontend
npm run dev
```

브라우저에서 http://localhost:5173 을 엽니다. `/api/*` 요청은 개발 서버가 백엔드로 전달합니다. API 문서는 http://localhost:8000/docs 입니다.

## 테스트

```bash
cd backend
pytest
```

실제 API를 한 번씩 호출해 보는 스크립트 (키가 맞는지 확인용, 과금될 수 있음):

```bash
cd backend
python scripts/test_apis.py                 # 카카오 · ODsay · 구글 각 1회
python scripts/demo_recommend.py            # 홍대입구·잠실·노원 추천 데모 (USE_MOCK 값을 따름)
```

## 주요 설정 파일 (`backend/config/`)

| 파일 | 내용 |
|---|---|
| `region.yaml` | RegionScore 가중치(평균 0.4 / 최대 0.3 / 편차 0.3), 후보 역 수 K=12 |
| `place.yaml` | PlaceScore 가중치, 모임 목적별 카테고리, 구글 하루 호출 상한 |
| `travel.yaml` | mock 이동시간 추정값, ODsay 호출 간격·재시도 |
| `age_preferences.json` | 연령대별 장소 선호도. **임의로 정한 값**(`"source": "assumed"`)이며 실제 데이터가 아닙니다 |

후보 역 62곳의 좌표(`backend/data/stations.json`)는 `python scripts/fetch_stations.py`로 카카오 검색에서 다시 만들 수 있습니다.

## API

- `POST /api/recommend` — 참여자 2~5명(이름, 출발지 좌표, 연령대)과 목적(`meal` | `cafe` | `drink`)을 받아 상위 3개 지역, 지역별 이동시간 지표와 참여자별 대중교통 경로(`route`), 지역별 장소 5곳을 반환
- `POST /api/recommend/regions` — 지역 추천만
- `GET /api/search/places?query=` — 출발지 자동완성 (카카오 키워드 검색 프록시)
- `GET /api/diagnostics/kakao-map?origin=` — 지도 SDK 로드 실패 원인 진단 (화면의 안내 문구용)
- `GET /health`
