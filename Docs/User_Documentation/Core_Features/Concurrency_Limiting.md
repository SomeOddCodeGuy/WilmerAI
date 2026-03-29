### **Feature Guide: Concurrency Limiting**

WilmerAI supports optional concurrency limiting via two command-line flags: `--concurrency` and `--concurrency-timeout`.
These flags cap the number of requests WilmerAI will process simultaneously. Requests that exceed the limit wait in a
queue until a slot opens or the timeout expires.

By default, concurrency is limited to 1 (serialized). This prevents resource contention on backend LLMs, which is the
common case for most WilmerAI deployments. To allow parallel requests, set `--concurrency 0` (no limit) or a higher
value.

-----

## Command-Line Flags

### `--concurrency N`

Sets the maximum number of requests that can be processed at the same time.

- **Default**: `1` (requests are serialized -- only one request is processed at a time)
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
- If a request waits for the full timeout duration without acquiring a slot, it is rejected with an HTTP 503 response.

-----

## Availability

Both flags are accepted by all WilmerAI entry points:

- `server.py` (Flask development server)
- `run_eventlet.py` (Eventlet production server)
- `run_waitress.py` (Waitress production server)
- `run_macos.sh` (macOS launcher script)
- `run_windows.bat` (Windows launcher script)

The launcher scripts forward these flags to the underlying Python entry point.

-----

## Rejected Request Response

When a request is rejected because the concurrency limit is reached and the timeout has elapsed, WilmerAI returns:

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

-----

## Scope

The concurrency limit applies to **all** endpoints exposed by WilmerAI. Every incoming request, regardless of path,
counts toward the limit. If a future health-check endpoint or other lightweight endpoint is added, it would also be
subject to the concurrency limit.

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
