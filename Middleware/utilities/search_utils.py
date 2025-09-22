# /Middleware/utilities/search_utils.py

import re
from collections import defaultdict
from itertools import combinations
from typing import List, Dict

# Conditional import for sklearn dependencies
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
except ImportError:
    TfidfVectorizer = None

# Assuming tokenize is correctly imported. We define a fallback for robustness.
try:
    from Middleware.utilities.text_utils import tokenize
except ImportError:
    # Fallback definition using standard word boundaries.
    def tokenize(text: str) -> List[str]:
        return re.findall(r'\b\w+\b', text)


def build_inverted_index(lines: List[str]) -> Dict[str, List[int]]:
    """
    Builds an inverted index from a list of text lines.

    This function processes a list of strings, tokenizes each line, and
    creates a mapping from each token to a list of line numbers where that
    token appears. This index is used for efficient text searching.

    Args:
        lines (List[str]): A list of strings to be indexed.

    Returns:
        Dict[str, List[int]]: A dictionary where each key is a token and each
        value is a list of line numbers where the token appears.
    """
    index = defaultdict(list)
    for line_number, line in enumerate(lines):
        speakers_in_line = {w.lower() for w in re.findall(r'(\b\w+):', line)}
        for token in tokenize(line):
            token_lower = token.lower().strip()
            if token_lower not in speakers_in_line:
                if line_number not in index[token_lower]:
                    index[token_lower].append(line_number)
    return index


def calculate_line_scores(lines: List[str], index: Dict[str, List[int]], query_tokens: List[str]) -> Dict[int, int]:
    """
    Calculates scores for each line based on the occurrence of query tokens.

    This function iterates through the query tokens and uses the inverted index
    to find which lines contain them. It assigns a score to each line,
    typically representing the count of query tokens found in that line.

    Args:
        lines (List[str]): The list of original text lines that were indexed.
        index (Dict[str, List[int]]): The inverted index mapping tokens to line
            numbers, created by `build_inverted_index`.
        query_tokens (List[str]): A list of tokens from the user's search query.

    Returns:
        Dict[int, int]: A dictionary where each key is a line number and the
        value is the calculated score for that line.
    """
    line_scores = defaultdict(int)
    lower_query_tokens = [t.lower() for t in query_tokens]
    relevant_line_numbers = set()
    for token in lower_query_tokens:
        if token in index:
            relevant_line_numbers.update(index[token])
    for line_number in relevant_line_numbers:
        if line_number < len(lines):
            line_tokens = [word.lower() for word in tokenize(lines[line_number])]
            score = sum(line_tokens.count(query_token) for query_token in lower_query_tokens)
            if score > 0:
                line_scores[line_number] = score
    return line_scores


def apply_proximity_filter(lines: List[str], line_scores: Dict[int, int], tokens: List[str], proximity_limit: int) -> \
        Dict[int, int]:
    """
    Applies a proximity filter to line scores, boosting lines with close tokens.

    This function refines search results by analyzing the distance between
    query tokens within each line. If tokens appear within the specified
    proximity limit, the score for that line is increased, improving the
    relevance of the final results.

    Args:
        lines (List[str]): The list of original text lines to analyze.
        line_scores (Dict[int, int]): A dictionary of the current line scores to be updated.
        tokens (List[str]): The list of query tokens to check for proximity.
        proximity_limit (int): The maximum distance (in words) between tokens
            to be considered proximate.

    Returns:
        Dict[int, int]: A dictionary with updated line scores after applying
        the proximity filter.
    """
    lower_query_tokens = {t.lower() for t in tokens}
    if len(lower_query_tokens) < 2:
        return line_scores
    updated_line_scores = line_scores.copy()
    for line_number in line_scores:
        if line_number >= len(lines):
            continue
        words = [word.lower() for word in tokenize(lines[line_number])]
        token_positions = defaultdict(list)
        for i, word in enumerate(words):
            if word in lower_query_tokens:
                token_positions[word].append(i)
        found_tokens = list(token_positions.keys())
        if len(found_tokens) < 2:
            continue
        proximity_score = 0
        for token1, token2 in combinations(found_tokens, 2):
            for pos1 in token_positions[token1]:
                for pos2 in token_positions[token2]:
                    if abs(pos1 - pos2) <= proximity_limit:
                        proximity_score += 1
        if proximity_score > 0:
            updated_line_scores[line_number] += proximity_score
    return updated_line_scores


def search_in_chunks(chunks: List[str], query: str, max_hits: int = 0) -> List[str]:
    """
    Performs a basic search for a query within a list of text chunks.

    This function filters a list of text chunks, returning only those that
    contain at least one of the tokens from the search query. It provides a
    simple and fast way to find potentially relevant chunks without scoring.

    Args:
        chunks (List[str]): A list of text chunks to search through.
        query (str): The query string to search for.
        max_hits (int, optional): The maximum number of matching chunks to
            return. Defaults to 0, which returns all matches.

    Returns:
        List[str]: A list of text chunks that contain one or more query tokens.
    """
    query_tokens = set(token.lower() for token in tokenize(query))
    if not query_tokens:
        return []
    relevant_chunks = []
    for chunk in chunks:
        chunk_tokens = set(token.lower() for token in tokenize(chunk))
        if query_tokens.intersection(chunk_tokens):
            relevant_chunks.append(chunk)
    return relevant_chunks[:max_hits] if max_hits > 0 else relevant_chunks


