## The `WebPageFetch` Node

The `WebPageFetch` node retrieves one public web page with page-oriented safety and publisher-respect controls. It is
intended for ordinary HTML, XHTML, and plain-text pages that will be read by a later workflow node. Its protections
are enabled when their fields are omitted.

This node requires Python **3.13.14 or a later 3.13 patch**, or **3.14.5 or a later 3.14 patch**, for its
robots.txt parser. Earlier interpreter versions are not supported by this node.

Use [WebFetch](WebFetch.md) instead for APIs, authenticated requests, JSON-specific handling, custom headers, request
bodies, non-GET methods, or curl transport. `WebFetch` remains the general HTTP/API node and does not apply robots.txt
rules.

`WebPageFetch` always makes a bodyless GET. It does not load images, scripts, stylesheets, video, fonts, frames, or
other linked resources. One node execution retrieves only robots.txt when needed, redirect responses when encountered,
and the selected page.

-----

### Basic Configuration

```json
{
  "title": "Read public documentation",
  "agentName": "DocumentationPage",
  "type": "WebPageFetch",
  "url": "https://docs.example.com/guide/{topic}",
  "outputFormat": "html-stripped"
}
```

The `url`, `proxy`, `caBundle`, and each `allowedHosts` entry support workflow variable substitution.

On the first request to an origin, the default path normally makes two HTTP calls: one to `/robots.txt`, then one to
the page. The page request waits for at least the five-second domain interval after the robots request. A valid cached
robots result removes the extra robots call on later executions, but the shared domain pacing interval still applies.

-----

### Fields

#### General request fields

| Field | Type | Default | Description |
|:------|:-----|:--------|:------------|
| `type` | String | required | Must be `"WebPageFetch"`. |
| `title` | String | `""` | Human-readable node name used in logging. |
| `agentName` | String | `""` | Fallback display name. The result remains available positionally as `{agent#Output}`. |
| `url` | String | required | Absolute `http://` or `https://` page URL. Supports variable substitution. Embedded credentials are rejected. |
| `method` | String | `"GET"` | Optional for clarity. The only accepted value is `GET`, case-insensitively. |
| `transport` | String | `"requests"` | The only accepted value is `requests`. The page service needs its streaming response controls. |
| `timeout` | Number | `30` | Positive timeout in seconds for each robots or page request, with an additional total read deadline. |
| `outputFormat` | String | `"html-stripped"` | `"html-stripped"`, `"text"`, or `"full"`. |
| `onError` | String | `"raise"` | `"raise"` aborts the workflow. `"return"` returns an error string or full error envelope. |
| `proxy` | String | none | Optional HTTP, HTTPS, SOCKS4, SOCKS5, or SOCKS5H proxy URL used for both robots and page requests. Supports variable substitution. Proxy credentials may be included when the configured proxy requires them. |
| `caBundle` | String | none | Optional path to a CA bundle used while keeping TLS verification enabled. Supports variable substitution. |
| `verify` | Boolean | `true` | Enables TLS certificate verification. `false` disables it and takes precedence over `caBundle`. |

`headers` and `body` are not supported. This prevents a page node from carrying caller identity, destination authentication,
cookies, a Referer, or an accidental write request. Use `WebFetch` when those HTTP features are required.

With the default `blockPrivateAddresses: true`, Wilmer resolves the destination locally before sending the request
through any configured proxy. A `socks5h://` proxy still performs the connection's DNS lookup remotely, but it does not
eliminate this earlier local safety lookup. A proxy-only hostname that local DNS cannot resolve will be refused by
default. To use such a hostname intentionally, set `blockPrivateAddresses` to false and prefer an exact `allowedHosts`
entry plus a proxy or network policy that restricts outbound destinations.

#### Destination controls

