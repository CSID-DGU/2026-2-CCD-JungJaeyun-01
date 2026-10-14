"""data/subway/ 의 공개 데이터와 노선 입력으로 지하철 네트워크(network.json)를 만든다.

실행 (backend 폴더에서):
    .venv\\Scripts\\python scripts/build_subway_network.py

입력
- seoul_metro_intervals_240810.csv : 서울교통공사 1~8호선 역 순서와 역간 소요시간 (공식 공개 데이터)
- extra_lines.yaml                 : 그 밖의 노선·구간 (노선도 기준 역 순서를 직접 입력)
- rules.yaml                       : 분기 규칙, 노선 색, 환승 규칙
역 좌표는 카카오 키워드 검색(지하철역 SW8)으로 가져오며 결과는 data/subway/_coord_cache.json에 캐시한다.
공식 소요시간이 없는 구간은 공식 데이터로 맞춘 '분 = a + b × km' 식으로 추정한다.
"""

import csv
import json
import math
import os
import sys
import time
from pathlib import Path

import httpx2 as httpx
import yaml
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_DIR / "data" / "subway"
load_dotenv(BACKEND_DIR.parent / ".env")

KAKAO_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
METRO_BBOX = (36.9, 38.2, 126.3, 127.8)  # lat_min, lat_max, lng_min, lng_max
# 역명 끝의 '역'까지 이름의 일부인 경우: 네트워크에서는 '서울'로 쓰고(후보 역 '서울역'과 맞추기 위해) 검색은 '서울역'으로 한다.
NAME_ALIASES = {"서울역": "서울"}
SEARCH_STEM = {"서울": "서울역"}


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def minutes_of(text: str) -> float:
    m, s = text.strip().split(":")
    return int(m) + int(s) / 60


# ----------------------------------------------------------------------------- 입력 읽기
def norm(name: str) -> str:
    return NAME_ALIASES.get(name.strip(), name.strip())


def read_official(rules: dict) -> list[tuple[str, str, str, float]]:
    """CSV → [(노선, 역A, 역B, 분)]. 분기·순환은 rules.official_breaks로 연결을 바로잡는다."""
    fix = rules.get("official_name_fix", {})
    breaks = rules.get("official_breaks", {})
    rows = list(csv.DictReader(open(DATA_DIR / "seoul_metro_intervals_240810.csv", encoding="utf-8")))
    edges = []
    by_line: dict[str, list[dict]] = {}
    for r in rows:
        by_line.setdefault(f"{r['호선'].strip()}호선", []).append(r)
    for line, rs in by_line.items():
        names = [norm(fix.get(r["역명"].strip(), r["역명"].strip())) for r in rs]
        connect = {b["station"]: b["connect_from"] for b in breaks.get(line, [])}
        for i in range(1, len(rs)):
            prev = connect.get(names[i], names[i - 1])
            edges.append((line, prev, names[i], minutes_of(rs[i]["소요시간"])))
    return edges


def read_extra() -> list[tuple[str, str, str]]:
    data = yaml.safe_load((DATA_DIR / "extra_lines.yaml").read_text(encoding="utf-8"))
    return [(line, norm(a), norm(b)) for line, chains in data.items() for chain in chains for a, b in zip(chain, chain[1:])]


# ----------------------------------------------------------------------------- 좌표 (카카오)
class Coords:
    def __init__(self, rules: dict):
        self.rules = rules
        self.cache_path = DATA_DIR / "_coord_cache.json"
        self.cache: dict = json.loads(self.cache_path.read_text(encoding="utf-8")) if self.cache_path.exists() else {}
        key = os.getenv("KAKAO_REST_API_KEY", "").strip()
        self.client = httpx.Client(headers={"Authorization": f"KakaoAK {key}"}, timeout=10.0) if key else None
        self.calls = 0

    def _search(self, query: str) -> list[dict]:
        if self.client is None:
            return []
        self.calls += 1
        time.sleep(0.04)
        r = self.client.get(KAKAO_URL, params={"query": query, "category_group_code": "SW8", "size": 15})
        r.raise_for_status()
        return r.json()["documents"]

    def find(self, line: str, name: str) -> dict | None:
        key = f"{line}|{name}"
        if self.cache.get(key) is not None:  # 못 찾은 역(null)은 다시 시도한다
            return self.cache[key]
        stem = SEARCH_STEM.get(name, f"{name}역")
        labels = self.rules["lines"][line]["kakao"]
        found = None
        for label in labels:
            for doc in self._search(f"{stem} {label}"):
                p = doc["place_name"]
                lat, lng = float(doc["y"]), float(doc["x"])
                inside = METRO_BBOX[0] <= lat <= METRO_BBOX[1] and METRO_BBOX[2] <= lng <= METRO_BBOX[3]
                if inside and p.startswith(stem) and any(l in p for l in labels):
                    found = {"lat": lat, "lng": lng, "place": p}
                    break
            if found:
                break
        self.cache[key] = found
        return found

    def save(self) -> None:
        self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False, indent=0), encoding="utf-8")


