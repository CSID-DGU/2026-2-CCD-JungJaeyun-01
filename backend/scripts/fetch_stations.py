"""후보 지역(지하철역) 좌표를 카카오 키워드 검색으로 조회해 data/stations.json에 저장한다.

실행 (backend 폴더에서):
    .venv\\Scripts\\python scripts/fetch_stations.py

좌표는 직접 입력하지 않고 항상 이 스크립트로 다시 생성한다.
역 목록을 바꾸려면 STATION_NAMES만 수정하고 다시 실행한다.
"""

import json
import math
import os
import sys
from pathlib import Path

import httpx2 as httpx
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR.parent / ".env")

OUTPUT_PATH = BACKEND_DIR / "data" / "stations.json"
KAKAO_KEYWORD_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
SUBWAY_CATEGORY = "SW8"
# 같은 이름의 다른 도시 역(예: 부산 교대역)을 노선 목록에서 빼기 위한 거리 기준
SAME_STATION_RADIUS_KM = 1.0

# '역'을 뺀 이름. 검색어는 f"{name}역"으로 만든다.
STATION_NAMES = [
    # 강남·동남권
    "강남", "신논현", "역삼", "선릉", "삼성", "교대", "고속터미널", "신사",
    "압구정로데오", "잠실", "잠실새내", "천호", "수서",
    # 동북권
    "건대입구", "성수", "왕십리", "청량리", "회기", "노원", "수유",
    "미아사거리", "성신여대입구", "혜화",
    # 도심권
    "동대문역사문화공원", "종로3가", "종각", "을지로입구", "을지로3가", "시청",
    "광화문", "서울", "명동", "안국",
    # 서북권
    "홍대입구", "합정", "신촌", "이대", "망원", "연신내", "디지털미디어시티", "공덕",
    # 서남권
    "여의도", "영등포", "당산", "신도림", "구로디지털단지", "신림", "서울대입구",
    "사당", "노량진", "오목교", "마곡나루",
    # 경기·인천
    "수원", "판교", "정자", "서현", "야탑", "범계", "부천", "부평", "주엽", "의정부",
]


def _distance_km(a: dict, b: dict) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (float(a["y"]), float(a["x"]), float(b["y"]), float(b["x"])))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def search_station(client: httpx.Client, name: str) -> dict | None:
    query = f"{name}역"
    r = client.get(KAKAO_KEYWORD_URL, params={
        "query": query, "category_group_code": SUBWAY_CATEGORY, "size": 15,
    })
    r.raise_for_status()
    docs = [d for d in r.json()["documents"]
            if d["place_name"] == query or d["place_name"].startswith(f"{query} ")]
    if not docs:
        return None

    first = docs[0]
    # "강남역 2호선" → "2호선". 같은 역(1km 이내)의 다른 노선 결과에서 노선명을 모은다.
    same_station = [d for d in docs if _distance_km(first, d) <= SAME_STATION_RADIUS_KM]
    lines = sorted({d["place_name"][len(query):].strip() for d in same_station} - {""})
    return {
        "id": first["id"],
        "name": query,
        "lat": float(first["y"]),
        "lng": float(first["x"]),
        "lines": lines,
        "address": first.get("road_address_name") or first.get("address_name"),
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    api_key = os.getenv("KAKAO_REST_API_KEY", "").strip()
    if not api_key:
        sys.exit("KAKAO_REST_API_KEY가 .env에 없습니다.")

    stations, missing = [], []
    with httpx.Client(headers={"Authorization": f"KakaoAK {api_key}"}, timeout=10.0) as client:
        for name in STATION_NAMES:
            station = search_station(client, name)
            if station is None:
                missing.append(name)
                print(f"[없음] {name}역")
                continue
            stations.append(station)
            print(f"[OK] {station['name']:<14} lat={station['lat']:.6f} lng={station['lng']:.6f} "
                  f"{', '.join(station['lines'])}")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(stations, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n{len(stations)}개 역 저장 → {OUTPUT_PATH.relative_to(BACKEND_DIR)}")
    if missing:
        print(f"찾지 못한 역 {len(missing)}개: {', '.join(missing)}")


if __name__ == "__main__":
    main()
