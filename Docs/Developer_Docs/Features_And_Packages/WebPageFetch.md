# WebPageFetch

## Purpose and Boundary

`WebPageFetch` is the page-oriented outbound HTTP workflow node. It retrieves one public HTML, XHTML, or plain-text
resource while applying default-on destination validation, robots policy, domain pacing, redirects, response bounds,
and server cooldowns.

It is intentionally separate from `WebFetch`. `WebFetch` remains a general HTTP/API client with arbitrary methods,
headers, bodies, JSON output, and Requests or curl transport. Do not add robots policy to `WebFetch` or route API calls
through `WebPageFetch` implicitly.

The following are hard invariants rather than node toggles:

- GET only, with no request body.
- No workflow-supplied destination headers, authentication, cookies, Referer, or identity. An explicitly configured
  proxy may have its own credentials.
- No automatic retries.
- No automatic subresource retrieval.
- No persistent session or on-disk browsing state.

## Python compatibility

The parser adapter requires the RFC 9309 implementation introduced in Python 3.13.14 and 3.14.5. It accesses
`RobotFileParser.groups`, `_find_entry`, `RuleLine.fullmatch`, and `robotparser.translate_pattern`. These are
implementation details rather than a stable cross-version contract. Keep compatibility checks when changing the
supported interpreter range. Earlier interpreters such as 3.11.10 and 3.12.13 raise `AttributeError` while parsing
even an ordinary robots.txt document because `groups` is absent.

This higher requirement applies to workflows that execute `WebPageFetch`. Existing installations without that node
are expected to continue working on 3.11.10+ within 3.11 or 3.12.13+ within 3.12. The general `WebFetch` and
`CurlCommand` nodes do not use this parser. Full dependency installations and the full suite on these older
versions remain unverified.

The project development pin is 3.14.6. A complete dependency installation and full-suite compatibility on
3.13.14 remain unverified.

## Source Map

| File | Role |
|:-----|:-----|
| `Middleware/services/web_page_fetch_service.py` | Stateful process-wide page policy, HTTP transport, robots cache, domain lanes, redirects, cooldowns, and bounded decoding. |
| `Middleware/workflows/handlers/impl/web_page_fetch_handler.py` | Node config validation, variable substitution, policy construction, output formatting, and streaming wrapper. |
| `Middleware/common/constants.py` | Adds `WebPageFetch` to `VALID_NODE_TYPES`. |
| `Middleware/workflows/managers/workflow_manager.py` | Constructs `WebPageFetchHandler` and registers it under the `WebPageFetch` type. |
| `Middleware/utilities/network_security_utils.py` | Shared hostname resolution and non-public-address rejection used before every connection. |
| `Tests/services/test_web_page_fetch_service.py` | Deterministic service tests with fake sessions, responses, bodies, DNS policy, clock, and sleeps. |
| `Tests/workflows/handlers/impl/test_web_page_fetch_handler.py` | Handler validation, policy mapping, formatting, and error tests. |
| `Tests/workflows/managers/test_workflow_manager.py` | Registry and `VALID_NODE_TYPES` lockstep assertion. |

## Registration and Lifetime

`WorkflowManager` creates a handler for each manager instance. Unless a service is injected for a test, the handler
calls `get_default_web_page_fetch_service()`. That accessor returns a process-wide singleton protected by a lock.

The singleton is needed because robots caching, pacing, and cooldowns must apply across workflows, not merely within a
single node execution. Its state is memory-only:

- `_robots_cache` is keyed by origin and all policy values, including proxy, TLS verification, address/port rules,
  redirect policy and response limits. A least-recently-used cap retains at most 1024 records; eviction requires a new
  robots fetch and never grants permission by itself.
- `_origin_locks` uses 64 fixed SHA-256 buckets for single-flight robots retrieval. Collisions serialize unrelated misses.
- `_domain_lanes` uses 1024 fixed SHA-256 buckets of conservative domain keys. Collisions share pacing and cooldowns,
  which can reduce throughput but cannot erase an active cooldown. No unbounded hostname registry is retained.

Restarting the process clears all three structures. The service does not write visited URLs, hostnames, robots files,
or cooldowns to disk.

## Handler Flow

`WebPageFetchHandler.handle()` performs only configuration work:

1. Require a non-empty string `url`.
2. Enforce GET-only, bodyless, headerless, Requests-only invariants.
3. Validate output and error modes.
4. Apply workflow variables to the URL and selected string/list fields.
5. Build an immutable `WebPageFetchPolicy` whose omitted booleans remain enabled.
6. Call the shared service.
7. Format the result as text, stripped HTML text, or a JSON envelope.
8. Convert a `WebPageFetchError` to output only when `onError` is `return`.
9. Wrap the final string with `maybe_stream` when the execution context is streaming.

