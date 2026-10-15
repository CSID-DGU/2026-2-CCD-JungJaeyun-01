import math

import pytest

from app.scoring.place import (
    AgeGroupPreference,
    PlaceFeatures,
    PlaceScoringParams,
    PlaceWeights,
    age_fit,
    bayesian_rating,
    keyword_fit,
    reason_line,
    rating_score,
    renormalize_weights,
    score_place,
)

WEIGHTS = PlaceWeights(accessibility=0.25, rating=0.25, popularity=0.15, purpose=0.20, age=0.15)
PARAMS = PlaceScoringParams(radius_m=500, prior_mean=3.9, prior_weight=30, rating_floor=3.0,
                            popularity_cap=1000, walk_m_per_min=67)


def features(**kw):
    base = dict(distance_m=100, purpose_fit=0.8, age_fit=0.7, rating=4.5, review_count=300)
    return PlaceFeatures(**{**base, **kw})


class TestWeights:
    def test_must_sum_to_one(self):
        with pytest.raises(ValueError):
            PlaceWeights(accessibility=0.3, rating=0.3, popularity=0.3, purpose=0.3, age=0.3)


class TestNoRating:
    def test_missing_rating_uses_the_prior_and_zero_reviews(self):
        result = score_place(features(rating=None, review_count=None), WEIGHTS, PARAMS)
        assert result.rating_used is False
        assert result.components["rating"] == pytest.approx(rating_score(PARAMS.prior_mean, 0, PARAMS))
        assert result.components["popularity"] == 0.0
        assert set(result.weights_used) == set(WEIGHTS.as_dict())  # 항목을 빼지 않는다

    def test_weights_are_not_renormalized(self):
        result = score_place(features(rating=None, review_count=None), WEIGHTS, PARAMS)
        assert result.weights_used == WEIGHTS.as_dict()

    def test_unrated_place_never_outranks_an_equal_place_with_a_good_rating(self):
        base = dict(distance_m=200, purpose_fit=0.8, age_fit=0.5)
        unrated = score_place(features(rating=None, review_count=None, **base), WEIGHTS, PARAMS).score
        rated = score_place(features(rating=4.3, review_count=120, **base), WEIGHTS, PARAMS).score
        assert unrated < rated

    def test_score_is_weighted_sum_with_prior_filled_in(self):
        f = features(distance_m=250, purpose_fit=0.6, age_fit=0.3, rating=None, review_count=None)
        result = score_place(f, WEIGHTS, PARAMS)
        expected = (0.25 * 0.5 + 0.25 * rating_score(PARAMS.prior_mean, 0, PARAMS) + 0.15 * 0.0 + 0.20 * 0.6 + 0.15 * 0.3)
        assert result.score == pytest.approx(expected)

    def test_rating_without_review_count_counts_as_missing(self):
        assert score_place(features(review_count=None), WEIGHTS, PARAMS).rating_used is False


class TestRenormalize:
    def test_sums_to_one(self):
        out = renormalize_weights(WEIGHTS.as_dict(), ["accessibility", "age"])
        assert sum(out.values()) == pytest.approx(1.0)
        assert set(out) == {"accessibility", "age"}

    def test_all_remaining_weights_zero_splits_evenly(self):
        out = renormalize_weights({"a": 0.0, "b": 0.0, "c": 1.0}, ["a", "b"])
        assert out == {"a": 0.5, "b": 0.5}

    def test_no_components_raises(self):
        with pytest.raises(ValueError):
            renormalize_weights(WEIGHTS.as_dict(), [])


class TestFewReviews:
    def test_bayesian_pulls_small_samples_toward_prior(self):
        assert bayesian_rating(5.0, 1, prior_mean=3.9, prior_weight=30) == pytest.approx((5.0 + 30 * 3.9) / 31)
        assert bayesian_rating(5.0, 1, 3.9, 30) < 4.0

    def test_many_reviews_converge_to_actual_rating(self):
        assert bayesian_rating(4.6, 100_000, 3.9, 30) == pytest.approx(4.6, abs=0.001)

    def test_five_stars_from_two_reviews_loses_to_solid_four_six(self):
        few = score_place(features(rating=5.0, review_count=2), WEIGHTS, PARAMS)
        many = score_place(features(rating=4.6, review_count=500), WEIGHTS, PARAMS)
        assert few.components["rating"] < many.components["rating"]
        assert few.components["popularity"] < many.components["popularity"]
        assert few.score < many.score

    def test_zero_reviews_with_rating_does_not_divide_by_zero(self):
        result = score_place(features(rating=4.0, review_count=0), WEIGHTS, PARAMS)
        assert result.components["popularity"] == 0.0
        assert 0.0 <= result.score <= 1.0

    def test_popularity_is_log_scaled_and_capped(self):
        low = score_place(features(review_count=10), WEIGHTS, PARAMS).components["popularity"]
        mid = score_place(features(review_count=100), WEIGHTS, PARAMS).components["popularity"]
        capped = score_place(features(review_count=50_000), WEIGHTS, PARAMS).components["popularity"]
        assert low < mid < capped == 1.0
        assert mid == pytest.approx(math.log1p(100) / math.log1p(1000))


class TestBounds:
    def test_components_and_score_in_unit_range(self):
        for dist in (0, 250, 500, 900):
            for rating, n in ((None, None), (1.0, 1), (5.0, 5000)):
                result = score_place(features(distance_m=dist, rating=rating, review_count=n), WEIGHTS, PARAMS)
                assert 0.0 <= result.score <= 1.0
                assert all(0.0 <= v <= 1.0 for v in result.components.values() if v is not None)

    def test_farther_is_less_accessible(self):
        near = score_place(features(distance_m=50), WEIGHTS, PARAMS)
        far = score_place(features(distance_m=450), WEIGHTS, PARAMS)
        assert near.components["accessibility"] > far.components["accessibility"]


class TestFit:
    def test_keyword_fit_takes_highest_match_else_default(self):
        kw = {"한식": 1.0, "뷔페": 0.9, "술집": 0.3}
        assert keyword_fit("음식점 > 한식 > 고기뷔페", kw, 0.6) == 1.0
        assert keyword_fit("음식점 > 술집 > 호프", kw, 0.6) == 0.3
        assert keyword_fit("음식점 > 기타", kw, 0.6) == 0.6

    def test_age_fit_averages_participants(self):
        prefs = {
            "10s": AgeGroupPreference(0.5, {"분식": 1.0}),
            "50s+": AgeGroupPreference(0.5, {"분식": 0.2}),
        }
        assert age_fit("음식점 > 분식", ["10s", "50s+"], prefs) == pytest.approx(0.6)


class TestReason:
    def test_with_rating(self):
        assert reason_line(200, 4.5, 320, 67) == "역에서 도보 3분, 평점 4.5(리뷰 320개)"

    def test_without_rating(self):
        assert reason_line(200, None, None, 67) == "역에서 도보 3분, 평점 정보 없음"

    def test_minimum_one_minute(self):
        assert reason_line(5, 4.0, 10, 67).startswith("역에서 도보 1분")
