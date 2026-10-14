"""카카오맵 SDK를 불러올 수 없을 때 원인을 알려주기 위한 진단.

브라우저는 SDK 실패 응답(401/403)의 본문을 읽을 수 없어서(CORS 헤더 없음) 원인을 구분하지 못한다.
그래서 백엔드가 같은 URL을 Referer/Origin을 붙여 한 번 호출해 본문을 분류한다. SDK 로드에 실패한 경우에만 쓰인다.
"""

import re
from dataclasses import dataclass

import httpx2 as httpx

SDK_URL = "https://dapi.kakao.com/v2/maps/sdk.js"


@dataclass(frozen=True)
class MapDiagnosis:
    code: str  # ok | no_key | domain_mismatch | rest_key_used | invalid_key | service_disabled | unreachable | unknown
    message: str


def classify_sdk_response(status: int, body: str, origin: str) -> MapDiagnosis:
    """SDK 응답을 원인 코드와 사용자 안내 문구로 바꾼다 (순수 함수)."""
    if status == 200:
        return MapDiagnosis("ok", "서버에서는 카카오맵 SDK를 정상적으로 받았습니다.")
    text = body.lower()
    if "domain mismatched" in text:
        return MapDiagnosis(
            "domain_mismatch",
            f"{origin} 도메인이 등록되어 있지 않습니다. 카카오 개발자 콘솔 → 내 애플리케이션 → 플랫폼 → Web 사이트 도메인에 추가해 주세요.",
        )
    if "appkeytype is rest_api_key" in text:
        return MapDiagnosis(
            "rest_key_used",
            "VITE_KAKAO_JS_KEY에 REST API 키가 들어 있습니다. 앱 키 화면의 JavaScript 키로 바꿔 주세요.",
        )
    if "does not exist" in text:
        return MapDiagnosis(
            "invalid_key",
            "VITE_KAKAO_JS_KEY가 올바르지 않습니다(존재하지 않는 키). 콘솔에서 JavaScript 키를 다시 복사해 주세요.",
        )
    if "disabled" in text and "service" in text:
        return MapDiagnosis(
            "service_disabled",
            "앱의 '카카오맵' 사용 설정이 꺼져 있습니다. 카카오 개발자 콘솔 → 제품 설정 → 카카오맵에서 사용 설정을 켜 주세요.",
        )
    detail = re.sub(r"appKey\([^)]*\)", "appKey(***)", body.strip())[:160]  # 응답에 키가 들어 있으면 가린다
    return MapDiagnosis("unknown", f"카카오맵 SDK 응답 오류(HTTP {status}): {detail}")


class KakaoMapDiagnostics:
    def __init__(self, js_key: str, timeout: float = 5.0, client: httpx.Client | None = None):
        self._js_key = js_key
        self._client = client or httpx.Client(timeout=timeout)

    def check(self, origin: str) -> MapDiagnosis:
        if not self._js_key:
            return MapDiagnosis("no_key", "VITE_KAKAO_JS_KEY가 .env에 없습니다. 루트 .env에 키를 넣고 개발 서버를 다시 시작해 주세요.")
        try:
            r = self._client.get(
                SDK_URL,
                params={"appkey": self._js_key, "autoload": "false", "libraries": "services"},
                headers={"Referer": f"{origin}/", "Origin": origin},
            )
        except httpx.HTTPError:
            return MapDiagnosis("unreachable", "서버에서 카카오(dapi.kakao.com)에 연결하지 못했습니다. 네트워크를 확인해 주세요.")
        return classify_sdk_response(r.status_code, r.text, origin)
