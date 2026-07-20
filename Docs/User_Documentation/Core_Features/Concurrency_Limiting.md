### **Feature Guide: Concurrency Limiting**

WilmerAI supports optional concurrency limiting via three command-line flags: `--concurrency`,
`--concurrency-timeout`, and `--concurrency-level`. The first two cap the number of in-flight units and how long a
caller will wait for a slot. The third selects *where* the gate is enforced: at the WSGI front door
(`wilmer`, default) or around the outbound LLM API call inside the workflow (`endpoint`).

By default, concurrency is limited to 1 (serialized) and enforced at the request boundary. This prevents resource
contention on backend LLMs, which is the common case for most WilmerAI deployments. To allow parallel requests,
set `--concurrency 0` (no limit) or a higher value. To allow requests to overlap while still serializing the actual
LLM calls, set `--concurrency-level endpoint`.

-----

## Command-Line Flags

### `--concurrency N`

Sets the maximum number of requests that can be processed at the same time.

- **Default**: `1` (requests are serialized; only one request is processed at a time)
- **Type**: Integer, zero or positive
- When set to `1`, requests are serialized: each request must complete before the next one begins processing.
- When set to a value greater than `1`, up to N requests are processed concurrently. Additional requests wait in a
  queue until a slot becomes available.

### `--concurrency-timeout N`

Sets the maximum number of seconds a queued request will wait for a concurrency slot before being rejected.

- **Default**: `900` (15 minutes)
- **Type**: Integer, positive (must be greater than zero)
- The high default is intentional. WilmerAI proxies LLM inference calls that can take several minutes to complete,
  especially on local hardware running quantized models. A short timeout would cause unnecessary rejections during
  normal operation.
- If a request waits for the full timeout duration without acquiring a slot, it is rejected with an HTTP 503 response
  in `wilmer` mode, or the workflow node receives a `TimeoutError` in `endpoint` mode (which surfaces as a 500 unless
  the node has its own handling).
- Applies to whichever level the gate is currently enforced at (`--concurrency-level`).

### `--concurrency-level LEVEL`

Selects where the concurrency gate is enforced.

- **Default**: `wilmer`
- **Choices**: `wilmer`, `endpoint`
- `wilmer` (default): the semaphore is acquired at the WSGI middleware before a request reaches the workflow engine.
  Only `--concurrency` requests run at a time; any further requests wait in the queue and either acquire a slot or
  get rejected with a 503 after `--concurrency-timeout` seconds. This is the historical behaviour.
- `endpoint`: the request-level gate is lifted entirely. Many requests can be in flight at once, doing whatever
  non-LLM work their workflows require (file IO, HTTP calls to other services, memory lookups, etc.). The semaphore
  is instead acquired only around the *outbound LLM API call* inside `LlmApiService.get_response_from_llm`. The
  same `--concurrency` value still controls how many LLM calls can run simultaneously: with `--concurrency 1`
  (the default), one LLM call at a time, but as many concurrent workflows as you like otherwise.

### When to use `endpoint` mode

The single problem `endpoint` mode solves: **reentrant requests deadlocking against the request-level gate**.

A concrete example: imagine one Wilmer instance hosts both a chatbot user and a second user whose workflow calls out
to a service that loops back into Wilmer, both pointing at the same physical Mac. With `--concurrency 1` in default
(`wilmer`) mode:

1. The chatbot user issues request A. A acquires the gate and enters the workflow.
2. Inside its workflow, A calls out via HTTP to a separate helper service.
3. The helper service does its work and, to answer A, calls back into the same Wilmer instance as request B.
4. B blocks at the gate because A is still holding it.
5. A is blocked waiting for the helper service's HTTP response.
6. The helper service is blocked waiting for B. Deadlock.

Switch to `--concurrency-level endpoint` and the same scenario plays out cleanly:

1. A enters; the gate is *not* held because the workflow has not made an outbound LLM call yet.
2. A calls the helper service; the helper service calls back as B.
3. B enters; both A and B sit in their respective workflows.
4. Whichever workflow next reaches an outbound LLM call acquires the gate, makes the call, releases.
5. The two requests interleave their LLM calls; neither can deadlock the other.

If your Wilmer instances never make outbound calls that loop back into themselves, you do not need this mode. If they
do (reentrant integrations that call back into Wilmer), `endpoint` mode is the safe choice.

-----

## Availability

These flags are accepted by all WilmerAI entry points:

- `server.py` (Flask development server)
- `run_eventlet.py` (Eventlet production server)
- `run_waitress.py` (Waitress production server)
- `run_macos.sh` (macOS launcher script)
- `run_windows.bat` (Windows launcher script)

The launcher scripts forward these flags to the underlying Python entry point.

