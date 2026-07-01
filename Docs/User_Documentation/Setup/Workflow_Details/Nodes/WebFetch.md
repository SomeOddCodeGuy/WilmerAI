## The `WebFetch` Node

The `WebFetch` node issues an HTTP request from inside a workflow and returns the response. It is implemented on top of
the `requests` library and supports any URL, method, and header set you configure. It is the recommended way to pull
data from arbitrary HTTP/HTTPS endpoints during a workflow run (for example, calling an internal API and feeding the
response into a later LLM node).

For shell-style invocations of the `curl` binary, see the [CurlCommand Node](CurlCommand.md). `WebFetch` is preferred
unless you specifically need shell semantics or a feature that only the `curl` binary provides.

-----

### **JSON Configuration**

#### **Complete Example**

```json
{
  "title": "Fetch user record",
  "agentName": "UserRecord",
  "type": "WebFetch",
  "url": "https://api.example.com/users/{userId}",
  "method": "GET",
  "headers": {
    "Authorization": "Bearer {apiToken}",
    "Accept": "application/json"
  },
  "timeout": 15,
  "outputFormat": "json",
  "onError": "raise"
}
```

#### **Fields**

* `"type"`: **(String, Required)**

    * Must be `"WebFetch"`.

* `"title"`: **(String, Optional)**

    * A human-readable name for the node, used in logging.

* `"agentName"`: **(String, Required)**

    * The output variable name. The node's return value becomes `{agentName}` for downstream nodes.

* `"url"`: **(String, Required)**

    * The target URL. Supports workflow variable substitution (e.g., `{userInput}`, `{agent2Output}`,
      `{Discussion_Id}`).

* `"method"`: **(String, Optional, default `"GET"`)**

    * The HTTP method. Case-insensitive. Common values: `GET`, `POST`, `PUT`, `PATCH`, `DELETE`.

* `"headers"`: **(Object, Optional, default `{}`)**

    * A JSON object of request headers. The values support variable substitution; keys are sent literally.

* `"body"`: **(String, Optional)**

    * A raw request body string. Supports variable substitution. If omitted, no body is sent. For form data or JSON
      payloads, you must serialize the body yourself before passing it in.

* `"timeout"`: **(Integer, Optional, default `30`)**

    * Request timeout in seconds. The timer applies to both the connection and the response read phases.
    * Note that this is the `requests` library's per-phase timeout (the connect attempt, and then each individual
      socket read), **not** a total wall-clock deadline: a server that keeps trickling bytes can hold the request
      longer than `timeout` in total. `maxResponseBytes` bounds how *much* such a server can send, not how *long*
      it can take. If you need a hard overall deadline, use the [CurlCommand Node](CurlCommand.md), whose `timeout`
      kills curl outright when it expires.

* `"outputFormat"`: **(String, Optional, default `"text"`)**

    * Controls what the node returns to downstream nodes:
        * `"text"` returns the response body as a string (decoded using the response encoding).
        * `"json"` parses the response as JSON and re-serializes it. Use this when you want to be confident the response
          was valid JSON before later nodes consume it.
        * `"full"` returns a JSON string with three fields: `status_code`, `headers`, and `body`. Useful when later
          nodes need to branch on the status code or read a specific header.
        * `"html-stripped"` runs the response body through a small built-in HTML stripper and returns only the
          visible text, joined with line breaks. Useful when feeding a fetched web page into an LLM, since the raw
          HTML is dominated by `<script>`, `<style>`, and `<head>` content that wastes context window tokens. See
          "HTML Stripping" below for what it does and does not strip.

* `"onError"`: **(String, Optional, default `"raise"`)**

    * Controls behavior when the request fails (connection error, timeout, or HTTP 4xx/5xx):
        * `"raise"` aborts the workflow with the underlying exception.
        * `"return"` causes the node to emit an error payload as its output, allowing a later `Conditional` node to
          branch on the failure. The shape of the payload matches `outputFormat`:
            * `"text"` or `"json"` — returns the response body if any, otherwise the error message.
            * `"full"` — returns a JSON string with `error`, `status_code`, `headers`, and `body` keys; missing values
              are `null`.

* `"proxy"`: **(String, Optional)**

    * A proxy URL routed through both `http` and `https` traffic. Any scheme `requests` supports works:
        * `socks5://host:port` — SOCKS5 with local DNS resolution.
        * `socks5h://host:port` — SOCKS5 with remote DNS (resolves at the proxy; useful for Tor/onion endpoints).
        * `socks4://host:port` — SOCKS4.
        * `http://host:port` or `https://host:port` — standard HTTP proxy.
    * Auth: include credentials inline, e.g., `socks5://user:pass@host:1080`.
    * Supports variable substitution. An empty string is treated as "no proxy".
    * **Dependency note:** SOCKS schemes require the `PySocks` package, which ships in Wilmer's `requirements.txt` and
      is loaded transparently by `requests` when a SOCKS proxy URL is configured.