| Field | Type | Default | Description |
|:------|:-----|:--------|:------------|
| `blockPrivateAddresses` | Boolean | `true` | Rejects hosts that are, or resolve to, private, loopback, link-local, reserved, multicast, unspecified, or otherwise non-public addresses. Applied to every page and robots redirect. |
| `allowedHosts` | Array of strings | none | Optional hostname allowlist. Every redirect must also match. Entries support variable substitution and contain hostnames only, without ports. |
| `restrictPorts` | Boolean | `true` | Allows only the normal port for the URL scheme: 80 for HTTP and 443 for HTTPS, plus entries in `allowedPorts`. |
| `allowedPorts` | Array of integers | `[]` | Additional ports from 1 through 65535 allowed while `restrictPorts` is true. |
| `allowRedirects` | Boolean | `true` | Follows HTTP 301, 302, 303, 307, and 308 responses manually so every destination is checked first. |
| `maxRedirects` | Integer | `5` | Maximum redirect count for the page and for robots.txt. Accepted range is 0 through 5. |

The address allowlist and public-address check are additive. If both are configured, a destination must pass both.
Setting `blockPrivateAddresses` to false is required for an intentionally private destination, even if that host is
listed in `allowedHosts`.

#### Robots and pacing controls

| Field | Type | Default | Description |
|:------|:-----|:--------|:------------|
| `respectRobots` | Boolean | `true` | Retrieves and evaluates the destination origin's `/robots.txt` before the page. |
| `failClosedOnRobotsError` | Boolean | `true` | Refuses the page when robots.txt times out, fails, is oversized, is malformed, or cannot be decoded. `false` permits the page after these general failures. A robots 401 or 403 remains a denial. |
| `enableDomainPacing` | Boolean | `true` | Enables the shared per-domain request interval. The robots request counts as a request in the same lane. |
| `minimumDelaySeconds` | Number | `5` | Minimum interval between requests in one domain lane. Must be non-negative. |
| `maxPacingWaitSeconds` | Number | `300` | Fails rather than holding a workflow worker when the required wait exceeds this value. Must be non-negative. |
| `honorCrawlDelay` | Boolean | `true` | Includes a matching integer `Crawl-delay` in the effective interval. |
| `honorRequestRate` | Boolean | `true` | Includes the evenly spaced interval implied by a matching `Request-rate`. |
| `honorRetryAfter` | Boolean | `true` | Applies `Retry-After` from HTTP 429 or 503 to future calls in the domain lane. |
| `honorForbiddenCooldown` | Boolean | `true` | Applies a cooldown after an HTTP 403 response. |
| `robotsCacheSeconds` | Number | `86400` | In-memory cache lifetime for successfully parsed or absent robots files. |
| `robotsFailureCacheSeconds` | Number | `300` | In-memory cache lifetime for refused, failed, or malformed robots results. |
| `forbiddenCooldownSeconds` | Number | `604800` | Domain cooldown after HTTP 403, seven days by default. |
| `retryAfterFallbackSeconds` | Number | `60` | Cooldown used for HTTP 429 or 503 when `Retry-After` is absent or invalid. |

The effective request interval is the greatest applicable value among `minimumDelaySeconds`, `Crawl-delay`, and the
interval represented by `Request-rate`. An active 403 or `Retry-After` cooldown fails fast instead of sleeping for a
long period. Requests are not retried automatically.

#### Response controls

| Field | Type | Default | Description |
|:------|:-----|:--------|:------------|
| `enforceContentType` | Boolean | `true` | Checks the final page Content-Type before reading its body. |
| `allowedContentTypes` | Array of strings | `text/html`, `application/xhtml+xml`, `text/plain` | Allowed media types without parameters. Matching is case-insensitive and ignores response parameters such as `charset`. |
| `maxHeaderBytes` | Integer | `131072` | Approximate response header cap, 128 KiB. Applied to page and robots responses. |
| `maxTransferBytes` | Integer | `5242880` | Maximum transferred response body, 5 MiB. Applied to page and robots responses while streaming. |
| `maxDecodedBytes` | Integer | `26214400` | Maximum body after gzip or deflate decoding, 25 MiB. |

All three limits must be positive integers. The header limit is checked after Requests has parsed the HTTP header block
but before Wilmer reads the body. It prevents an accepted response from carrying an unbounded header collection farther
through the workflow, but it is not a socket-level header parser limit.

-----

### Output Formats

