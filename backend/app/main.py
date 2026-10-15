import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import settings
from app.routers import auth, diagnostics, realtime, recommend, search

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
    # 브라우저는 프론트(Vite) 프록시로 같은 출처에서 호출하므로 CORS는 백엔드를 직접 열어 볼 때만 쓴다.
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$|^https://[a-z0-9-]+\.trycloudflare\.com$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(recommend.router)
app.include_router(recommend.route_router)
app.include_router(search.router)
app.include_router(diagnostics.router)
app.include_router(realtime.router)
app.include_router(auth.router)
app.include_router(auth.share_router)


@app.get("/health")
@app.get("/api/health")  # 프론트 프록시(/api/*)로 접근할 때 쓰는 경로
def health() -> dict:
    return {"status": "ok", "mock": {"places": settings.MOCK_PLACES, "ratings": settings.MOCK_RATINGS, "routes": settings.MOCK_ROUTES}, "route_provider": settings.ROUTE_PROVIDER,
            "route_mode": settings.ROUTE_MODE}
