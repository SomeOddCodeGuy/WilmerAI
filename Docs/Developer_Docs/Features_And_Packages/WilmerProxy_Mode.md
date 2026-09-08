# Developer Guide: WilmerProxy Mode

## Purpose and boundary

WilmerProxy mode provides an allowlisted OpenAI-compatible relay between a client and one or more operator-configured
WilmerAI instances. Its central invariant is that a proxied request does not enter normal WilmerAI workflow processing.

The request path is:

```text
Flask route
  -> WilmerProxyOpenAIApiHandler
  -> model allowlist lookup and top-level model replacement
  -> WilmerProxyTransport
  -> configured upstream WilmerAI
```

It does not call `workflow_gateway.handle_user_prompt`, `WorkflowManager`, `WorkflowProcessor`,
`LLMDispatchService`, `LlmApiService`, any `llmapis` handler, or `ResponseBuilderService`.

## Runtime selection and startup

`Middleware/common/launch_arguments.py` accepts:

- `--Mode Workflow`, the default existing behavior
- `--Mode WilmerProxy --WilmerProxyConfig <name>`, the dedicated relay behavior

The selected values are stored in `instance_global_variables.RUNTIME_MODE` and `WILMER_PROXY_CONFIG`.

During WilmerProxy startup:

- The selected config is validated before the API server is created.
- User config validation and workflow-lock cleanup are skipped.
- `resolve_port()` uses the WilmerProxy config's `port` after the CLI override.
- `resolve_file_logging()` uses the WilmerProxy config's `useFileLogging` after the CLI override.
- Request concurrency middleware remains available because it is a server boundary, not workflow processing.

`ApiServer` imports only `wilmer_proxy_openai_api_handler.py` when the active mode is `wilmerproxy`. In workflow mode,
it excludes that module and registers the existing OpenAI and Ollama handlers. The class-level `SUPPORTED_MODES`
property provides
a second registration guard. The base handler defaults to `{"workflow"}`, while `WilmerProxyOpenAIApiHandler` declares
`{"wilmerproxy"}`.

Restricting module import is intentional. The normal OpenAI and Ollama handler modules import the workflow gateway and
workflow-facing services, which WilmerProxy mode must not initialize as part of its request stack.

## Configuration model

`Middleware/wilmer_proxy/config.py` owns strict parsing of `Public/Configs/WilmerProxy/<name>.json`.

The top-level structure is:

```json
{
  "port": 5050,
  "useFileLogging": false,
  "upstreams": {},
  "models": {}
}
```

An upstream contains:

| Field | Required | Default | Meaning |
|---|---:|---:|---|
| `baseUrl` | Yes | none | Absolute HTTP or HTTPS URL. Trailing slash is normalized away. |
| `authorizationMode` | No | `passthrough` | `passthrough`, `configured`, or `omit`. |
| `apiKey` | Only for `configured` | none | Credential used by configured authorization. Rejected in other modes. |
| `forwardHeaders` | No | `["X-Idempotency-Key"]` | Explicit additional request-header allowlist. |
| `connectTimeoutSeconds` | No | `10` | Positive TCP/TLS connection timeout. |
| `readTimeoutSeconds` | No | `14400` | Positive upstream response read timeout. |
| `verifyTls` | No | `true` | Requests TLS certificate validation setting. |

Each model entry requires `upstream` and `targetModel`. Upstream names are config-local identifiers. Public model names
and target model values are separate so WilmerAI's existing colon-delimited `user:workflow` syntax is never overloaded.

The parser rejects unknown fields, empty maps, missing references, unsafe flat config names, unsupported URL schemes,
embedded URL credentials, query strings, URL fragments, invalid timeouts, invalid ports, and managed or hop-by-hop
headers in `forwardHeaders`. A malformed WilmerProxy configuration fails startup rather than leaving a partially
registered server.

## Request processing

`WilmerProxyOpenAIApiHandler` registers model-list aliases and both prefixed and unprefixed chat/completion POST
routes. The unprefixed POST aliases still target the canonical upstream `/v1/...` paths.

For POST requests, the handler:

1. Reads and parses the complete JSON body while rejecting nonstandard constants such as `NaN`.
2. Requires the body to be an object and `model` to be a non-empty string.
3. Resolves `model` against `WilmerProxyConfig.models`.
4. Replaces only the top-level `model` value.
5. Serializes the complete mapped object with standard JSON values only.
6. Calls `WilmerProxyTransport.open_request()` with the canonical path and incoming headers.

