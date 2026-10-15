import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import settings
from app.routers import auth, diagnostics, recommend, search

# 앱 로그(추정 vs 실제 차이, 순위 변경, 경로 API 호출·오류)를 INFO까지 콘솔에 남긴다. uvicorn은 자기 로거만 설정한다.
_app_logger = logging.getLogger("app")
_app_logger.setLevel(logging.INFO)
if not _app_logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s:     [%(name)s] %(message)s"))
    _app_logger.addHandler(_handler)

app = FastAPI(title="Meetup Recommender API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(recommend.router)
app.include_router(recommend.route_router)
app.include_router(search.router)
app.include_router(diagnostics.router)
app.include_router(auth.router)
app.include_router(auth.share_router)


@app.get("/health")
@app.get("/api/health")  # 프론트 프록시(/api/*)로 접근할 때 쓰는 경로
def health() -> dict:
    return {"status": "ok", "use_mock": settings.USE_MOCK, "route_provider": settings.ROUTE_PROVIDER,
            "route_mode": settings.ROUTE_MODE}
