## The `CurlCommand` Node

The `CurlCommand` node invokes the system `curl` binary inside a workflow. Arguments are supplied as a JSON list and
passed to curl directly with `shell=False`. There is no shell parsing, no glob expansion, and no
environment-variable expansion done by the node itself; each argument is treated as a literal string after Wilmer's
own variable substitution runs. The node spawns curl via `subprocess.Popen` and streams its output, so the response
body can be bounded in-process (see `maxResponseBytes`).

For most HTTP and HTTPS calls, the [WebFetch Node](WebFetch.md) is the better choice: it has no external binary
dependency, runs on every platform Wilmer supports, and integrates cleanly with the workflow variable system. Use
`CurlCommand` only when you specifically need the `curl` binary itself.

-----

### **JSON Configuration**

#### **Complete Example**

```json
{
  "title": "POST to internal API",
  "agentName": "ApiResponse",
  "type": "CurlCommand",
  "args": [
    "-sS", "-X", "POST",
    "-H", "Authorization: Bearer {apiToken}",
    "-H", "Content-Type: application/json",
    "-d", "{requestBody}",
    "https://api.example.com/items"
  ],
  "timeout": 20,
  "outputFormat": "full",
  "onError": "raise"
}
```

#### **Fields**

* `"type"`: **(String, Required)**

    * Must be `"CurlCommand"`.

* `"title"`: **(String, Optional)**

    * A human-readable name for the node, used in logging.

* `"agentName"`: **(String, Optional)**

    * A fallback display name used in logs when `title` is not set. It does not create a named output variable;
      the node's return value is available to later nodes only positionally, as `{agent#Output}`.

* `"args"`: **(List of Strings, Required)**

    * The arguments passed to `curl`. The node prepends `curl` itself, so this list contains everything else: flags,
      URLs, headers, payload, etc. Each element is variable-substituted in place. **Each argument is sent as a separate
      `argv` entry**; there is no shell tokenization, so `"-H 'X: Y'"` would be one argument including the quotes, not
      two arguments.

* `"timeout"`: **(Integer, Optional, default `30`)**

    * Maximum time in seconds curl is allowed to run. If exceeded, the node either raises `subprocess.TimeoutExpired`
      (when `onError` is `"raise"`) or emits a timeout payload (when `onError` is `"return"`).

* `"outputFormat"`: **(String, Optional, default `"stdout"`)**

    * Controls what the node returns to downstream nodes:
        * `"stdout"` returns curl's standard output as a string. Best for the common case where you use `-sS` to
          silence progress output and just want the response body.
        * `"stdout+stderr"` returns curl's stdout concatenated with stderr. Useful for debugging.
        * `"full"` returns a JSON string with three fields: `stdout`, `stderr`, and `returncode`. Useful when later
          nodes need to branch on the curl exit code.

* `"onError"`: **(String, Optional, default `"raise"`)**

    * Controls behavior when curl exits with a non-zero status code or the timeout is exceeded:
        * `"raise"` aborts the workflow. Non-zero exits raise `RuntimeError`; timeouts raise
          `subprocess.TimeoutExpired`.
        * `"return"` causes the node to emit an error payload as its output, allowing a later `Conditional` node to
          branch on the failure. The shape of the payload matches `outputFormat`:
            * `"stdout"` or `"stdout+stderr"`: returns whatever curl produced before the failure, or a short
              `"curl timed out after N seconds"` message for timeouts.
            * `"full"`: returns the JSON envelope; for timeouts, `returncode` is `null` and an additional `error`
              field describes the timeout.

* `"proxy"`: **(String, Optional)**

    * A proxy URL. When set, the node prepends `-x <url>` to the `args` list before invoking curl. Any scheme curl
      supports works:
        * `socks5://host:port`: SOCKS5 with local DNS resolution.
        * `socks5h://host:port`: SOCKS5 with remote DNS (resolves at the proxy; useful for Tor/onion endpoints).
        * `socks4://host:port`: SOCKS4.
        * `http://host:port` or `https://host:port`: standard HTTP proxy.
    * Auth: include credentials inline, e.g., `socks5://user:pass@host:1080`.
    * Supports variable substitution. An empty string is treated as "no proxy".
    * **Note:** curl handles the proxy entirely on its own; no Python SOCKS library is involved.

* `"maxResponseBytes"`: **(Integer, Optional, default `10485760`, 10 MiB)**

    * Caps how many bytes curl may pull onto the machine, using two layers:
        1. **Early abort (`--max-filesize`).** When set above `0`, the node injects curl's native
           `--max-filesize <bytes>`. curl aborts before downloading when the server advertises a `Content-Length`
           larger than the cap. This is cheap but **only fires for advertised-length responses**; a chunked or
           unknown-length response (no `Content-Length`) slips past it. If you supply your own `--max-filesize` in
           `args`, the node does not add a second one.
        2. **In-process cap (the true bound).** The node reads curl's stdout incrementally with a running byte total
           and **kills curl the instant the body exceeds the cap**, so even a chunked/unknown-length response cannot
           buffer an unbounded body into memory. stderr is drained concurrently and bounded to the same cap.
    * When the cap is exceeded, the node treats it as a failure and honors `onError`: `"raise"` raises a `RuntimeError`
      naming the cap; `"return"` emits the over-cap message (for `stdout`/`stdout+stderr`) or a `full` envelope whose
      `returncode` is `null` and whose `error` field names the cap, carrying the truncated `stdout`/`stderr`.
    * Set to `0` (or a negative number) to disable **both** layers and read the entire body unbounded.

