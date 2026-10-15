"""카카오 로그인·나에게 보내기 호출 (REST API). 키·토큰은 로그나 응답에 남기지 않는다."""

import json
import secrets
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode

import httpx2 as httpx

AUTHORIZE_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"
ME_URL = "https://kapi.kakao.com/v2/user/me"
MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
SCOPES = "profile_nickname,talk_message"


class KakaoAuthError(Exception):
    """사용자에게 보여줘도 되는 메시지만 담는다."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


@dataclass
class Session:
    nickname: str
    access_token: str
    refresh_token: str | None
    expires_at: float
    created_at: float = field(default_factory=time.time)


class SessionStore:
    """메모리 세션 저장소. 서버를 다시 켜면 로그아웃된다 (토큰을 디스크에 남기지 않기 위해)."""

    def __init__(self, ttl_seconds: int = 7 * 24 * 3600):
        self._items: dict[str, Session] = {}
        self.ttl = ttl_seconds

    def create(self, session: Session) -> str:
        sid = secrets.token_urlsafe(32)
        self._items[sid] = session
        return sid

    def get(self, sid: str | None) -> Session | None:
        if not sid:
            return None
        s = self._items.get(sid)
        if s and time.time() - s.created_at > self.ttl:
            self._items.pop(sid, None)
            return None
        return s

    def delete(self, sid: str | None) -> None:
        if sid:
            self._items.pop(sid, None)


def _json(r: httpx.Response) -> dict:
    try:
        body = r.json()
        return body if isinstance(body, dict) else {}
    except ValueError:
        return {}


class KakaoAuthClient:
    def __init__(self, rest_key: str, client_secret: str, redirect_uri: str, http: httpx.Client | None = None):
        self.rest_key, self.client_secret, self.redirect_uri = rest_key, client_secret, redirect_uri
        self._http = http or httpx.Client(timeout=10)

    def authorize_url(self, state: str) -> str:
        return AUTHORIZE_URL + "?" + urlencode({
            "client_id": self.rest_key, "redirect_uri": self.redirect_uri, "response_type": "code",
            "scope": SCOPES, "state": state,
        })

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        try:
            return self._http.request(method, url, **kwargs)
        except httpx.HTTPError as e:
            raise KakaoAuthError(f"카카오 서버에 연결하지 못했어요 ({type(e).__name__})") from None

    def _token(self, data: dict) -> dict:
        data = {**data, "client_id": self.rest_key}
        if self.client_secret:
            data["client_secret"] = self.client_secret
        r = self._request("POST", TOKEN_URL, data=data)
        body = _json(r)
        if r.status_code != 200:
            code, desc = body.get("error_code", ""), body.get("error_description", "")
            raise KakaoAuthError(f"카카오 토큰 발급 실패 {code} {desc}".strip(), 401)
        return body

    def exchange_code(self, code: str) -> Session:
        tok = self._token({"grant_type": "authorization_code", "redirect_uri": self.redirect_uri, "code": code})
        access = tok["access_token"]
        return Session(nickname=self.nickname(access), access_token=access, refresh_token=tok.get("refresh_token"),
                       expires_at=time.time() + int(tok.get("expires_in", 21599)))

    def refresh(self, session: Session) -> None:
        if not session.refresh_token:
            raise KakaoAuthError("로그인이 만료됐어요. 다시 로그인해 주세요.", 401)
        tok = self._token({"grant_type": "refresh_token", "refresh_token": session.refresh_token})
        session.access_token = tok["access_token"]
        session.expires_at = time.time() + int(tok.get("expires_in", 21599))
        if tok.get("refresh_token"):
            session.refresh_token = tok["refresh_token"]

    def nickname(self, access_token: str) -> str:
        r = self._request("GET", ME_URL, headers={"Authorization": f"Bearer {access_token}"})
        if r.status_code != 200:
            raise KakaoAuthError(f"카카오 사용자 정보 조회 실패 (HTTP {r.status_code})", 401)
        d = _json(r)
        profile = (d.get("kakao_account") or {}).get("profile") or {}
        return profile.get("nickname") or (d.get("properties") or {}).get("nickname") or "카카오 사용자"

    def send_memo(self, session: Session, text: str, url: str, button_title: str = "결과 다시 보기") -> None:
        """나에게 보내기(기본 템플릿 text). 토큰이 만료됐으면 한 번 갱신해서 다시 시도한다."""
        template = {"object_type": "text", "text": text,
                    "link": {"web_url": url, "mobile_web_url": url}, "button_title": button_title}
        if session.expires_at - time.time() < 60:
            self.refresh(session)
        for attempt in range(2):
            r = self._request("POST", MEMO_URL, headers={"Authorization": f"Bearer {session.access_token}"},
                              data={"template_object": json.dumps(template, ensure_ascii=False)})
            if r.status_code == 401 and attempt == 0:
                self.refresh(session)
                continue
            if r.status_code == 200:
                return
            body = _json(r)
            if body.get("code") == -402 or r.status_code == 403:
                raise KakaoAuthError("카카오톡 메시지 전송 권한이 없어요. 로그아웃 후 다시 로그인해서 '카카오톡 메시지 전송'에 동의해 주세요.", 403)
            raise KakaoAuthError(f"나에게 보내기 실패 (HTTP {r.status_code}) {body.get('msg', '')}".strip())