Local validation errors use an OpenAI-style `error` object. Unknown aliases return 404. Invalid JSON or model fields
return 400. A transport connection failure returns 502 without including the upstream exception or configured URL in
the client response.

Parsing and serialization preserve JSON semantics, not byte representation. Whitespace, key order, and duplicate JSON
object keys are not part of the WilmerProxy contract. Every supported JSON value other than the mapped model remains
in the payload, including fields unknown to this WilmerAI version.

## Header and transport policy

`Middleware/wilmer_proxy/transport.py` creates a new `requests.Session` for each upstream request. It sets `trust_env` to
false so environment proxy settings and netrc credentials cannot silently affect the configured connection. The
transport does not install retry adapters, passes `allow_redirects=False`, requests a streaming-capable response, and
sets `Accept-Encoding: identity`. It also calls `disable_session_redirects` on its private session. Requests otherwise
prepares `Response.next`, reads redirect bodies and parses Location even with `allow_redirects=False`. The helper
keeps response-body consumption under the relay owner's control without issuing a second request.

Request headers are constructed rather than copied wholesale:

- `Content-Type` is preserved, defaulting to `application/json`.
- `Accept` is preserved when present.
- Authorization follows the upstream's explicit mode.
- Only configured `forwardHeaders` are copied.
- Host, content length, transfer encoding, connection controls, and proxy authorization are never copied.

Authorization values and request bodies are not logged.

## Response relay and resource ownership

The upstream request always opens with `stream=True` so the handler controls buffering. For a non-streaming client, or
for any upstream response with status 400 or higher, the body is buffered and returned with the original status.
Successful responses to a client that sent JSON boolean `stream: true` use a generator over `iter_content()`.

SSE chunks are yielded as bytes without JSON or SSE parsing. WilmerProxy does not regenerate chunk IDs, timestamps,
finish reasons, usage, or error objects from the upstream response.

Hop-by-hop response headers, including names nominated by Connection tokens, content length, and content encoding are
removed. Location and Content-Location are normalized with Werkzeug's URI serializer before constructing the response.
An invalid URL header that the serializer cannot represent is omitted, with a diagnostic that excludes its value.
This prevents a late WSGI serialization failure while preserving the upstream status and body. Other response headers
are returned.
Content encoding is removed because the transport explicitly requests identity encoding and the HTTP client can decode
an encoded response before Flask receives it.

The handler owns both the upstream response and its session. Non-streaming paths close them after buffering. Streaming
paths close them in the generator's `finally` block and register an idempotent Flask `call_on_close` callback so normal
completion, iteration failure, and client disconnect all release the upstream connection. The response uses Werkzeug's
normal closing iterator, so closing the WSGI iterable before its first yield also invokes the callback.

ConcurrencyLimitMiddleware keeps the request gate active in proxy mode even if CONCURRENCY_LEVEL is endpoint.
WilmerProxy does not use LlmApiService's endpoint gate. Both configured timeouts must be finite positive numbers.

## Testing expectations

Tests for this feature are split across:

- `Tests/wilmer_proxy/test_wilmer_proxy_config.py`
- `Tests/wilmer_proxy/test_wilmer_proxy_transport.py`
- `Tests/wilmer_proxy/test_proxy_redirect_boundaries.py`
- `Tests/api/handlers/impl/test_wilmer_proxy_openai_api_handler.py`
- mode-specific additions to launch, API server, and startup tests

Basic transport tests mock `requests.Session`; handler tests inject a recording transport. Redirect boundary tests use
real Requests sessions with in-memory adapters and the real Flask relay. WilmerProxy tests must never make real network
calls. Important regression invariants are allowlist enforcement before transport, exact target-model mapping,
preservation of otherwise unknown JSON fields, explicit header policy, raw streamed bytes, upstream error relay,
connection-failure handling, and exactly-once connection closure.

## Extension rules

New WilmerProxy routes should stay in a WilmerProxy-only handler and use the dedicated transport. They must not reuse
the workflow handlers or `llmapis`, because those layers intentionally normalize requests and responses. If a new route cannot
preserve its payload while performing only the minimum policy inspection, document its transformations explicitly.

Adding a new forwarded header must remain an operator choice in `forwardHeaders`. Do not broaden the default request
header set or add implicit credentials, environment routing, telemetry, redirects, or retries.
