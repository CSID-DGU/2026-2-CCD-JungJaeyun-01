import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HEADER = "respondent_id,ahp_avg_vs_max,ahp_avg_vs_std,ahp_max_vs_std,cs_avg,cs_max,cs_std,ps_access,ps_rating,ps_popularity,ps_purpose,ps_age,f2_extra_minutes\n"


def run(tmp_path, body: str):
    f = tmp_path / "r.csv"
    f.write_text(HEADER + body, encoding="utf-8")
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "analyze_survey.py"), str(f), "--bootstrap", "50"],
                          capture_output=True, text=True, encoding="utf-8", cwd=ROOT)


def test_empty_responses_make_up_nothing(tmp_path):
    r = run(tmp_path, "")
    assert r.returncode != 0 and "응답이 없습니다" in (r.stderr + r.stdout)


def test_few_responses_are_flagged_as_preliminary_and_do_not_propose_weights(tmp_path):
    # pytest 안에서만 쓰는 검증용 가짜 응답 (실제 설문 데이터가 아니다)
    rows = "".join(f"t{i},2,4,2,50,30,20,25,25,15,20,15,10\n" for i in range(4))
    out = run(tmp_path, rows).stdout
    assert "예비" in out and "제안 (config/region.yaml" not in out
    assert "AHP 쌍대비교" in out and "100점 배분" in out


def test_enough_consistent_responses_propose_weights_that_sum_to_one(tmp_path):
    rows = "".join(f"t{i},2,4,2,57,29,14,25,25,15,20,15,10\n" for i in range(16))  # 4:2:1 ≈ 57:29:14
    out = run(tmp_path, rows).stdout
    line = next(l for l in out.splitlines() if l.startswith("제안"))
    nums = [float(x.split()[-1]) for x in line.split(":", 1)[1].split(",")]
    assert abs(sum(nums) - 1) < 1e-9 and nums[0] > nums[1] > nums[2]


# --------------------------------------------------------------------------- 응답 코드 → CSV
import base64  # noqa: E402
import json  # noqa: E402


def code_for(**overrides):
    # pytest 안에서만 쓰는 검증용 가짜 응답 (실제 설문 데이터가 아니다)
    row = {"v": 1, "respondent_id": "abc123", "ahp_avg_vs_max": 3, "ahp_avg_vs_std": 3, "ahp_max_vs_std": 1,
           "cs_avg": 50, "cs_max": 30, "cs_std": 20, "ps_access": 20, "ps_rating": 20, "ps_popularity": 20,
           "ps_purpose": 20, "ps_age": 20, "f2_extra_minutes": 10, "e1": "Q", "age": "20대"}
    row.update(overrides)
    raw = base64.urlsafe_b64encode(json.dumps(row, ensure_ascii=False).encode("utf-8")).decode().rstrip("=")
    return "MP1." + raw