Configuration errors remain `ValueError` and are not converted by `onError`. That prevents a misspelled or invalid
security setting from silently becoming ordinary workflow data.

The handler reuses `_strip_html` from `web_fetch_handler.py`; the extractor skips `script`, `style`, `head`, `noscript`,
and `iframe` contents. It is not an HTML sanitizer or main-content detector.

## Retrieval State Machine

`WebPageFetchService.fetch()` processes the requested page and each redirect hop in this order:

1. `_validate_url()` normalizes and checks the current target.
2. `_robots_record_for()` reads a valid cached record or performs one robots retrieval under the origin lock.
3. `_enforce_robots()` checks `Allow` and `Disallow` and calculates the selected agent's robots interval.
4. `_pace()` serializes the domain lane and waits for the maximum applicable interval.
5. `_open_response()` creates a new stateless Requests session and sends one streamed GET with automatic redirects
   disabled.
6. The service records received 403/429/503 cooldown state, then bounds response headers. A rejected header
   collection cannot discard an already observed restriction. Retry-After accepts ASCII integer seconds or an HTTP date.
   Invalid values, including non-ASCII digit characters, and values over 128 characters use the configured fallback.
7. A redirect is resolved and returned to step 1. A cross-origin destination therefore receives a new robots check.
8. A final response rejects non-2xx status and checks Content-Type before
   reading the body.
9. `_read_bounded_body()` counts transferred bytes, incrementally decodes gzip or deflate, and counts decoded bytes.
10. The service returns bytes and public response metadata. The `finally` block closes the response and session.

There is no retry loop. The only loop in page retrieval is the bounded redirect loop.

Location resolution uses `redirect_policy.resolve_redirect_url` to decode UTF-8 header bytes before URL joining,
canonicalization and destination checks. This applies to both page and robots redirects; invalid encoding follows
the same error policy as an invalid redirect URL.

URL splitting and Location resolution translate parser errors into `WebPageFetchError`. Page failures therefore honor
the handler's `onError` setting. Robots URL normalization, redirect resolution and directive parsing failures are
cached as failed permission checks and follow `failClosedOnRobotsError`; no rejected robots target is contacted.
Robots numeric directives require ASCII digits and finite values. Invalid Content-Length text does not replace the
streamed byte limit; numeric conversion failures stay within the fetch error contract.

Both the service and handler use the request-sensitive logger. Remote metadata included in errors, including rejected
Content-Type or Content-Encoding values, is redacted in diagnostics when request redaction is active. This includes
the service warning emitted when an operator permits a page after a robots failure.

## URL and SSRF Policy

URL validation occurs before every page and robots connection. It requires:

- An absolute HTTP or HTTPS URL.
- A hostname and no embedded username or password.
- No backslash, whitespace, control character, or IPv6 zone identifier.
- The scheme's default port, unless `allowedPorts` or `restrictPorts: false` permits another.
- A host accepted by `allowedHosts` when that list is configured.
- A globally routable address when `blockPrivateAddresses` is true.

Fragments are discarded before requests. Hostnames are lowercased and IDNA-encoded. Default ports are removed from the
normalized URL and origin key.

Before address and robots checks, `_canonicalize_transport_url()` applies Requests URL preparation until the URL
is stable, with at most three preparation attempts and no I/O. Preparation can decode unreserved escapes that expose
dot segments for a subsequent pass. An unstable or invalid URL raises `WebPageFetchError`. The stable URL is used for
authorization, transport, redirect resolution and result metadata. This applies to initial pages, page redirects and
robots destinations, so transport preparation cannot change the authorized path afterward.

`check_url_allowed()` screens every DNS answer, including IPv4-mapped IPv6 addresses. The check and the socket connect
perform separate DNS resolutions, so DNS rebinding remains a residual risk. The user documentation tells operators to
combine an exact host allowlist with an enforcing proxy or network policy when this matters.

This pre-connection lookup remains local when the configured Requests proxy uses `socks5h://`. SOCKS5H controls the
subsequent connection lookup, not the address-policy lookup. A proxy-only hostname therefore requires an explicit
`blockPrivateAddresses: false`; it should be constrained with `allowedHosts` and proxy-side policy.

## Network Identity and Session Isolation

Both robots and page requests use the Requests default User-Agent, `python-requests/<installed version>`.
`WEB_PAGE_ROBOTS_TOKEN` is derived from `requests.utils.default_user_agent()` before the version separator, so robots
rules match the client identity (`python-requests`). No custom User-Agent or identifying metadata is added.