* `"blockOptionInjection"`: **(Boolean, Optional, default `false`)**

    * When `true`, the node rejects any `args` element that **resolves** (after variable substitution) to a value
      starting with `-` (a curl option) or with `@` (an `@file` data read, e.g. `-d @/etc/passwd`), unless the
      author's template literally started with that character. This blocks curl-option injection and local-file-read
      injection via untrusted variables (see "Security and Safety Notes"). It is off by default because it can
      interfere with workflows that legitimately build flags or `@file` arguments from variables; enable it when a
      conversation-derived variable feeds an `args` slot you intend to hold a data value (a URL, a search term, etc.).
      For a variable-fed request body, prefer `--data-raw`, which sends the value literally and never treats a leading
      `@` as a file.

* `"allowSchemeInjection"`: **(Boolean, Optional, default `false`)**

    * Controls the scheme-injection guard, which is **on by default** (safe-by-default). With the guard on, the node
      rejects an `args` element whose resolved value introduces a non-`http`/`https` URL scheme (`file://`, `ftp://`,
      `scp://`, `dict://`, `gopher://`, ...) **via variable substitution**. Such a scheme would let curl read a local
      file or reach an internal service from a conversation-derived value. A scheme the author writes **literally** in
      the template (e.g. `args: ["file://{path}"]`) is treated as intentional and is allowed; only a scheme that the
      *substituted value* introduces is blocked. Set this to `true` to fully open the node back up and permit
      substituted schemes of any kind. Note: the guard inspects only the leading scheme of a value; it is not a host or
      SSRF allowlist (see "Security and Safety Notes").

* `"blockPrivateAddresses"`: **(Boolean, Optional, default `false`)**

    * Opt-in SSRF guard. When `true`, any `http(s)` URL among the resolved `args` (a bare `http://...`/`https://...`
      value, or a `--url=<url>`) is rejected if its host is, or resolves to, an address that is not globally routable:
      loopback/link-local/private/reserved (e.g. `127.0.0.1`, the cloud metadata endpoint `169.254.169.254`, and the
      `10.x` / `172.16-31.x` / `192.168.x` ranges), plus shared CGNAT space (`100.64.0.0/10`) and the TEST-NET ranges.
      While the guard is active the node also pins curl to `--max-redirs 0` (unless you set your own) so a `3xx` cannot
      bounce the request to an unvalidated host; curl resolves and follows redirects itself, so they cannot be
      re-checked in-process the way `WebFetch` does. Default `false` preserves the historical behavior. **This guard is
      best-effort on `CurlCommand`**; see the SSRF note below for why, and prefer `WebFetch` for conversation-derived URLs.

* `"allowedHosts"`: **(List of strings, Optional, default none)**

    * Opt-in host allowlist. When non-empty, every `http(s)` URL among the resolved `args` must target
      (case-insensitively) one of the listed hosts; any other host is rejected. Entries support variable substitution.
      As with `blockPrivateAddresses`, curl is pinned to `--max-redirs 0` while active. Combine the two to require both
      an allowlisted host *and* a non-private address.
    * Entries must be hostnames only (no port). Matching runs against the URL's hostname with any port stripped, so an
      entry written as `"example.com:8080"` can never match and every request to it will be rejected. Write
      `"example.com"` instead; the port in the URL itself is unaffected.

-----

### **Variable Substitution**

Each element of the `args` list (and the `proxy` field) is passed through Wilmer's standard variable resolver
before curl is invoked. This means you can reference any of:

* Other agent outputs: `{agent1Output}`, `{agent2Output}`, ...
* Built-in variables: `{Discussion_Id}`, `{YYYY_MM_DD}`, `{userInput}`, etc.
* Custom workflow variables defined at the top of the workflow JSON.

Substitution is per-element; an argument's content can be any string after substitution, but the argument boundaries
are fixed by the list structure. If your variable contains spaces, those spaces stay inside the same argument; curl
will see one argument, not multiple.

-----

### **Security and Safety Notes**

* **No shell.** The command runs with `shell=False`. Shell metacharacters in arguments (such as `;`, `|`, `&`, `>`,
  `*`) are treated as literal characters by curl; they do not invoke a shell.
* **System binary.** The node calls whichever `curl` binary appears first on the Wilmer process's `PATH`. If you need
  a specific build, pre-pend its directory to `PATH` before starting Wilmer.
