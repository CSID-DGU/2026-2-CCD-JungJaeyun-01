"""MeetPick 평가 실험.

  python scripts/evaluate.py collect            # 실제 호출 없이 호출 계획(횟수·칸 수)만 출력 (dry-run)
  python scripts/evaluate.py collect --run      # Google Routes로 이동시간을 수집해 docs/evaluation/data/에 저장
  python scripts/evaluate.py analyze            # 저장된 데이터로 비교·민감도 표를 만들어 docs/evaluation/ 에 쓴다 (API 호출 0)

수집은 시나리오마다 한 번만 하면 되고, 이후 분석은 몇 번이든 무료로 다시 돌릴 수 있다.
"""

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from app.config import load_region_config  # noqa: E402
from app.evaluation import (  # noqa: E402
    group_stats, hub_pick, midpoint_pick, pipeline_pick, rank_with_weights, sensitivity, weight_grid,
)
from app.geo import Coord, centroid  # noqa: E402
from app.meeting import default_meeting_time  # noqa: E402
from app.scoring.region import RegionWeights, score_regions  # noqa: E402
from app.stations import Station, load_stations, nearest_stations  # noqa: E402

_STATIONS = {s.id: s for s in load_stations()}
CONFIG = yaml.safe_load((ROOT / "backend" / "config" / "evaluation.yaml").read_text(encoding="utf-8"))
OUT = ROOT / "docs" / "evaluation"
DATA = OUT / "data"


def station_by_name() -> dict[str, Station]:
    return {s.name: s for s in load_stations()}


def scenario_pool(origins: list[Station], by_name: dict[str, Station]) -> list[Station]:
    """후보 풀: 출발지 중심에서 가까운 K곳 + 대표 허브 (중복 제거, 순서 고정)."""
    center = centroid([o.coord for o in origins])
    pool = nearest_stations(load_stations(), center, CONFIG["candidate_k"])
    seen = {s.id for s in pool}
    for name in CONFIG["hubs"]:
        if by_name[name].id not in seen:
            pool.append(by_name[name])
            seen.add(by_name[name].id)
    return pool


