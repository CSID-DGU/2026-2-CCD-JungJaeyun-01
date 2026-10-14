"""외부 API 연결 확인용 스크립트 (실제 API를 한 번씩 호출한다).

실행 (backend 폴더에서):
    .venv\\Scripts\\python scripts/test_apis.py
    .venv\\Scripts\\python scripts/test_apis.py --only kakao,odsay   # 구글 제외하고 재실행

- 키는 루트 .env에서 python-dotenv로 읽는다. 키 값은 출력하지 않는다.
- 구글 Places는 과금되므로 실행당 정확히 1번만 호출하고, 실패해도 재시도하지 않는다.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

import httpx2 as httpx
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")

KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY", "").strip()
ODSAY_API_KEY = os.getenv("ODSAY_API_KEY", "").strip()
GOOGLE_PLACES_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()

SECRETS = [k for k in (KAKAO_REST_API_KEY, ODSAY_API_KEY, GOOGLE_PLACES_API_KEY) if k]

# 강남역 키워드 검색이 실패해도 다음 단계를 진행할 수 있게 하는 기본 좌표
GANGNAM_FALLBACK = (127.027610, 37.497950)  # (x=경도, y=위도)
HONGDAE = (126.923778, 37.557527)  # 홍대입구역

TIMEOUT = 10.0
results: list[dict] = []


def mask(text: object) -> str:
    """출력 문자열에 키 값이 섞여 있으면 *** 로 가린다 (에러 메시지·URL 대비)."""
    s = str(text)
    for secret in SECRETS:
        s = s.replace(secret, "***")
        s = s.replace(quote(secret, safe=""), "***")  # URL 인코딩된 형태
    return s


def header(title: str) -> None:
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def record(name: str, ok: bool, status: int | None, message: str = "") -> None:
    results.append({"name": name, "ok": ok, "status": status, "message": mask(message)})
    mark = "성공" if ok else "실패"
    print(f"\n[{mark}] HTTP {status if status is not None else '-'}"
          + (f" | {mask(message)}" if message else ""))


def pretty(obj: object) -> str:
    return mask(json.dumps(obj, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------- 1. 카카오 키워드
def test_kakao_keyword() -> tuple[float, float] | None:
    name = "1. 카카오 키워드 검색"
    header(f"{name}: '강남역'")
    if not KAKAO_REST_API_KEY:
        record(name, False, None, "KAKAO_REST_API_KEY가 비어 있음")
        return None
    try:
        r = httpx.get(
            "https://dapi.kakao.com/v2/local/search/keyword.json",
            params={"query": "강남역", "size": 5},
            headers={"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"},
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as e:
        record(name, False, None, f"요청 오류: {e!r}")
        return None

    if r.status_code != 200:
        record(name, False, r.status_code, r.text[:300])
        return None

    docs = r.json().get("documents", [])
    for d in docs:
        print(f"- {d['place_name']} | {d.get('road_address_name') or d.get('address_name')}"
              f" | x={d['x']}, y={d['y']} | {d.get('category_name')}")
    if not docs:
        record(name, False, r.status_code, "검색 결과 0건")
        return None

    # 지하철역(SW8) 결과를 우선 사용
    station = next((d for d in docs if d.get("category_group_code") == "SW8"), docs[0])
    print(f"\n→ 이후 테스트에 사용할 강남역 좌표: {station['place_name']} "
          f"(x={station['x']}, y={station['y']})")
    record(name, True, r.status_code)
    return float(station["x"]), float(station["y"])


# ---------------------------------------------------------------- 2. 카카오 카테고리
def test_kakao_category(x: float, y: float) -> None:
    for code, label in (("FD6", "음식점"), ("CE7", "카페")):
        name = f"2. 카카오 카테고리 검색({code} {label})"
        header(f"{name}: 반경 500m, 3개")
        if not KAKAO_REST_API_KEY:
            record(name, False, None, "KAKAO_REST_API_KEY가 비어 있음")
            continue
        try:
            r = httpx.get(
                "https://dapi.kakao.com/v2/local/search/category.json",
                params={"category_group_code": code, "x": x, "y": y,
                        "radius": 500, "size": 3, "sort": "distance"},
                headers={"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"},
                timeout=TIMEOUT,
            )
        except httpx.HTTPError as e:
            record(name, False, None, f"요청 오류: {e!r}")
            continue

        if r.status_code != 200:
            record(name, False, r.status_code, r.text[:300])
            continue

        body = r.json()
        print("meta:", pretty(body.get("meta")))
        for i, d in enumerate(body.get("documents", []), 1):
            print(f"\n[{i}] 응답 필드 전체:")
            print(pretty(d))
        record(name, True, r.status_code, f"{len(body.get('documents', []))}건")


# ---------------------------------------------------------------- 3. ODsay
TRAFFIC = {1: "지하철", 2: "버스", 3: "도보"}


def test_odsay(dest: tuple[float, float]) -> None:
    name = "3. ODsay 대중교통 경로"
    header(f"{name}: 홍대입구역 → 강남역")
    if not ODSAY_API_KEY:
        record(name, False, None, "ODSAY_API_KEY가 비어 있음")
        return
    try:
        r = httpx.get(
            "https://api.odsay.com/v1/api/searchPubTransPathT",
            params={"SX": HONGDAE[0], "SY": HONGDAE[1], "EX": dest[0], "EY": dest[1],
                    "apiKey": ODSAY_API_KEY},
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as e:
        record(name, False, None, f"요청 오류: {e!r}")
        return

    body = r.json() if "json" in r.headers.get("content-type", "") else {}
    # ODsay는 키/IP 오류도 HTTP 200 + {"error": ...} 로 돌려준다.
    if r.status_code != 200 or "error" in body or "result" not in body:
        err = body.get("error", r.text[:300])
        record(name, False, r.status_code, json.dumps(err, ensure_ascii=False))
        return

    paths = body["result"].get("path", [])
    if not paths:
        record(name, False, r.status_code, "경로 0건")
        return

    info = paths[0]["info"]
    transfers = info.get("busTransitCount", 0) + info.get("subwayTransitCount", 0) - 1
    print(f"검색된 경로 수: {len(paths)}")
    print(f"첫 번째 경로 총 소요시간: {info['totalTime']}분")
    print(f"환승 횟수: {max(transfers, 0)}회 "
          f"(지하철 {info.get('subwayTransitCount', 0)}회 탑승, 버스 {info.get('busTransitCount', 0)}회 탑승)")
    print(f"요금: {info.get('payment')}원 | 총 도보: {info.get('totalWalk')}m")
    print("구간 요약:")
    for sp in paths[0].get("subPath", []):
        kind = TRAFFIC.get(sp["trafficType"], str(sp["trafficType"]))
        if sp["trafficType"] == 3:
            print(f"  - {kind} {sp.get('distance', 0)}m ({sp['sectionTime']}분)")
            continue
        lane = sp.get("lane", [{}])[0]
        line = lane.get("name") or lane.get("busNo")
        print(f"  - {kind} [{line}] {sp.get('startName')} → {sp.get('endName')} "
              f"({sp.get('stationCount')}개 정류장/역, {sp['sectionTime']}분)")
    record(name, True, r.status_code, f"{info['totalTime']}분")


# ---------------------------------------------------------------- 4. Google Places (New)
GOOGLE_FIELD_MASK = ",".join([
    "places.displayName",
    "places.formattedAddress",
    "places.rating",
    "places.userRatingCount",
])


def test_google_places() -> None:
    name = "4. Google Places (New) Text Search"
    header(f"{name}: '강남역 맛집' 1건 (호출 1회)")
    if not GOOGLE_PLACES_API_KEY:
        record(name, False, None, "GOOGLE_PLACES_API_KEY가 비어 있음")
        return
    print(f"FieldMask: {GOOGLE_FIELD_MASK}")
    try:
        r = httpx.post(
            "https://places.googleapis.com/v1/places:searchText",
            headers={
                "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
                "X-Goog-FieldMask": GOOGLE_FIELD_MASK,
                "Content-Type": "application/json",
            },
            json={"textQuery": "강남역 맛집", "pageSize": 1, "languageCode": "ko",
                  "regionCode": "KR"},
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as e:
        record(name, False, None, f"요청 오류(재시도 안 함): {e!r}")
        return

    body = r.json() if r.content else {}
    if r.status_code != 200:
        err = body.get("error", {})
        record(name, False, r.status_code,
               f"{err.get('status')} - {err.get('message', r.text[:300])}")
        return

    places = body.get("places", [])
    for p in places:
        print(f"displayName     : {p.get('displayName', {}).get('text')}")
        print(f"formattedAddress: {p.get('formattedAddress')}")
        print(f"rating          : {p.get('rating')}")
        print(f"userRatingCount : {p.get('userRatingCount')}")
    record(name, bool(places), r.status_code, "" if places else "결과 0건")


# ---------------------------------------------------------------- main
def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="kakao,odsay,google",
                        help="실행할 API (쉼표 구분): kakao, odsay, google")
    only = set(parser.parse_args().only.split(","))

    gangnam = GANGNAM_FALLBACK
    if "kakao" in only:
        found = test_kakao_keyword()
        if found:
            gangnam = found
        else:
            print(f"\n→ 키워드 검색 실패, 기본 좌표 사용: x={gangnam[0]}, y={gangnam[1]}")
        test_kakao_category(*gangnam)
    if "odsay" in only:
        test_odsay(gangnam)
    if "google" in only:
        test_google_places()

    header("요약")
    for res in results:
        mark = "OK  " if res["ok"] else "FAIL"
        status = res["status"] if res["status"] is not None else "-"
        print(f"{mark} | HTTP {status} | {res['name']}"
              + (f" | {res['message']}" if res["message"] and not res["ok"] else ""))


if __name__ == "__main__":
    main()
