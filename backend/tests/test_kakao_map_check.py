import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routers.diagnostics import get_map_diagnostics
from app.services.kakao_map_check import KakaoMapDiagnostics, MapDiagnosis, classify_sdk_response

ORIGIN = "http://localhost:5173"


@pytest.mark.parametrize(
    "status, body, code",
    [
        (200, "window.kakao=...", "ok"),
        (401, '{"errorType":"AccessDeniedError","message":"domain mismatched! caller=http://localhost:5173. check out registered web domains."}', "domain_mismatch"),
        (401, '{"errorType":"AccessDeniedError","message":"appKeyType is REST_API_KEY. but expected [NATIVE_APP_KEY, JAVASCRIPT_KEY]"}', "rest_key_used"),
        (401, '{"errorType":"AccessDeniedError","message":"appKey(abc123) does not exist"}', "invalid_key"),
        (403, '{"errorType":"NotAuthorizedError","message":"App(meetpick) disabled OPEN_MAP_AND_LOCAL service."}', "service_disabled"),
        (500, "boom", "unknown"),
    ],
)
def test_classify(status, body, code):
    assert classify_sdk_response(status, body, ORIGIN).code == code


def test_domain_message_names_the_origin():
    assert ORIGIN in classify_sdk_response(401, "domain mismatched!", ORIGIN).message


def test_unknown_response_never_leaks_the_key():
    msg = classify_sdk_response(401, '{"message":"appKey(SECRETKEY123) weird"}', ORIGIN).message
    assert "SECRETKEY123" not in msg


def test_missing_key_is_reported_without_calling_kakao():
    class Boom:
        def get(self, *a, **k):
            raise AssertionError("호출하면 안 됨")

    assert KakaoMapDiagnostics("", client=Boom()).check(ORIGIN).code == "no_key"


def test_endpoint_validates_origin_and_returns_diagnosis():
    class Fake:
        def check(self, origin):
            return MapDiagnosis("domain_mismatch", f"{origin} 미등록")

    app.dependency_overrides[get_map_diagnostics] = Fake
    try:
        client = TestClient(app)
        ok = client.get("/api/diagnostics/kakao-map", params={"origin": ORIGIN})
        assert ok.json() == {"code": "domain_mismatch", "message": f"{ORIGIN} 미등록"}
        assert client.get("/api/diagnostics/kakao-map", params={"origin": "javascript:alert(1)"}).status_code == 422
        assert client.get("/api/diagnostics/kakao-map").status_code == 422
    finally:
        app.dependency_overrides.clear()
