### **Developer Guide: The Streaming Request Pipeline**

This guide provides a comprehensive walkthrough of the lifecycle of a streaming request in WilmerAI, from its arrival at
an API endpoint to the final Server-Sent Event (SSE) being delivered to the client. Understanding this data flow is
essential for developers aiming to extend or debug the platform's real-time response capabilities.

The architecture is founded on a clear separation of concerns:

* The **API Layer** (`Middleware/api/`) acts as the entry point, translating external request schemas into a
  standardized internal format.
* The **Workflow Engine** (`Middleware/workflows/`) orchestrates the overall logic, executing a series of steps defined
  in a JSON configuration.
* The **LLM API Layer** (`Middleware/llmapis/`) abstracts communication with various backend LLMs, returning a raw but
  standardized data stream.
* The **Stream Processing Layer** (`Middleware/workflows/streaming/`) is responsible for all final cleaning, formatting,
  and conversion of the raw stream into a client-ready SSE format.

-----

## 1\. Architectural Flow: The Journey of a Streaming Request

Let's trace a request made to the OpenAI-compatible `/v1/chat/completions` endpoint with `stream=true`.

### **Step 1: API Ingress and Transformation**

1. **Request Arrival:** An external client sends a POST request to `/v1/chat/completions`.

2. **Routing:** The `ApiServer` routes the request to the `ChatCompletionsAPI` `MethodView` within
   `openai_api_handler.py`.

3. **Initial Processing:** The `post()` method is executed.

    * It immediately sets a global variable, `instance_global_variables.API_TYPE = "openaichatcompletion"`, to inform
      downstream components which response schema to use.
    * It transforms the incoming JSON payload into the standardized internal `messages` list.
    * It calls `handle_user_prompt(messages, stream=True)` from `workflow_gateway.py`.
    * It immediately returns a Flask `Response` object, wrapping the generator returned by the gateway. This begins
      sending the response headers to the client while the backend processes the request.

   <!-- end list -->

   ```python
   # In Middleware/api/handlers/impl/openai_api_handler.py
   if stream:
       # The generator from the engine is returned directly to Flask
       return Response(
           handle_user_prompt(messages, stream=True),
           mimetype='text/event-stream'
       )
   ```

### **Step 2: Workflow Initiation and Execution**

1. **Gateway Handoff:** The `handle_user_prompt` function in `workflow_gateway.py` acts as the bridge to the logic
   engine, calling the `$WorkflowManager$`.
2. **Manager Setup:** The `$WorkflowManager$` (`workflow_manager.py`) is instantiated. It loads the relevant workflow
   JSON file and creates a registry mapping all valid node `type` strings to their corresponding handler class
   instances.
3. **Processor Delegation:** The manager creates an instance of `$WorkflowProcessor$` and delegates the execution to it,
   passing along the messages, stream flag, and all necessary dependencies.
4. **Execution Loop:** The `$WorkflowProcessor.execute()` method iterates through the nodes defined in the workflow.
    * **Context Creation:** For **each node**, the processor assembles a new, comprehensive `$ExecutionContext$` object.
      This dataclass contains the complete runtime state: the node's config, the full conversation history, outputs from
      previous nodes, and service references.
    * **Responder Identification:** The processor identifies the "responder" node (the one whose output is sent to the
      user), which is typically marked with `"returnToUser": true`.
    * **Handler Dispatch:** For the responder node, the processor passes the `$ExecutionContext$` to the appropriate
      node handler (e.g., `$StandardNodeHandler$`). The handler makes the final call to the LLM.

### **Step 3: LLM API Abstraction**

1. **Service Call:** The node handler calls the `$LlmApiService.get_response_from_llm()` method.
2. **Handler Factory:** The `$LlmApiService$` uses its `create_api_handler()` factory method to instantiate the correct
   `$LlmApiHandler$` (e.g., `$OllamaChatHandler$`) based on the endpoint's configuration.
3. **Streaming Request:** The service calls the handler's `handle_streaming()` method. The handler prepares the
   API-specific payload and uses the `requests` library to make the HTTP call with `stream=True`.
4. **Standardization:** As raw data chunks arrive from the LLM, the handler's `_process_stream_data()` method parses the
   API-specific format (e.g., line-delimited JSON or SSE) and `yield`s a **raw, standardized dictionary**:
   `{'token': str, 'finish_reason': str|None}`. This uncleaned, standardized generator is the sole output of the
   `llmapis` layer.

### **Step 4: Final Stream Processing and Formatting**

The raw dictionary generator travels back up to the `$WorkflowProcessor$`, which delegates it to the final stage.

