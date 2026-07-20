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
    * **Standard Mode**: It looks for a `startThinkTag` that **starts** within the grace window (see "Grace Window
      Semantics" below). If a qualifying opening tag is found, the first `endThinkTag` after it closes the block, and
      the entire block (including tags) is removed. Only **one** think block is ever removed; any tags appearing after
      the first block's closing tag are left untouched. If no qualifying opening tag exists, or the closing tag is
      missing, the **original text is returned unmodified**.
    * **`expectOnlyClosingThinkTag` Mode**: If this flag is `True`, the function searches for the `endThinkTag` only. If
      found, it discards everything up to and including the **first** closing tag and returns only the content that
      follows. If the tag is not found, the **original text is returned unmodified**.
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

### **Grace Window Semantics**

`openingTagGracePeriod` (default: `100`) decides whether a think block counts as starting "at the beginning" of the
response. The rule, applied identically by both the streaming and non-streaming paths, is: **the opening tag qualifies
if it starts at 0-based character index `openingTagGracePeriod` or earlier**. The tag does not need to *end* inside the
window; a tag whose first character lands inside the window but whose last character falls beyond it still qualifies.

This is a deliberate reconciliation decision. Historically the two paths disagreed: the non-streaming path required the
entire opening tag to end inside the window, and the streaming result could change depending on where chunk boundaries
happened to fall. The start-based rule was chosen because the window's purpose is to locate where the block *begins*.
To guarantee the streaming outcome is independent of chunk sizes, `StreamingThinkRemover` holds its buffer until
`openingTagGracePeriod + len(startThinkTag)` characters have accumulated before concluding that no qualifying tag will
appear. Parity between the two paths is enforced by a parametrized test
(`TestStreamingNonStreamingParity` in `Tests/utilities/test_streaming_utils.py`) that runs a battery of inputs through
both implementations at multiple chunk sizes, including one character at a time.

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

* **Standard Mode**: The remover buffers initial chunks while it decides whether a think block starts at the beginning
  of the response. A `startThinkTag` qualifies if it **starts** within the grace window (see "Grace Window Semantics"
  above); the remover holds up to `openingTagGracePeriod + len(startThinkTag)` characters before giving up, so a
  qualifying tag split across chunk boundaries at the window's edge is still caught. If a qualifying tag is found, it
  enters a "thinking" state and discards all subsequent text until the `endThinkTag` is found, after which all
  remaining text passes through untouched; only **one** block is ever removed. If the window is crossed without a
  qualifying tag, the remover stops looking and passes all future text through untouched. If the stream ends with an
  unterminated think block, the remover flushes the opening tag plus the buffered content, reconstructing the original
  text.
* **`expectOnlyClosingThinkTag` Mode**: The remover buffers all text until it finds the `endThinkTag`. Once the tag is
  found, it discards everything up to and including the tag and begins yielding all subsequent text. If the stream ends
  without the tag ever appearing, the full buffered text is returned at finalization.

The rest of the system only sees the "clean" stream output by `$StreamingThinkRemover$`.

#### **Stage 2: Prefix Removal (One-Time at Start)**

The `$StreamingResponseHandler$` takes the cleaned stream from Stage 1 and performs a one-time buffering operation to
handle all other prefix removals.

1. **Buffering:** It collects the initial chunks from `$StreamingThinkRemover$` into its own `_prefix_buffer` until a
   sufficient amount of text is gathered to check for prefixes. No text is yielded to the client during this phase.
2. **Processing:** Once the buffer is ready, the `_process_prefixes_from_buffer` method is called **once**. After
   applying group-chat reconstruction, it delegates to the same `strip_leading_response_prefixes` function
   (in `Middleware/utilities/streaming_utils.py`) that the non-streaming `post_process_llm_output` uses, so the
   two paths share one ordered implementation of the prefix rules.
3. **Streaming:** The cleaned text from the buffer is yielded to the client. From this point on, the prefix buffer is
   disabled, and all subsequent chunks from `$StreamingThinkRemover$` are yielded directly to the client without delay.

### **Tool Call Chunks: Pipeline Bypass**

When a chunk from the LLM handler contains a `tool_calls` key, the `$StreamingResponseHandler$` skips both cleaning
stages entirely. The chunk is formatted directly into an SSE message and emitted to the client without passing through
`$StreamingThinkRemover$` or the prefix buffer. This is intentional: tool call data is structured JSON, not natural
language text, and applying prefix stripping, think-block removal, or group chat reconstruction to it would corrupt
the payload. Once a tool call chunk with a `finish_reason` is received, the stream terminates immediately.

Two interactions with the text pipeline are handled explicitly (`_drain_pending_text`):

1. **Ordering:** Text still held in the prefix buffer when a tool-call chunk arrives is flushed and emitted *before*
   the tool call, so the client sees content in generation order. An empty buffer is left untouched mid-stream, so
   prefix stripping stays armed for text that follows the tool call.
2. **Stream ending on a tool-call chunk:** If the tool-call chunk carries the `finish_reason`, the normal
   finalization block is skipped, so the handler finalizes the think remover and flushes the prefix buffer at that
   point instead; buffered text is emitted rather than silently dropped.

**Ollama front-ends (`ollamaapichat`):** Ollama's chat protocol has no delta form for tool calls: clients expect
each call as one complete object with `arguments` as a JSON object. The handler therefore accumulates OpenAI-style
tool-call deltas (keyed by delta index, argument fragments concatenated) instead of forwarding them, and emits the
complete calls in Ollama's native shape on the terminal `done: true` chunk. Other output formats keep the
passthrough-delta behavior.

-----

## 3\. How to Add a New Rule

Prefix removal rules live in one place: `strip_leading_response_prefixes` in
`Middleware/utilities/streaming_utils.py`. Both the non-streaming `post_process_llm_output` and the streaming
`_process_prefixes_from_buffer` (in `Middleware/workflows/streaming/response_handler.py`) call it, so a rule added
there applies to both paths automatically.

**Example:** Remove a `[DIAGNOSTIC]:` prefix.

```python
# In strip_leading_response_prefixes...

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
| **Workflow Custom Prefixes (Array)** | `streaming_utils.py` (`strip_leading_response_prefixes`, shared) | same shared function, called from `response_handler.py` (`_process_prefixes_from_buffer`) |
| **Endpoint Custom Prefixes (Array)** | `streaming_utils.py` (`strip_leading_response_prefixes`, shared) | same shared function |
| **Timestamp (`[Sent...ago]`)**       | `streaming_utils.py` (`strip_leading_response_prefixes`, shared) | same shared function |
| **"Assistant:" Prefix**              | `streaming_utils.py` (`strip_leading_response_prefixes`, shared) | same shared function |
| **Leading/Trailing Whitespace**      | `streaming_utils.py` (`post_process_llm_output`)   | `response_handler.py` (`_process_prefixes_from_buffer`) |