"""설문 페이지(docs/evaluation/survey/survey.html)의 응답을 analyze_survey.py가 읽는 CSV로 바꾼다.

  python scripts/survey_to_csv.py 응답.txt -o 응답.csv        # 응답 코드(MP1.…)를 한 줄에 하나씩 적은 파일
  python scripts/survey_to_csv.py dump_폴더 -o 응답.csv        # 설문 저장소를 JSON 파일로 내려받은 폴더 (문서 하나당 파일 하나)
  python scripts/survey_to_csv.py 구글시트.csv -o 응답.csv     # 구글폼 응답 시트를 CSV로 내려받은 파일 ([B1] 같은 문항 표시가 있는 표)

두 가지를 섞어도 된다(폴더 안의 .txt는 코드로, .json은 문서로 읽는다). 같은 respondent_id는 한 번만 센다.
응답 CSV는 개인 응답이므로 저장소에 올리지 않는다 (docs/evaluation/survey/.gitignore).
"""

import argparse
import base64
import csv
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

COLUMNS = ["respondent_id", "ahp_avg_vs_max", "ahp_avg_vs_std", "ahp_max_vs_std", "cs_avg", "cs_max", "cs_std",
           "ps_access", "ps_rating", "ps_popularity", "ps_purpose", "ps_age", "f2_extra_minutes", "e1", "age"]
REQUIRED = COLUMNS[:13]


def decode_code(code: str) -> dict:
    """'MP1.<base64url(JSON)>' → 응답 dict. 형식이 틀리면 ValueError."""
    code = code.strip()
    if not code.startswith("MP1."):
        raise ValueError("MP1.로 시작하지 않는 코드")
    body = code[4:]
    raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("응답 형식이 아님")
    return data


# ---------------------------------------------------------------------------- 구글폼 응답 시트
# 문항 제목 앞의 [B1] 같은 표시로 열을 찾는다. 문구는 docs/evaluation/survey/create_google_form.gs와 같아야 한다.
PAIRS = {  # 문항 → (왼쪽 기준 + 조사, 오른쪽 기준 + 조사, CSV 열)
    "B1": ("평균 이동시간이", "최대 이동시간이", "ahp_avg_vs_max"),
    "B2": ("평균 이동시간이", "이동시간 편차가", "ahp_avg_vs_std"),
    "B3": ("최대 이동시간이", "이동시간 편차가", "ahp_max_vs_std"),
}
LEVELS = (7.0, 3.0, 1.0, 1 / 3, 1 / 7)  # 왼쪽이 훨씬 / 조금 / 비슷 / 오른쪽이 조금 / 훨씬
SCALES = {"C1": "cs_avg", "C2": "cs_max", "C3": "cs_std", "D1": "ps_access", "D2": "ps_rating",
          "D3": "ps_popularity", "D4": "ps_purpose", "D5": "ps_age"}


def pair_choices(left: str, right: str) -> list[str]:
    return [f"{left} 훨씬 더 중요해요", f"{left} 조금 더 중요해요", "둘은 비슷하게 중요해요",
            f"{right} 조금 더 중요해요", f"{right} 훨씬 더 중요해요"]


def from_google_sheet(path: Path) -> tuple[list[dict], list[str]]:
    """구글폼 응답 시트(CSV) → 응답 dict 목록."""
    problems: list[str] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        col = {m.group(1): i for i, h in enumerate(header) if (m := re.match(r"\s*\[([A-Z]\d)\]", h))}
        rows = []
        for n, cells in enumerate(reader, 2):
            if not any(c.strip() for c in cells):
                continue
            get = lambda k: cells[col[k]].strip() if k in col and col[k] < len(cells) else ""
            row: dict = {"respondent_id": f"form-{n - 1}"}
            ok = True
            for qid, (left, right, key) in PAIRS.items():
                choices = pair_choices(left, right)
                if get(qid) in choices:
                    row[key] = LEVELS[choices.index(get(qid))]
                else:
                    ok = False
                    problems.append(f"{n}행 {qid}: 알 수 없는 선택지 '{get(qid)}'")
            for qid, key in SCALES.items():
                try:
                    row[key] = float(get(qid))
                except ValueError:
                    ok = False
                    problems.append(f"{n}행 {qid}: 숫자가 아님 '{get(qid)}'")
            e1 = get("E1")
            row["e1"] = "P" if e1.startswith("장소 P") else "Q" if e1.startswith("장소 Q") else ""
            digits = re.search(r"\d+", get("F2"))
            row["f2_extra_minutes"] = int(digits.group()) if digits else ""
            row["age"] = get("A1")
            if ok:
                rows.append(row)
    return rows, problems


def valid(row: dict) -> bool:
    """필수 값이 모두 있고 숫자 범위가 말이 되는 응답만 쓴다."""
    try:
        if any(row.get(k) in (None, "") for k in REQUIRED):
            return False
        ratios = [float(row[k]) for k in REQUIRED[1:4]]
        scores = [float(row[k]) for k in REQUIRED[4:12]]
        return all(1 / 9 <= r <= 9 for r in ratios) and all(0 <= s <= 100 for s in scores) \
            and sum(scores[:3]) > 0 and sum(scores[3:]) > 0
    except (TypeError, ValueError):
        return False


def load(source: Path) -> tuple[list[dict], list[str]]:
    rows, problems = [], []
    files = sorted(source.rglob("*")) if source.is_dir() else [source]
    for f in files:
        if f.suffix == ".csv" and "[B1]" in (f.read_text(encoding="utf-8-sig").splitlines() or [""])[0]:
            sheet_rows, sheet_problems = from_google_sheet(f)
            rows.extend(sheet_rows)
            problems.extend(sheet_problems)
            continue
        if f.suffix == ".json":
            try:
                rows.append(json.loads(f.read_text(encoding="utf-8")))
            except ValueError:
                problems.append(f"{f.name}: JSON을 읽지 못함")
        elif f.suffix in (".txt", ".csv", ""):
            for n, line in enumerate(f.read_text(encoding="utf-8-sig").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    rows.append(decode_code(line))
                except (ValueError, KeyError) as e:
                    problems.append(f"{f.name} {n}번째 줄: {e}")
    return rows, problems


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path)
    ap.add_argument("-o", "--output", type=Path, required=True)
    args = ap.parse_args()
    rows, problems = load(args.source)
    seen, kept = set(), []
    for r in rows:
        rid = str(r.get("respondent_id", ""))
        if not valid(r):
            problems.append(f"{rid or '(id 없음)'}: 필수 값이 없거나 범위를 벗어나 제외")
        elif rid in seen:
            problems.append(f"{rid}: 중복 응답이라 한 번만 사용")
        else:
            seen.add(rid)
            kept.append(r)
    with args.output.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        w.writeheader()
        w.writerows(kept)
    print(f"유효 응답 {len(kept)}건 → {args.output}")
    for p in problems:
        print("  제외/경고:", p)


if __name__ == "__main__":
    main()
