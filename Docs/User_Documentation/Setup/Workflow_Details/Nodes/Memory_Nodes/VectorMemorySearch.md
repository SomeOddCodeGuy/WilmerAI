## The `VectorMemorySearch` Node

This guide provides a comprehensive, code-validated overview of the `VectorMemorySearch` node. It details the node's
precise execution logic, properties, and best practices for implementing Retrieval-Augmented Generation (RAG).

### Core Purpose

The **`VectorMemorySearch`** node is the primary tool for RAG in WilmerAI. It performs a relevance-based
keyword search against a discussion's dedicated vector memory database. This allows an agent to instantly retrieve
specific facts, topics, or details from any point in a long conversation's history to inform its next response.

**Note:** This node is stateful and requires an active `[DiscussionId]` in the conversation to function. Without one, it
will return the error message `"Cannot perform VectorMemorySearch without a discussionId."` and will not perform a
search.

> Example: "[DiscussionId]my_chat_2123[/DiscussionId] How are you?"
> That discussionid can be anywhere in the conversation. Wilmer will find it and strip it out,
> then utilitize it. In this case, your discussionid is my_chat_2123.

-----

### Internal Execution Flow

1. **Input Parsing**: The node takes the `input` string and splits it into a list of keywords using the semicolon (`;`)
   as a delimiter.
2. **Query Sanitization**: Each keyword is individually sanitized to be safe for a database full-text search query.
3. **Query Construction**: The sanitized keywords are joined with `OR` logic to form a single query.
4. **Database Execution**: The query is executed against the `memories_fts` virtual table in the discussion's SQLite
   database.
5. **Ranking and Retrieval**: The database uses the **`bm25`** algorithm to score results by relevance. It retrieves the
   `memory_text` column, which contains the LLM-generated summary of the original conversation chunk.
6. **Entity Expansion (optional)**: When `useEntityExpansion` is enabled, entities listed in the metadata of the top
   results (minus any that were already query terms) become the query for a second keyword search, a one-hop lookup
   of everything stored about the entities the first pass surfaced. Memories only the second pass found are given a
   reserved share of the final result slots (roughly a third), appended after the base results.
7. **Result Aggregation**: The summaries from the top `limit` results are joined into a single string, separated by
   `\n\n---\n\n`.

-----

### Data Flow

* **Direct Output (`{agent#Output}`)**: The node **always** returns the aggregated string of relevant memory summaries
  as its standard output. If the `VectorMemorySearch` is the first node, this string is available to subsequent nodes
  via `{agent1Output}`. If no memories are found, it returns the string:
  `"No relevant memories found in the vector database for the given keywords."`

-----

### Node Properties

