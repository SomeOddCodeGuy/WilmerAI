# backfill_embeddings.py
#
# One-time bulk embedding backfill for an existing vector memory database.
#
# Deliberately standalone: takes the database file path directly instead of
# resolving it through Wilmer's user configuration, so it works on databases at
# the current location, legacy locations, or copies, and requires no running
# Wilmer instance. Only writes to the additive memory_embeddings table; the
# memories and memories_fts tables are never touched.
#
# Wilmer does not need this script to use embeddings: the write path lazily
# backfills a small batch per memory cycle (embeddingBackfillBatchSize). This
# script just does the whole backlog at once for users with years of memories.
#
# Examples (from the project root):
#   python Scripts/backfill_embeddings.py --db Public/DiscussionIds/mychat/vector_memory.db \
#       --url http://localhost:8081 --model nomic-embed-text
#   python Scripts/backfill_embeddings.py --db /path/to/vector_memory.db \
#       --url http://localhost:11434 --api-shape ollama --model nomic-embed-text

import argparse
import os
import sqlite3
import sys
from array import array

import requests

CREATE_EMBEDDINGS_TABLE = '''
    CREATE TABLE IF NOT EXISTS memory_embeddings (
        memory_id INTEGER NOT NULL,
        model TEXT NOT NULL,
        dim INTEGER NOT NULL,
        vector BLOB NOT NULL,
        PRIMARY KEY (memory_id, model)
    );
'''


def fetch_embeddings(session, base_url, api_shape, model, api_key, texts, timeout):
    """Requests embeddings for a batch of texts. Returns one vector per text."""
    base = base_url.rstrip('/')
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    if api_shape == "ollama":
        url = f"{base}/api/embed"
    else:
        url = f"{base}/v1/embeddings"

    response = session.post(url, headers=headers,
                            json={"model": model, "input": texts}, timeout=timeout)
    response.raise_for_status()
    body = response.json()

    if api_shape == "ollama":
        vectors = body.get("embeddings")
    else:
        data = body.get("data", [])
        vectors = [item.get("embedding") for item in sorted(data, key=lambda d: d.get("index", 0))]

    if not isinstance(vectors, list) or len(vectors) != len(texts):
        raise ValueError(f"Endpoint returned {len(vectors) if isinstance(vectors, list) else 'no'} "
                         f"vectors for {len(texts)} texts.")
    if not all(isinstance(vector, list) and vector for vector in vectors):
        raise ValueError("Endpoint response did not contain a list of non-empty vectors.")
    return vectors


def main():
    parser = argparse.ArgumentParser(
        description="Backfill embeddings for an existing WilmerAI vector memory database.")
    parser.add_argument("--db", required=True, help="Path to the vector_memory.db file.")
    parser.add_argument("--url", required=True, help="Base URL of the embeddings server.")
    parser.add_argument("--model", required=True,
                        help="Embedding model name. Must match the endpoint's "
                             "modelNameToSendToAPI so Wilmer's search finds these vectors.")
    parser.add_argument("--api-shape", choices=["openai", "ollama"], default="openai",
                        help="API flavor: 'openai' for /v1/embeddings (OpenAI, llama.cpp "
                             "--embedding), 'ollama' for /api/embed. Default: openai.")
    parser.add_argument("--api-key", default="", help="Optional bearer token.")
    parser.add_argument("--batch-size", type=int, default=32,
                        help="Texts per embedding request. Default: 32.")
    parser.add_argument("--timeout", type=int, default=120,
                        help="Per-request timeout in seconds. Default: 120.")
    args = parser.parse_args()

    if args.batch_size < 1:
        parser.error("--batch-size must be at least 1.")

    # sqlite3.connect would silently create an empty database at a typo'd
    # path; require an existing file instead.
    if not os.path.isfile(args.db):
        print(f"Error: no database file found at '{args.db}'.")
        return 1

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    # Validate before creating anything, so pointing --db at a non-Wilmer
    # SQLite file leaves it untouched.
    has_memories = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'memories'").fetchone()
    if has_memories is None:
        print(f"Error: '{args.db}' has no 'memories' table; it does not look like "
              "a WilmerAI vector memory database.")
        conn.close()
        return 1

    conn.execute(CREATE_EMBEDDINGS_TABLE)
    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    session = requests.Session()
    done = 0
    failures = 0

    while True:
        rows = conn.execute(
            '''SELECT id, memory_text FROM memories
               WHERE id NOT IN (SELECT memory_id FROM memory_embeddings WHERE model = ?)
               ORDER BY id ASC LIMIT ?''',
            (args.model, args.batch_size)).fetchall()
        if not rows:
            break

        texts = [row["memory_text"] for row in rows]
        try:
            vectors = fetch_embeddings(session, args.url, args.api_shape, args.model,
                                       args.api_key, texts, args.timeout)
        except Exception as e:
            failures += 1
            print(f"\nBatch failed ({e}). "
                  f"{'Aborting after repeated failures.' if failures >= 3 else f'Retrying ({3 - failures} attempt(s) left)...'}")
            if failures >= 3:
                break
            continue

        failures = 0
        payload = [(row["id"], args.model, len(vector), array('f', vector).tobytes())
                   for row, vector in zip(rows, vectors)]
        conn.executemany(
            "INSERT OR REPLACE INTO memory_embeddings (memory_id, model, dim, vector) "
            "VALUES (?, ?, ?, ?)", payload)
        conn.commit()
        done += len(rows)
        print(f"\rEmbedded {done} memories...", end="", flush=True)

    remaining = conn.execute(
        '''SELECT COUNT(*) FROM memories
           WHERE id NOT IN (SELECT memory_id FROM memory_embeddings WHERE model = ?)''',
        (args.model,)).fetchone()[0]
    conn.close()

    print(f"\nDone. {total} memories total, {done} embedded this run, {remaining} remaining "
          f"for model '{args.model}'.")
    return 0 if remaining == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
