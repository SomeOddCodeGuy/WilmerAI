# Middleware/utilities/vector_math_utils.py
"""
Stdlib-only vector math for the embedding-based memory search.

Embeddings are stored as float32 blobs and compared with brute-force cosine
similarity. At the scale of a discussion's memory database (thousands of rows)
this completes in milliseconds without any numeric library: math.sumprod (C
speed, Python 3.12+) is used when available, with a pure-Python fallback.
"""

import logging
import math
from array import array
from typing import Iterable, List, Sequence, Tuple

logger = logging.getLogger(__name__)

# math.sumprod was added in Python 3.12; fall back to a pure-Python dot product
# on older interpreters.
_dot = getattr(math, "sumprod", None) or (lambda a, b: sum(x * y for x, y in zip(a, b)))


def vector_to_blob(vector: Sequence[float]) -> bytes:
    """
    Serializes a vector to a float32 blob for BLOB-column storage.

    Args:
        vector (Sequence[float]): The embedding values.

    Returns:
        bytes: The packed float32 representation.
    """
    return array('f', vector).tobytes()


def blob_to_vector(blob: bytes) -> array:
    """
    Deserializes a float32 blob back into an array of floats.

    Args:
        blob (bytes): The packed float32 representation.

    Returns:
        array: An array('f') of the embedding values.
    """
    vec = array('f')
    vec.frombytes(blob)
    return vec


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """
    Computes the cosine similarity between two vectors.

    Args:
        a (Sequence[float]): The first vector.
        b (Sequence[float]): The second vector.

    Returns:
        float: The cosine similarity in [-1, 1], or 0.0 when either vector has
        zero magnitude or the dimensions differ (logged, not raised, so a single
        malformed row cannot break a search).
    """
    if len(a) != len(b):
        logger.warning("Cosine similarity dimension mismatch: %d vs %d. Returning 0.", len(a), len(b))
        return 0.0
    norm_a = math.sqrt(_dot(a, a))
    norm_b = math.sqrt(_dot(b, b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return _dot(a, b) / (norm_a * norm_b)


def rank_by_cosine(query_vector: Sequence[float],
                   id_blob_pairs: Iterable[Tuple[int, bytes]],
                   top_n: int) -> List[Tuple[int, float]]:
    """
    Ranks stored embedding blobs by cosine similarity to a query vector.

    Args:
        query_vector (Sequence[float]): The query embedding.
        id_blob_pairs (Iterable[Tuple[int, bytes]]): (memory_id, float32 blob) pairs.
        top_n (int): The maximum number of results to return.

    Returns:
        List[Tuple[int, float]]: (memory_id, similarity) pairs, best first.
    """
    scored = []
    for memory_id, blob in id_blob_pairs:
        similarity = cosine_similarity(query_vector, blob_to_vector(blob))
        scored.append((memory_id, similarity))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:top_n]


def reciprocal_rank_fusion(ranked_id_lists: Sequence[Sequence[int]], k: int = 60) -> List[int]:
    """
    Merges multiple ranked id lists with Reciprocal Rank Fusion.

    Each id scores the sum over lists of 1 / (k + rank), where rank is its
    1-based position in that list. RRF requires no score normalization between
    heterogeneous rankers (BM25 and cosine), which is why it is used here.

    Args:
        ranked_id_lists (Sequence[Sequence[int]]): The ranked id lists to merge.
        k (int): The standard RRF dampening constant. Defaults to 60.

    Returns:
        List[int]: The merged ids, best first.
    """
    scores = {}
    for id_list in ranked_id_lists:
        for rank, item_id in enumerate(id_list, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda item_id: scores[item_id], reverse=True)