1. **Handoff to Handler:** The processor passes the raw generator to an instance of `$StreamingResponseHandler$`.

   ```python
   # In Middleware/workflows/processors/workflows_processor.py
   if self.stream and isinstance(llm_result, Generator):
       stream_handler = StreamingResponseHandler(...)
       # The final, client-facing generator is produced here
       yield from stream_handler.process_stream(llm_result)
   ```

2. **Two-Stage Cleaning:** The `$StreamingResponseHandler.process_stream()` method in `response_handler.py` performs all
   user-facing stream cleaning in a two-stage process:

    * **Stage 1 (Continuous):** Every chunk from the raw generator is first passed to `$StreamingThinkRemover$`. This
      stateful helper identifies and removes content within `<think>...</think>` tags in real-time.
    * **Stage 2 (One-Time):** The handler buffers the *initial* clean chunks from Stage 1 to identify and strip any
      configured prefixes (e.g., `"Assistant: "`, or custom prefixes from the workflow/endpoint config). After this
      initial buffer is processed and yielded, all subsequent chunks pass through without delay.

3. **JSON Construction:** For each cleaned token, the handler calls `api_helpers.build_response_json()`. This helper
   function acts as a dispatcher. It reads the globally set `API_TYPE` and calls the appropriate method on the
   `$ResponseBuilderService$` (e.g., `build_openai_chat_completion_chunk()`) to construct the schema-compliant JSON
   chunk.

4. **SSE Formatting:** The resulting JSON string is passed to `api_helpers.sse_format()`, which prepends ` data:  ` to
   conform to the Server-Sent Event specification.

5. **Final Yield:** The handler `yield`s the final, clean, SSE-formatted string. This travels all the way back to the
   Flask `Response` object and is sent to the client.

-----

## 2\. Key Component Responsibilities

| Component                        | File Location                                 | Key Responsibility in Streaming                                                                                                                 |
|:---------------------------------|:----------------------------------------------|:------------------------------------------------------------------------------------------------------------------------------------------------|
| **API Handlers**                 | `Middleware/api/handlers/impl/`               | Translate the client request, set the global `API_TYPE`, and hand off to the `workflow_gateway`.                                                |
| **`$WorkflowProcessor$`**        | `workflows/processors/workflows_processor.py` | Orchestrate the workflow, create the `$ExecutionContext$` for each node, and delegate the raw LLM stream to the `$StreamingResponseHandler$`.   |
| **`$LlmApiService$`**            | `llmapis/llm_api.py`                          | Act as a factory to select the correct LLM handler and return a **raw, standardized generator of dictionaries**.                                |
| **`$StreamingResponseHandler$`** | `workflows/streaming/response_handler.py`     | Perform all **content cleaning** on the stream, including removing thinking tags and unwanted prefixes.                                         |
| **`$ResponseBuilderService$`**   | `services/response_builder_service.py`        | Act as the single source of truth for **constructing the final JSON payload** for each chunk, ensuring it matches the client's expected schema. |

-----

## 3\. How to Extend the Pipeline

The most common extension is adding a new text-cleaning rule to the stream. Because the logic is mirrored for streaming
and non-streaming responses, any new rule must be implemented in both places to ensure consistent behavior.

### **Example: Add a New `[DIAGNOSTIC]:` Prefix Removal Rule**

1. **Update Non-Streaming Logic:**

    * Open `Middleware/utilities/streaming_utils.py`.
    * Locate the `post_process_llm_output` function.
    * Add your new logic into the existing sequence of prefix removals.

   <!-- end list -->

   ```python
   # In streaming_utils.py -> post_process_llm_output()
   # ... after existing custom prefix removal ...

   # NEW RULE
   if content.startswith("[DIAGNOSTIC]:"):
       content = content[len("[DIAGNOSTIC]:"):].lstrip()

   # ... before existing "Assistant:" prefix removal ...
   ```

2. **Update Streaming Logic:**

    * Open `Middleware/workflows/streaming/response_handler.py`.
    * Locate the `_strip_prefixes_from_buffer` method.
    * Add the identical logic to this method, ensuring it appears in the same order as in the non-streaming function.

   <!-- end list -->

   ```python
   # In response_handler.py -> _strip_prefixes_from_buffer()
   # ... after existing custom prefix removal ...

   # NEW RULE (Identical logic)
   if content.startswith("[DIAGNOSTIC]:"):
       content = content[len("[DIAGNOSTIC]:"):].lstrip()

   # ... before existing "Assistant:" prefix removal ...
   ```

By adding the rule to both locations, you guarantee that the system will produce the same clean output regardless of
whether the user requested a streaming or non-streaming response.