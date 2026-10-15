"""카카오 로그인 (인가 코드 방식)과 나에게 보내기. 토큰은 서버 세션에만 있고 브라우저에는 httpOnly 세션 쿠키만 간다."""

import logging
import re
import secrets
from functools import lru_cache
from urllib.parse import urlparse

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app import settings
from app.services.kakao_auth import KakaoAuthClient, KakaoAuthError, Session, SessionStore

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])
share_router = APIRouter(prefix="/api/share", tags=["share"])

SESSION_COOKIE = "mr_session"
STATE_COOKIE = "mr_oauth_state"
SESSION_MAX_AGE = 7 * 24 * 3600


@lru_cache
def get_sessions() -> SessionStore:
    return SessionStore(SESSION_MAX_AGE)


@lru_cache
def get_kakao_auth() -> KakaoAuthClient:
    return KakaoAuthClient(settings.KAKAO_REST_API_KEY, settings.KAKAO_CLIENT_SECRET)


HOST_PATTERN = re.compile(r"^[A-Za-z0-9.\-]+(:\d{1,5})?$")


def public_origin(request: Request) -> str:
    """사용자가 접속한 주소(scheme://host). 터널·프록시 뒤에서는 X-Forwarded-* 헤더를 따른다. FRONTEND_URL로 고정할 수도 있다."""
    if settings.FRONTEND_URL:
        return settings.FRONTEND_URL
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip().lower()
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc).split(",")[0].strip()
    if proto not in ("http", "https") or not HOST_PATTERN.match(host):
        raise HTTPException(400, "올바르지 않은 접속 주소예요.")
    return f"{proto}://{host}"


def redirect_uri_of(request: Request) -> str:
    return settings.KAKAO_REDIRECT_URI or f"{public_origin(request)}/auth/kakao/callback"


def current_session(sid: str | None = Cookie(default=None, alias=SESSION_COOKIE),
                    sessions: SessionStore = Depends(get_sessions)) -> Session | None:
    return sessions.get(sid)


def _back(request: Request, error: str | None = None) -> RedirectResponse:
    return RedirectResponse(f"{public_origin(request)}/" + (f"?login_error={error}" if error else "?login=ok"), status_code=302)


def _secure(request: Request) -> bool:
    return public_origin(request).startswith("https://")


@router.get("/kakao/login")
def kakao_login(request: Request, auth: KakaoAuthClient = Depends(get_kakao_auth)) -> Response:
    if not settings.KAKAO_REST_API_KEY:
        raise HTTPException(503, "KAKAO_REST_API_KEY가 설정되지 않아 로그인할 수 없어요.")
    state = secrets.token_urlsafe(16)
    resp = RedirectResponse(auth.authorize_url(state, redirect_uri_of(request)), status_code=302)
    resp.set_cookie(STATE_COOKIE, state, max_age=600, httponly=True, samesite="lax", secure=_secure(request))
    return resp


@router.get("/kakao/callback")
def kakao_callback(
    request: Request,
    code: str | None = None, state: str | None = None, error: str | None = None,
    state_cookie: str | None = Cookie(default=None, alias=STATE_COOKIE),
    auth: KakaoAuthClient = Depends(get_kakao_auth), sessions: SessionStore = Depends(get_sessions),
) -> Response:
    if error or not code:
        return _back(request, "denied")  # 사용자가 동의 화면에서 취소한 경우 등
    if not state or not state_cookie or not secrets.compare_digest(state, state_cookie):
        return _back(request, "state")
    try:
        session = auth.exchange_code(code, redirect_uri_of(request))
    except KakaoAuthError as e:
        logger.warning("카카오 로그인 실패: %s", e)
        return _back(request, "token")
    resp = _back(request)
    resp.set_cookie(SESSION_COOKIE, sessions.create(session), max_age=SESSION_MAX_AGE, httponly=True, samesite="lax", secure=_secure(request))
    resp.delete_cookie(STATE_COOKIE)
    return resp


@router.get("/me")
def me(session: Session | None = Depends(current_session)) -> dict:
    return {"loggedIn": session is not None, "nickname": session.nickname if session else None}


@router.post("/logout")
def logout(response: Response, sid: str | None = Cookie(default=None, alias=SESSION_COOKIE),
           sessions: SessionStore = Depends(get_sessions)) -> dict:
    sessions.delete(sid)
    response.delete_cookie(SESSION_COOKIE)
    return {"loggedIn": False}


class MemoRequest(BaseModel):
    text: str = Field(min_length=1, max_length=200)   # 카카오 text 템플릿 한도
    url: str = Field(max_length=2000)                 # "결과 다시 보기" 링크


@share_router.post("/memo")
def send_memo(body: MemoRequest, request: Request, session: Session | None = Depends(current_session),
              auth: KakaoAuthClient = Depends(get_kakao_auth)) -> dict:
    """나에게 보내기. 로그인한 사용자만. 링크는 우리 프론트 주소만 허용한다."""
    if session is None:
        raise HTTPException(401, "로그인이 필요해요.")
    expected, got = urlparse(public_origin(request)), urlparse(body.url)
    if (got.scheme, got.netloc) != (expected.scheme, expected.netloc):
        raise HTTPException(422, "허용되지 않는 링크예요.")
    try:
        auth.send_memo(session, body.text, body.url)
    except KakaoAuthError as e:
        raise HTTPException(e.status, str(e)) from e
    return {"sent": True}