* `"caBundle"`: **(String, Optional)**

    * Path to a CA bundle file (PEM) used to verify the server's TLS certificate. TLS verification stays **on**; this
      only adds trust for the CA(s) in the file. Use it to reach an HTTPS endpoint whose certificate is issued by a
      private or internal CA (for example a `mkcert`, corporate, or self-managed CA) that is not in the default trust
      store. Supports variable substitution. An empty string is treated as "not set" (falls back to the default below).
      If the path does not point at an existing file, the node raises a `ValueError`.
    * **Opt-in:** when this field is omitted, verification uses the bundled default store exactly as before.

* `"verify"`: **(Boolean, Optional, default `true`)**

    * Whether the server's TLS certificate is verified. The default (`true`) verifies against the default CA store
      (the bundled `certifi` roots — note this is **not** the operating system's certificate store, so a certificate
      trusted only by the OS keychain will still fail unless you supply `caBundle`). Set it to `false` to disable
      certificate verification entirely.
    * **Security warning:** `verify: false` exposes the connection to man-in-the-middle attacks. Prefer `caBundle`
      (which keeps verification on) for private/internal CAs, and reserve `verify: false` for trusted hosts where you
      cannot obtain the CA. When verification is disabled the node logs a warning.
    * **Precedence:** an explicit `verify: false` disables verification and `caBundle` is ignored.
    * **Opt-in:** when this field is omitted, verification is on (default behavior is unchanged).

* `"allowRedirects"`: **(Boolean, Optional, default `true`)**

    * Whether HTTP 3xx redirects are followed. The default (`true`) preserves the historical behavior. Set it to
      `false` to stop a remote redirect from bouncing the request to a different host — see "Privacy and Network
      Behavior" below for why this matters when any part of the `url` comes from a variable.

* `"maxResponseBytes"`: **(Integer, Optional, default `10485760` — 10 MiB)**

    * Caps how many bytes of the response body are read into memory. The body is streamed and the read is aborted once
      the cap is exceeded, so a very large or chunked-infinite response cannot exhaust memory. When the cap is exceeded
      the node behaves like any other failure (honoring `onError`). Set to `0` (or a negative number) to disable the
      cap and read the entire body.

* `"blockPrivateAddresses"`: **(Boolean, Optional, default `false`)**

    * Opt-in SSRF guard. When `true`, the request is rejected if its host is, or resolves to, an address that is not
      globally routable — loopback/link-local/private/reserved (e.g. `127.0.0.1`, the cloud metadata endpoint
      `169.254.169.254`, and the `10.x` / `172.16–31.x` / `192.168.x` ranges), plus shared CGNAT space (`100.64.0.0/10`)
      and the TEST-NET ranges. The check is re-applied to every redirect hop *before* the connection is made. A blocked
      target is treated like any other failure (honoring `onError`). Default `false` preserves the historical behavior.
      See "Privacy and Network Behavior" below.

* `"allowedHosts"`: **(List of strings, Optional, default none)**

    * Opt-in host allowlist. When non-empty, the request host must match (case-insensitively) one of the listed hosts;
      any other host is rejected (and re-checked on every redirect hop). Entries support variable substitution. Combine
      with `blockPrivateAddresses` to require both an allowlisted host *and* a non-private address.

-----

### **Variable Substitution**

All string fields are passed through Wilmer's standard variable resolver before the request is issued. This means you
can reference any of:

