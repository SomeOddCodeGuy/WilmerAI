### **Feature Guide: WilmerAI's Adaptable API Gateway**

WilmerAI's Adaptable API Gateway acts as a compatibility layer for front-end applications. This allows you to connect
existing tools and UIs—like SillyTavern, OpenWebUI, or your own custom scripts—as if you were connecting directly to
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
   chain of actions—like using a local model to extract keywords, searching a database, and then sending the results to
   a cloud model like GPT-4o for the final answer.
3. **Standard Response:** WilmerAI takes the final generated text and formats it into an Ollama-compliant JSON response.
4. **Seamless Display:** Your UI receives the formatted response and displays it to the user, unaware of the multi-LLM
   workflow that just occurred.

-----

## Supported API Endpoints

WilmerAI provides compatibility with commonly used API specifications.

### OpenAI API Compatibility (Recommended)

This is a widely adopted standard and provides significant flexibility. By pointing your OpenAI-compatible client at
WilmerAI's address, you can use the following endpoints:

* **`/v1/chat/completions`**: The primary endpoint for chat-based interactions. It supports message histories with
  roles (`user`, `assistant`).
* **`/v1/completions`**: The legacy endpoint for single-prompt text completion.
* **`/v1/models`**: Allows clients to query for a list of available models, which can be configured within WilmerAI.

### Ollama API Compatibility

For users whose tools and scripts are already integrated with the Ollama ecosystem.

* **`/api/chat`**: The standard endpoint for Ollama chat models.
* **`/api/generate`**: Used for direct text generation with a single prompt.
* **`/api/tags`**: Provides a list of available models, mirroring the behavior of a local Ollama server.

-----

## Key Features Available Through Any API

The following features of the WilmerAI engine are available regardless of the API standard used.

### Streaming and Non-Streaming Responses

Include the standard `stream=true` parameter in your API call to receive a token-by-token response, which is useful for
interactive chat applications. If `stream=false` (or omitted), WilmerAI will wait for the full response and return it in
a single block.

### Stateful Conversation Memory

WilmerAI can track conversation history across multiple requests. To enable this, include the `[DiscussionId]` tag in
the **first user message** of your API call.

For example:

```json
{
  "model": "gpt-4o",
  "messages": [
    {
      "role": "user",
      "content": "[DiscussionId] my-unique-chat-session-123\n\nHello, who are you?"
    }
  ]
}
```

WilmerAI will use this ID to load and save conversational memory, summaries, and other stateful data associated with
that specific chat.

### Access to Complex Workflows

A simple API call can trigger a backend workflow. The client does not need to be aware of the workflow's structure. It
sends a message and gets a response, while WilmerAI handles the orchestration of multiple models, tools, and memory
systems in the background.

-----

## The Next Step: Backend Connections

Once your request is received through the Adaptable API Gateway, it's processed by WilmerAI's workflow engine, which can
in turn connect to a variety of backend LLMs.

To learn more about how WilmerAI manages these backend connections, see our guide on the **Adaptable LLM Connector**.