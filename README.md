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
| `KAKAO_CLIENT_SECRET` | (선택) 카카오 로그인 Client Secret. 콘솔에서 **사용함**으로 켰다면 필수 (백엔드 전용) | 앱 → 제품 설정 → 카카오 로그인 → **보안** |
| `FRONTEND_URL` | 프론트 주소 (로그인 후 돌아갈 곳, 공유 링크 허용 주소). 기본 `http://localhost:5173` | - |
| `KAKAO_REDIRECT_URI` | 카카오 로그인 Redirect URI. 기본 `http://localhost:5173/auth/kakao/callback` | 아래 "카카오 로그인·공유 설정" |
| `SEOUL_SUBWAY_API_KEY` | (선택) 지하철 실시간 도착정보 (백엔드 전용) | [서울 열린데이터광장](https://data.seoul.go.kr) → "지하철 실시간 도착정보" → 인증키 신청 |
| `SEOUL_BUS_API_KEY` | (선택) 버스 실시간 도착정보 (백엔드 전용) | [공공데이터포털](https://www.data.go.kr) → "서울특별시_정류소정보조회 서비스"·"버스도착정보조회 서비스" **활용신청** 후 일반 인증키. 서비스마다 신청이 따로이고 승인까지 시간이 걸릴 수 있어요 |
| `ROUTE_PROVIDER` | 경로 API 종류: `google`(기본) \| `odsay`(기본 비활성화) | - |
| `ROUTE_MODE` | Google 호출 방식: `live`(기본) \| `record` \| `replay`(테스트용) — 아래 "경로 API 호출 구조" 참고 | - |
| `ODSAY_API_KEY` | `ROUTE_PROVIDER=odsay`일 때만 사용 | [ODsay LAB](https://lab.odsay.com) → 애플리케이션 등록 → API 키 |
| `GOOGLE_PLACES_API_KEY` | (선택) 평점·리뷰 수 (백엔드 전용) | [Google Cloud Console](https://console.cloud.google.com) → **Places API (New)** 사용 설정 → 사용자 인증 정보 → API 키 |
| `MOCK_PLACES` | 장소 검색(카카오)을 가짜 데이터로 대체. **pytest 전용**, 기본 `false` (카카오는 무료라 항상 실제 호출) | - |
| `MOCK_RATINGS` | 평점(구글 Places)을 가짜로 대체. **pytest 전용**, 기본 `false` (실제 호출, 하루 상한 `place.yaml`). 평점을 못 받은 장소는 "평점 정보 없음"으로 표시 | - |
| `MOCK_ROUTES` | 경로(구글 Routes)를 저장본(`fixtures/`)만 읽도록 고정. **pytest 전용**, 기본 `false` (캐시 우선 + 하루 상한 `routes.yaml`) | - |

카카오 설정에서 꼭 확인할 것:

1. 앱의 **카카오맵** 사용 설정을 ON으로 바꿉니다 (꺼져 있으면 장소 검색이 403).
2. 앱의 **플랫폼 → Web 사이트 도메인**에 `http://localhost:5173`을 등록합니다 (없으면 지도가 뜨지 않음). `http://127.0.0.1:5173`으로 접속하려면 이것도 등록하고 프론트를 `npm run dev -- --host 127.0.0.1`로 실행하세요.

지도가 뜨지 않으면 화면에 원인(도메인 미등록 / 키 오류 / REST 키 사용 / 카카오맵 미사용 설정)이 표시됩니다. `.env`를 바꾼 뒤에는 프론트 개발 서버를 다시 시작해야 합니다.

참고:

- 구글 Places는 결제 계정 연결이 필요하고 호출마다 과금됩니다. 키가 없으면 평점 없이 동작하며(평점 항목을 빼고 가중치 재정규화), 하루 호출 상한은 `backend/config/place.yaml`의 `google.daily_limit`(기본 100)입니다.
- 장소·평점·경로 모두 실제 API를 씁니다. `MOCK_*`가 켜진 채로 서버를 실행하면 가짜 데이터가 화면에 섞이므로 시작 자체를 막습니다 (옛 `USE_MOCK`은 더 이상 읽지 않고 경고만 냅니다).
- Google Routes 키는 프론트에 노출하지 않습니다. 키 제한을 쓴다면 API 제한을 Routes API로 두고, IP 제한을 쓸 때는 서버 IP를 등록하세요.
- Google Maps Platform 약관은 응답 저장·캐시에 제한을 둘 수 있어요. 7일 캐시와 `backend/fixtures/google/` 저장본은 개발·발표용으로 쓰고, 공개 배포 전에 약관을 확인하세요.

## 카카오 로그인·공유 설정 (Kakao Developers)

로그인 없이도 추천은 전부 쓸 수 있고, 로그인하면 결과를 카카오톡 "나에게 보내기"로 받을 수 있습니다. 카카오톡 공유 창(`카카오톡으로 공유`)은 로그인 여부와 관계없이 동작합니다.

1. [Kakao Developers](https://developers.kakao.com) → 내 애플리케이션 → 앱 선택 → **앱 키**에서 REST API 키(`KAKAO_REST_API_KEY`), JavaScript 키(`VITE_KAKAO_JS_KEY`)를 `.env`에 넣습니다.
2. **플랫폼 → Web**에 사이트 도메인 `http://localhost:5173`을 등록합니다 (지도·카카오톡 공유 SDK용).
3. **제품 설정 → 카카오 로그인**: 활성화 설정을 **ON**으로 하고, **Redirect URI**에 `http://localhost:5173/auth/kakao/callback`을 등록합니다 (`KAKAO_REDIRECT_URI`를 `.env`에 고정했다면 글자까지 같아야 하고, 비워 두면 접속한 주소 기준으로 자동 계산됩니다).
4. **카카오 로그인 → 보안**에서 Client Secret을 **사용함**으로 켰다면 그 값을 `.env`의 `KAKAO_CLIENT_SECRET`에 넣습니다 (끄면 비워 둡니다).
5. **동의항목**: `닉네임`(profile_nickname)과 `카카오톡 메시지 전송`(talk_message)을 설정합니다. talk_message는 "선택 동의"로 설정할 수 있습니다.
6. 로그인 후에도 "나에게 보내기"가 권한 오류로 실패하면, 로그아웃 후 다시 로그인해 동의 화면에서 메시지 전송에 동의해 주세요.

동작 방식: `GET /auth/kakao/login` → 카카오 인가 페이지 → `GET /auth/kakao/callback`에서 백엔드가 토큰을 교환합니다. 토큰은 백엔드 메모리 세션에만 있고, 브라우저에는 httpOnly 쿠키(`mr_session`)만 저장됩니다 (서버를 다시 켜면 로그아웃됩니다). 개발 서버는 `/auth/*`도 백엔드로 프록시해서 쿠키가 `localhost:5173`에 저장됩니다.

결과 다시 보기 링크(`/?s=...`)에는 참여자 이름·출발지 좌표·연령대·목적·약속 시간이 담기고, 접속하면 같은 입력으로 결과를 다시 계산합니다. 약속 시간이 이미 지났다면 기본값(다음 토요일 18시)으로 계산하고 안내를 보여줍니다.

## 실시간 도착 정보

- `GET /api/realtime?type=subway&station=&line=&headsign=&next=` — 역 이름 + 호선 + 방면(종착역 또는 다음 역)으로 거른 다음 열차 최대 2개. `type=bus&lat=&lng=&stop=&line=` — 승차 정류장 좌표 반경 120m 정류소 중 이름이 같은 곳을 찾고(정류소 조회) 그 정류소의 도착정보에서 노선 번호로 거릅니다. 같은 요청은 30초 캐시합니다.
- 키가 없거나, 서울 밖이거나, API가 실패하면 오류가 아니라 `available: false`("실시간 정보 없음")로 조용히 처리합니다.
- 표시 조건: 경로의 출발 시각 30분 전부터 자동으로 켜지고, 그 전에는 결과 화면의 **지금 출발** 버튼을 눌렀을 때만 켜집니다. 켜져 있는 동안 30초마다 갱신하고, 화면을 떠나거나(조건 다시 입력) 탭이 숨겨지면 멈춥니다.
- 타임라인의 **첫 번째 승차역/정류장** 옆에 "첫 번째 3분 후 도착 · 2정거장 전 / 두 번째 …"로 표시합니다. 환승 뒤의 열차는 지금 도착 정보가 의미가 없어서 표시하지 않습니다.
- 지하철 정거장 수는 API 메시지에 없으면 `data/subway/network.json` 노선도로 현재 위치에서 계산합니다.

## 친구에게 임시 공유 (cloudflared 터널)

외부 접속은 프론트(5173) 하나로 끝납니다. `/api`, `/auth`는 Vite 프록시가 백엔드(8000)로 넘기고, 백엔드는 **접속한 주소(요청 Host / X-Forwarded-*)** 로 로그인 Redirect URI와 공유 링크를 만듭니다 (`FRONTEND_URL`, `KAKAO_REDIRECT_URI`는 고정하고 싶을 때만 `.env`에 넣으세요).

```bash
winget install --id Cloudflare.cloudflared -e
cloudflared tunnel --url http://localhost:5173
```

출력되는 `https://xxxx.trycloudflare.com` 주소를 친구에게 보내면 됩니다. 주소는 터널을 열 때마다 바뀌므로, 매번 카카오 개발자 콘솔에 다음을 등록해야 카카오 로그인·카톡 공유·지도가 동작합니다.

- **플랫폼 → Web** 사이트 도메인: `https://xxxx.trycloudflare.com`
- **카카오 로그인 → Redirect URI**: `https://xxxx.trycloudflare.com/auth/kakao/callback`

등록하지 않아도 추천 기능 자체는 동작하지만 지도·로그인·카톡 공유는 막힙니다. (Vite `server.allowedHosts`에 `.trycloudflare.com`이 허용돼 있습니다.)

## 경로 API 호출 구조 (2단계)

경로 API 비용을 줄이려고 후보를 API 없이 먼저 거르고, 상위 3곳만 Google로 확인합니다.

1. **1단계 (API 호출 0회)**: 후보 역 20곳(`config/region.yaml`의 K)에 대해 `출발지 → 가장 가까운 역 도보 + 지하철 그래프 최단 시간(다익스트라)`으로 참여자별 이동시간을 추정하고 RegionScore로 상위 **8곳**(`SHORTLIST_SIZE`, 기본 8)을 후보로 뽑습니다. 지하철 그래프에는 버스가 없어서 최종 개수(3)보다 넓게 뽑아, 버스가 유리한 지역이 1단계에서 탈락하지 않게 합니다. 후보가 몇 개든 호출은 0입니다.
   지하철 그래프는 서울교통공사 공개 데이터 + 노선도 기준 입력으로 만든 것입니다 — 출처와 한계는 [backend/data/subway/README.md](backend/data/subway/README.md).
2. **2단계 (검색당 Google 최대 1회)**: `computeRouteMatrix(TRANSIT)` 한 번으로 참여자 × 후보 8곳의 실제 소요시간을 받습니다 (허용 수단은 버스·지하철·기차·경전철 모두, 출발 시각은 다음 평일 오후 6시). 이 값(버스 포함)으로 평균·최대·편차와 RegionScore를 다시 계산해 **최종 3곳**을 정합니다. 1단계 순위와 달라진 지역은 로그(`순위 변경`, `탈락`)와 화면("추정 7위 → 실제 경로 반영 2위")에 남습니다. 실패한 칸은 1단계 추정값을 쓰고 화면에 **"추정"** 으로 표시합니다.
3. **상세 경로**: 사용자가 참여자 이름을 누를 때만 `computeRoutes`를 호출하고 결과를 캐시합니다. 실패하면 지하철 그래프 추정 경로를 "추정 경로"로 보여줍니다.

상세 경로의 버스 구간은 지하철처럼 노선명·노선 색 실선으로 그리고 타는 지점에 버스 아이콘을 붙입니다. 1단계 추정과 2단계 실제값의 차이는 로그와 응답의 `meta.estimate_accuracy`에 남습니다. 2026-10-15 기준 재윤·서영 후보 8곳 16건에서 평균절대오차 2.4분(편향 -0.2분)이었어요.

호출 보호 장치: (출발지 좌표 소수 4자리, 도착역, 요일·시간대) 키의 디스크 캐시 7일 · 같은 요청이 동시에 오면 한 번만 호출 · 네트워크·5xx·429만 1회 재시도, 키 제한·API 미사용·할당량 오류는 재시도 없이 2분간 호출 중단 · FieldMask로 필요한 필드만 요청 · 오늘 호출 수는 백엔드 로그와 개발 서버 화면 오른쪽 아래에 표시됩니다.

| `ROUTE_MODE` | 동작 | 쓰임 |
|---|---|---|
| `live` (기본) | 캐시 우선: `backend/fixtures/google/` 저장본 → 7일 디스크 캐시 → 없을 때만 실제 호출 후 캐시 저장. 하루 호출 상한은 `backend/config/routes.yaml`의 `daily_call_limit`(기본 200), 넘으면 추정값으로 표시 | 평소·발표 |
| `record` | 실제로 호출하고 응답을 `backend/fixtures/google/`에 저장 (캐시는 쓰지 않음) | 저장본 만들기 |
| `replay` | 저장본만 사용. 호출 0. 저장본이 없는 요청은 추정값으로 표시 | 테스트 전용 |

저장본은 요청(출발지 4자리 좌표·도착역·시간대)이 같을 때만 재사용됩니다. 지금 들어 있는 저장본은 재윤(홍대입구역)·서영(잠실역) 2명의 검색 1회(후보 8곳)와 최종 3곳 경로 6개, 그리고 버스가 포함된 경로 1개(서초구 내곡동 → 강남역)입니다.
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
python scripts/demo_recommend.py            # 홍대입구·잠실·노원 추천 데모 (실제 API, 캐시 우선)
```

## 주요 설정 파일 (`backend/config/`)

| 파일 | 내용 |
|---|---|
| `region.yaml` | RegionScore 가중치(평균 0.4 / 최대 0.3 / 편차 0.3), 1단계 후보 역 수 K=20, 2단계 확인 후보 수 `shortlist_size`=8(환경변수 `SHORTLIST_SIZE`로 덮어쓰기), 최종 3곳 |
| `place.yaml` | PlaceScore 가중치, 모임 목적별 카테고리, 구글 하루 호출 상한 |
| `subway.yaml` | 1단계 추정 파라미터 (도보 속도, 승차 대기, 가까운 역 후보 수) |
| `routes.yaml` | Google 호출 설정 (출발 시각, 허용 대중교통 수단, 캐시 7일, 재시도 1회, 호출 중단 시간) |
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
- `GET /auth/kakao/login`, `GET /auth/kakao/callback`, `GET /auth/me`, `POST /auth/logout` — 카카오 로그인 (인가 코드 방식, 백엔드 세션)
- `POST /api/share/memo` — 나에게 보내기 (로그인 필요, `{text, url}`)
- `GET /api/realtime` — 실시간 도착 정보 (위 "실시간 도착 정보" 참고)
- `GET /health`