* **Outbound calls.** The node only contacts the URLs you put in `args`. Wilmer adds nothing to the request.
* **`shell=False` stops shell injection, not curl's own options.** Each `args` element is a real curl argument, and
  curl has features that touch the local filesystem:
    * `file://` URLs and `-d @file` / `--data-binary @file` make curl **read a local file** (and, with a data flag,
      send its contents to the remote server, an exfiltration path).
    * `-o` / `--output` and `-O` make curl **write/overwrite a local file**.
    * `-K` / `--config` makes curl read further options from a file.
    * Any argument that starts with `-` is parsed as an **option**, including one produced by variable substitution.
      To pin a value to the URL slot regardless of its content, use `--` or `--url <value>`.
  Workflow `args` are author-written and trusted, but a variable such as `{userInput}` that flows into an `args` slot
  is conversation-derived. If an `args` slot you intend as a data value can be filled from the conversation, set
  `"blockOptionInjection": true`: with the guard on, a substituted value beginning with `-` cannot become a curl
  option, and a substituted value beginning with `@` cannot become an `@file` read (the `@` expansion that turns
  `-d {userInput}` into a local-file read/exfil when `{userInput}` resolves to `@/etc/passwd`). To send variable
  content as a literal request body regardless of a leading `@`, use `--data-raw`, which does not honor `@`.
* **Scheme injection is blocked by default.** A conversation-derived value that introduces a non-`http`/`https` scheme
  (e.g. `file:///etc/passwd`, `dict://`, `gopher://`) is rejected before curl runs, because such a value would make
  curl read a local file or reach an internal service. This guard is on by default; a scheme the author writes
  *literally* in the template is still allowed (it is your intent, not injection). Set `"allowSchemeInjection": true`
  to disable the guard and fully open the node back up. Note the guard checks the **scheme only**; it is not a host
  or IP allowlist, so it does not by itself stop a substituted `http://169.254.169.254/...` SSRF; keep building the
  host portion of any URL from values you control, or enable the opt-in address guard described below.
* **`blockOptionInjection` guards leading-`-` and `@file` injection (separate, opt-in).** The scheme guard handles
  `scheme://` values; a substituted value that becomes a curl **option** (`-o`, `-K`, ...) or an **`@file` data read**
  (`-d @/etc/passwd`) is a different vector, guarded by `blockOptionInjection`, which is off by default. When enabled it
  rejects a substituted `args` value beginning with `-` or with `@` (values the author wrote literally in the template
  are still allowed). Enable it when a conversation-derived variable feeds an `args` slot you intend to hold a data
  value, and prefer `--data-raw` for variable-fed request bodies so a leading `@` is sent literally rather than
  expanded into a file read.
* **SSRF address guard (opt-in, best-effort on this node).** For defense in depth when conversation-derived data can
  reach a URL, set `"blockPrivateAddresses": true` to reject `http(s)` URL args that target any non-globally-routable
  address (loopback/link-local/private/reserved, plus CGNAT `100.64.0.0/10` and the TEST-NET ranges), and/or
  `"allowedHosts"` to restrict them to a fixed host list. While either is active the node pins curl to `--max-redirs 0`
  (unless you supply your own `--max-redirs`) so a redirect cannot reach an unvalidated host; curl follows redirects
  itself and they cannot be re-validated in-process.

  **Why "best-effort": the component Wilmer validates is not the component that connects.** Wilmer parses the URL and
  resolves DNS in Python to make the decision, then hands the original string to the `curl` binary, which parses the URL
  and resolves DNS *itself*. Two gaps follow from that:
    * **URL-parser divergence.** A host string Python's parser reads one way (backslashes, multiple `@`, unusual
      delimiters, alternate IP encodings such as decimal `2130706433`, hex `0x7f000001`, or octal `0177.0.0.1`) can be
      read differently by curl's URL grammar, so curl may connect to a host the guard never screened.
    * **DNS divergence / rebinding.** Even when the host string agrees, curl re-resolves it, so a name that answered a
      public address at check time can answer an internal one at connect time.
  `--max-redirs 0` closes the *redirect*-bounce vector; it does **not** close these two. `allowedHosts` narrows the
  damage (only listed names are even attempted) but does not pin the resolved IP, so rebinding still applies.

  **Recommendation:** treat `CurlCommand`'s address guard as a hardening layer for *author-trusted* invocations, not as
  a boundary you can point untrusted input at. **When a URL can be filled from conversation-derived data, use
  `WebFetch`**, which parses and resolves with the same Python stack it connects with (so the screened target is the
  dialed target, rebinding aside). To constrain untrusted egress through `curl` specifically, route it via a vetted
  allow-listing forward proxy (`proxy`) that enforces the policy at the component that actually opens the connection.

-----

### **Choosing Between `CurlCommand` and `WebFetch`**

| Reason                                                            | Prefer        |
|:------------------------------------------------------------------|:--------------|
| You want a cross-platform, no-binary-required HTTP/HTTPS request  | `WebFetch`    |
| A URL can be filled from conversation-derived/untrusted data      | `WebFetch`    |
| You want clean integration with the workflow variable system      | `WebFetch`    |
| You want output as parsed JSON or a full headers envelope         | `WebFetch`    |
| You need a curl-only flag (such as `--data-binary @file`)         | `CurlCommand` |
| You need to mirror an exact `curl` invocation a user gave you     | `CurlCommand` |
| You need a protocol or feature the `requests` library doesn't provide | `CurlCommand` |