| `outputFormat` | Success | Failure with `onError: "return"` |
|:---------------|:--------|:---------------------------------|
| `"html-stripped"` | Visible text extracted from the page. Content inside `script`, `style`, `head`, `noscript`, and `iframe` elements is omitted. | Error message. |
| `"text"` | Decoded response body, including HTML markup when the page is HTML. | Error message. |
| `"full"` | JSON string with `status_code`, `headers`, `body`, and final `url`. | JSON string with `error`, `status_code`, `headers`, `body: null`, and `url`. |

The HTML stripper is a small standard-library extractor, not a main-article detector or sanitizer. Navigation, cookie
banners, footers, and other visible body text may remain.

`Set-Cookie` is removed from the returned headers. The service does not retain or resend response cookies.

Received publisher cooldowns apply even when page or robots headers exceed `maxHeaderBytes`. A Retry-After value
over 128 characters, or an invalid numeric or date value, uses the configured fallback cooldown. Numeric seconds must
use ASCII digits. The rejected response body is not read.

-----

### Robots Behavior

When `respectRobots` is true, the node performs these steps for each page origin:

1. Validate the page destination.
2. Retrieve `scheme://host/robots.txt` using the same proxy, TLS, timeout, size limits, client-default User-Agent, redirect
   validation, and domain pacing as page requests.
3. Parse the file as strict UTF-8 and select rules for the Requests client product token (`python-requests`).
4. Check the exact page URL against `Allow` and `Disallow`.
5. Apply matching `Crawl-delay` and `Request-rate` values before requesting the page.

Robots status handling is conservative:

| Result | Behavior |
|:-------|:---------|
| HTTP 200 through 299 with valid rules | Evaluate and cache the rules. |
| HTTP 404 or 410 | Treat robots.txt as absent and allow the page. |
| HTTP 401 or 403 | Deny the page. |
| Other HTTP status, timeout, connection failure, bad encoding, malformed file, decompression failure, or size breach | Fail closed unless `failClosedOnRobotsError` is false. |

A failed robots request is not retried during the operation. Parsed, absent, denied, and failed results are cached in
memory according to their configured lifetime. Concurrent checks for the same origin and fetch policy share one robots
retrieval. Different proxy, TLS, redirect, address, or response-limit settings require separate permission checks.
The cache retains at most 1024 records; an evicted record must be fetched again.

The parser accepts integer `Crawl-delay` values and `requests/seconds` values for `Request-rate`. A fractional or
otherwise invalid directive is treated as malformed under the default fail-closed policy.

Matching rules are ranked by their normalized rule-path length, with `Allow` preferred on equal specificity. Wildcards
match paths but do not gain priority from the number of URL characters they consume. An unanchored trailing `*` adds no
specificity: `Allow: /*` is equivalent to `Allow: /`, so `Disallow: /private` still blocks `/private/page`. Internal `*`
and a terminal `$` remain part of the rule, and `$` requires the path to end there. Matching user-agent groups are merged.
These decisions apply to initial pages and redirect destinations, using the same canonical URL that the transport sends.

-----

### Identity, Cookies, and Request State

Page and robots requests use the Requests default User-Agent, `python-requests/<installed version>`, and its matching
robots product token, `python-requests`. No custom User-Agent, person, project, owner, email address, machine name,
or installation identifier is added.

Each HTTP hop uses a new Requests session. Environment proxy and `.netrc` discovery are disabled. The service sends
the library-default User-Agent and explicit Accept, Accept-Encoding, and Connection headers. It sends no caller
headers, destination credentials, cookies, or Referer. Explicit credentials in `proxy` authenticate to that configured
proxy. Sessions and responses are closed after the hop, and `Set-Cookie` is discarded.

No browsing history, robots cache, pacing lane, or cooldown is persisted to disk. The shared state is process-wide and
is cleared when Wilmer restarts.

Shared pacing uses a fixed set of 1024 buckets. Unrelated domains can share a bucket and therefore a delay or cooldown.
This bounds memory without forgetting an active publisher restriction. The pacing wait budget includes time queued
behind another caller. Cancellation interrupts queued waits and pacing within approximately 100 ms. During an active
HTTP operation, cancellation and the additional deadline are checked at read boundaries; a blocked transport must
return or time out first. The timeout is per HTTP hop, not a hard wall-clock limit for the complete node.

