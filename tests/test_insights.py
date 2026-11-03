from trakt_ify.insights import (
    confidence_for,
    match_label,
    quality_factor,
    rating_weight,
    score_candidates,
)
from trakt_ify.models import CalibrationBucket


def test_ranks_by_support_and_excludes_watched():
    related = {1: {100, 101, 2}, 2: {100, 101}, 3: {100, 102}, 4: {100}}
    ranked = score_candidates(related, {1: 0, 2: 0, 3: 1, 4: 1}, {1, 2, 3, 4}, min_support=1)
    ids = [c.id for c in ranked]
    assert ids[0] == 100  # listed by all four
    assert 2 not in ids  # watched films are never recommended
    assert ranked[0].support == 4


def test_files_pick_under_cluster_with_most_pointers_and_lists_them():
    related = {1: {100}, 2: {100}, 3: {100}, 4: {100}, 5: {100}}
    communities = {1: 0, 2: 1, 3: 1, 4: 1, 5: None}
    ranked = score_candidates(related, {k: v for k, v in communities.items() if v is not None},
                              {1, 2, 3, 4, 5}, min_support=1)
    pick = ranked[0]
    assert pick.cluster == 1
    assert pick.cluster_support == 3
    assert sorted(pick.because) == [2, 3, 4]


def test_ratings_weight_support():
    related = {1: {100}, 2: {101}}
    weights = {1: rating_weight(9), 2: rating_weight(3)}
    ranked = score_candidates(related, {1: 0, 2: 0}, {1, 2}, weights, min_support=1)
    assert [c.id for c in ranked] == [100, 101]


def test_min_support_filters():
    related = {1: {100, 101}, 2: {100}, 3: {100}}
    ranked = score_candidates(related, {1: 0, 2: 0, 3: 0}, {1, 2, 3}, min_support=3)
    assert [c.id for c in ranked] == [100]


def test_confidence_lookup_by_support_per_thousand():
    cal = [
        CalibrationBucket(min_per_thousand=0, hit_rate=0.01, samples=10),
        CalibrationBucket(min_per_thousand=5, hit_rate=0.1, samples=10),
        CalibrationBucket(min_per_thousand=16, hit_rate=0.3, samples=10),
    ]
    assert confidence_for(1, 1000, cal) == 0.01
    assert confidence_for(6, 1000, cal) == 0.1
    assert confidence_for(40, 2000, cal) == 0.3
    assert confidence_for(5, 1000, []) is None


def test_quality_factor_drops_obscure_and_poorly_rated():
    assert quality_factor(None, None) == 1.0
    assert quality_factor(8.0, 50) is None
    assert quality_factor(4.0, 50000) is None
    assert quality_factor(8.0, 50000) > quality_factor(6.8, 50000)


def test_label_matching_survives_renumbering():
    stored = [{"members": {1, 2, 3, 4}, "label": "A"}, {"members": {9, 10}, "label": "B"}]
    assert match_label({1, 2, 3, 5}, stored)["label"] == "A"
    assert match_label({20, 21}, stored) is None