def convert(tmp_path, lines):
    src, out = tmp_path / "codes.txt", tmp_path / "out.csv"
    src.write_text("\n".join(lines), encoding="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "survey_to_csv.py"), str(src), "-o", str(out)],
                       capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    return r, out


def test_codes_become_csv_rows_and_duplicates_and_garbage_are_dropped(tmp_path):
    r, out = convert(tmp_path, [code_for(), code_for(), code_for(respondent_id="zzz", cs_avg=0, cs_max=0, cs_std=0),
                                "MP1.not-base64!!", "hello"])
    assert "유효 응답 1건" in r.stdout
    lines = out.read_text(encoding="utf-8-sig").strip().splitlines()
    assert lines[0].startswith("respondent_id,ahp_avg_vs_max") and len(lines) == 2 and lines[1].startswith("abc123,3")


def test_converted_csv_feeds_the_analysis_script(tmp_path):
    r, out = convert(tmp_path, [code_for(respondent_id=f"t{i}") for i in range(4)])
    assert "유효 응답 4건" in r.stdout
    res = subprocess.run([sys.executable, str(ROOT / "scripts" / "analyze_survey.py"), str(out), "--bootstrap", "20"],
                         capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    assert "응답 4명" in res.stdout and "예비" in res.stdout


# --------------------------------------------------------------------------- 구글폼 응답 시트
import csv as _csv  # noqa: E402
import re  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
import survey_to_csv as conv  # noqa: E402

GS = ROOT.parent / "docs" / "evaluation" / "survey" / "create_google_form.gs"
HEAD = ["타임스탬프", "[B1] a", "[B2] b", "[B3] c", "[C1] x", "[C2] x", "[C3] x", "[D1] x", "[D2] x", "[D3] x", "[D4] x", "[D5] x",
        "[E1] x", "[F2] x", "[A1] 연령대", "[Z1] 의견"]


def sheet_row(b1, b2, b3, scales=(8, 5, 3, 7, 9, 4, 6, 3), e1="장소 Q (조금 길어도 모두 비슷해요)", f2="10분"):
    return ["2026/11/05 오후 1:00:00", b1, b2, b3, *map(str, scales), e1, f2, "20대", ""]


def write_sheet(tmp_path, rows):
    path = tmp_path / "sheet.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = _csv.writer(f)
        w.writerow(HEAD)
        w.writerows(rows)
    return path


def test_google_sheet_options_become_the_right_ratios(tmp_path):
    ch = {k: conv.pair_choices(l, r) for k, (l, r, _) in conv.PAIRS.items()}
    path = write_sheet(tmp_path, [sheet_row(ch["B1"][0], ch["B2"][1], ch["B3"][4]), sheet_row(ch["B1"][2], ch["B2"][3], ch["B3"][2])])
    rows, problems = conv.from_google_sheet(path)
    assert problems == [] and len(rows) == 2
    assert (rows[0]["ahp_avg_vs_max"], rows[0]["ahp_avg_vs_std"], rows[0]["ahp_max_vs_std"]) == (7.0, 3.0, 1 / 7)
    assert (rows[1]["ahp_avg_vs_max"], rows[1]["ahp_avg_vs_std"], rows[1]["ahp_max_vs_std"]) == (1.0, 1 / 3, 1.0)
    assert rows[0]["cs_avg"] == 8 and rows[0]["ps_age"] == 3 and rows[0]["f2_extra_minutes"] == 10 and rows[0]["e1"] == "Q"


def test_unknown_option_text_is_reported_not_guessed(tmp_path):
    ch = {k: conv.pair_choices(l, r) for k, (l, r, _) in conv.PAIRS.items()}
    path = write_sheet(tmp_path, [sheet_row("아무 말", ch["B2"][1], ch["B3"][4])])
    rows, problems = conv.from_google_sheet(path)
    assert rows == [] and any("B1" in p for p in problems)


def test_sheet_csv_goes_through_the_cli(tmp_path):
    ch = {k: conv.pair_choices(l, r) for k, (l, r, _) in conv.PAIRS.items()}
    path = write_sheet(tmp_path, [sheet_row(ch["B1"][1], ch["B2"][1], ch["B3"][1])] * 2)
    out = tmp_path / "o.csv"
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "survey_to_csv.py"), str(path), "-o", str(out)],
                       capture_output=True, text=True, encoding="utf-8", cwd=ROOT)
    assert "유효 응답 2건" in r.stdout and out.read_text(encoding="utf-8-sig").count("form-") == 2


def test_the_apps_script_wording_matches_the_converter():
    """create_google_form.gs의 문구가 바뀌면 변환기가 응답을 못 읽으므로 두 파일이 같은지 검사한다."""
    gs = GS.read_text(encoding="utf-8")
    calls = re.findall(r"addPair\(form, '(B\d)', '([^']+)', '([^']+)', '([^']+)', '([^']+)'\)", gs)
    assert len(calls) == 3
    for qid, a, ja, b, jb in calls:
        assert conv.PAIRS[qid][:2] == (a + ja, b + jb)
    for phrase in ("훨씬 더 중요해요", "조금 더 중요해요", "둘은 비슷하게 중요해요", "장소 P (", "장소 Q ("):
        assert phrase in gs
    for qid in conv.SCALES:
        assert f"'{qid}'" in gs
    assert all(f"[{q}]" in gs for q in ("E1", "F2", "A1"))