# ----------------------------------------------------------------------------- 조립
def fit_line(points: list[tuple[float, float]]) -> tuple[float, float, float]:
    """분 = a + b × km 최소제곱 적합. (a, b, 평균절대오차)"""
    n = len(points)
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    b = sum((x - mx) * (y - my) for x, y in points) / sum((x - mx) ** 2 for x, _ in points)
    a = my - b * mx
    mae = sum(abs(a + b * x - y) for x, y in points) / n
    return a, b, mae


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    rules = yaml.safe_load((DATA_DIR / "rules.yaml").read_text(encoding="utf-8"))
    official = read_official(rules)
    extra = read_extra()
    coords = Coords(rules)

    # 1) 노드와 좌표
    node_keys = {(l, a) for l, a, _, _ in official} | {(l, b) for l, _, b, _ in official}
    node_keys |= {(l, a) for l, a, _ in extra} | {(l, b) for l, _, b in extra}
    nodes: dict[tuple[str, str], dict] = {}
    missing: list[str] = []
    for line, name in sorted(node_keys):
        c = coords.find(line, name)
        if c is None:
            missing.append(f"{line} {name}")
        else:
            nodes[(line, name)] = c
    coords.save()
    print(f"노드 {len(node_keys)}개 중 좌표 확보 {len(nodes)}개 (카카오 호출 {coords.calls}건)")
    if missing:
        print(f"좌표를 찾지 못해 제외한 역 {len(missing)}개: {', '.join(missing)}")

    # 2) 간선: 공식(분 그대로) + 추정. 좌표 없는 역은 차수 2면 앞뒤를 이어 붙인다 (공식 분은 합산).
    edge_map: dict[tuple[str, str, str], dict] = {}
    for line, a, b, minutes in official:
        edge_map[(line, *sorted((a, b)))] = {"line": line, "a": a, "b": b, "minutes": minutes, "source": "official"}
    for line, a, b in extra:
        edge_map.setdefault((line, *sorted((a, b))), {"line": line, "a": a, "b": b, "minutes": None, "source": "estimated"})

    adjacency: dict[tuple[str, str], list[dict]] = {}
    for e in edge_map.values():
        adjacency.setdefault((e["line"], e["a"]), []).append(e)
        adjacency.setdefault((e["line"], e["b"]), []).append(e)
    for line, name in sorted(node_keys - set(nodes)):
        around = adjacency.get((line, name), [])
        if len(around) != 2:
            continue
        e1, e2 = around
        n1 = e1["b"] if e1["a"] == name else e1["a"]
        n2 = e2["b"] if e2["a"] == name else e2["a"]
        minutes = (e1["minutes"] + e2["minutes"]) if e1["minutes"] is not None and e2["minutes"] is not None else None
        for e in (e1, e2):
            edge_map.pop((line, *sorted((e["a"], e["b"]))), None)
        merged = {"line": line, "a": n1, "b": n2, "minutes": minutes,
                  "source": "official" if minutes is not None else "estimated"}
        edge_map[(line, *sorted((n1, n2)))] = merged
        adjacency[(line, n1)] = [x for x in adjacency[(line, n1)] if x not in (e1, e2)] + [merged]
        adjacency[(line, n2)] = [x for x in adjacency[(line, n2)] if x not in (e1, e2)] + [merged]

    cur = rules["estimate"]["route_curvature"]

    def km(line_a: str, a: str, line_b: str, b: str) -> float:
        pa, pb = nodes[(line_a, a)], nodes[(line_b, b)]
        return haversine_km((pa["lat"], pa["lng"]), (pb["lat"], pb["lng"])) * cur

    samples = [(km(e["line"], e["a"], e["line"], e["b"]), e["minutes"]) for e in edge_map.values()
               if e["source"] == "official" and (e["line"], e["a"]) in nodes and (e["line"], e["b"]) in nodes]
    a0, b0, mae = fit_line(samples)
    print(f"공식 구간 {len(samples)}개로 적합: 분 = {a0:.3f} + {b0:.3f} × km (평균절대오차 {mae:.2f}분)")

    edges = []
    for e in edge_map.values():
        if (e["line"], e["a"]) not in nodes or (e["line"], e["b"]) not in nodes:
            continue
        minutes = e["minutes"]
        if minutes is None:
            factor = rules["lines"][e["line"]]["factor"]
            minutes = max(rules["estimate"]["min_edge_minutes"], factor * (a0 + b0 * km(e["line"], e["a"], e["line"], e["b"])))
        edges.append({"a": f"{e['line']}|{e['a']}", "b": f"{e['line']}|{e['b']}",
                      "minutes": round(minutes, 2), "source": e["source"]})

    # 3) 환승: 같은 역명 + 가까움, 또는 별칭
    tr = rules["transfer"]
    by_name: dict[str, list[tuple[str, str]]] = {}
    for line, name in nodes:
        by_name.setdefault(name, []).append((line, name))
    transfers, seen = [], set()

    def add_transfer(n1: tuple[str, str], n2: tuple[str, str]) -> None:
        pair = tuple(sorted((f"{n1[0]}|{n1[1]}", f"{n2[0]}|{n2[1]}")))
        if pair in seen or n1[0] == n2[0]:
            return
        seen.add(pair)
        minutes = tr["overrides"].get(n1[1], tr["overrides"].get(n2[1], tr["default_minutes"]))
        transfers.append({"a": pair[0], "b": pair[1], "minutes": minutes})

    for name, group in by_name.items():
        for i, n1 in enumerate(group):
            for n2 in group[i + 1:]:
                p1, p2 = nodes[n1], nodes[n2]
                if haversine_km((p1["lat"], p1["lng"]), (p2["lat"], p2["lng"])) * 1000 <= tr["max_distance_m"]:
                    add_transfer(n1, n2)
    for (l1, s1), (l2, s2) in tr["aliases"]:
        if (l1, s1) in nodes and (l2, s2) in nodes:
            add_transfer((l1, s1), (l2, s2))

    stations = [{"id": f"{l}|{n}", "line": l, "name": n, "lat": round(c["lat"], 6), "lng": round(c["lng"], 6)}
                for (l, n), c in sorted(nodes.items())]
    network = {
        "meta": {"fit": {"a": round(a0, 4), "b": round(b0, 4), "mae_minutes": round(mae, 3), "samples": len(samples)},
                 "route_curvature": cur},
        "lines": {l: {"color": v["color"]} for l, v in rules["lines"].items()},
        "stations": stations, "edges": edges, "transfers": transfers,
    }
    (DATA_DIR / "network.json").write_text(json.dumps(network, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    # 4) 검증 리포트
    ids = {s["id"] for s in stations}
    parent = {i: i for i in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in edges:
        parent[find(e["a"])] = find(e["b"])
    for t in transfers:
        parent[find(t["a"])] = find(t["b"])
    comps: dict[str, int] = {}
    for i in ids:
        comps[find(i)] = comps.get(find(i), 0) + 1
    sizes = sorted(comps.values(), reverse=True)
    print(f"역 노드 {len(stations)}개, 간선 {len(edges)}개 (공식 {sum(e['source'] == 'official' for e in edges)} / 추정 {sum(e['source'] == 'estimated' for e in edges)}), 환승 {len(transfers)}개")
    print(f"연결 요소 크기: {sizes[:6]}{' ...' if len(sizes) > 6 else ''}")
    cand = json.loads((BACKEND_DIR / "data" / "stations.json").read_text(encoding="utf-8"))
    names = {s["name"] for s in stations}
    absent = [c["name"] for c in cand if c["name"].removesuffix("역") not in names]
    print(f"후보 역 {len(cand)}개 중 네트워크에 없는 역: {absent or '없음'}")


if __name__ == "__main__":
    main()
