import json
from urllib.parse import parse_qs, urlparse

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient

from app import settings
from app.main import app
from app.routers.auth import get_kakao_auth, get_sessions
from app.services.kakao_auth import KakaoAuthClient, SessionStore

FRONT = settings.FRONTEND_URL


class FakeKakao:
    """kauth/kapi 서버 흉내. 받은 요청을 기록한다."""

    def __init__(self):
        self.calls: list[httpx.Request] = []
        self.memo_status = 200
        self.token_status = 200

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        url = str(request.url)
        if url.endswith("/oauth/token"):
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error_code": "KOE320", "error_description": "bad code"})
            return httpx.Response(200, json={"access_token": "AT-1", "refresh_token": "RT-1", "expires_in": 21599})
        if url.endswith("/v2/user/me"):
            return httpx.Response(200, json={"kakao_account": {"profile": {"nickname": "서영"}}})
        if url.endswith("/memo/default/send"):
            if self.memo_status == 401 and request.headers["authorization"] == "Bearer AT-1":
                return httpx.Response(401, json={"msg": "expired", "code": -401})
            return httpx.Response(self.memo_status, json={"result_code": 0} if self.memo_status == 200 else {"msg": "x", "code": -402})
        raise AssertionError(url)


@pytest.fixture
def kakao():
    fake = FakeKakao()
    client = KakaoAuthClient("rest-key", "", f"{FRONT}/auth/kakao/callback", http=httpx.Client(transport=httpx.MockTransport(fake)))
    store = SessionStore()
    app.dependency_overrides[get_kakao_auth] = lambda: client
    app.dependency_overrides[get_sessions] = lambda: store
    yield fake, client
    app.dependency_overrides.clear()


def login(c: TestClient):
    r = c.get("/auth/kakao/login", follow_redirects=False)
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    return c.get(f"/auth/kakao/callback?code=abc&state={state}", follow_redirects=False)


def test_login_redirects_to_kakao_with_required_scopes(kakao, monkeypatch):
    monkeypatch.setattr(settings, "KAKAO_REST_API_KEY", "rest-key")
    r = TestClient(app).get("/auth/kakao/login", follow_redirects=False)
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert r.status_code == 302 and r.headers["location"].startswith("https://kauth.kakao.com/oauth/authorize")
    assert q["scope"] == ["profile_nickname,talk_message"] and q["response_type"] == ["code"]
    assert q["redirect_uri"] == [f"{FRONT}/auth/kakao/callback"] and q["client_id"] == ["rest-key"]
    assert "httponly" in r.headers["set-cookie"].lower()


def test_callback_creates_httponly_session_and_never_exposes_the_token(kakao, monkeypatch):
    monkeypatch.setattr(settings, "KAKAO_REST_API_KEY", "rest-key")
    fake, _ = kakao
    c = TestClient(app)
    r = login(c)
    assert r.status_code == 302 and r.headers["location"].startswith(FRONT)
    cookies = [h for h in r.headers.get_list("set-cookie") if h.startswith("mr_session=")]
    assert cookies and "httponly" in cookies[0].lower()
    assert "AT-1" not in r.text and all("AT-1" not in h for h in r.headers.get_list("set-cookie"))
    me = c.get("/auth/me").json()
    assert me == {"loggedIn": True, "nickname": "서영"} and "AT-1" not in json.dumps(me)


def test_client_secret_is_sent_only_when_configured(kakao):
    fake, client = kakao
    client.exchange_code("abc")
    assert b"client_secret" not in fake.calls[0].content
    client.client_secret = "sec"
    client.exchange_code("abc")
    assert b"client_secret=sec" in [c for c in fake.calls if str(c.url).endswith("/oauth/token")][1].content


def test_callback_rejects_wrong_state_and_denied_login(kakao):
    c = TestClient(app)
    assert "login_error=state" in c.get("/auth/kakao/callback?code=abc&state=nope", follow_redirects=False).headers["location"]
    assert "login_error=denied" in c.get("/auth/kakao/callback?error=access_denied", follow_redirects=False).headers["location"]
    assert c.get("/auth/me").json()["loggedIn"] is False


def test_token_exchange_failure_redirects_with_error(kakao, monkeypatch):
    monkeypatch.setattr(settings, "KAKAO_REST_API_KEY", "rest-key")
    fake, _ = kakao
    fake.token_status = 400
    assert "login_error=token" in login(TestClient(app)).headers["location"]


def test_logout_clears_the_session(kakao, monkeypatch):
    monkeypatch.setattr(settings, "KAKAO_REST_API_KEY", "rest-key")
    c = TestClient(app)
    login(c)
    assert c.post("/auth/logout").json() == {"loggedIn": False}
    assert c.get("/auth/me").json()["loggedIn"] is False


MEMO = {"text": "1위 홍대입구", "url": f"{FRONT}/?s=abc"}


def test_memo_requires_login(kakao):
    assert TestClient(app).post("/api/share/memo", json=MEMO).status_code == 401


def test_memo_sends_text_template_with_bearer_token(kakao, monkeypatch):
    monkeypatch.setattr(settings, "KAKAO_REST_API_KEY", "rest-key")
    fake, _ = kakao
    c = TestClient(app)
    login(c)
    assert c.post("/api/share/memo", json=MEMO).json() == {"sent": True}
    req = fake.calls[-1]
    assert str(req.url) == "https://kapi.kakao.com/v2/api/talk/memo/default/send" and req.headers["authorization"] == "Bearer AT-1"
    template = json.loads(parse_qs(req.content.decode())["template_object"][0])
    assert template["object_type"] == "text" and template["button_title"] == "결과 다시 보기"
    assert template["link"]["web_url"] == MEMO["url"] and template["text"] == MEMO["text"]


def test_memo_refreshes_an_expired_token_once(kakao, monkeypatch):
    monkeypatch.setattr(settings, "KAKAO_REST_API_KEY", "rest-key")
    fake, _ = kakao
    c = TestClient(app)
    login(c)
    fake.memo_status = 401
    # 갱신 뒤 토큰이 AT-1로 다시 발급되므로 여전히 실패한다 → 오류를 그대로 알려준다 (무한 재시도 없음)
    assert c.post("/api/share/memo", json=MEMO).status_code in (403, 502)
    assert len([x for x in fake.calls if str(x.url).endswith("/oauth/token")]) == 2  # 로그인 1 + 갱신 1


def test_memo_rejects_foreign_links(kakao, monkeypatch):
    monkeypatch.setattr(settings, "KAKAO_REST_API_KEY", "rest-key")
    c = TestClient(app)
    login(c)
    assert c.post("/api/share/memo", json={"text": "x", "url": "https://evil.example/?s=1"}).status_code == 422
