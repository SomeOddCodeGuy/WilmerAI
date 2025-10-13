## The `VectorMemorySearch` Node

This guide provides a comprehensive, code-validated overview of the `VectorMemorySearch` node. It details the node's
precise execution logic, properties, and best practices for implementing powerful Retrieval-Augmented Generation (RAG).

### Core Purpose

The **`VectorMemorySearch`** node is the primary tool for RAG in WilmerAI. It performs a powerful, relevance-based
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
6. **Result Aggregation**: The summaries from the top `limit` results are joined into a single string, separated by
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
| **`type`**  | String  | ✅ Yes     | Must be exactly `"VectorMemorySearch"`.                                                                                                                                                                                                   |
| **`input`** | String  | ✅ Yes     | A string of keywords to search for. **Keywords must be separated by a semicolon (`;`)**. This field supports all workflow variables. The system limits searches to a maximum of **60 keywords**; any additional keywords will be ignored. |
| **`limit`** | Integer | ❌ No      | **Default: `5`**. The maximum number of memory summaries to retrieve from the database.                                                                                                                                                   |

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