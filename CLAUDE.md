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
│   ├── config/         # 점수 가중치 설정 파일
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
- 예외: **카카오맵 JavaScript 키(`KAKAO_JS_API_KEY`)만** 프론트에서 사용한다.
  - `frontend/vite.config.ts`의 `envPrefix: ['KAKAO_JS_']` 때문에 이 키만 프론트 번들에 노출된다. prefix를 넓히거나 다른 키를 프론트에 추가하지 않는다.
- API 키는 루트의 `.env`로 관리한다. `.env`는 `.gitignore`에 포함되어 있으며 절대 커밋하지 않는다.
- 새 환경변수를 추가하면 `.env.example`에도 빈 값과 설명을 함께 추가한다.

### 외부 API 호출 분리
- 외부 API 호출은 `backend/app/services/` 아래에 **인터페이스(추상 클래스 또는 Protocol)** 로 정의한다.
- 각 인터페이스마다 **mock 구현**과 **실제 구현**을 둔다.
  - 예: `TransitService` → `MockTransitService`, `OdsayTransitService`
  - 예: `PlaceService` → `MockPlaceService`, `KakaoPlaceService`
- 환경변수 `USE_MOCK=true/false`로 구현을 전환한다 (`app.settings.USE_MOCK`). 라우터·점수 계산 코드는 구현체가 아니라 인터페이스에만 의존한다.
- mock 구현은 API 키 없이도 전체 흐름이 동작하도록 현실적인 고정 데이터를 반환한다.

### 점수 계산
- RegionScore, PlaceScore의 **가중치는 `backend/config/` 아래 설정 파일로 분리**한다. 코드에 가중치를 하드코딩하지 않는다.
  - RegionScore: 평균 이동시간(효율성), 최대 이동시간(과도한 부담 방지), 이동시간 편차(공정성) — 각각 정규화 후 가중치 적용
  - PlaceScore: 접근성, 평점, 리뷰 수, 모임 목적 적합성, 연령대 선호도
- 점수 계산 함수(`backend/app/scoring/`)는 **순수 함수**로 작성한다: 입력(이동시간, 장소 정보, 가중치)만 받아 결과를 반환하고, 외부 API 호출·파일 읽기·전역 상태 변경을 하지 않는다. 가중치도 인자로 전달받는다.
- 점수 계산 함수를 추가·수정할 때는 `backend/tests/`에 **pytest 테스트를 함께 작성**한다 (정규화 경계값, 동점, 참여자 2명/5명 등).
- 연령대 가중치는 실제 데이터 기반인지 사전 정의 가중치인지 구분할 수 있게 구현한다.

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

### 프론트엔드 (http://localhost:5173)

```bash
cd frontend
npm install
npm run dev
```

- 개발 서버에서 `/api/*` 요청은 백엔드(`localhost:8000`)로 프록시된다. 예: `fetch('/api/health')`
- 빌드: `npm run build`
