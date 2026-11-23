"""빌드된 프론트(frontend/dist)를 백엔드가 함께 내준다.

개발할 때는 Vite(5173)가 화면을, 백엔드(8000)가 API를 나눠 맡지만, 실행 패키지(더블클릭 실행)에서는
서버 하나(기본 5173)가 화면과 API를 같이 내준다. dist 폴더가 없으면 아무것도 하지 않는다(개발 모드 그대로).
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# 이 경로들은 화면이 아니라 서버 기능이다: 없는 주소면 index.html이 아니라 404를 돌려준다.
API_PREFIXES = ("api/", "auth/", "docs", "redoc", "openapi.json", "health")


def mount_frontend(app: FastAPI, dist_dir: Path) -> bool:
    """dist_dir에 빌드 결과가 있으면 화면 파일과 SPA 기본 경로를 등록한다. 등록했으면 True."""
    index = dist_dir / "index.html"
    if not index.is_file():
        return False
    assets = dist_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str) -> FileResponse:
        if path.startswith(API_PREFIXES):
            raise HTTPException(status_code=404, detail="Not Found")
        target = (dist_dir / path).resolve()
        if path and target.is_file() and dist_dir.resolve() in target.parents:  # favicon.svg 같은 파일
            return FileResponse(target)
        return FileResponse(index)  # 새로고침·공유 링크(?s=…)는 항상 앱 화면으로

    return True