def batches(pool: list[Station], n_origins: int) -> list[list[Station]]:
    size = max(1, CONFIG["max_elements_per_call"] // n_origins)
    return [pool[i:i + size] for i in range(0, len(pool), size)]


# ----------------------------------------------------------------------------- collect
def collect(run: bool) -> None:
    by_name = station_by_name()
    meeting = default_meeting_time()
    total_calls = total_elements = 0
    plans = []
    for sc in CONFIG["scenarios"]:
        origins = [by_name[n] for n in sc["origins"]]
        pool = scenario_pool(origins, by_name)
        parts = batches(pool, len(origins))
        plans.append((sc, origins, pool, parts))
        total_calls += len(parts)
        total_elements += len(pool) * len(origins)
        print(f"- {sc['id']}: 출발지 {len(origins)}명 × 후보 {len(pool)}곳 = {len(pool) * len(origins)}칸, 호출 {len(parts)}회")
    print(f"\n합계: Google Routes 행렬 호출 {total_calls}회 / {total_elements}칸 (약속 시간 {meeting:%Y-%m-%d %H:%M} 도착 기준)")
    if not run:
        print("실제 호출은 하지 않았습니다. 실행하려면 --run 을 붙이세요.")
        return

    from app.services import get_route_provider
    provider = get_route_provider()
    DATA.mkdir(parents=True, exist_ok=True)
    for sc, origins, pool, parts in plans:
        minutes: dict[str, list[float | None]] = {}
        calls = hits = 0
        error = None
        for part in parts:
            m = provider.matrix([o.coord for o in origins], part, meeting)
            calls += m.api_calls
            hits += m.cache_hits
            error = error or m.error
            for j, st in enumerate(part):
                minutes[st.id] = [m.minutes[i][j] for i in range(len(origins))]
        for st in pool:  # 출발지 역 자신으로 가는 칸은 이동이 필요 없다
            for i, o in enumerate(origins):
                if o.id == st.id:
                    minutes[st.id][i] = 0.0
        missing = sum(1 for v in minutes.values() for x in v if x is None)
        payload = {
            "scenario": sc["id"], "title": sc["title"], "meetingTime": meeting.isoformat(timespec="minutes"),
            "collectedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "apiCalls": calls, "cacheHits": hits,
            "origins": [{"name": o.name, "id": o.id, "lat": o.coord.lat, "lng": o.coord.lng} for o in origins],
            "stations": {st.id: {"name": st.name, "lat": st.coord.lat, "lng": st.coord.lng} for st in pool},
            "minutes": minutes, "missingCells": missing, "error": error,
        }
        (DATA / f"{sc['id']}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"저장: {sc['id']} | 실제 호출 {calls}회, 캐시 {hits}칸, 비어 있는 칸 {missing}" + (f" | 오류: {error}" if error else ""))


# ----------------------------------------------------------------------------- analyze
def load_scenarios() -> list[dict]:
    out = []
    for sc in CONFIG["scenarios"]:
        path = DATA / f"{sc['id']}.json"
        if path.exists():
            out.append(json.loads(path.read_text(encoding="utf-8")))
    return out


def complete_times(d: dict) -> dict[str, list[float]]:
    """비어 있는 칸이 있는 후보는 비교에서 뺀다."""
    return {sid: v for sid, v in d["minutes"].items() if all(x is not None for x in v)}


def fmt(x: float) -> str:
    return f"{x:.1f}"


def analyze() -> None:
    from app.services import get_estimator
    estimator = get_estimator()
    cfg = load_region_config()
    default_w = cfg.weights
    by_name = station_by_name()
    hub_ids = [by_name[n].id for n in CONFIG["hubs"]]
    scenarios = load_scenarios()
    if not scenarios:
        sys.exit("저장된 데이터가 없습니다. 먼저 collect --run 을 실행하세요.")

    compare_rows, sens_blocks, per_scenario, short_check = [], [], [], []
    for d in scenarios:
        times = complete_times(d)
        name = {sid: s["name"] for sid, s in d["stations"].items()}
        origins = [Coord(o["lat"], o["lng"]) for o in d["origins"]]
        coords = {sid: Coord(d["stations"][sid]["lat"], d["stations"][sid]["lng"]) for sid in times}
        pool_stations = [_STATIONS[sid] for sid in times]
        per_origin = [estimator.estimate(o, pool_stations) for o in origins]  # 1단계 추정 (API 호출 0)
        estimates = {sid: [per_origin[i][sid] for i in range(len(origins))] for sid in times}
        picks = {
            "MeetPick (실제 흐름)": pipeline_pick(estimates, times, default_w, cfg.shortlist_size),
            "MeetPick (후보 전체 최적)": rank_with_weights(times, default_w)[0],
            "평균 이동시간만": rank_with_weights(times, RegionWeights(avg=1.0, max=0.0, std=0.0))[0],
            "지리적 중간점": midpoint_pick(coords, origins),
            "대표 번화가 중 최선": hub_pick(times, hub_ids),
        }
        best = rank_with_weights(times, default_w)[0]
        short_check.append((d, name, times, {k: pipeline_pick(estimates, times, default_w, k) for k in SHORTLIST_SIZES}, best))
        ranked = {r.region_id: i for i, r in enumerate(score_regions(times, default_w), 1)}
        for label, sid in picks.items():
            s = group_stats(times[sid])
            compare_rows.append({"scenario": d["scenario"], "n": len(d["origins"]), "method": label, "station": name[sid],
                                 "avg": s.avg, "max": s.max, "gap": s.gap, "std": s.std, "rank": ranked[sid],
                                 "pool": len(times), "is_hub": sid in hub_ids})
        sens = sensitivity(times, default_w)
        sens_blocks.append((d, name, times, sens))
        per_scenario.append((d, name, times, picks))

    write_comparison(compare_rows, per_scenario, short_check)
    write_sensitivity(sens_blocks, default_w)
    write_example(per_scenario, default_w)
    (OUT / "data").mkdir(parents=True, exist_ok=True)
    (OUT / "data" / "comparison.csv").write_text(
        "scenario,people,method,station,avg_min,max_min,gap_min,std_min,regionscore_rank,pool,is_famous_hub\n" +
        "\n".join(f"{r['scenario']},{r['n']},{r['method']},{r['station']},{fmt(r['avg'])},{fmt(r['max'])},{fmt(r['gap'])},{fmt(r['std'])},{r['rank']},{r['pool']},{int(r['is_hub'])}" for r in compare_rows),
        encoding="utf-8-sig")
    print("생성: docs/evaluation/02-baseline-comparison.md, 03-sensitivity.md, 04-3x3-example.md, data/comparison.csv")


SHORTLIST_SIZES = (4, 8, 12, 16)


def write_comparison(rows: list[dict], per_scenario: list, short_check: list) -> None:
    methods = ["MeetPick (실제 흐름)", "MeetPick (후보 전체 최적)", "평균 이동시간만", "지리적 중간점", "대표 번화가 중 최선"]
    lines = ["# 비교 실험: 같은 모임 조건을 기존 방식과 MeetPick에 적용", "",
             "각 시나리오의 실제 대중교통 이동시간(Google Routes, 약속 시간 도착 기준)을 한 번 수집해 모든 방식에 똑같이 적용했다.",
             "`최대`는 가장 오래 걸리는 사람의 시간, `차이`는 가장 오래 걸리는 사람과 가장 적게 걸리는 사람의 시간 차이(불공평 정도)다.", "",
             "비교 방식 설명:",
             "- **지리적 중간점**: 출발지 좌표의 평균점에서 가장 가까운 역 (지도 앱의 '중간 지점 찾기'와 같은 발상)",
             "- **대표 번화가 중 최선**: 강남·홍대입구·서울·신촌·건대입구·잠실·사당 중 평균 이동시간이 가장 짧은 곳 (사람들이 흔히 떠올리는 장소를 고르되, 이동시간은 안다고 가정한 유리한 비교)",
             "- **평균 이동시간만**: RegionScore에서 평균만 보는 추천 (가중치 1/0/0)",
             "- **MeetPick (실제 흐름)**: 지하철 그래프 추정으로 8곳을 뽑고 그 안에서 실제 시간으로 다시 점수를 매긴 서비스의 실제 결과",
             "- **MeetPick (후보 전체 최적)**: 후보 풀 전체에 RegionScore를 적용한 최선 (실제 흐름이 후보를 놓치는지 확인용)", ""]
    for d, name, times, picks in per_scenario:
        lines += [f"## {d['title']}", f"`{d['scenario']}` · 후보 풀 {len(times)}곳 · 약속 {d['meetingTime']}", "",
                  "| 방식 | 추천 지역 | 평균 | 최대 | 차이 | 편차 | RegionScore 순위 | 대표 번화가? |", "|---|---|---|---|---|---|---|---|"]
        for m in methods:
            r = next(x for x in rows if x["scenario"] == d["scenario"] and x["method"] == m)
            lines.append(f"| {m} | {r['station']} | {fmt(r['avg'])}분 | {fmt(r['max'])}분 | {fmt(r['gap'])}분 | {fmt(r['std'])} | {r['rank']}/{r['pool']} | {'예' if r['is_hub'] else '아니오'} |")
        lines.append("")
    # 요약
    lines += ["## 전체 요약", "", "| 방식 | 평균(분) | 최대(분) | 차이(분) | 대표 번화가를 고른 횟수 |", "|---|---|---|---|---|"]
    for m in methods:
        rs = [r for r in rows if r["method"] == m]
        n = len(rs)
        lines.append(f"| {m} | {fmt(sum(r['avg'] for r in rs) / n)} | {fmt(sum(r['max'] for r in rs) / n)} | {fmt(sum(r['gap'] for r in rs) / n)} | {sum(r['is_hub'] for r in rs)}/{n} |")
    mp = {r["scenario"]: r for r in rows if r["method"] == "MeetPick (실제 흐름)"}
    hub = {r["scenario"]: r for r in rows if r["method"] == "대표 번화가 중 최선"}
    mid = {r["scenario"]: r for r in rows if r["method"] == "지리적 중간점"}
    avg_only = {r["scenario"]: r for r in rows if r["method"] == "평균 이동시간만"}
    same_hub = sum(mp[s]["station"] == hub[s]["station"] for s in mp)
    lines += ["", "### 해석 (자동 계산)", "",
              f"- 시나리오 {len(mp)}개 중 MeetPick이 '대표 번화가 중 최선'과 **같은 지역**을 고른 경우: {same_hub}개, 다른 지역을 고른 경우: {len(mp) - same_hub}개.",
              f"- 최대 이동시간(가장 힘든 사람) 평균: MeetPick {fmt(sum(mp[s]['max'] for s in mp) / len(mp))}분 / 대표 번화가 {fmt(sum(hub[s]['max'] for s in hub) / len(hub))}분 / 중간점 {fmt(sum(mid[s]['max'] for s in mid) / len(mid))}분 / 평균만 {fmt(sum(avg_only[s]['max'] for s in avg_only) / len(avg_only))}분.",
              f"- 시간 차이(불공평 정도) 평균: MeetPick {fmt(sum(mp[s]['gap'] for s in mp) / len(mp))}분 / 대표 번화가 {fmt(sum(hub[s]['gap'] for s in hub) / len(hub))}분 / 중간점 {fmt(sum(mid[s]['gap'] for s in mid) / len(mid))}분 / 평균만 {fmt(sum(avg_only[s]['gap'] for s in avg_only) / len(avg_only))}분.", "",
              "> 시나리오 5개, 후보 풀 약 20~27곳의 작은 실험이다. 일반화하려면 시나리오를 더 늘려야 하고, 이 표는 '이동시간' 기준 비교일 뿐 사용자 만족도는 아직 측정하지 않았다 (05-evaluation-plan.md 참고).", ""]
    lines += ["## 점검: 1단계 후보 수(shortlist)가 부족하면 최선을 놓친다", "",
              "서비스는 지하철 그래프 추정(버스 없음)으로 후보를 shortlist곳만 뽑고 그 안에서 실제 시간으로 재점수한다. "
              "shortlist 크기에 따라 '후보 전체 최적'과 같은 지역을 고르는지 확인했다 (같으면 ✔, 다르면 선택한 지역과 평균·최대 차이).", "",
              "| 시나리오 | " + " | ".join(f"{k}곳" for k in SHORTLIST_SIZES) + " |", "|---|" + "---|" * len(SHORTLIST_SIZES)]
    hit = {k: 0 for k in SHORTLIST_SIZES}
    for d, name, times, picks_by_k, best in short_check:
        cells = []
        for k in SHORTLIST_SIZES:
            sid = picks_by_k[k]
            if sid == best:
                hit[k] += 1
                cells.append("✔")
            else:
                a, b = group_stats(times[sid]), group_stats(times[best])
                cells.append(f"{name[sid]} (평균 {a.avg - b.avg:+.1f}분, 최대 {a.max - b.max:+.1f}분)")
        lines.append(f"| {d['title']} | " + " | ".join(cells) + " |")
    lines += ["| **최적과 같은 비율** | " + " | ".join(f"{hit[k]}/{len(short_check)}" for k in SHORTLIST_SIZES) + " |", "",
              "> 현재 서비스 설정은 shortlist 8곳이다 (config/region.yaml). 경로 행렬은 후보가 늘어도 호출이 1회라, shortlist를 키우는 비용은 호출 횟수가 아니라 요청 칸 수(출발지 수 × 후보 수)뿐이다.", ""]
    (OUT / "02-baseline-comparison.md").write_text("\n".join(lines), encoding="utf-8")


def write_sensitivity(blocks: list, default_w: RegionWeights) -> None:
    lines = ["# 가중치 민감도: 가중치를 바꾸면 추천이 얼마나 달라지는가", "",
             f"기본 가중치는 평균 {default_w.avg} / 최대 {default_w.max} / 편차 {default_w.std} 이다 (현재는 설계자가 정한 잠정값, 설문으로 조정 예정).",
             "합이 1인 모든 조합(0.1 간격 66가지)으로 같은 데이터를 다시 점수화해 순위가 얼마나 바뀌는지 확인했다.", "",
             "## 요약", "", "| 시나리오 | 1위가 기본과 같은 비율 | 상위 3곳이 같은 비율 | 평균 켄들 타우 | 1위가 된 적 있는 지역 수 |", "|---|---|---|---|---|"]
    for d, name, times, s in blocks:
        lines.append(f"| {d['title']} | {s['top1_same_ratio']:.0%} | {s['topk_same_ratio']:.0%} | {s['mean_kendall_tau']:.2f} | {len(s['winners'])} |")
    lines += ["", "켄들 타우는 두 순위가 얼마나 같은 순서인지(1 = 같음, 0 = 무관, -1 = 정반대)를 뜻한다.", ""]
    presets = [("기본", default_w), ("평균만", RegionWeights(1.0, 0.0, 0.0)), ("최대만", RegionWeights(0.0, 1.0, 0.0)),
               ("편차만", RegionWeights(0.0, 0.0, 1.0)), ("균등", RegionWeights(1 / 3, 1 / 3, 1 / 3)), ("평균 중시", RegionWeights(0.6, 0.2, 0.2)),
               ("공정성 중시", RegionWeights(0.2, 0.4, 0.4))]
    for d, name, times, s in blocks:
        lines += [f"## {d['title']}", "", "대표 가중치별 1위 지역:", "", "| 가중치(평균/최대/편차) | 1위 | 2위 | 3위 | 기본 1위의 순위 |", "|---|---|---|---|---|"]
        base_top = s["default_order"][0]
        for label, w in presets:
            order = rank_with_weights(times, w)
            lines.append(f"| {label} ({w.avg:.2f}/{w.max:.2f}/{w.std:.2f}) | {name[order[0]]} | {name[order[1]]} | {name[order[2]]} | {order.index(base_top) + 1}위 |")
        win = ", ".join(f"{name[k]} {v}/{s['grid_size']}" for k, v in list(s["winners"].items())[:5])
        lines += ["", f"66가지 가중치에서 1위가 된 지역과 횟수: {win}", ""]
    (OUT / "03-sensitivity.md").write_text("\n".join(lines), encoding="utf-8")


def write_example(per_scenario: list, default_w: RegionWeights) -> None:
    sid_example = CONFIG["example_scenario"]
    d, name, times, picks = next(x for x in per_scenario if x[0]["scenario"] == sid_example)
    scores = score_regions(times, default_w)[:3]
    people = [o["name"] for o in d["origins"]]
    lines = ["# 출발지 3 × 후보 3 실제 이동시간 계산 예시", "",
             f"{d['title']} · 약속 {d['meetingTime']} 도착 기준 · Google Routes 실제 대중교통 시간", "",
             f"후보 풀 {len(times)}곳 전체에 대해 RegionScore를 계산하고 상위 3곳만 표로 보인다. (아래 정규화는 풀 {len(times)}곳 사이의 최솟값·최댓값 기준)", "",
             "## 1. 실제 이동시간 (분)", "", "| 후보 지역 | " + " | ".join(people) + " |", "|---|" + "---|" * len(people)]
    for r in scores:
        lines.append(f"| {name[r.region_id]} | " + " | ".join(fmt(m) for m in r.minutes) + " |")
    lines += ["", "## 2. 지표 계산", "", "| 후보 지역 | 평균 | 최대 | 편차 |", "|---|---|---|---|"]
    for r in scores:
        lines.append(f"| {name[r.region_id]} | {fmt(r.metrics.avg)} | {fmt(r.metrics.max)} | {fmt(r.metrics.std)} |")
    allm = [group_stats(v) for v in times.values()]
    lines += ["", "## 3. 정규화 (min-max, 0 = 가장 좋음 / 1 = 가장 나쁨)", "",
              f"풀 전체의 범위: 평균 {fmt(min(s.avg for s in allm))}~{fmt(max(s.avg for s in allm))}분, 최대 {fmt(min(s.max for s in allm))}~{fmt(max(s.max for s in allm))}분, 편차 {fmt(min(s.std for s in allm))}~{fmt(max(s.std for s in allm))}. "
              "세 지표는 단위는 같은 '분'이어도 범위가 달라(평균은 수십 분, 편차는 몇 분) 그대로 더하면 범위가 큰 지표가 점수를 지배한다. 그래서 각 지표를 0~1로 맞춘 뒤 가중합한다.", "",
              "| 후보 지역 | 평균 | 최대 | 편차 | RegionScore = 1 − (" + f"{default_w.avg}×평균 + {default_w.max}×최대 + {default_w.std}×편차" + ") |", "|---|---|---|---|---|"]
    for r in scores:
        n = r.normalized
        lines.append(f"| {name[r.region_id]} | {n.avg:.3f} | {n.max:.3f} | {n.std:.3f} | {r.score:.3f} |")
    lines += ["", "## 4. 다른 방식이면?", "", "| 방식 | 추천 지역 | " + " | ".join(people) + " |", "|---|---|" + "---|" * len(people)]
    for label, sid in picks.items():
        lines.append(f"| {label} | {name[sid]} | " + " | ".join(fmt(m) for m in times[sid]) + " |")
    lines.append("")
    (OUT / "04-3x3-example.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["collect", "analyze"])
    ap.add_argument("--run", action="store_true", help="collect에서 실제로 Google을 호출한다")
    args = ap.parse_args()
    collect(args.run) if args.command == "collect" else analyze()
