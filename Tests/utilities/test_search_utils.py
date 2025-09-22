# Tests/utilities/test_search_utils.py

import re

import pytest


# Mocking the tokenize function used in search_utils for consistent testing.
def mock_tokenize(text: str) -> list[str]:
    return re.findall(r'\b\w+\b', text)


@pytest.fixture(autouse=True)
def patch_dependencies(mocker):
    """Patch dependencies used by search_utils."""
    mocker.patch('Middleware.utilities.search_utils.tokenize', side_effect=mock_tokenize)

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        sklearn_available = True
    except ImportError:
        sklearn_available = False

    if not sklearn_available:
        mocker.patch('Middleware.utilities.search_utils.TfidfVectorizer', None)

    return {'sklearn_available': sklearn_available}


# Import functions after patching
from Middleware.utilities.search_utils import (
    build_inverted_index,
    calculate_line_scores,
    apply_proximity_filter,
    search_in_chunks,
    advanced_search_in_chunks,
    filter_keywords_by_speakers,
    calculate_tfidf_scores,
    advanced_search
)

# Sample data to be used across multiple tests
SAMPLE_LINES = [
    "The quick brown fox jumps over the lazy dog.",  # 0
    "A lazy brown dog is a happy dog.",  # 1
    "Never underestimate a quick fox.",  # 2
    "The quick brown bear is not a dog.",  # 3
    "User: a quick note about the dog"  # 4
]


@pytest.fixture
def sample_index():
    """A pre-built inverted index from SAMPLE_LINES."""
    return build_inverted_index(SAMPLE_LINES)


class TestBuildInvertedIndex:
    """Tests for the build_inverted_index function."""

    def test_build_inverted_index_basic(self):
        lines = ["hello world", "hello there"]
        expected = {"hello": [0, 1], "world": [0], "there": [1]}
        assert dict(build_inverted_index(lines)) == expected

    def test_build_inverted_index_case_insensitivity(self):
        lines = ["Hello world", "hello THERE"]
        expected = {"hello": [0, 1], "world": [0], "there": [1]}
        assert dict(build_inverted_index(lines)) == expected

    def test_build_inverted_index_empty_input(self):
        assert build_inverted_index([]) == {}

    def test_build_inverted_index_ignores_speaker_tags(self):
        """Tests that words followed by a colon are correctly identified as speakers and ignored."""
        lines = ["User: hello world", "System: goodbye", "agent: hello again"]
        index = build_inverted_index(lines)
        assert "user" not in index
        assert "system" not in index
        assert "agent" not in index
        assert "hello" in index
        assert "world" in index
        assert "goodbye" in index
        assert index["hello"] == [0, 2]


class TestCalculateLineScores:
    """Tests for the calculate_line_scores function."""

    def test_calculate_line_scores_basic(self, sample_index):
        query_tokens = ["quick", "dog"]
        scores = calculate_line_scores(SAMPLE_LINES, sample_index, query_tokens)
        assert dict(scores) == {0: 2, 1: 2, 2: 1, 3: 2, 4: 2}

    def test_calculate_line_scores_no_matches(self, sample_index):
        query_tokens = ["nonexistent", "word"]
        scores = calculate_line_scores(SAMPLE_LINES, sample_index, query_tokens)
        assert dict(scores) == {}

    def test_calculate_line_scores_case_insensitivity(self, sample_index):
        query_tokens = ["QUICK", "Dog"]
        scores = calculate_line_scores(SAMPLE_LINES, sample_index, query_tokens)
        assert scores[0] == 2
        assert scores[1] == 2


class TestApplyProximityFilter:
    """Tests for the apply_proximity_filter function with the distinct token logic."""

    def test_apply_proximity_filter_boosts_score(self):
        lines = ["the quick brown fox"]
        scores = {0: 2}
        query_tokens = ["quick", "fox"]
        updated_scores = apply_proximity_filter(lines, scores.copy(), query_tokens, proximity_limit=2)
        assert updated_scores[0] == 3

    def test_apply_proximity_filter_no_boost_when_far(self):
        lines = ["quick dogs are brown but the fox is far away"]
        scores = {0: 2}
        query_tokens = ["quick", "fox"]
        updated_scores = apply_proximity_filter(lines, scores.copy(), query_tokens, proximity_limit=3)
        assert updated_scores[0] == 2

    def test_apply_proximity_filter_multiple_pairs(self):
        lines = ["quick brown fox and another quick brown fox"]
        scores = {0: 6}
        query_tokens = ["quick", "brown", "fox"]
        updated_scores = apply_proximity_filter(lines, scores.copy(), query_tokens, proximity_limit=2)
        assert updated_scores[0] == 12

    def test_apply_proximity_filter_no_boost_for_self_proximity(self):
        """Ensures that proximity boost is NOT applied if only one distinct query token is present in the line."""
        lines = ["dog dog dog"]
        scores = {0: 3}
        query_tokens = ["quick", "dog"]
        updated_scores = apply_proximity_filter(lines, scores.copy(), query_tokens, proximity_limit=1)
        assert updated_scores[0] == 3

    def test_apply_proximity_filter_single_token_query(self):
        """Ensures that proximity filter short-circuits if the query itself has < 2 distinct tokens."""
        lines = ["dog dog dog"]
        scores = {0: 3}
        query_tokens = ["dog", "DOG"]
        updated_scores = apply_proximity_filter(lines, scores.copy(), query_tokens, proximity_limit=1)
        assert updated_scores[0] == 3


