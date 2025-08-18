### **Developer Guide: LLM Response Cleaning and Formatting**

This guide provides a deep dive into how WilmerAI processes and cleans the raw output from a Large Language Model (LLM)
before it is returned to the user. This process is essential for removing diagnostic tags, boilerplate prefixes, and
other unwanted artifacts from the final response.

The core principle is that all text cleaning occurs **after** the raw, unmodified response is received from the backing
LLM via the `llmapis` layer. The logic is implemented in parallel for non-streaming and streaming responses to ensure
functionally identical outcomes.

-----

## 1\. Handling Non-Streaming Responses

For a complete, non-streaming response, the entire block of text is processed at once in a sequential series of cleaning
steps.

### **Location of Logic**

* **Primary Function:** `post_process_llm_output` in `Middleware/utilities/streaming_utils.py`.
* **Calling Context:** This function is typically invoked by a higher-level workflow processor after a non-streaming
  node has executed.

### **Order of Operations**

The `post_process_llm_output` function applies cleaning rules in a precise order. The sequence is as follows:

1. **Thinking Tag Removal:** The text is first passed to `remove_thinking_from_text`. This function's behavior depends
   on the endpoint configuration:
    * **Standard Mode**: It looks for a `startThinkTag` within an initial `openingTagGracePeriod` (e.g., the first 100
      characters). If found, it then searches for the corresponding `endThinkTag`. If both are found, the entire block (
      including tags) is removed. If the opening tag isn't in the grace period or the closing tag is missing, the *
      *original text is returned unmodified**.
    * **`expectOnlyClosingThinkTag` Mode**: If this flag is `True`, the function searches for the `endThinkTag` only. If
      found, it discards everything before it and returns only the content that follows. If the tag is not found, it
      returns an **empty string**.
2. **Leading Whitespace Stripped:** The result is left-stripped to prepare it for prefix matching.
3. **Workflow-Level Custom Prefixes:** It checks for prefixes defined by `removeCustomTextFromResponseStart` and
   `responseStartTextToRemove` in the workflow node's config. The `responseStartTextToRemove` value is an **array of
   strings**. The function iterates through this array and removes the **first** prefix that matches the beginning of
   the response.
4. **Endpoint-Level Custom Prefixes:** It performs the same array-based iteration for prefixes defined by
   `removeCustomTextFromResponseStartEndpointWide` and `responseStartTextToRemoveEndpointWide` in the endpoint's config.
5. **Timestamp Text:** It removes the hardcoded `[Sent less than a minute ago]` prefix if the node's
   `addDiscussionIdTimestampsForLLM` flag is `True`.
6. **"Assistant:" Prefix:** It removes the `Assistant:` prefix based on a composite check of global settings (
   `get_is_chat_complete_add_user_assistant()` and `get_is_chat_complete_add_missing_assistant()`).
7. **Final Trim:** If `trimBeginningAndEndLineBreaks` is `True` in the endpoint config, a final `.strip()` is applied to
   remove any leading or trailing whitespace and line breaks.

-----

## 2\. Handling Streaming Responses

Cleaning a streaming response is more complex, as it must be done chunk-by-chunk. This process is orchestrated by the
`$StreamingResponseHandler$` class, which uses a stateful helper for tag removal.

### **Location of Logic**

* **Primary Class:** `$StreamingResponseHandler$` in `Middleware/workflows/streaming/response_handler.py`.
* **Key Dependency:** It relies on the `$StreamingThinkRemover$` class from `Middleware/utilities/streaming_utils.py`
  for stateful tag removal.

### **The Two-Stage Cleaning Process**

`$StreamingResponseHandler$` uses a two-stage process to clean the stream:

#### **Stage 1: Thinking Tag Removal (Continuous)**

Every delta chunk from the LLM is immediately passed to an instance of `$StreamingThinkRemover$`. This stateful class
uses an internal buffer to find and remove thinking blocks in real-time.

* **Standard Mode**: The remover buffers initial chunks up to the `openingTagGracePeriod` limit. If the `startThinkTag`
  appears within this window, it enters a "thinking" state and discards all subsequent text until the `endThinkTag` is
  found. If the grace period passes without an opening tag, the remover stops looking and passes all future text through
  untouched. If the stream ends with an unterminated think block, the remover flushes its buffer, returning the opening
  tag and the buffered content.
* **`expectOnlyClosingThinkTag` Mode**: The remover buffers and discards all text until it finds the `endThinkTag`. Once
  the tag is found, it discards the buffer and begins yielding all subsequent text.

The rest of the system only sees the "clean" stream output by `$StreamingThinkRemover$`.

#### **Stage 2: Prefix Removal (One-Time at Start)**

The `$StreamingResponseHandler$` takes the cleaned stream from Stage 1 and performs a one-time buffering operation to
handle all other prefix removals.

1. **Buffering:** It collects the initial chunks from `$StreamingThinkRemover$` into its own `_prefix_buffer` until a
   sufficient amount of text is gathered to check for prefixes. No text is yielded to the client during this phase.
2. **Processing:** Once the buffer is ready, the `_strip_prefixes_from_buffer` method is called **once**. This method
   applies the exact same ordered logic as the non-streaming `post_process_llm_output` function, including iterating
   through the arrays of custom prefixes.
3. **Streaming:** The cleaned text from the buffer is yielded to the client. From this point on, the prefix buffer is
   disabled, and all subsequent chunks from `$StreamingThinkRemover$` are yielded directly to the client without delay.

-----

## 3\. How to Add a New Rule

To add a new hardcoded prefix removal rule, you must add it to **both** the non-streaming and streaming logic to ensure
consistent behavior.

1. **Non-Streaming:** Add your logic to the sequence in `post_process_llm_output` in
   `Middleware/utilities/streaming_utils.py`.
2. **Streaming:** Add the identical logic to the `_strip_prefixes_from_buffer` method in
   `Middleware/workflows/streaming/response_handler.py`.

**Example:** Remove a `[DIAGNOSTIC]:` prefix.

```python
# In both post_process_llm_output and _strip_prefixes_from_buffer...

# ... (existing custom text and timestamp removals) ...

# NEW RULE: Add it here in the sequence
if content.startswith("[DIAGNOSTIC]:"):
    content = content[len("[DIAGNOSTIC]:"):].lstrip()

# ... (existing "Assistant:" prefix removal) ...
```

-----

## 4\. Summary of Logic Locations

| Feature / Rule                       | File for Non-Streaming Logic                       | File for Streaming Logic                              |
|--------------------------------------|----------------------------------------------------|-------------------------------------------------------|
| **Thinking Tags (start/end)**        | `streaming_utils.py` (`remove_thinking_from_text`) | `streaming_utils.py` (`StreamingThinkRemover`)        |
| **Workflow Custom Prefixes (Array)** | `streaming_utils.py` (`post_process_llm_output`)   | `response_handler.py` (`_strip_prefixes_from_buffer`) |
| **Endpoint Custom Prefixes (Array)** | `streaming_utils.py` (`post_process_llm_output`)   | `response_handler.py` (`_strip_prefixes_from_buffer`) |
| **Timestamp (`[Sent...ago]`)**       | `streaming_utils.py` (`post_process_llm_output`)   | `response_handler.py` (`_strip_prefixes_from_buffer`) |
| **"Assistant:" Prefix**              | `streaming_utils.py` (`post_process_llm_output`)   | `response_handler.py` (`_strip_prefixes_from_buffer`) |
| **Leading/Trailing Whitespace**      | `streaming_utils.py` (`post_process_llm_output`)   | `response_handler.py` (`_strip_prefixes_from_buffer`) |