* Other agent outputs: `{agent1Output}`, `{agent2Output}`, ...
* Named agents: `{MyAgent}` (matching an earlier node's `agentName`)
* Built-in variables: `{Discussion_Id}`, `{YYYY_MM_DD}`, `{userInput}`, etc.
* Custom workflow variables defined at the top of the workflow JSON.

Substitution applies to:

* `url`
* Each value in `headers`
* `body`
* `proxy`

Header keys are not substituted; they are sent exactly as written.

-----

### **Output Format Reference**

The exact shape of the node's output depends on `outputFormat`:

| `outputFormat`     | Output (success)                                                          | Output (failure, `onError: "return"`)                                  |
|:-------------------|:--------------------------------------------------------------------------|:-----------------------------------------------------------------------|
| `"text"`           | Response body as a string                                                 | Response body if available, otherwise the error message                |
| `"json"`           | JSON-encoded string of the parsed response                                | Response body if available, otherwise the error message                |
| `"full"`           | JSON string: `{ "status_code": ..., "headers": {...}, "body": "..." }`    | JSON string: `{ "error": ..., "status_code": ..., "headers": ..., "body": ... }` |
| `"html-stripped"`  | Stripped visible text                                                     | Stripped error body if available, otherwise the error message          |

-----

### **HTML Stripping**

When `outputFormat: "html-stripped"` is set, the response body is passed through a small built-in HTML stripper
implemented on top of Python's standard library `html.parser`. There is no third-party HTML parsing dependency.

What it does:

* Skips all content inside `<script>`, `<style>`, `<head>`, `<noscript>`, and `<iframe>` elements.
* Decodes HTML character entities (`&amp;`, `&#x27;`, etc.) automatically.
* Emits each text-bearing element's stripped content as one line, joined with newlines.

What it does **not** do:

* It does not strip `<nav>`, `<header>`, `<footer>`, `<aside>`, advertising blocks, cookie banners, or other body-level
  chrome. Those are real, semantically-valid body content, and removing them aggressively would also drop legitimate
  sidebars on some sites. As a result, the stripped output of a typical content site still includes the visible
  navigation text alongside the article body. An LLM can still work with this — the script/style noise was the part
  blowing out the context window — but the output is not "article body only" in the Mozilla-Readability sense.
* It is not a sanitizer. Do not use the output as HTML.
* It will not crash on malformed HTML; `html.parser` is lenient. Broken pages may leak a small amount of unintended
  text into the output.

For a typical content-heavy web page (e.g., a Wikipedia article), `html-stripped` produces output roughly **1–3% the
size of the raw HTML**, which is what makes it useful for LLM pipelines.

For pages where you need true main-content extraction, run the response through a `PythonModule` node with a
specialist library of your choice.

-----

### **Privacy and Network Behavior**

`WebFetch` makes outbound HTTP/HTTPS calls only to the URLs you configure in a workflow JSON. Wilmer does not augment
the request with any additional headers, cookies, or telemetry. The only data sent is the method, URL, headers, and
body you have written into the node configuration (after variable substitution).

For HTTPS, certificate verification is on by default and uses the bundled `certifi` CA roots (not the operating
system's certificate store). To trust a private or internal CA, set `caBundle` to a PEM file (verification stays on);
to disable verification entirely for a trusted host, set `verify: false`. Both are opt-in — see the `caBundle` and
`verify` fields above.

**Treat substituted `url` values as trusted input (SSRF).** By default the node sends the request to whatever the `url`
resolves to after variable substitution — with no guard enabled there is no host, IP, or scheme allowlist. If any part
of the `url` (or a variable inside it) is derived from the conversation (e.g. `{userInput}`), an attacker-controlled
value could point the request at an internal address (`127.0.0.1:<port>`, the cloud metadata endpoint
`169.254.169.254`, other LAN hosts) and, with arbitrary `method`/`headers`/`body`, turn the node into a server-side
request forgery (SSRF) and egress primitive. Prefer to build the `url` only from values you control.

For defense in depth when conversation-derived data may reach a URL, enable the opt-in address guard: set
`"blockPrivateAddresses": true` to reject targets that resolve to any non-globally-routable address
(loopback/link-local/private/reserved, plus CGNAT `100.64.0.0/10` and the TEST-NET ranges), and/or set `"allowedHosts"`
to restrict requests to a fixed host list. Both are re-checked on every redirect hop *before* connecting, so a remote
`3xx` cannot bounce the request to an internal host. (When neither control is enabled, redirects are still followed by
default; set `"allowRedirects": false` to stop a redirect from reaching another host.) Note that `blockPrivateAddresses`
resolves the hostname here, but the OS resolves it again at connect time, so a hostile DNS that answers
public-then-private (DNS rebinding) can still slip past — pin to fixed names with `allowedHosts` when that residual risk
matters.

`WebFetch` is the node to prefer when a URL can be filled from untrusted/conversation-derived data: it parses the URL
and resolves DNS with the same Python stack it then connects with, so the host the guard screened is the host actually
dialed (rebinding aside). `CurlCommand`'s equivalent guard is best-effort only — it validates in Python but the `curl`
binary re-parses and re-resolves independently — so route untrusted URLs here rather than through `CurlCommand`. See the
`CurlCommand` node's "SSRF address guard" note for details.

-----

### **When to Choose `WebFetch` vs `CurlCommand`**

* Use `WebFetch` for HTTP and HTTPS calls that fit the standard request/response model. It is cross-platform, has no
  external binary dependency, and integrates cleanly with the workflow variable system.
* Use `CurlCommand` only when you specifically need the `curl` binary itself — for example, to use a `curl`-only flag
  (such as `--data-binary @file`), to call protocols `requests` does not support, or to mirror a shell command exactly
  as a user would run it.