| Property    | Type    | Required? | Description                                                                                                                                                                                                                               |
|:------------|:--------|:----------|:------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **`type`**  | String  | Yes     | Must be exactly `"VectorMemorySearch"`.                                                                                                                                                                                                   |
| **`input`** | String  | Yes     | A string of keywords to search for. **Keywords must be separated by a semicolon (`;`)**. This field supports all workflow variables. The system limits searches to a maximum of **60 keywords**; any additional keywords will be ignored. |
| **`limit`** | Integer | No      | **Default: `5`**. The maximum number of memory summaries to retrieve from the database.                                                                                                                                                   |
| **`bm25Weights`** | List of 5 Numbers | No | Per-column BM25 weights, in order: title, summary, entities, key_phrases, memory text. Omitting it keeps the historical equal weighting. A good starting point is `[3.0, 2.0, 2.0, 2.0, 0.5]`, which favors matches in the curated metadata over incidental matches in the memory body. Malformed values are logged and ignored. |
| **`useRecencyScoring`** | Boolean | No | **Default: `false`**. When `true`, each match's rank is multiplied by a time-decay boost (up to ~2.5x for brand-new memories, fading toward 1.0x over time), so newer memories win ties against stale ones. Recommended for long-running conversations where facts change over the years. |
| **`includeDates`** | Boolean | No | **Default: `false`**. When `true`, each returned memory is prefixed with its creation date (e.g. `[2024-03-15]`), which lets the responding LLM arbitrate between contradictory facts from different eras. |
| **`searchMode`** | String | No | **Default: `"keyword"`**. `"keyword"` is the historical BM25 search. `"semantic"` ranks memories by embedding similarity to `semanticQuery`, matching meaning even when no words overlap. `"hybrid"` runs both and merges them with Reciprocal Rank Fusion (recommended when embeddings are available). Semantic and hybrid require `embeddingEndpointName` and degrade gracefully to keyword search if the embeddings endpoint is missing or unreachable, or no embeddings have been stored yet. |
| **`semanticQuery`** | String | No | Raw text to embed as the semantic query (e.g. the user's last message, or a variable like `{agent1Output}`). Supports all workflow variables. When omitted, the keyword string is reused with semicolons replaced by spaces. |
| **`embeddingEndpointName`** | String | No | The name of an Endpoints config file whose ApiType is an embeddings type (`openAIEmbeddings` or `ollamaEmbeddings`). Required for `semantic` and `hybrid` modes. |
| **`useEntityExpansion`** | Boolean | No | **Default: `false`**. When `true`, entities from the metadata of the top results seed a second keyword pass, and roughly a third of the result slots are reserved for memories only that pass found. Bridges facts connected by an entity the query could not name (e.g. "what does the user's sister do?" -> a hit names the sister as Sarah -> the second pass finds Sarah's job). Pure keyword/BM25; works in every `searchMode` and never requires an embeddings endpoint. Expansion-only hits are appended after the base results. |

-----

### Tuning `bm25Weights`

The five weights are positional and map to the FTS index columns in this order: `title`, `summary`, `entities`,
`key_phrases`, `memory text`. Each weight multiplies how much a keyword match in that column contributes to a memory's
relevance score. `1.0` is the baseline (the value every column takes when `bm25Weights` is omitted); a value above
`1.0` amplifies matches in that column, a value below `1.0` suppresses them, and `0` excludes the column from scoring
entirely. Only the ratios between the weights matter, not their absolute size, so `[3, 2, 2, 2, 0.5]` and
`[6, 4, 4, 4, 1]` behave identically.

The default `[3.0, 2.0, 2.0, 2.0, 0.5]` favors the curated metadata (what the extraction step decided the memory is
about) over the raw memory body (where a query word may appear only in passing). Adjust from there based on what your
memories look like and how they are searched:

| Column | Contains | Raise it when | Lower it when |
|:---|:---|:---|:---|
| `title` | the short generated headline | titles are consistently accurate and on-topic | your extraction produces weak or generic titles |
| `summary` | the one-line gist | you want broadly relevant memories to surface | summaries are terse or repetitive |
| `entities` | proper nouns (people, places, organizations) | users search by name often | the domain has few proper nouns |
| `key_phrases` | conceptual phrases (plus `topics`, when `vectorMemoryIndexTopics` is on) | queries are conceptual rather than name based | key phrases are sparse |
| `memory text` | the full memory body | memories are short and body matches should count normally | irrelevant memories surface on incidental word matches |

To tune against real behavior, change one weight at a time and re-run the same queries:

* Off-topic memories that merely mention a query word in passing usually mean `memory text` is too high; lower it
  (toward `0.5`, or `0` to search the curated fields only).
* A memory that is clearly about a named person or place the query mentioned but does not surface usually means
  `entities` is too low; raise it.
* Narrowly relevant memories ranking above broadly relevant ones usually means `summary` is too low relative to
  `title`; raise `summary`.

Notes:

* Weighting a column your memories do not populate has no effect. If the extraction leaves `title` empty, the title
  weight does nothing.
* The weights shape only the keyword (BM25) ranking. They apply in `keyword` mode and to the keyword half of `hybrid`
  mode; they do not affect the `semantic` embedding ranking.
* `useRecencyScoring` multiplies the final weighted rank, so it composes with these weights rather than replacing them.
* A value that is not exactly five numbers is logged and ignored, falling back to equal weighting.

-----

### Workflow Strategy and Annotated Example

Place this node **early** in a workflow to gather relevant facts *before* the main response generation node. This allows
the LLM to use the retrieved context to formulate a more informed answer.

```json
[
  {
    "title": "Step 1: Identify key topics in the user's prompt",
    "type": "Standard",
    "prompt": "Read the user's last message: '{chat_user_prompt_last_one}'. List the key nouns, entities, and concepts as a semicolon-separated list.",
    "returnToUser": false
    // This node acts as a pre-processor to generate clean keywords for the search.
  },
  {
    "title": "Step 2: Use identified topics to search vector memory",
    "type": "VectorMemorySearch",
    "input": "{agent1Output}",
    "limit": 3
    // --- DATA GATHERING ---
    // It takes the keywords from the previous node and executes the search.
    // The result will be stored in {agent2Output}.
  },
  {
    "title": "Step 3: Respond to the user with retrieved context",
    "type": "Standard",
    "returnToUser": true,
    "systemPrompt": "You have the following memories retrieved from storage:\n<context>\n{agent2Output}\n</context>\n\nUse this context to formulate an answer to the user's last message: {chat_user_prompt_last_one}"
    // The final node uses the retrieved memories to provide a fact-based response.
  }
]
```