class TestSearchInChunks:
    """Tests for the simple search_in_chunks function."""

    def test_search_in_chunks_basic(self):
        query = "lazy dog"
        results = search_in_chunks(SAMPLE_LINES, query)
        assert len(results) == 4
        assert SAMPLE_LINES[0] in results
        assert SAMPLE_LINES[1] in results
        assert SAMPLE_LINES[3] in results
        assert SAMPLE_LINES[4] in results

    def test_search_in_chunks_max_hits(self):
        query = "dog"
        results = search_in_chunks(SAMPLE_LINES, query, max_hits=2)
        assert len(results) == 2
        assert results[0] == SAMPLE_LINES[0]
        assert results[1] == SAMPLE_LINES[1]

    def test_search_in_chunks_no_results(self):
        query = "nonexistent word"
        results = search_in_chunks(SAMPLE_LINES, query)
        assert len(results) == 0


class TestAdvancedSearch:
    """Tests for the advanced search orchestrator functions with the fixed proximity logic."""

    def test_advanced_search_in_chunks_end_to_end(self):
        query = "quick dog"
        results = advanced_search_in_chunks(SAMPLE_LINES, query, max_excerpts=3, proximity_limit=5)
        assert len(results) == 3
        assert results[0] == SAMPLE_LINES[4]
        remaining_results = set(results[1:])
        assert remaining_results.issubset({SAMPLE_LINES[0], SAMPLE_LINES[1], SAMPLE_LINES[3]})

    def test_advanced_search_in_chunks_no_proximity(self):
        query = "quick dog"
        results = advanced_search_in_chunks(SAMPLE_LINES, query, proximity_limit=0)
        top_results = {SAMPLE_LINES[0], SAMPLE_LINES[1], SAMPLE_LINES[3], SAMPLE_LINES[4]}
        assert set(results[:4]) == top_results

    def test_advanced_search_with_prebuilt_index(self, sample_index):
        query = "quick dog"
        results = advanced_search(SAMPLE_LINES, sample_index, query, max_excerpts=3, proximity_limit=5)
        expected_top_result = "User: a quick note about the dog"
        assert len(results) == 3
        assert results[0] == expected_top_result.strip()


class TestFilterKeywordsBySpeakers:
    """Tests for the filter_keywords_by_speakers function with cleanup fixes."""

    def test_filter_keywords_by_speakers_basic(self):
        messages = [{"role": "user", "content": "User: Hello there."}]
        keywords = "User AND hello"
        expected = "AND hello"
        assert filter_keywords_by_speakers(messages, keywords) == expected

    def test_filter_keywords_by_speakers_multiple(self):
        messages = [{"role": "user", "content": "User: Hi"}, {"role": "assistant", "content": "WilmerAI: Hello"}]
        keywords = "User WilmerAI greeting"
        expected = "greeting"
        assert filter_keywords_by_speakers(messages, keywords) == expected

    def test_filter_keywords_whitespace_cleanup(self):
        """Tests the fix for removing empty parentheses and cleaning whitespace."""
        messages = [{"role": "user", "content": "User: foo"}]
        keywords = "( User ) AND ( bar )"
        expected = "AND (bar)"
        assert filter_keywords_by_speakers(messages, keywords) == expected

    def test_filter_keywords_no_speakers(self):
        messages = [{"role": "user", "content": "Just a message."}]
        keywords = "a message"
        assert filter_keywords_by_speakers(messages, keywords) == keywords

    def test_filter_keywords_case_insensitivity(self):
        """Tests that speaker identification and keyword filtering are case-insensitive."""
        messages = [{"role": "user", "content": "user: Hi"}]
        keywords = "USER AND hello"
        expected = "AND hello"
        assert filter_keywords_by_speakers(messages, keywords) == expected

    def test_filter_keywords_removes_labels(self):
        """Ensures that tokens ending in ':' are removed even if not identified as speakers in messages."""
        messages = []
        keywords = "User: AND hello"
        expected = "AND hello"
        assert filter_keywords_by_speakers(messages, keywords) == expected


class TestTfidfScoring:
    """Tests for the calculate_tfidf_scores function."""

    def test_calculate_tfidf_scores(self, patch_dependencies):
        if not patch_dependencies['sklearn_available']:
            pytest.skip("scikit-learn not installed")

        chunks = [
            "this is the first document",
            "this document is the second document",
            "and this is the third one",
            "is this the first document"
        ]
        query = "this is the first document"
        scores = calculate_tfidf_scores(chunks, query)

        assert len(scores) == len(chunks)
        assert all(isinstance(s, float) for s in scores)
        assert scores[0] > scores[1]
        assert scores[0] > scores[2]
        assert scores[3] > scores[1]
        assert scores[3] > scores[2]

    def test_calculate_tfidf_scores_empty_input(self):
        assert calculate_tfidf_scores([], "query") == []
        assert calculate_tfidf_scores(["doc1"], "") == [0.0]