def advanced_search_in_chunks(chunks: List[str], query: str, max_excerpts: int = 40, proximity_limit: int = 5) -> List[
    str]:
    """
    Performs an advanced search within text chunks using scoring and proximity.

    This function implements a comprehensive search pipeline. It builds an
    inverted index of the chunks, calculates scores based on token frequency,
    optionally applies a proximity filter to boost relevance, and returns the
    top-scoring chunks.

    Args:
        chunks (List[str]): A list of text chunks to search through.
        query (str): The query string to search for.
        max_excerpts (int, optional): The maximum number of top-scoring chunks
            (excerpts) to return. Defaults to 40.
        proximity_limit (int, optional): The maximum distance between tokens for
            the proximity filter. Defaults to 5.

    Returns:
        List[str]: A sorted list of the most relevant chunks based on scoring.
    """
    if not chunks or not query:
        return []
    index = build_inverted_index(chunks)
    query_tokens = tokenize(query)
    chunk_scores = calculate_line_scores(chunks, index, query_tokens)
    if proximity_limit > 0:
        chunk_scores = apply_proximity_filter(chunks, chunk_scores, query_tokens, proximity_limit)
    sorted_chunk_indices = sorted(chunk_scores, key=chunk_scores.get, reverse=True)
    relevant_chunks = [chunks[chunk_index] for chunk_index in sorted_chunk_indices[:max_excerpts]]
    return relevant_chunks


def filter_keywords_by_speakers(messages: List[Dict[str, str]], keywords: str) -> str:
    """
    Filters speaker names from a keyword search string.

    This function inspects a list of conversation messages to identify speaker
    names (e.g., "User:", "WilmerAI:"). It then removes these names from a
    given keyword string to prevent them from interfering with search logic.

    Args:
        messages (List[Dict[str, str]]): A list of role/content message pairs
            representing a conversation.
        keywords (str): The keyword string to filter.

    Returns:
        str: The filtered keyword string with speaker names removed.
    """
    speakers = set()
    for message in messages:
        content = message.get('content', '')
        found_speakers = re.findall(r'\b(\w+):', content)
        speakers.update(s.lower() for s in found_speakers)
    tokens = re.findall(r'(\b\w+\b:|\bAND\b|\bOR\b|\(|\)|\b\w+\b)', keywords)
    filtered_tokens = []
    for token in tokens:
        is_speaker = token.lower() in speakers
        is_label = token.endswith(':')
        if not is_speaker and not is_label:
            filtered_tokens.append(token)
    result = ' '.join(filtered_tokens)
    result = re.sub(r'\(\s+', '(', result)
    result = re.sub(r'\s+\)', ')', result)
    result = re.sub(r'\(\s*\)', '', result)
    result = re.sub(r'\s{2,}', ' ', result).strip()
    return result


def calculate_tfidf_scores(chunks: List[str], query: str) -> List[float]:
    """
    Calculates TF-IDF scores for each text chunk against a query.

    This function uses the Term Frequency-Inverse Document Frequency (TF-IDF)
    algorithm to evaluate the relevance of each chunk in a list to a given
    query string. It returns a score for each chunk indicating its relevance.

    Args:
        chunks (List[str]): A list of text chunks (documents) to score.
        query (str): The query string to use for comparison.

    Returns:
        List[float]: A list of TF-IDF scores, where each score corresponds to a
        chunk at the same index.
    """
    if not chunks or not query:
        return [0.0] * len(chunks)
    if TfidfVectorizer is None:
        return [0.0] * len(chunks)
    try:
        vectorizer = TfidfVectorizer()
        tfidf_matrix = vectorizer.fit_transform(chunks)
        query_vector = vectorizer.transform([query])
        scores = (tfidf_matrix * query_vector.T).toarray().flatten()
        return scores.tolist()
    except ValueError:
        return [0.0] * len(chunks)


def advanced_search(lines: List[str], index: Dict[str, List[int]], query: str, max_excerpts: int = 5,
                    proximity_limit: int = 5) -> List[str]:
    """
    Performs an advanced search using a pre-built inverted index.

    This function executes a search query against a list of text lines. It
    leverages a provided inverted index for efficiency, calculates line scores,
    applies a proximity filter to refine results, and returns a list of the
    top-scoring lines.

    Args:
        lines (List[str]): The list of lines to search through.
        index (Dict[str, List[int]]): A pre-built inverted index for the lines.
        query (str): The query string to search for.
        max_excerpts (int, optional): The maximum number of top-scoring lines
            (excerpts) to return. Defaults to 5.
        proximity_limit (int, optional): The maximum distance between tokens for
            the proximity filter. Defaults to 5.

    Returns:
        List[str]: A sorted list of the most relevant lines (excerpts).
    """
    if not lines or not query or not index:
        return []
    query_tokens = tokenize(query)
    line_scores = calculate_line_scores(lines, index, query_tokens)
    if proximity_limit > 0:
        line_scores = apply_proximity_filter(lines, line_scores, query_tokens, proximity_limit)
    sorted_line_numbers = sorted(line_scores, key=line_scores.get, reverse=True)
    excerpts = [lines[line_number].strip() for line_number in sorted_line_numbers[:max_excerpts] if
                line_number < len(lines)]
    return excerpts
