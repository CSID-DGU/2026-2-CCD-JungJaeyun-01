import math

import pytest

from app.scoring.region import (
    RegionWeights,
    compute_metrics,
    min_max_normalize,
    score_regions,
    top_regions,
)

DEFAULT = RegionWeights(avg=0.4, max=0.3, std=0.3)


def ids(results):
    return [r.region_id for r in results]


class TestMetrics:
    def test_avg_max_std(self):
        m = compute_metrics([30, 40, 50])
        assert m.avg == pytest.approx(40)
        assert m.max == 50
        assert m.std == pytest.approx(math.sqrt(200 / 3))  # 모표준편차

    def test_single_value_has_zero_std(self):
        assert compute_metrics([25]).std == 0

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            compute_metrics([])


class TestNormalize:
    def test_min_is_zero_max_is_one(self):
        assert min_max_normalize([10, 20, 30]) == [0.0, 0.5, 1.0]

    def test_all_equal_gives_zeros(self):
        assert min_max_normalize([15, 15, 15]) == [0.0, 0.0, 0.0]

    def test_empty(self):
        assert min_max_normalize([]) == []


class TestWeights:
    def test_must_sum_to_one(self):
        with pytest.raises(ValueError):
            RegionWeights(avg=0.5, max=0.5, std=0.5)

    def test_negative_rejected(self):
        with pytest.raises(ValueError):
            RegionWeights(avg=1.2, max=-0.2, std=0.0)


class TestScoreRegions:
    def test_formula_and_range(self):
        data = {"a": [20, 20], "b": [40, 40], "c": [10, 70]}
        by_id = {r.region_id: r for r in score_regions(data, DEFAULT)}
        # a: 평균·최대·편차 모두 후보 중 최소 → 1.0
        assert by_id["a"].score == pytest.approx(1.0)
        # b: avg=40(→0.4 정규화), max=40, std=0
        n = by_id["b"].normalized
        assert by_id["b"].score == pytest.approx(1 - (0.4 * n.avg + 0.3 * n.max + 0.3 * n.std))
        assert all(0.0 <= r.score <= 1.0 for r in by_id.values())

    def test_sorted_descending(self):
        data = {"a": [20, 20], "b": [40, 40], "c": [10, 70]}
        scores = [r.score for r in score_regions(data, DEFAULT)]
        assert scores == sorted(scores, reverse=True)

    def test_keeps_participant_order(self):
        result = score_regions({"a": [10, 20, 30], "b": [15, 15, 15]}, DEFAULT)
        assert {r.region_id: r.minutes for r in result}["a"] == (10, 20, 30)

    def test_weight_change_flips_ranking(self):
        # x: 평균은 낮지만 한 명이 오래 걸림(불공정) / y: 평균은 조금 높지만 모두 비슷함
        data = {"x": [10, 10, 70], "y": [35, 35, 35]}
        efficiency = RegionWeights(avg=1.0, max=0.0, std=0.0)
        fairness = RegionWeights(avg=0.0, max=0.0, std=1.0)
        assert ids(score_regions(data, efficiency))[0] == "x"  # 평균 30 < 35
        assert ids(score_regions(data, fairness))[0] == "y"    # 편차 0
        assert ids(score_regions(data, DEFAULT))[0] == "y"

    def test_max_weight_penalizes_worst_case(self):
        data = {"x": [10, 10, 70], "y": [35, 35, 35]}
        only_max = RegionWeights(avg=0.0, max=1.0, std=0.0)
        assert ids(score_regions(data, only_max))[0] == "y"  # 최대 35 < 70

    def test_two_participants(self):
        data = {"a": [30, 30], "b": [10, 60], "c": [50, 50]}
        result = score_regions(data, DEFAULT)
        assert ids(result)[0] == "a"
        assert len(result) == 3

    def test_five_participants(self):
        data = {
            "a": [20, 25, 30, 35, 40],
            "b": [10, 10, 10, 10, 90],
            "c": [50, 50, 50, 50, 50],
        }
        result = score_regions(data, DEFAULT)
        assert ids(result)[0] == "a"
        assert all(len(r.minutes) == 5 for r in result)

    def test_all_travel_times_equal_everywhere(self):
        data = {"a": [30, 30, 30], "b": [30, 30, 30], "c": [30, 30, 30]}
        result = score_regions(data, DEFAULT)
        assert all(r.score == pytest.approx(1.0) for r in result)
        assert ids(result) == ["a", "b", "c"]  # 동점이면 id 순으로 고정

    def test_single_candidate(self):
        result = score_regions({"only": [10, 50]}, DEFAULT)
        assert len(result) == 1 and result[0].score == pytest.approx(1.0)

    def test_tie_broken_by_average_time(self):
        # 같은 점수를 만들기 위해 가중치를 std에만 주고 편차를 같게 한다
        data = {"slow": [50, 50], "fast": [10, 10]}
        only_std = RegionWeights(avg=0.0, max=0.0, std=1.0)
        assert ids(score_regions(data, only_std)) == ["fast", "slow"]

    def test_does_not_mutate_input(self):
        data = {"a": [10, 20], "b": [30, 40]}
        snapshot = {k: list(v) for k, v in data.items()}
        score_regions(data, DEFAULT)
        assert data == snapshot


class TestTopRegions:
    def test_returns_top_n(self):
        data = {f"r{i}": [10 + i * 5, 10 + i * 5] for i in range(6)}
        assert ids(top_regions(data, DEFAULT, 3)) == ["r0", "r1", "r2"]

    def test_fewer_candidates_than_n(self):
        assert len(top_regions({"a": [10, 20], "b": [20, 30]}, DEFAULT, 3)) == 2
