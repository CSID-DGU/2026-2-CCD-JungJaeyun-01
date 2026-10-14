"""Google Routes API(computeRoutes, TRANSIT) 품질 확인용 프로브. 경로 3개를 한 번씩만 호출한다.

실행 (backend 폴더에서):
    .venv\\Scripts\\python scripts/probe_google_routes.py

확인 항목: 경로 유무, 소요시간, steps의 transitDetails(노선명·색·승하차역·정류장 수), polyline.
키는 .env의 GOOGLE_ROUTES_KEY에서 읽고 출력하지 않는다.
"""

import json
import os
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

import httpx2 as httpx
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR.parent / ".env")

from app.providers.google import ROUTES_FIELD_MASK  # noqa: E402
from app.services.polyline import decode_polyline  # noqa: E402

KST = timezone(timedelta(hours=9))
URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIELD_MASK = ROUTES_FIELD_MASK  # 서비스가 실제로 쓰는 FieldMask와 같게 둔다
FIXTURE_DIR = BACKEND_DIR / "tests" / "fixtures"
FIXTURE_NAMES = {"합정역": "hapjeong_euljiro3ga", "서울대입구역": "seouldae_anguk", "수원역": "suwon_jonggak"}
CASES = [("합정역", "을지로3가역"), ("서울대입구역", "안국역"), ("수원역", "종각역")]


def next_weekday_6pm() -> datetime:
    """오늘 이후 첫 평일의 오후 6시(KST)."""
    d = date.today() + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return datetime.combine(d, time(18, 0), tzinfo=KST)


def latlng(station: dict) -> dict:
    return {"location": {"latLng": {"latitude": station["lat"], "longitude": station["lng"]}}}


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    key = os.getenv("GOOGLE_ROUTES_KEY", "").strip()
    if not key:
        sys.exit("GOOGLE_ROUTES_KEY가 .env에 없습니다.")
    stations = {s["name"]: s for s in json.loads((BACKEND_DIR / "data" / "stations.json").read_text(encoding="utf-8"))}
    depart = next_weekday_6pm()
    print(f"출발 시각: {depart.isoformat()} (KST)\n")

    for origin_name, dest_name in CASES:
        print("=" * 72)
        print(f"{origin_name} → {dest_name}")
        body = {
            "origin": latlng(stations[origin_name]),
            "destination": latlng(stations[dest_name]),
            "travelMode": "TRANSIT",
            "departureTime": depart.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "languageCode": "ko",
            "regionCode": "KR",
        }
        try:
            r = httpx.post(URL, json=body, timeout=15.0,
                           headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": FIELD_MASK})
        except httpx.HTTPError as e:
            print(f"  요청 실패: {type(e).__name__}")
            continue
        print(f"  HTTP {r.status_code}")
        data = r.json() if r.content else {}
        if r.status_code != 200:
            err = data.get("error", {})
            print(f"  오류: {err.get('status')} - {str(err.get('message'))[:200].replace(key, '***')}")
            continue
        if "--save" in sys.argv:
            FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
            out = FIXTURE_DIR / f"google_route_{FIXTURE_NAMES[origin_name]}.json"
            out.write_text(json.dumps({"origin": origin_name, "destination": dest_name,
                                       "origin_latlng": [stations[origin_name]["lat"], stations[origin_name]["lng"]],
                                       "destination_latlng": [stations[dest_name]["lat"], stations[dest_name]["lng"]],
                                       "response": data}, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"  저장: {out.name}")
        routes = data.get("routes") or []
        if not routes:
            print("  경로 없음 (routes 비어 있음)")
            continue
        route = routes[0]
        minutes = int(route["duration"].rstrip("s")) / 60
        overall = decode_polyline(route.get("polyline", {}).get("encodedPolyline", ""))
        print(f"  소요시간 {minutes:.0f}분 | 거리 {route.get('distanceMeters', 0) / 1000:.1f}km | 전체 polyline {len(overall)}점")
        for leg in route["legs"]:
            for i, step in enumerate(leg["steps"], 1):
                mode = step.get("travelMode")
                dur = int(step.get("staticDuration", "0s").rstrip("s")) / 60
                pts = len(decode_polyline(step.get("polyline", {}).get("encodedPolyline", "")))
                td = step.get("transitDetails")
                if not td:
                    print(f"   {i}. {mode:<8} {dur:4.1f}분 | polyline {pts}점")
                    continue
                line = td.get("transitLine", {})
                stops = td.get("stopDetails", {})
                print(f"   {i}. {mode:<8} {dur:4.1f}분 | polyline {pts}점 | "
                      f"노선 nameShort={line.get('nameShort')!r} name={line.get('name')!r} "
                      f"색={line.get('color')} 차량={line.get('vehicle', {}).get('type')} | "
                      f"{stops.get('departureStop', {}).get('name')} → {stops.get('arrivalStop', {}).get('name')} "
                      f"({td.get('stopCount')}개 정류장)")


if __name__ == "__main__":
    main()
