# tests/utilities/test_vector_math_utils.py

import math
from array import array

import pytest

from Middleware.utilities.vector_math_utils import (
    blob_to_vector,
    cosine_similarity,
    rank_by_cosine,
    reciprocal_rank_fusion,
    vector_to_blob,
)


class TestBlobSerialization:
    def test_roundtrip_preserves_values(self):
        original = [0.5, -1.25, 3.0, 0.0]

        restored = blob_to_vector(vector_to_blob(original))

        assert list(restored) == original

    def test_blob_is_four_bytes_per_float(self):
        assert len(vector_to_blob([1.0, 2.0, 3.0])) == 12

    def test_float32_precision_is_close_not_exact(self):
        original = [0.1, 0.2, 0.3]

        restored = blob_to_vector(vector_to_blob(original))

        for a, b in zip(restored, original):
            assert a == pytest.approx(b, abs=1e-6)


class TestCosineSimilarity:
    def test_identical_vectors(self):
        assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_scale_invariance(self):
        assert cosine_similarity([1.0, 2.0], [10.0, 20.0]) == pytest.approx(1.0)

    def test_zero_vector_returns_zero(self):
        assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0

    def test_dimension_mismatch_returns_zero(self):
        assert cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0]) == 0.0

    def test_known_value(self):
        # cos(45 degrees) between (1,0) and (1,1)
        assert cosine_similarity([1.0, 0.0], [1.0, 1.0]) == pytest.approx(1 / math.sqrt(2))

    def test_accepts_array_inputs(self):
        a = array('f', [1.0, 2.0])
        b = array('f', [2.0, 4.0])

        assert cosine_similarity(a, b) == pytest.approx(1.0)


class TestRankByCosine:
    def test_ranks_best_first_and_truncates(self):
        query = [1.0, 0.0]
        pairs = [
            (1, vector_to_blob([0.0, 1.0])),   # orthogonal: 0.0
            (2, vector_to_blob([1.0, 0.0])),   # identical: 1.0
            (3, vector_to_blob([1.0, 1.0])),   # ~0.707
        ]

        ranked = rank_by_cosine(query, pairs, top_n=2)

        assert [memory_id for memory_id, _ in ranked] == [2, 3]
        assert ranked[0][1] == pytest.approx(1.0)

    def test_empty_input(self):
        assert rank_by_cosine([1.0, 0.0], [], top_n=5) == []


class TestReciprocalRankFusion:
    def test_agreement_wins(self):
        # id 10 is ranked first by both lists; it must win.
        merged = reciprocal_rank_fusion([[10, 20, 30], [10, 30, 40]])

        assert merged[0] == 10

    def test_consistent_middle_beats_single_top(self):
        # id 5 appears at rank 2 in both lists (2/(k+2)); id 1 and id 9 are
        # rank-1 in one list only (1/(k+1)). With k=60, 2/62 > 1/61.
        merged = reciprocal_rank_fusion([[1, 5, 6], [9, 5, 7]])

        assert merged[0] == 5

    def test_single_list_preserves_order(self):
        assert reciprocal_rank_fusion([[3, 1, 2]]) == [3, 1, 2]

    def test_empty_lists(self):
        assert reciprocal_rank_fusion([]) == []
        assert reciprocal_rank_fusion([[], []]) == []

    def test_dedupes_across_lists(self):
        merged = reciprocal_rank_fusion([[1, 2], [2, 1]])

        assert sorted(merged) == [1, 2]
        assert len(merged) == 2

    def test_rank_position_scores_across_lists(self):
        # Pins the rank arithmetic itself: id 30 is rank-1 in its list (1/61)
        # and must beat id 20 at rank-2 (1/62); id 10 ties 30 on score and wins
        # by stable insertion order. An "appearance count" impostor (every id
        # scores 1.0) would instead return [10, 20, 30].
        merged = reciprocal_rank_fusion([[10, 20], [30]])

        assert merged == [10, 30, 20]
