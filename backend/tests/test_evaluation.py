import math

import pytest

from app.evaluation import (
    ahp_weights,
    constant_sum_weights,
    geometric_mean_matrix,
    group_stats,
    hub_pick,
    kendall_tau,
    midpoint_pick,
    pipeline_pick,
    rank_with_weights,
    sensitivity,
    weight_grid,
)
from app.evaluation.survey import pairwise_matrix
from app.geo import Coord
from app.scoring.region import RegionWeights

DEFAULT = RegionWeights(avg=0.4, max=0.3, std=0.3)
# A: 평균은 낮지만 한 사람이 매우 멀다 / B: 평균은 조금 높아도 모두 비슷하다
TIMES = {"A": [10, 10, 50], "B": [28, 30, 32], "C": [40, 41, 45]}


def test_group_stats_and_gap():
    s = group_stats([10, 20, 30])
    assert (s.avg, s.max, s.min, s.gap) == (20, 30, 10, 20)
    assert s.std == pytest.approx(8.1649658)


class TestWeights:
    def test_grid_has_66_points_summing_to_one(self):
        grid = weight_grid(0.1)
        assert len(grid) == 66
        assert all(math.isclose(sum(g), 1.0) for g in grid)

    def test_average_only_prefers_the_unfair_region_but_default_prefers_the_fair_one(self):
        assert rank_with_weights(TIMES, RegionWeights(avg=1, max=0, std=0))[0] == "A"
        assert rank_with_weights(TIMES, DEFAULT)[0] == "B"

    def test_kendall_tau_bounds(self):
        assert kendall_tau(["a", "b", "c"], ["a", "b", "c"]) == 1.0
        assert kendall_tau(["a", "b", "c"], ["c", "b", "a"]) == -1.0

    def test_sensitivity_reports_how_much_the_top_changes(self):
        s = sensitivity(TIMES, DEFAULT)
        assert s["default_order"][0] == "B"
        assert 0 < s["top1_same_ratio"] < 1       # 가중치에 따라 1위가 바뀌는 사례
        assert set(s["winners"]) >= {"A", "B"}
        assert -1 <= s["mean_kendall_tau"] <= 1


class TestBaselines:
    def test_midpoint_is_the_nearest_station_to_the_centroid(self):
        stations = {"x": Coord(37.50, 127.00), "y": Coord(37.60, 127.10)}
        assert midpoint_pick(stations, [Coord(37.49, 126.99), Coord(37.51, 127.01)]) == "x"

    def test_hub_pick_chooses_the_best_average_among_hubs_only(self):
        assert hub_pick(TIMES, ["B", "C"]) == "B"
        with pytest.raises(ValueError):
            hub_pick(TIMES, ["Z"])

    def test_pipeline_pick_only_looks_inside_the_estimated_shortlist(self):
        estimates = {"A": [10, 10, 10], "B": [20, 20, 20], "C": [30, 30, 30]}
        # 실제로는 C가 가장 좋지만 추정 상위 2곳(A, B)에 없으면 고를 수 없다
        actual = {"A": [40, 40, 40], "B": [30, 30, 30], "C": [10, 10, 10]}
        assert pipeline_pick(estimates, actual, DEFAULT, shortlist=2) == "B"
        assert pipeline_pick(estimates, actual, DEFAULT, shortlist=3) == "C"


class TestSurveyMath:
    def test_ahp_recovers_known_weights_from_a_consistent_matrix(self):
        # 평균:최대:편차 = 4:2:1 이 되도록 만든 완전 일관 행렬
        m = pairwise_matrix(3, {(0, 1): 2, (0, 2): 4, (1, 2): 2})
        w, cr = ahp_weights(m)
        assert w == pytest.approx([4 / 7, 2 / 7, 1 / 7], abs=1e-6)
        assert cr == pytest.approx(0, abs=1e-6)

    def test_inconsistent_answers_have_a_high_consistency_ratio(self):
        m = pairwise_matrix(3, {(0, 1): 9, (1, 2): 9, (0, 2): 1 / 9})  # A>B>C 인데 C>A
        assert ahp_weights(m)[1] > 0.1

    def test_geometric_mean_of_two_respondents(self):
        a = pairwise_matrix(2, {(0, 1): 2})
        b = pairwise_matrix(2, {(0, 1): 8})
        assert geometric_mean_matrix([a, b])[0][1] == pytest.approx(4.0)

    def test_constant_sum_normalizes_each_respondent(self):
        w = constant_sum_weights([[50, 30, 20], [10, 10, 10], [0, 0, 0]])  # 합 0 응답은 버린다
        assert w == pytest.approx([(0.5 + 1 / 3) / 2, (0.3 + 1 / 3) / 2, (0.2 + 1 / 3) / 2])
        assert sum(w) == pytest.approx(1)
        with pytest.raises(ValueError):
            constant_sum_weights([[0, 0]])


# --------------------------------------------------------------------------- 공정성 vs 장소 만족도 규칙
from app.scoring.picks import FairnessLevels, PickRules, RegionForPick, choose_picks, fairness_level, place_quality  # noqa: E402

RULES = PickRules(tolerance_score=0.10, max_extra_minutes=8, quality_top_n=3)


class TestPicks:
    def test_fairness_levels(self):
        lv = FairnessLevels(high_gap_max=5, mid_gap_max=12)
        assert [fairness_level(g, lv) for g in (0, 5, 5.1, 12, 12.1)] == ["high", "high", "mid", "mid", "low"]

    def test_place_quality_is_the_mean_of_the_top_n(self):
        assert place_quality([0.9, 0.5, 0.8, 0.1], 3) == pytest.approx((0.9 + 0.8 + 0.5) / 3)
        assert place_quality([], 3) is None

    def test_same_region_when_the_fair_one_also_has_the_best_places(self):
        rs = [RegionForPick(1, 0.9, 30, 0.8), RegionForPick(2, 0.85, 31, 0.6)]
        assert choose_picks(rs, RULES) == (1, 1)

    def test_a_nearly_as_fair_region_with_better_places_becomes_the_satisfaction_pick(self):
        rs = [RegionForPick(1, 0.90, 30, 0.55), RegionForPick(2, 0.84, 34, 0.80), RegionForPick(3, 0.80, 33, 0.70)]
        assert choose_picks(rs, RULES) == (1, 2)

    def test_regions_outside_the_fairness_guardrails_are_never_chosen(self):
        too_unfair_score = [RegionForPick(1, 0.90, 30, 0.50), RegionForPick(2, 0.60, 31, 0.99)]
        too_far = [RegionForPick(1, 0.90, 30, 0.50), RegionForPick(2, 0.88, 45, 0.99)]
        assert choose_picks(too_unfair_score, RULES) == (1, 1)
        assert choose_picks(too_far, RULES) == (1, 1)

    def test_ties_go_to_the_fairer_region_and_missing_places_are_ignored(self):
        assert choose_picks([RegionForPick(1, 0.9, 30, 0.7), RegionForPick(2, 0.88, 30, 0.7)], RULES) == (1, 1)
        assert choose_picks([RegionForPick(1, 0.9, 30, None), RegionForPick(2, 0.88, 30, 0.7)], RULES) == (1, 2)
        assert choose_picks([RegionForPick(1, 0.9, 30, None)], RULES) == (1, 1)
