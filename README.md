# Meetup Recommender

이동 편의성과 연령대별 트렌드를 고려한 맞춤형 모임 장소 추천 서비스 (캡스톤디자인).

- 개요서: [docs/spec.md](docs/spec.md)
- 개발 규칙과 실행 방법: [CLAUDE.md](CLAUDE.md)

## 빠른 시작

```bash
cp .env.example .env

# 백엔드
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 프론트엔드 (새 터미널)
cd frontend
npm install
npm run dev
```