-----

## Rejected Request Response

When `--concurrency-level wilmer` (the default) is in effect and a request is rejected because the limit is reached
and the timeout has elapsed, WilmerAI returns:

- **HTTP status**: `503 Service Unavailable`
- **Response body**:

```json
{
  "error": {
    "message": "Server busy, concurrency limit reached",
    "type": "server_error",
    "code": 503
  }
}
```

When `--concurrency-level endpoint` is in effect, requests are never rejected at the gate; they simply wait inside
the workflow for an LLM-call slot. If an LLM call times out waiting for its slot, the workflow node raises a
`TimeoutError`. Without specific handling, this surfaces to the client as a generic 500.

-----

## Scope

The concurrency limit applies to **POST** endpoints only, the ones that dispatch requests to LLM backends. Lightweight
endpoints that return metadata or perform administrative actions are exempt and will never be blocked by the semaphore:

- **GET** endpoints (`/v1/models`, `/models`, `/api/tags`, `/api/version`): these return model lists and version info
  and are used by front-ends to populate UI elements. They are always available regardless of how many LLM requests are
  in flight.
- **DELETE** endpoints (`/api/generate`, `/api/chat`): these handle request cancellation and are always available.

This means a front-end can always query available models or cancel a running request, even while a long-running LLM
call is occupying all concurrency slots.

-----

## Practical Guidance

### Single-User Setups

Use `--concurrency 1` if you are running WilmerAI for a single user against a single backend LLM (local or remote).
This serializes all requests so that only one LLM call is in flight at a time, preventing resource contention on the
backend. This is the recommended setting for most local-hardware setups where a single GPU is serving inference.

### Multi-User or Multi-Backend Setups

Use a higher value (e.g., `--concurrency 4`) or set `--concurrency 0` (no limit) if your backend can handle
parallel requests. This applies to setups with multiple LLM backends or a cloud-hosted inference service.

When running multiple users from a single Wilmer instance (via repeated `--User` flags), the concurrency gate
applies to all users' requests. With `--concurrency 1`, requests from all users are serialized, which is
appropriate when all users share the same LLM hardware (e.g., a single Mac Studio). This is the primary advantage
of multi-user mode over running separate Wilmer instances: a single concurrency gate protects the shared hardware
regardless of which user is making the request.

In multi-user mode, the per-user `port` config setting is ignored. Use `--port` to specify the listening port
(defaults to `5050` if omitted).

In multi-user mode, when file logging is enabled via `--file-logging`, log output is automatically isolated per
user. Each user gets their own log file under a subdirectory of the logging directory:

```
logs/
    wilmerai.log              <- system/startup logs
    alice/wilmerai.log        <- Alice's request logs
    bob/wilmerai.log          <- Bob's request logs
```

This prevents one user's prompts and responses from appearing in another user's log file. In single-user mode,
the standard single `wilmerai.log` file is used (backward compatible).

-----

## Server-Specific Notes

### Waitress (`run_waitress.py`)

Waitress uses a thread pool (8 threads by default). When `--concurrency 1` is set, one thread processes the active
request while up to 7 threads block waiting for a concurrency slot. This is functionally correct and fine for
single-user use. The blocked threads consume minimal resources (they are idle, waiting on a semaphore). For multi-user
setups with a low concurrency value, be aware that the Waitress thread pool size places an upper bound on how many
requests can be queued inside the server process at once.

### Eventlet (`run_eventlet.py`)

Eventlet uses cooperative multitasking with lightweight greenlets rather than OS threads. Waiting for a concurrency slot
does not tie up a thread, so there is no thread-pool concern. Eventlet handles the queuing efficiently regardless of
the concurrency value.

-----

## Usage Examples

**macOS launcher with concurrency 1 (single-user, serialized):**

```bash
bash run_macos.sh --User myuser --concurrency 1
```

**Windows launcher with concurrency 1:**

```bat
run_windows.bat --User myuser --concurrency 1
```

**Python entry point with concurrency 2 and a 30-minute timeout:**

```bash
python3 server.py --User myuser --concurrency 2 --concurrency-timeout 1800
```

**Eventlet server with concurrency 4 and default timeout (15 minutes):**

```bash
python3 run_eventlet.py --User myuser --concurrency 4
```

**No concurrency limit (parallel requests allowed):**

```bash
python3 server.py --User myuser --concurrency 0
```

**Allow many concurrent requests but serialize the actual LLM calls (fixes reentrant deadlocks):**

```bash
python3 run_eventlet.py --User myuser --concurrency 1 --concurrency-level endpoint
```

This is the recommended setup for any Wilmer instance whose workflows make outbound calls to services that may, in
turn, call back into the same Wilmer instance.
