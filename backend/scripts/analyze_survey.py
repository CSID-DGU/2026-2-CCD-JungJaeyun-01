"""설문 응답 CSV로 가중치를 계산한다 (docs/evaluation/06-survey.md의 열 이름 사용).

  python scripts/analyze_survey.py 응답.csv [--bootstrap 2000]

출력: AHP(쌍대비교)와 100점 배분 두 방식의 평균·최대·편차 가중치, 일관성 비율(CR), 신뢰구간(부트스트랩),
      PlaceScore 5개 항목 가중치, F2(추가 허용 이동시간) 분포, 그리고 config에 반영할 값 제안.
응답이 15명 미만이면 '예비' 결과라고 표시한다. 이 스크립트는 응답이 없으면 아무 값도 만들어내지 않는다.
"""

import argparse
import csv
import random
import sys
from pathlib import Path
from statistics import fmean, median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from app.evaluation.survey import ahp_weights, constant_sum_weights, geometric_mean_matrix, pairwise_matrix  # noqa: E402

REGION_ITEMS = ("avg", "max", "std")
PLACE_ITEMS = ("access", "rating", "popularity", "purpose", "age")
MIN_RESPONSES = 15


def read_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if any((v or "").strip() for v in r.values())]


def num(row: dict, key: str) -> float | None:
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError):
        return None


def region_matrix(row: dict):
    a, b, c = (num(row, k) for k in ("ahp_avg_vs_max", "ahp_avg_vs_std", "ahp_max_vs_std"))
    if None in (a, b, c) or min(a, b, c) <= 0:
        return None
    return pairwise_matrix(3, {(0, 1): a, (0, 2): b, (1, 2): c})


def region_weights(rows: list[dict]) -> dict:
    matrices = [m for m in (region_matrix(r) for r in rows) if m]
    out: dict = {"ahp": None, "cs": None}
    if matrices:
        w, cr = ahp_weights(geometric_mean_matrix(matrices))
        crs = [ahp_weights(m)[1] for m in matrices]
        out["ahp"] = {"weights": w, "cr_group": cr, "n": len(matrices), "consistent_share": sum(c < 0.1 for c in crs) / len(crs)}
    cs_rows = [[num(r, f"cs_{k}") for k in REGION_ITEMS] for r in rows]
    cs_rows = [r for r in cs_rows if None not in r]
    if cs_rows:
        out["cs"] = {"weights": constant_sum_weights(cs_rows), "n": len(cs_rows)}
    return out


def bootstrap_ci(rows: list[dict], fn, n: int, seed: int = 7) -> list[tuple[float, float]]:
    """항목별 95% 부트스트랩 신뢰구간 (응답자를 복원추출)."""
    rng = random.Random(seed)
    draws = []
    for _ in range(n):
        sample = [rng.choice(rows) for _ in rows]
        w = fn(sample)
        if w:
            draws.append(w)
    if not draws:
        return []
    cols = list(zip(*draws))
    return [(sorted(c)[int(0.025 * len(c))], sorted(c)[min(len(c) - 1, int(0.975 * len(c)))]) for c in cols]


def ahp_fn(rows):
    ms = [m for m in (region_matrix(r) for r in rows) if m]
    return ahp_weights(geometric_mean_matrix(ms))[0] if ms else None


def cs_fn(rows, keys, prefix):
    data = [[num(r, f"{prefix}_{k}") for k in keys] for r in rows]
    data = [d for d in data if None not in d and sum(d) > 0]
    return constant_sum_weights(data) if data else None


def show(title: str, labels, weights, ci=None) -> None:
    print(f"\n{title}")
    for i, (lab, w) in enumerate(zip(labels, weights)):
        extra = f"  (95% 신뢰구간 {ci[i][0]:.2f}~{ci[i][1]:.2f})" if ci else ""
        print(f"  {lab:<10} {w:.3f}{extra}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", type=Path)
    ap.add_argument("--bootstrap", type=int, default=2000)
    args = ap.parse_args()
    rows = read_rows(args.csv)
    if not rows:
        sys.exit("응답이 없습니다. 값을 만들어내지 않습니다.")
    n = len(rows)
    print(f"응답 {n}명" + ("" if n >= MIN_RESPONSES else f"  ※ {MIN_RESPONSES}명 미만이라 '예비' 결과입니다. 가중치를 바꾸는 근거로 쓰지 마세요."))

    rw = region_weights(rows)
    labels = ["평균", "최대", "편차"]
    if rw["ahp"]:
        show(f"[이동시간] AHP 쌍대비교 (유효 {rw['ahp']['n']}명)", labels, rw["ahp"]["weights"],
             bootstrap_ci(rows, ahp_fn, args.bootstrap))
        print(f"  집단 일관성 비율 CR = {rw['ahp']['cr_group']:.3f} (0.1 미만이면 일관), 개인 CR < 0.1 비율 {rw['ahp']['consistent_share']:.0%}")
    if rw["cs"]:
        show(f"[이동시간] 100점 배분 (유효 {rw['cs']['n']}명)", labels, rw["cs"]["weights"],
             bootstrap_ci(rows, lambda s: cs_fn(s, REGION_ITEMS, "cs"), args.bootstrap))
    adopt = None
    if rw["ahp"] and rw["cs"]:
        diff = max(abs(a - b) for a, b in zip(rw["ahp"]["weights"], rw["cs"]["weights"]))
        ok_cr = rw["ahp"]["consistent_share"] > 0.5
        ok_diff = diff <= 0.1
        print(f"\n채택 조건 (05-evaluation-plan.md 6절): 개인 CR<0.1 과반 → {'충족' if ok_cr else '미충족'}, 두 방식 차이 {diff:.3f} ≤ 0.1 → {'충족' if ok_diff else '미충족'}")
        if ok_cr and ok_diff and n >= MIN_RESPONSES:
            adopt = [round((a + b) / 2, 2) for a, b in zip(rw["ahp"]["weights"], rw["cs"]["weights"])]
            adopt[0] = round(1 - adopt[1] - adopt[2], 2)  # 합이 정확히 1이 되도록
            print(f"\n제안 (config/region.yaml weights): avg {adopt[0]}, max {adopt[1]}, std {adopt[2]}")
        else:
            print("\n조건을 모두 충족하지 못해 가중치 변경을 제안하지 않습니다 (현재 값 유지).")

    place = cs_fn(rows, PLACE_ITEMS, "ps")
    if place:
        show("[장소] 100점 배분 평균", ["접근성", "평점", "리뷰 수", "목적 적합", "연령 적합"], place,
             bootstrap_ci(rows, lambda s: cs_fn(s, PLACE_ITEMS, "ps"), args.bootstrap))
    extra = [v for v in (num(r, "f2_extra_minutes") for r in rows) if v is not None]
    if extra:
        print(f"\n[충돌 규칙] F2 추가 허용 이동시간: 중앙값 {median(extra):.0f}분, 평균 {fmean(extra):.1f}분 → picks.max_extra_minutes 조정 근거 (현재 8분)")


if __name__ == "__main__":
    main()