`_open_response()` creates a fresh `requests.Session` for each hop, sets `trust_env = False`, resets session headers to
`requests.utils.default_headers()`, and clears cookies. It overrides only Accept, Accept-Encoding, and Connection,
retaining the library User-Agent. This prevents environment proxy and
`.netrc` discovery as well as cookie persistence between redirect hops. Automatic redirects are disabled. Every
response and session is closed in a `finally` block. Acquisition errors and control-flow interruption also close the
session. Private sessions disable `resolve_redirects` as well as setting `allow_redirects=False`: Requests otherwise
prepares `Response.next` and consumes redirect bodies before returning. `Set-Cookie` is removed from returned headers.

The node is Requests-only. Curl support in `WebFetch` remains available for general HTTP work, but the page node relies
on the Requests raw streaming response for header-first content checks and separate transferred/decoded body limits.

## Robots Processing

Robots cache keys combine origins with fetch policies, independently of domain pacing keys. A cache miss requests
`<origin>/robots.txt`. The `allowRedirects` setting applies to robots as well as pages. Robots redirects
are manually bounded, URL-validated, and paced. They are not recursively guarded by another robots file.

The response rules are:

- 2xx: read under the same header, transfer, decoded, and timeout bounds as a page, decode strict UTF-8, validate core
  directive structure, and parse with `urllib.robotparser.RobotFileParser`.
- 404 or 410: cache an `absent` record that permits pages.
- 401 or 403: cache a `denied` record that always refuses the page.
- Other status or processing error: cache a `failure` record. Refuse the page unless
  `failClosedOnRobotsError` is false.

Rules and absent results use `robotsCacheSeconds`, default 24 hours. Denials and failures use
`robotsFailureCacheSeconds`, default five minutes. A non-positive TTL disables reuse. The origin lock repeats the cache
check after acquiring the lock, so concurrent misses produce one network request.

The strict pre-check rejects malformed core directives, directives placed before a User-agent group, empty User-agent,
non-integer Crawl-delay, and invalid Request-rate. `_RobotsParser` retains the pinned `RobotFileParser` product-token
selection, merged groups, and pacing directives. Allow/Disallow paths are temporarily replaced with unique inert
markers during group parsing, then `_RobotsRule` rebuilds each rule from its original directive text. Markers are
never sent over HTTP or retained as cached rule paths. The wrapper replaces the parser's match score with the normalized rule-path byte length, plus one to keep zero
reserved for a non-match. Internal `*` and terminal `$` count toward rule specificity; redundant unanchored trailing
stars do not. Equal specificity keeps the parser's Allow preference. For example, `Allow: /*` cannot override
`Disallow: /private` for `/private/page`.

The shared `_normalize_robots_path()` normalizer decodes unreserved escapes, uppercases retained escapes, and encodes
literal non-ASCII characters. Reserved escapes stay distinct from path separators and query syntax: `/private%2Fpublic`
does not match an Allow for `/private/public`. Escaped percent signs are not decoded a second time. Literal query
delimiters retain their structure, while encoded delimiters remain data. Only directive paths interpret literal `*`
and terminal `$` as pattern syntax; their percent-encoded forms remain literal. An internal end anchor is an invalid
directive value and follows `failClosedOnRobotsError`.

This adapter is required because the pinned Python parser decodes reserved escapes and scores wildcard rules using
the consumed URL length. All distinct entries in both `parser.entries` and `parser.groups` are adapted, including
merged groups. Matching uses the pinned `RuleLine` predicate and wildcard translator with locally normalized paths.
No global parser class is modified. The adapter depends on the pinned parser's entry/rule representation and pattern
translator; runtime upgrades must run both the specificity and reserved-path adapter regressions. It is not a
general RFC compliance certification.

The service uses the maximum of Crawl-delay and `seconds / requests` from Request-rate when the corresponding controls
are enabled.

## Domain Pacing and Cooldowns

Domain lanes contain an admission lock, a short state lock, the last request time, the next allowed time, and cooldown
metadata. Admission remains serialized during pacing sleeps; in-flight HTTP requests can overlap after admission.
The state lock is released before sleeping. Publisher cooldown updates use only that short lock and are independent
of caller cancellation or pacing budgets. A waiter rechecks cooldown and timing after sleeping before claiming a slot.

On a robots cache miss, the robots request claims the lane using the configured minimum interval. Once robots rules are
known, the page's `_pace()` call recomputes the required time from the preceding robots request. A newly discovered
longer Crawl-delay or Request-rate therefore applies before the page request, not only after it.

