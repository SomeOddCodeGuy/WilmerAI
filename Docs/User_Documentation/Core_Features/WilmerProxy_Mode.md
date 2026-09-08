# WilmerProxy Mode

WilmerProxy mode lets one WilmerAI instance expose a controlled subset of workflows from another WilmerAI instance.
It is intended for a layout such as:

```text
Front end
  -> WilmerProxy filter instance with a limited model list
  -> Main WilmerAI instance with the complete workflow set
  -> Configured backend APIs
```

The WilmerProxy instance serves ordinary OpenAI-compatible URLs, but it does not run a workflow. It validates the public
model alias, changes that alias to the configured model name for the main instance, and relays the request and response.

## Create a WilmerProxy configuration

Copy `Public/Configs/WilmerProxy/_example.json` to a new file such as
`Public/Configs/WilmerProxy/frontend-filter.json`:

```json
{
  "port": 5050,
  "useFileLogging": false,
  "upstreams": {
    "main": {
      "baseUrl": "http://127.0.0.1:5060",
      "authorizationMode": "passthrough",
      "forwardHeaders": [
        "X-Idempotency-Key"
      ],
      "connectTimeoutSeconds": 10,
      "readTimeoutSeconds": 14400,
      "verifyTls": true
    }
  },
  "models": {
    "general": {
      "upstream": "main",
      "targetModel": "chat-ui:general"
    },
    "task": {
      "upstream": "main",
      "targetModel": "chat-ui:task"
    }
  }
}
```

`main` is a name local to this WilmerProxy configuration. It can be renamed, and it is not part of the model value sent
to the main WilmerAI instance. Each `targetModel` must be the exact model identifier accepted by its selected upstream,
including the WilmerAI `user:workflow` prefix when that instance requires one.

Only the keys in `models` are listed for model discovery and accepted for selection. In this example, clients can
select `general` and `task`. Upstream JSON and streaming response bodies are relayed unchanged and can contain the
upstream model name. The aliases restrict selection; they do not conceal names in response bodies.

## Start the WilmerProxy instance

Pass the WilmerProxy mode and configuration name through the normal launcher:

```bash
./run_macos.sh --Mode WilmerProxy --WilmerProxyConfig frontend-filter
```

With the installation's virtual environment activated, the equivalent direct command is:

```bash
python run_eventlet.py --Mode WilmerProxy --WilmerProxyConfig frontend-filter
```

On Windows, the same options can be passed to `run_windows.bat`.

`--WilmerProxyConfig` is a filename without `.json`. WilmerProxy mode does not require `--User`. Workflow, endpoint,
preset, routing, memory, and LLM API configurations are not used by the WilmerProxy instance.

The config's `port` is used unless `--port` is supplied. The config's `useFileLogging` value is used unless the
`--file-logging` flag is supplied. `--PublicDirectory`, `--ConfigDirectory`, `--LoggingDirectory`, `--listen`, and the
request concurrency options continue to apply.

In WilmerProxy mode, endpoint-level concurrency selection also uses the request gate, held until the response is
consumed or closed. Proxy requests do not enter the workflow engine's endpoint gate. Connect and read timeout values
must be finite positive numbers; NaN, infinity and overflowing numeric values fail configuration validation.

## Supported client endpoints

WilmerProxy mode exposes only these OpenAI-compatible routes:

- `GET /v1/models`
- `GET /models`
- `POST /v1/chat/completions`
- `POST /chat/completions`
- `POST /v1/completions`
- `POST /completions`

The model routes are generated locally from the configured aliases. Ollama-compatible routes are not registered in
WilmerProxy mode.

## Request and response behavior

For a completion request, WilmerProxy mode:

1. Requires a valid JSON object with a non-empty string `model`.
2. Rejects any model that is not in the configured `models` map.
3. Selects the model's configured upstream.
4. Replaces only the top-level `model` value with `targetModel`.
5. Sends the full resulting JSON object to the upstream route.
6. Relays the upstream status, body, error body, and permitted response headers.

Messages, multimodal content blocks, tools, tool choice, sampling values, response format, stream options, reasoning
settings, metadata, and extension fields remain present. The JSON is parsed and serialized again, so insignificant
formatting, object key order, and duplicate object keys are not preserved. Valid JSON values and structure are
preserved except for the intentional `model` mapping.

When `stream` is exactly `true`, successful upstream response chunks are relayed without parsing or rebuilding the
SSE events. If the client disconnects, WilmerProxy closes its upstream response. WilmerProxy mode does not retry
generation requests and does not follow redirects.

Redirect bodies remain under the same relay and cleanup policy. If an upstream Location or Content-Location header
contains a URL that the response serializer cannot represent, WilmerProxy omits that header and still relays the
upstream status and body. Valid URL headers remain available to the client.

## Authorization modes

Each upstream has one explicit authorization policy:

| Value | Behavior |
|---|---|
| `passthrough` | Forward the client's `Authorization` header when present. |
| `configured` | Replace any client authorization with `Authorization: Bearer <apiKey>` from the WilmerProxy config. |
| `omit` | Do not send an Authorization header upstream. |

Use `passthrough` when the main WilmerAI instance uses the client API key for discussion isolation or encryption. Use
`configured` only when every client should share one upstream credential and one downstream identity. The configured
API key is stored as plain text in the WilmerProxy JSON file, so protect that file appropriately.

`forwardHeaders` is an allowlist for additional request headers. It defaults to `X-Idempotency-Key`. Authorization,
host, content length, content type, and hop-by-hop headers are managed by WilmerProxy and cannot be placed in this list.

## Multiple upstreams

More than one upstream can be defined. Each public alias independently selects one:

```json
{
  "upstreams": {
    "main": {
      "baseUrl": "http://127.0.0.1:5060",
      "authorizationMode": "passthrough"
    },
    "specialized": {
      "baseUrl": "http://127.0.0.1:5070",
      "authorizationMode": "configured",
      "apiKey": "replace-with-the-upstream-key"
    }
  },
  "models": {
    "general": {
      "upstream": "main",
      "targetModel": "chat-ui:general"
    },
    "analysis": {
      "upstream": "specialized",
      "targetModel": "research:analysis"
    }
  }
}
```

The top-level `port` and `useFileLogging` fields may be omitted when their defaults of `5050` and `false` are suitable.
Timeout and TLS fields may also be omitted. Their defaults are a 10 second connection timeout, a 14,400 second read
timeout, and TLS certificate verification enabled.