-----

### Redirects and Domain Pacing

Automatic redirect following is disabled in Requests. Before each redirect is followed, `WebPageFetch` resolves the
new URL and repeats scheme, credential, port, hostname, public-address, and allowlist validation. A redirect to a new
origin gets its own robots decision. A redirect to another subdomain also uses the shared domain pacing lane.

The initial offline domain grouping uses the final two hostname labels. For example, `www.example.com` and
`docs.example.com` share the `example.com` lane. Without downloading or periodically updating a Public Suffix List,
this approach intentionally over-groups multi-label public suffixes: `a.example.co.uk` and `b.other.co.uk` share the
`co.uk` lane. This can reduce throughput but does not create extra request lanes.

-----

### Failure and Retry Behavior

`WebPageFetch` does not automatically retry any request. Redirects are bounded continuations, not retries.

URLs are normalized using the HTTP transport's rules before address and robots checks. This includes dot segments
such as `/section/../page` and unreserved percent escapes. The checked URL is the URL sent and reported in full output.
The same rule applies to page redirects and robots URLs. URLs that cannot be prepared consistently fail before a request.

Robots comparison preserves reserved escapes in rules and URLs. An Allow for `/private/public` does not authorize
`/private%2Fpublic`, and an encoded query delimiter stays data rather than becoming query syntax. Unreserved escapes
still compare equally to their literal characters. These rules apply to cached policies and redirect destinations.
An end anchor (`$`) inside a rule path is malformed and follows `failClosedOnRobotsError`.

The node stops after an HTTP error, timeout, connection failure, robots denial or failure, invalid URL, disallowed
destination, content-type rejection, decompression error, or size breach. Error response bodies are not read. HTTP 403
creates the configured domain cooldown when enabled. HTTP 429 and 503 apply `Retry-After`, or the configured fallback,
when enabled.

With `onError: "return"`, runtime fetch failures become node output. Invalid node configuration still raises a
`ValueError` before a network request is attempted.

Malformed page URLs and redirect Location values also follow `onError`. Malformed robots URLs or directives become
cached permission failures and follow `failClosedOnRobotsError`. No rejected robots URL is contacted. Page-handler
diagnostics and warnings about permitted robots failures honor the request's log-redaction setting.

-----

### Security Limitations

`blockPrivateAddresses` resolves a hostname and validates every returned address before connecting, but the operating
system resolves the name again during the connection. A hostile DNS service could return a public address for the
check and a private address for the connection. Use `allowedHosts` and an enforcing outbound proxy or network policy
when this residual DNS-rebinding risk matters.

The local address-policy resolution also occurs before a SOCKS5H connection. See the proxy note under the general
request fields when remote-only DNS is required.

`allowedHosts` entries are exact hostnames, without ports or wildcard matching. The node accepts only HTTP and HTTPS
page URLs and normal ports by default, but it is still an outbound network capability. Keep workflow-authored URL
templates narrow when any substituted value can be influenced by untrusted input.

-----

### Example With Explicit Policy Settings

```json
{
  "title": "Read a public article",
  "agentName": "ArticleText",
  "type": "WebPageFetch",
  "url": "https://www.example.com/articles/{articleId}",
  "timeout": 30,
  "outputFormat": "html-stripped",
  "onError": "return",
  "respectRobots": true,
  "failClosedOnRobotsError": true,
  "blockPrivateAddresses": true,
  "allowedHosts": ["www.example.com"],
  "restrictPorts": true,
  "enableDomainPacing": true,
  "minimumDelaySeconds": 5,
  "honorCrawlDelay": true,
  "honorRequestRate": true,
  "honorRetryAfter": true,
  "honorForbiddenCooldown": true,
  "allowRedirects": true,
  "maxRedirects": 5,
  "enforceContentType": true,
  "allowedContentTypes": [
    "text/html",
    "application/xhtml+xml",
    "text/plain"
  ],
  "maxHeaderBytes": 131072,
  "maxTransferBytes": 5242880,
  "maxDecodedBytes": 26214400
}
```

Fields shown with their default values may be omitted. Omitting them keeps the protections enabled.
