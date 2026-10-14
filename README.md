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
| `GOOGLE_ROUTES_KEY` | 상위 3곳의 실제 대중교통 시간·상세 경로 (백엔드 전용) | [Google Cloud Console](https://console.cloud.google.com) → **Routes API** 사용 설정 → 사용자 인증 정보 → API 키 (결제 계정 필요) |
| `ROUTE_PROVIDER` | 경로 API 종류: `google`(기본) \| `odsay`(기본 비활성화) | - |
| `ROUTE_MODE` | Google 호출 방식: `replay`(기본) \| `record` \| `live` — 아래 "경로 API 호출 구조" 참고 | - |
| `ODSAY_API_KEY` | `ROUTE_PROVIDER=odsay`일 때만 사용 | [ODsay LAB](https://lab.odsay.com) → 애플리케이션 등록 → API 키 |
| `GOOGLE_PLACES_API_KEY` | (선택) 평점·리뷰 수 (백엔드 전용) | [Google Cloud Console](https://console.cloud.google.com) → **Places API (New)** 사용 설정 → 사용자 인증 정보 → API 키 |
| `USE_MOCK` | `true`: 장소 검색·평점을 가짜 데이터로 대체 / `false`: 실제 API 호출 (경로 API는 `ROUTE_MODE`가 따로 정한다) | - |

카카오 설정에서 꼭 확인할 것:

1. 앱의 **카카오맵** 사용 설정을 ON으로 바꿉니다 (꺼져 있으면 장소 검색이 403).
2. 앱의 **플랫폼 → Web 사이트 도메인**에 `http://localhost:5173`을 등록합니다 (없으면 지도가 뜨지 않음). `http://127.0.0.1:5173`으로 접속하려면 이것도 등록하고 프론트를 `npm run dev -- --host 127.0.0.1`로 실행하세요.

지도가 뜨지 않으면 화면에 원인(도메인 미등록 / 키 오류 / REST 키 사용 / 카카오맵 미사용 설정)이 표시됩니다. `.env`를 바꾼 뒤에는 프론트 개발 서버를 다시 시작해야 합니다.

참고:

- 구글 Places는 결제 계정 연결이 필요하고 호출마다 과금됩니다. 키가 없으면 평점 없이 동작하며(평점 항목을 빼고 가중치 재정규화), 하루 호출 상한은 `backend/config/place.yaml`의 `google.daily_limit`(기본 100)입니다.
- `USE_MOCK=true`여도 출발지 자동완성(`GET /api/search/places`)은 항상 실제 카카오 API를 사용하므로 `KAKAO_REST_API_KEY`가 필요합니다.
- Google Routes 키는 프론트에 노출하지 않습니다. 키 제한을 쓴다면 API 제한을 Routes API로 두고, IP 제한을 쓸 때는 서버 IP를 등록하세요.
- Google Maps Platform 약관은 응답 저장·캐시에 제한을 둘 수 있어요. 7일 캐시와 `backend/fixtures/google/` 저장본은 개발·발표용으로 쓰고, 공개 배포 전에 약관을 확인하세요.

## 경로 API 호출 구조 (2단계)

경로 API 비용을 줄이려고 후보를 API 없이 먼저 거르고, 상위 3곳만 Google로 확인합니다.

1. **1단계 (API 호출 0회)**: 후보 역 20곳(`config/region.yaml`의 K)에 대해 `출발지 → 가장 가까운 역 도보 + 지하철 그래프 최단 시간(다익스트라)`으로 참여자별 이동시간을 추정하고 RegionScore로 상위 3곳을 고릅니다. 후보가 몇 개든 호출은 0입니다.
   지하철 그래프는 서울교통공사 공개 데이터 + 노선도 기준 입력으로 만든 것입니다 — 출처와 한계는 [backend/data/subway/README.md](backend/data/subway/README.md).
2. **2단계 (검색당 Google 최대 1회)**: `computeRouteMatrix(TRANSIT)` 한 번으로 참여자 × 상위 3곳의 실제 소요시간을 받아 평균·최대·편차와 순위를 다시 계산합니다 (출발 시각은 다음 평일 오후 6시). 실패한 칸은 1단계 추정값을 쓰고 화면에 **"추정"** 으로 표시합니다.
3. **상세 경로**: 사용자가 참여자 이름을 누를 때만 `computeRoutes`를 호출하고 결과를 캐시합니다. 실패하면 지하철 그래프 추정 경로를 "추정 경로"로 보여줍니다.

1단계 추정과 2단계 실제값의 차이는 로그와 응답의 `meta.estimate_accuracy`에 남습니다. 2026-10-15 기준 6건에서 평균절대오차 1.2분이었어요.

호출 보호 장치: (출발지 좌표 소수 4자리, 도착역, 요일·시간대) 키의 디스크 캐시 7일 · 같은 요청이 동시에 오면 한 번만 호출 · 네트워크·5xx·429만 1회 재시도, 키 제한·API 미사용·할당량 오류는 재시도 없이 2분간 호출 중단 · FieldMask로 필요한 필드만 요청 · 오늘 호출 수는 백엔드 로그와 개발 서버 화면 오른쪽 아래에 표시됩니다.

| `ROUTE_MODE` | 동작 | 쓰임 |
|---|---|---|
| `replay` (기본) | `backend/fixtures/google/`의 저장본만 사용. 호출 0. 저장본이 없는 요청은 추정값으로 표시 | 개발·테스트 |
| `record` | 실제로 호출하고 응답을 `backend/fixtures/google/`에 저장 (캐시는 쓰지 않음) | 저장본 만들기 |
| `live` | 실제 호출 + 7일 디스크 캐시 | 발표용 |

저장본은 요청(출발지 4자리 좌표·도착역·시간대)이 같을 때만 재사용됩니다. 지금 들어 있는 저장본은 재윤(홍대입구역)·서영(잠실역) 2명의 검색 1회와 상위 3곳 경로 6개입니다.
새로 녹화하려면 `ROUTE_MODE=record`로 백엔드를 띄우고 원하는 참여자로 검색한 뒤 이름을 눌러 보세요 (호출 수 = 검색 1 + 이름 클릭마다 1).

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
python scripts/test_apis.py                 # 카카오 · ODsay · 구글 Places 각 1회
python scripts/probe_google_routes.py       # Google Routes 품질 확인 (경로 3개, --save로 테스트 픽스처 저장)
python scripts/build_subway_network.py      # 지하철 그래프 다시 만들기
python scripts/demo_recommend.py            # 홍대입구·잠실·노원 추천 데모 (USE_MOCK 값을 따름)
```

## 주요 설정 파일 (`backend/config/`)

| 파일 | 내용 |
|---|---|
| `region.yaml` | RegionScore 가중치(평균 0.4 / 최대 0.3 / 편차 0.3), 후보 역 수 K=20 |
| `place.yaml` | PlaceScore 가중치, 모임 목적별 카테고리, 구글 하루 호출 상한 |
| `subway.yaml` | 1단계 추정 파라미터 (도보 속도, 승차 대기, 가까운 역 후보 수) |
| `routes.yaml` | Google 호출 설정 (출발 시각, 캐시 7일, 재시도 1회, 호출 중단 시간) |
| `travel.yaml` | ODsay(`ROUTE_PROVIDER=odsay`) 호출 간격·재시도 |
| `age_preferences.json` | 연령대별 장소 선호도. **임의로 정한 값**(`"source": "assumed"`)이며 실제 데이터가 아닙니다 |

후보 역 62곳의 좌표(`backend/data/stations.json`)는 `python scripts/fetch_stations.py`로 카카오 검색에서 다시 만들 수 있습니다.

## API

- `POST /api/recommend` — 참여자 2~5명(이름, 출발지 좌표, 연령대)과 목적(`meal` | `cafe` | `drink`)을 받아 상위 3개 지역, 지역별 이동시간 지표(`meta.phase2`에 2단계 결과), 지역별 장소 5곳을 반환
- `POST /api/recommend/regions` — 지역 추천만
- `POST /api/route` — 참여자 한 명의 상세 경로 (이름을 눌렀을 때만 호출). 응답은 API 종류와 무관한 공통 형식: `route = {totalMinutes, transfers, segments[{mode: WALK|SUBWAY|BUS, lineName, lineColor, from, to, minutes, path[[lat,lng],...]}], source: "google"|"estimate"}`
- `GET /api/dev/usage` — 오늘 경로 API 호출 수 (개발용 표시)
- `GET /api/search/places?query=` — 출발지 자동완성 (카카오 키워드 검색 프록시)
- `GET /api/diagnostics/kakao-map?origin=` — 지도 SDK 로드 실패 원인 진단 (화면의 안내 문구용)
- `GET /health`
