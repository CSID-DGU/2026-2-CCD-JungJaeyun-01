from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import settings
from app.routers import recommend, search

app = FastAPI(title="Meetup Recommender API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(recommend.router)
app.include_router(search.router)


@app.get("/health")
@app.get("/api/health")  # 프론트 프록시(/api/*)로 접근할 때 쓰는 경로
def health() -> dict:
    return {"status": "ok", "use_mock": settings.USE_MOCK}
