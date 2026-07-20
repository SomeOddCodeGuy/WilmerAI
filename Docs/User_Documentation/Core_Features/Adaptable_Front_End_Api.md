### **Feature Guide: WilmerAI's Adaptable API Gateway**

WilmerAI's Adaptable API Gateway acts as a compatibility layer for front-end applications. This allows you to connect
existing tools and UIs (like SillyTavern, OpenWebUI, or your own custom scripts) as if you were connecting directly to
industry-standard services like OpenAI or Ollama, without needing to learn a new API.

This means you can use your existing user interface while utilizing the multi-step workflow capabilities of the WilmerAI
engine on the backend.

-----

## How It Works: API Emulation

WilmerAI works by emulating the API schemas of popular LLM providers. It accepts requests in a familiar format,
processes them through its node-based workflow engine, and then packages the final response in the format the client
application expects.

The client application is not aware of the backend processing, which allows it to access more advanced capabilities.

**A typical flow looks like this:**

1. **Standard Request:** Your UI (e.g., OpenWebUI) sends a standard request to WilmerAI's `/api/chat` endpoint, as if it
   were communicating with an Ollama server.
2. **Internal Processing:** WilmerAI receives the request and passes it to its workflow engine. The engine may execute a
   chain of actions, like using a local model to extract keywords, searching a database, and then sending the results to
   a cloud model like GPT-4o for the final answer.
3. **Standard Response:** WilmerAI takes the final generated text and formats it into an Ollama-compliant JSON response.
4. **Display:** Your UI receives the formatted response and displays it to the user, unaware of the multi-LLM
   workflow that just occurred.

-----

## Supported API Endpoints

WilmerAI provides compatibility with commonly used API specifications.

### OpenAI API Compatibility (Recommended)

This is a widely adopted standard and provides significant flexibility. By pointing your OpenAI-compatible client at
WilmerAI's address, you can use the following endpoints:

* **`/v1/chat/completions`**: The primary endpoint for chat-based interactions. It supports message histories with
  roles (`user`, `assistant`). Supports cancellation via client disconnection (close the HTTP connection to stop
  the request).
* **`/v1/completions`**: The legacy endpoint for single-prompt text completion. Supports cancellation via client
  disconnection.
* **`/v1/models`**: Allows clients to query for a list of available models, which can be configured within WilmerAI.

### Ollama API Compatibility

For users whose tools and scripts are already integrated with the Ollama ecosystem.

* **`/api/chat`**: The standard endpoint for Ollama chat models.
* **`/api/generate`**: Used for direct text generation with a single prompt.
* **`/api/tags`**: Provides a list of available models, mirroring the behavior of a local Ollama server
* **`DELETE /api/chat`** and **`DELETE /api/generate`**: Cancel an in-progress request by sending a DELETE request with
  a JSON body containing `{"request_id": "your-request-id"}`. This immediately stops the request, even during prompt
  processing or streaming responses.

-----

## Key Features Available Through Any API

The following features of the WilmerAI engine are available regardless of the API standard used.

### Streaming and Non-Streaming Responses

Include the standard `stream=true` parameter in your API call to receive a token-by-token response, which is useful for
interactive chat applications. If `stream=false` (or omitted), WilmerAI will wait for the full response and return it in
a single block.

### Stateful Conversation Memory

WilmerAI can track conversation history across multiple requests. To enable this, include the `[DiscussionId]` tag
anywhere in your API call.

For example:

```json
{
  "model": "gpt-4o",
  "messages": [
    {
      "role": "user",
      "content": "[DiscussionId]my-unique-chat-session-123[/DiscussionId]\n\nHello, who are you?"
    }
  ]
}
```

WilmerAI will use this ID to load and save conversational memory, summaries, and other stateful data associated with
that specific chat.

### Per-User Encryption and Data Isolation

If your client sends an `Authorization: Bearer <key>` header with its requests, WilmerAI will store discussion files
in an isolated, per-key directory. If `encryptUsingApiKey` is enabled in the user config, files will also be encrypted
at rest. This allows multiple users or applications to share a single WilmerAI instance securely. See the **Per-User
Encryption** guide for details.

### Request Cancellation and Idempotent Retries

WilmerAI cancels backend generation when the requesting client goes away. If your client closes the HTTP connection
of a `/v1/chat/completions` (or `/v1/completions`) request, whether mid-stream or before the first token has been
sent, WilmerAI stops the associated backend generation and frees the slot it held. There is nothing to configure;
this happens for every client. (Ollama clients can additionally cancel explicitly with `DELETE /api/chat` or
`DELETE /api/generate`, described above.)

To make retries safe on a single-GPU backend, a client may send an idempotency header:

```
X-Idempotency-Key: 9f6c1c1e-8e42-4a6f-b1a2-3c4d5e6f7a8b
```

The contract is:

* Send **one** value per logical request, and reuse the **same** value across every retry of that request. Use a
  fresh value for each new logical request. An opaque string of at most 128 characters (a UUID4 is ideal); the
  header name is case-insensitive.
* Only retry after an attempt failed **before** its response started (a connection error, or an accepted connection
  that closed with no HTTP response). Never retry once tokens have begun arriving; replaying a half-delivered
  stream corrupts the transcript.

When WilmerAI receives a request whose key matches one that is still in flight, it treats the original as
abandoned: it cancels that original's backend generation immediately and serves the new request fresh. It never
splices or replays the old generation into the new response. This means a retry does not double-generate on the
backend. The header is optional: a client that omits it behaves exactly as before, protected by the
disconnect-cancellation above.

The idempotency key is applied to the OpenAI-compatible completion endpoints (`/v1/chat/completions` and
`/v1/completions`). Keys are only meaningful within a single running WilmerAI instance; they are not persisted
across restarts.

### Access to Complex Workflows

A simple API call can trigger a backend workflow. The client does not need to be aware of the workflow's structure. It
sends a message and gets a response, while WilmerAI handles the orchestration of multiple models, tools, and memory
systems in the background.

-----

## The Next Step: Backend Connections

Once your request is received through the Adaptable API Gateway, it's processed by WilmerAI's workflow engine, which can
in turn connect to a variety of backend LLMs.

To learn more about how WilmerAI manages these backend connections, see our guide on the **Adaptable LLM Connector**.