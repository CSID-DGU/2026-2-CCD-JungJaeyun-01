from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import settings
from app.routers import recommend

app = FastAPI(title="Meetup Recommender API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(recommend.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "use_mock": settings.USE_MOCK}
