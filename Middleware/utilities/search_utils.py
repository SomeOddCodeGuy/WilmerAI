import re
from collections import defaultdict
from itertools import combinations
from typing import List, Dict

from sklearn.feature_extraction.text import TfidfVectorizer

from Middleware.utilities.text_utils import tokenize


def build_inverted_index(lines: List[str]) -> Dict[str, List[int]]:
    """
    Build an inverted index from a list of text lines.

    Parameters:
    lines (List[str]): A list of strings to be indexed.

    Returns:
    Dict[str, List[int]]: A dictionary where each key is a token and each value is a list of line numbers where the token appears.
    """
    index = defaultdict(list)
    for line_number, line in enumerate(lines):
        for token in tokenize(line):
            token_lower = token.lower().strip()
            if not token_lower.endswith(':'):
                index[token_lower].append(line_number)
    return index


def calculate_line_scores(lines: List[str], index: Dict[str, List[int]], query_tokens: List[str]) -> Dict[int, int]:
    """
    Calculate scores for each line based on the occurrence of query tokens.

    Parameters:
    lines (List[str]): The list of lines to score.
    index (Dict[str, List[int]]): The inverted index built from the lines.
    query_tokens (List[str]): The list of tokens to search for in the lines.

    Returns:
    Dict[int, int]: A dictionary where each key is a line number and each value is the score for that line.
    """
    line_scores = defaultdict(int)
    for token in query_tokens:
        token_lower = token.lower()
        if token_lower in index:
            for line_number in index[token_lower]:
                line_scores[line_number] += 1
    return line_scores


def apply_proximity_filter(lines: List[str], line_scores: Dict[int, int], tokens: List[str], proximity_limit: int) -> \
Dict[int, int]:
    """
    Apply a proximity filter to the line scores, considering the distance between tokens.

    Parameters:
    lines (List[str]): The list of lines to filter.
    line_scores (Dict[int, int]): The dictionary of line scores.
    tokens (List[str]): The list of tokens to consider for proximity.
    proximity_limit (int): The maximum distance between tokens to consider them relevant.

    Returns:
    Dict[int, int]: A dictionary with updated line scores based on token proximity.
    """
    new_scores = defaultdict(int)
    token_positions = defaultdict(list)

    for line_number, score in line_scores.items():
        words = tokenize(lines[line_number])
        positions = {word.lower(): idx for idx, word in enumerate(words)}
        for token in tokens:
            if token.lower() in positions:
                token_positions[token].append((line_number, positions[token.lower()]))

    for token_pos in token_positions.values():
        for pos1, pos2 in combinations(token_pos, 2):
            if abs(pos1[1] - pos2[1]) <= proximity_limit:
                new_scores[pos1[0]] += 1  # Increment the score for lines where tokens are within the proximity limit.

    # Apply the proximity score only if it's higher than the existing score.
    for line_number in new_scores:
        line_scores[line_number] = max(line_scores[line_number], new_scores[line_number])

    return line_scores


def search_in_chunks(chunks: List[str], query: str, max_hits: int = 0) -> List[str]:
    """
    Search for a query within chunks of text and return the relevant chunks.

    Parameters:
    chunks (List[str]): A list of text chunks to search through.
    query (str): The query string to search for.
    max_hits (int, optional): The maximum number of relevant chunks to return. Defaults to 0 (no limit).

    Returns:
    List[str]: A list of chunks that contain the query tokens.
    """
    query_tokens = set(token.lower() for token in tokenize(query))
    relevant_chunks = [chunk for chunk in chunks if any(
        any(query_token in token.lower() for token in tokenize(chunk)) for query_token in query_tokens)]
    return relevant_chunks[:max_hits] if max_hits else relevant_chunks


def advanced_search_in_chunks(chunks: List[str], query: str, max_excerpts: int = 40, proximity_limit: int = 5) -> List[
    str]:
    """
    Perform an advanced search within chunks of text, applying scoring and proximity filters.

    Parameters:
    chunks (List[str]): A list of text chunks to search through.
    query (str): The query string to search for.
    max_excerpts (int, optional): The maximum number of excerpts to return. Defaults to 40.
    proximity_limit (int, optional): The maximum distance between tokens to consider them relevant. Defaults to 5.

    Returns:
    List[str]: A list of the top-scoring chunks based on the query and proximity limit.
    """
    index = build_inverted_index(chunks)
    query_tokens = tokenize(query)
    chunk_scores = calculate_line_scores(chunks, index, query_tokens)

    if proximity_limit:
        chunk_scores = apply_proximity_filter(chunks, chunk_scores, query_tokens, proximity_limit)

    sorted_chunk_indices = sorted(chunk_scores, key=chunk_scores.get, reverse=True)
    relevant_chunks = [chunks[chunk_index] for chunk_index in sorted_chunk_indices[:max_excerpts]]
    return relevant_chunks


def filter_keywords_by_speakers(messages: List[Dict[str, str]], keywords: str) -> str:
    """
    Filter out keywords that match any speaker names found in the messages.

    Parameters:
    messages (List[Dict[str, str]]): The list of messages containing the conversation with speaker names.
    keywords (str): The keywords to filter, potentially containing speaker names.

    Returns:
    str: The filtered keywords with speaker names removed.
    """
    # Extract speakers from the messages
    speakers = set()
    for message in messages:
        content = message['content']
        found_speakers = re.findall(r'\b(\w+):', content)
        speakers.update(found_speakers)

    # Tokenize the keywords
    tokens = re.findall(r'(\b\w+\b:|\bAND\b|\bOR\b|\(|\)|\b\w+\b)', keywords)

    # Filter tokens
    filtered_tokens = [token for token in tokens if token not in speakers and not token.endswith(':')]

    # Join filtered tokens back into a string
    result = ' '.join(filtered_tokens)
    result = re.sub(r'\(\s+', '(', result)
    result = re.sub(r'\s+\)', ')', result)

    return result


def calculate_tfidf_scores(chunks: List[str], query: str) -> List[float]:
    """
    Calculate the TF-IDF scores for each chunk against the query.

    Parameters:
    chunks (List[str]): A list of text chunks to score.
    query (str): The query string to compare against the chunks.

    Returns:
    List[float]: A list of TF-IDF scores for each chunk.
    """
    vectorizer = TfidfVectorizer()
    tfidf_matrix = vectorizer.fit_transform(chunks)
    query_vector = vectorizer.transform([query])
    return (tfidf_matrix * query_vector.T).toarray().flatten()


def advanced_search(lines: List[str], index: Dict[str, List[int]], query: str, max_excerpts: int = 5,
                    proximity_limit: int = 5) -> List[str]:
    """
    Perform an advanced search across lines of text, applying scoring and proximity filters.

    Parameters:
    lines (List[str]): The list of lines to search through.
    index (Dict[str, List[int]]): The inverted index built from the lines.
    query (str): The query string to search for.
    max_excerpts (int, optional): The maximum number of excerpts to return. Defaults to 5.
    proximity_limit (int, optional): The maximum distance between tokens to consider them relevant. Defaults to 5.

    Returns:
    List[str]: A list of the top-scoring excerpts.
    """
    query_tokens = tokenize(query)
    line_scores = calculate_line_scores(lines, index, query_tokens)

    if proximity_limit:
        line_scores = apply_proximity_filter(lines, line_scores, query_tokens, proximity_limit)

    sorted_line_numbers = sorted(line_scores, key=line_scores.get, reverse=True)
    excerpts = [lines[line_number].strip() for line_number in sorted_line_numbers[:max_excerpts]]
    return excerpts