The offline lane key uses the final two hostname labels. This shares a lane for ordinary subdomains such as
`www.example.com` and `docs.example.com`. It over-groups multi-label public suffixes such as `co.uk`. The implementation
does not download a Public Suffix List, avoiding an implicit update call and keeping behavior deterministic. If a
bundled and maintained suffix table is added later, replace `_registrable_domain_lane()` without changing callers.

HTTP 403 sets `forbiddenCooldownSeconds` when enabled. HTTP 429 and 503 parse numeric or HTTP-date `Retry-After`, falling
back to `retryAfterFallbackSeconds`. Cooldowns are shared by the domain lane. An active cooldown raises immediately;
the service does not hold a workflow worker for minutes or days. A normal pacing requirement also raises if it exceeds
`maxPacingWaitSeconds`.

## Response Bounds and Decoding

The service passes an urllib3 `Timeout` through Requests with connect, read, and total values set from the node timeout.
It records a monotonic deadline from the start of each HTTP hop and checks it before and after each raw read,
including EOF. urllib3's `read1` is used when available to avoid waiting to fill a complete application chunk.
These are cooperative checks, not a hard wall-clock interrupt: DNS, connection setup and a currently blocked read
must return or hit their transport timeout before the service can observe the deadline or cancellation.

The handler passes `ExecutionContext.request_id` to `fetch`. A scoped ContextVar isolates concurrent request IDs.
Cancellation is checked before each hop, around reads, and during pacing and lock waits. Lock acquisition polls at
50 ms; pacing sleeps poll at 100 ms when a request ID exists. Cancellation propagates as EarlyTerminationException,
including when onError is return. maxPacingWaitSeconds covers both the pacing lane queue and its subsequent delay;
robots single-flight acquisition has the same bounded queue budget. Each hop has its own transport deadline.

Response processing applies three independent limits:

- Header estimate, default 128 KiB. This is calculated after Requests parses the header collection but before the body
  is read. It is not a socket-level HTTP parser limit.
- Transferred body bytes, default 5 MiB. A numeric Content-Length can reject early, and raw chunks are counted even
  without Content-Length.
- Decoded body bytes, default 25 MiB. Identity, gzip, zlib-wrapped deflate, and raw deflate are supported. Output is
  bounded incrementally so a small compressed input cannot expand without limit.

The final page Content-Type is checked before the body. Media type parameters are removed and the base type is matched
case-insensitively. Robots files do not use the page Content-Type allowlist because real publishers serve robots.txt
with several different text media types.

HTTP error bodies, rejected content types, redirects, and responses with oversized declared lengths are never read.

## Error Contract

`WebPageFetchError` carries a message and optional final `status_code`, public response `headers`, and normalized `url`.
The handler re-raises it by default. With `onError: return`, text formats return the message and full format returns:

```json
{
  "error": "failure description",
  "status_code": 403,
  "headers": {},
  "body": null,
  "url": "https://example.com/page"
}
```

Transport failures, policy rejections, malformed robots, timeouts, unsupported encodings, and body limit errors may
not have all metadata fields. Error bodies remain `null` by design because they are not consumed.

## Testing Requirements

Unit tests must not perform real DNS resolution, socket access, proxy calls, sleeps, or HTTP requests. Construct a fresh
`WebPageFetchService` with injected session, monotonic clock, sleep, wall clock, and URL checker boundaries. The service
tests use fake raw streams so content-type-before-body and transferred/decoded size invariants are directly observable.

Important regression groups include:

- Stable identical identity for robots and page requests.
- Default-on policy mapping when all optional node fields are absent.
- Allow, Disallow, Crawl-delay, Request-rate, robots status mapping, caching, and failure mode.
- Same-domain and cross-domain redirects with repeated destination validation.
- Domain pacing, shared subdomain lane, 403 cooldown, and Retry-After behavior.
- Header, transferred, and decoded caps, including gzip and both deflate formats.
- No retry after transport, HTTP, robots, content, decompression, or limit failures.
- Handler hard invariants, output formats, `onError`, variable substitution, proxy, and TLS configuration.
- Exact registry equality between `WorkflowManager.node_handlers` and `VALID_NODE_TYPES`.

Run focused tests with:

```bash
pytest -q Tests/services/test_web_page_fetch_service.py \
  Tests/workflows/handlers/impl/test_web_page_fetch_handler.py \
  Tests/workflows/managers/test_workflow_manager.py
```

Then run the required repository suite:

```bash
pytest --cov=Middleware
```
