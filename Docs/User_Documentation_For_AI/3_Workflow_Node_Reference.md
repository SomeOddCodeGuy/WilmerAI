# WilmerAI Node Reference

Every node has `"type"` (required) and `"title"` (optional, for logging). Below lists all node types with their
properties. Properties marked **[var]** support variable substitution. Properties marked **[limited var]** support only
`{agent#Input}` and static custom workflow variables (NOT `{agent#Output}`).

---

## Standard

The core LLM-calling node. Assembles a prompt, sends it to an endpoint, returns the response.

| Property | Type | Default | Description |
|---|---|---|---|
| `endpointName` | String | required | LLM endpoint name. **[limited var]** |
| `preset` | String | required | Generation preset name or endpoint with embedded preset samplers. **[limited var]** |
| `systemPrompt` | String | required | System prompt. **[var]** |
| `prompt` | String | required | User prompt. If empty, falls back to sending recent messages directly. **[var]** |
| `lastMessagesToSendInsteadOfPrompt` | Int | 5 | When `prompt` is empty, how many recent turns to send. |
| `lastMessagesToSendInsteadOfPromptMaxTokenSize` | Int | optional | Estimated-token ceiling on the last-N window (only when `prompt` is empty); trims the selected turns newest-first to this budget. Scaled by `wilmerContextEstimationLevel` when `clampPromptToContextWindow` is on. Largely subsumed by the clamp when enabled. |
| `maxResponseSizeInTokens` | Int/String | 400 | Max tokens to generate. **[limited var]** |
| `maxContextTokenSize` | Int | 4096 | Max context window size. |
| `returnToUser` | Bool | false | Override: force this node to be the responder. |
| `jinja2` | Bool | false | Enable Jinja2 templating in prompt/systemPrompt. |
| `acceptImages` | Bool | false | Pass images to the LLM. An endpoint with `backendSupportsImages: false` overrides this and receives text only. |
| `maxImagesToSend` | Int | 0 | Limit images sent (0 = no limit). **[limited var]** |
| `allowTools` | Bool | false | Forward frontend tool definitions to the LLM. Only useful on responder. |
| `appendNativeToolExchange` | Bool | false | Authored-prompt nodes: deliver the trailing assistant `tool_calls` + `role:"tool"` exchange as native messages after the authored prompt (excluded from the text transcript). Responders pair it with `allowTools`; internal planners may use it with `allowTools: false` to inspect native history without receiving tool definitions. Inert on collection-mode nodes, completions backends, and endpoints with `backendSupportsToolTurns: false`. |
| `lowercaseToolCallFunctionNames` | Bool | false | Lowercase tool call function names in LLM responses. Fixes local models that produce `Glob` instead of `glob`. |
| `structuredOutputFile` | String | none | Grammar-constrain this node's output to a JSON Schema from `Configs/StructuredOutputs/` (backend must declare a `structuredOutput` mechanism in its ApiType). Enforcement depends on backend and schema support; validate the returned JSON and required fields before using it. Describe the shape in the prompt too. |
| `addDiscussionIdTimestampsForLLM` | Bool | false | Inject timestamps into messages. |
| `useRelativeTimestamps` | Bool | false | Use relative timestamps ("5 min ago") instead of absolute. |
| `useGroupChatTimestampLogic` | Bool | false | Commit assistant timestamps immediately (for group chats). If false, commit on next user turn. |
| `addUserTurnTemplate` | Bool | false | Wrap prompt in user turn template. |
| `addOpenEndedAssistantTurnTemplate` | Bool | false | Append assistant turn start to prompt. |
| `blockGenerationPrompt` | Bool | false | Block automatic generation prompt. |
| `forceGenerationPromptIfEndpointAllows` | Bool | false | Force generation prompt. |
| `addUserAssistantTags` | Bool | false | Prefix messages in `chat_user_prompt_*` vars with `User: `/`Assistant: `. |
| `includeToolCallsInConversation` | Bool | false | Inject `[Tool Call: {name}]` summaries into blank assistant turns. |
| `mergeConsecutiveAssistantMessages` | Bool | false | Merge consecutive assistant messages into one. |
| `mergeConsecutiveAssistantMessagesDelimiter` | String | "\n" | Delimiter for merged messages. |
| `insertUserTurnBetweenAssistantMessages` | Bool | false | Insert synthetic user turns between consecutive assistant messages. |
| `insertedUserTurnText` | String | "Continue." | Text for synthetic user turns. |
| `nMessagesToIncludeInVariable` | Int | 5 | Controls `{chat_user_prompt_n_messages}` count. |
| `estimatedTokensToIncludeInVariable` | Int | 2048 | Token budget for `{chat_user_prompt_estimated_token_limit}`. |
| `minMessagesInVariable` | Int | 5 | Min messages for `{chat_user_prompt_min_n_max_tokens}`. |
| `maxEstimatedTokensInVariable` | Int | 2048 | Token budget for expansion beyond min messages. |

When `prompt` is empty, the node sends the raw conversation (last N messages) to the LLM. This is how you do
"passthrough": just set `"prompt": ""` and the LLM sees the actual conversation.

---

## Conditional

Evaluates a logical expression. Returns the string `"TRUE"` or `"FALSE"`.

| Property | Type | Description |
|---|---|---|
| `condition` | String | Expression to evaluate. **[var]** Supports `==`, `!=`, `>=`, `<=`, `>`, `<`, `AND`, `OR`, parentheses. |

Unquoted `TRUE`/`FALSE` are booleans; quoted `'value'` are strings; unquoted numbers are numeric. The output of a
Conditional is boolean, so compare with `{agentXOutput} == TRUE`, not `{agentXOutput} == 'TRUE'`.

---

## ConditionalCustomWorkflow

Branches to different sub-workflows based on a variable's value.

| Property | Type | Description |
|---|---|---|
| `conditionalKey` | String | Variable to evaluate (e.g., `{agent1Output}`). **[var]** |
| `conditionalWorkflows` | Object | Map of value -> workflow name. `"Default"` key is fallback. Keys match case-insensitively. |
| `UseDefaultContentInsteadOfWorkflow` | String | Static content to return if no match. Takes precedence over Default workflow. **[var]** |
| `scoped_variables` | Array | Values to pass to the chosen child workflow. **[var]** |
| `routeOverrides` | Object | Per-route prompt overrides. Outer keys are **case-insensitive** (matched after lowercasing, so any casing works) and must correspond to `conditionalWorkflows` keys. Inner keys: `systemPromptOverride`, `promptOverride`. Values support **[var]**. |
| `workflowUserFolderOverride` | String | User folder to load workflow from. Use `_common` for shared. |
| `returnToUser` | Bool | If true, output goes to user. |

**Important:** If the resolved `conditionalKey` does not match any entry in `conditionalWorkflows` and neither a
`"Default"` key nor `UseDefaultContentInsteadOfWorkflow` is defined, the node will error at runtime. Always include
at least one fallback: either a `"Default"` workflow or `UseDefaultContentInsteadOfWorkflow` (use `""` for a no-op).

---

## CustomWorkflow

Executes another workflow file as a child. Child runs in isolated context.

| Property | Type | Description |
|---|---|---|
| `workflowName` | String | Filename of child workflow (without `.json`). Static, no variables. |
| `scoped_variables` | Array | Values passed to child as `{agent1Input}`, `{agent2Input}`, etc. **[var]** |
| `workflowUserFolderOverride` | String | User folder to load from. `_common` for shared. |
| `returnToUser` | Bool | If true, child's final output goes to user. |

---

## StringConcatenator

Joins a list of strings with a delimiter.

| Property | Type | Description |
|---|---|---|
| `strings` | Array | List of strings to join. **[var]** |
| `delimiter` | String | Separator between strings. Default: `""`. |
| `returnToUser` | Bool | Can act as responder with streaming. |

---

## ArithmeticProcessor

Evaluates a simple math expression (`+`, `-`, `*`, `/`). Returns result as string, or `"-1"` on error.

| Property | Type | Description |
|---|---|---|
| `expression` | String | Math expression (e.g., `{agent1Output} * 1.07`). **[var]** |

---

## JsonExtractor

Extracts a field from a JSON string. Auto-strips markdown code block wrappers.

| Property | Type | Description |
|---|---|---|
| `jsonToExtractFrom` | String | The JSON string. **[var]** |
| `fieldToExtract` | String | Field name to extract. **[var]** |

---

## TagTextExtractor

Extracts content between XML/HTML-style tags (e.g., `<answer>...</answer>`). First match only, case-sensitive.

| Property | Type | Description |
|---|---|---|
| `tagToExtractFrom` | String | Text to search. **[var]** |
| `fieldToExtract` | String | Tag name (without angle brackets). **[var]** |
| `defaultText` | String | Optional fallback returned (substituted) when the tag is absent, unclosed, or only whitespace. Default empty string. **[var]** |

---

## DelimitedChunker

Splits a string on a delimiter, returns first N or last N chunks rejoined.

| Property | Type | Description |
|---|---|---|
| `content` | String | Text to split. **[var]** |
| `delimiter` | String | Split delimiter. **[var]** |
| `mode` | String | `"head"` (first N) or `"tail"` (last N). Literal only. |
| `count` | Int | Number of chunks to keep. Literal only. |

---

## GetCustomFile

Reads a text file from disk and returns its content.

| Property | Type | Description |
|---|---|---|
| `filepath` | String | Path to file. **[var]** Use `{Discussion_Directory}` for discussion state; supports `{YYYY_MM_DD}` and other variables. |
| `delimiter` | String | Optional: string to find in file content and replace. |
| `customReturnDelimiter` | String | Optional: replacement for delimiter occurrences. |
| `headCount` / `tailCount` | Int | Optional, opt-in: return only the first/last N chunks. Set at most one. |
| `chunkDelimiter` | String | Optional: chunk separator for headCount/tailCount. Default `"\n"` (lines). |

Returns `"Custom instruction file did not exist"` if file not found. Omit `delimiter`/`customReturnDelimiter` if you
want the file returned as-is. `headCount`/`tailCount` default to off (whole file); use `tailCount` to feed only the
recent tail of an unbounded log to an LLM.

---

## SaveCustomFile

Writes content to a text file. Creates parent directories if needed.

| Property | Type | Description |
|---|---|---|
| `filepath` | String | Path to save to. **[var]** Use `{Discussion_Directory}` for discussion state; supports `{YYYY_MM_DD}` and other variables. |
| `content` | String | Content to write. **[var]** |
| `mode` | String | Optional: `"overwrite"` (default) or `"append"` (adds to end of file, creating it if missing). |

---

## StaticResponse

Returns a hardcoded string. No LLM call. Can stream if set as responder.

| Property | Type | Description |
|---|---|---|
| `content` | String | Text to return. **[var]** |
| `returnToUser` | Bool | If true, streams content to user. |

---

## ImageProcessor

Sends user-provided images to a vision LLM and returns text descriptions.

| Property | Type | Description |
|---|---|---|
| `endpointName` | String | Vision-capable endpoint. **[limited var]** |
| `preset` | String | Generation preset. **[limited var]** |
| `systemPrompt` | String | Instructions for the vision LLM. **[var]** |
| `prompt` | String | User prompt for the vision LLM. **[var]** |
| `addAsUserMessage` | Bool | If true, injects description into conversation history. |
| `message` | String | Template for injected message. Must contain `[IMAGE_BLOCK]` placeholder. **[var]** |
| `saveVisionResponsesToDiscussionId` | Bool | If true, caches vision responses per-discussion to avoid redundant LLM calls. When true with `addAsUserMessage`, descriptions are injected per-message instead of aggregated. Default: false. |

---

## PythonModule

Executes a custom Python script. The script must define `Invoke(*args, **kwargs)` returning a string.

| Property | Type | Description |
|---|---|---|
| `module_path` | String | Path to the `.py` file. Absolute, or relative (resolved against the cwd, then the install root). |
| `args` | Array | Positional arguments. **[var]** |
| `kwargs` | Object | Keyword arguments. **[var]** |

---

## WorkflowLock

Acquires a named lock. If the lock is already held, the workflow terminates immediately. Locks auto-release after
10 minutes or on workflow completion. Scoped per-user.

| Property | Type | Description |
|---|---|---|
| `workflowLockId` | String | Unique lock identifier. Same ID = same lock. |

Place after the responder node and before long-running tasks (e.g., memory generation).

---

## ContextCompactor

Compacts conversation history into two rolling summaries (Old and Oldest) using token-based windowing.
Independent from the memory system; it directly summarizes raw conversation messages, not memory chunks.

Output is XML-tagged: `<context_compactor_old>` and `<context_compactor_oldest>`. Use `TagTextExtractor` to parse.

**Requirements:** `contextCompactorSettingsFile` in user config pointing to a separate settings JSON (see
6_Configuration_Reference.md for the full settings schema). Requires a `discussionId`.

The settings file controls token budgets for Recent/Old windows, the LLM endpoint, and summarization prompts.
No additional node properties beyond `type` and `title`.

---

## Offline Wikipedia Nodes

Query a local `OfflineWikipediaTextApi` service. All have `promptToSearch` **[var]**.

| Type | Description |
|---|---|
| `OfflineWikiApiBestFullArticle` | Returns the single best-matching full article. |
| `OfflineWikiApiFullArticle` | Returns the first full article from results. |
| `OfflineWikiApiPartialArticle` | Returns article summaries. Extra props: `num_results` (int), `percentile` (float). |
| `OfflineWikiApiTopNFullArticles` | Returns top N full articles. Extra props: `top_n_articles` (int), `num_results` (int), `percentile` (float). |

---

## Keyword Search Nodes

Run a non-LLM keyword search and return the matching text. The search target is selected by the `searchTarget`
property, **not** by the node type: `ConversationalKeywordSearchPerformerTool` and `MemoryKeywordSearchPerformerTool`
both dispatch to the same handler and route purely on `searchTarget`. A `MemoryKeywordSearchPerformerTool` node
therefore requires `"searchTarget": "RecentMemories"`; written without it, it falls back to the default
(`CurrentConversation`) and searches the conversation, not memory.

| Property | Type | Default | Description |
|---|---|---|---|
| `keywords` | String | required | Keywords to search for. **[var]** |
| `searchTarget` | String | `"CurrentConversation"` | What to search over. Valid values: `"CurrentConversation"` (the live conversation) or `"RecentMemories"` (generated memory files). |
| `lookbackStartTurn` | Int | 0 | Turn offset to start the conversation search from. |

---

## SlowButQualityRAG

A tool-based node that chunks a target body of text and runs a keyword/LLM RAG pass over the chunks. Advanced node;
see the user documentation for full behavior.

| Property | Type | Description |
|---|---|---|
| `ragTarget` | String | The text body to run RAG over. **[var]** |
| `ragType` | String | The RAG strategy to apply. |
| `prompt` | String | User prompt for the RAG LLM pass. **[var]** |
| `systemPrompt` | String | System prompt for the RAG LLM pass. **[var]** |
| `endpointName` | String | LLM endpoint used for the RAG pass. **[limited var]** |
| `preset` | String | Generation preset. **[limited var]** |

---

## WebFetch

Issues an HTTP request via Python Requests (default) or the system curl executable and returns the response. See
`Nodes/WebFetch.md` for the full transport, timeout, TLS, and security/privacy behavior.

| Property | Type | Default | Description |
|---|---|---|---|
| `url` | String | required | Target URL. **[var]** |
| `method` | String | `"GET"` | HTTP method (case-insensitive). |
| `transport` | String | `"requests"` | `"requests"` or `"curl"` (case-insensitive). Curl must be on `PATH`. No User-Agent is set by Wilmer; the selected client uses its generic default unless `headers` overrides it. Curl config-file loading is disabled. |
| `headers` | Object | `{}` | Request headers; values support **[var]**. Keys are sent as written. |
| `body` | String | None | Raw request body. **[var]** |
| `timeout` | Number | 30 | Positive timeout in seconds. Requests uses a per-phase timeout; curl uses connection and total-transfer timeouts. |
| `outputFormat` | String | `"text"` | `"text"`, `"json"` (re-serialized), `"full"` (status/headers/body envelope), or `"html-stripped"`. |
| `onError` | String | `"raise"` | `"raise"` aborts on failure; `"return"` emits an error payload to branch on. |
| `proxy` | String | None | Proxy URL for both HTTP and HTTPS; supported schemes depend on the transport. **[var]** |
| `caBundle` | String | None | Custom CA bundle path. **[var]** |
| `verify` | Bool | true | Enables TLS verification. False disables verification and takes precedence over `caBundle`. |
| `allowRedirects` | Bool | true | Whether HTTP 3xx redirects are followed. Set false to stop a remote redirect bouncing the request to another host. |
| `maxResponseBytes` | Int | 10485760 | Body-size cap in bytes. Both transports enforce it while streaming. `0` disables the cap. |
| `blockPrivateAddresses` | Bool | false | Reject non-public target addresses and re-check every redirect. |
| `allowedHosts` | Array of strings | None | Restrict target hostnames and re-check every redirect. Entries support **[var]**. |

---

## WebPageFetch

Retrieves one ordinary public webpage with publisher-cautious defaults. It is GET-only, bodyless, headerless,
stateless, does not retry, and does not load page subresources. Use `WebFetch` for APIs, JSON handling, custom headers,
authentication, bodies, methods other than GET, or curl. See `Nodes/WebPageFetch.md` for the complete robots, pacing,
limits, identity, and security behavior.

| Property | Type | Default | Description |
|---|---|---|---|
| `url` | String | required | Absolute HTTP or HTTPS page URL. **[var]** |
| `method` | String | `"GET"` | Only `GET` is accepted. |
| `transport` | String | `"requests"` | Only `requests` is accepted. |
| `timeout` | Number | 30 | Per-request timeout with an additional bounded body-read deadline. |
| `outputFormat` | String | `"html-stripped"` | `"html-stripped"`, `"text"`, or `"full"`. |
| `onError` | String | `"raise"` | `"raise"` aborts; `"return"` emits an error message or full envelope. |
| `proxy` | String | None | Proxy used by robots and page requests. **[var]** |
| `caBundle` | String | None | Custom CA bundle path. **[var]** |
| `verify` | Bool | true | Enables TLS verification. False takes precedence over `caBundle`. |
| `respectRobots` | Bool | true | Retrieves and evaluates robots.txt before the page. |
| `failClosedOnRobotsError` | Bool | true | Refuses a page after a general robots retrieval or parsing failure. Robots 401/403 always denies. |
| `blockPrivateAddresses` | Bool | true | Rejects non-public destinations and re-checks every redirect. |
| `allowedHosts` | Array of strings | None | Exact hostname allowlist, re-checked on each hop. Entries support **[var]**. |
| `restrictPorts` | Bool | true | Permits only scheme-default ports plus `allowedPorts`. |
| `allowedPorts` | Array of integers | `[]` | Additional ports accepted while port restriction is enabled. |
| `enableDomainPacing` | Bool | true | Enables the shared domain request lane. |
| `minimumDelaySeconds` | Number | 5 | Minimum request interval. |
| `maxPacingWaitSeconds` | Number | 300 | Refuses a pacing requirement above this duration. |
| `honorCrawlDelay` | Bool | true | Includes matching integer Crawl-delay in the request interval. |
| `honorRequestRate` | Bool | true | Includes the evenly spaced matching Request-rate interval. |
| `honorRetryAfter` | Bool | true | Applies 429/503 Retry-After to future domain calls. |
| `honorForbiddenCooldown` | Bool | true | Applies a future domain cooldown after HTTP 403. |
| `robotsCacheSeconds` | Number | 86400 | In-memory successful or absent robots cache lifetime. |
| `robotsFailureCacheSeconds` | Number | 300 | In-memory denied or failed robots cache lifetime. |
| `forbiddenCooldownSeconds` | Number | 604800 | 403 cooldown duration. |
| `retryAfterFallbackSeconds` | Number | 60 | 429/503 cooldown when Retry-After is absent or invalid. |
| `allowRedirects` | Bool | true | Manually follows validated redirects. |
| `maxRedirects` | Int | 5 | Redirect cap from 0 through 5. |
| `enforceContentType` | Bool | true | Requires an allowed page Content-Type before body read. |
| `allowedContentTypes` | Array of strings | HTML, XHTML, plain text | Base media types accepted by the final page. |
| `maxHeaderBytes` | Int | 131072 | Approximate parsed-header cap for robots and page responses. |
| `maxTransferBytes` | Int | 5242880 | Transferred body cap for robots and page responses. |
| `maxDecodedBytes` | Int | 26214400 | Body cap after gzip or deflate decoding. |

Both robots and page requests use the Requests default User-Agent, `python-requests/<installed version>`, with
`python-requests` as the robots product token. No custom User-Agent, caller headers, destination credentials, cookies,
Referer, or persisted browsing state are used. An explicitly configured proxy may use its own credentials.

Malformed page URLs and redirect metadata follow `onError`. Robots URL/directive failures are cached and follow
`failClosedOnRobotsError`. Retry-After integer seconds require ASCII digits; invalid numeric/date values use the
configured fallback cooldown. Handler diagnostics and service warnings honor request log redaction.
Page and robots URLs are prepared to a stable transport form before address and robots checks. Dot segments and
unreserved escapes are normalized before authorization; the same URL is sent and returned in result metadata.
Preparation failures use the corresponding page or robots error policy.

Robots permission uses normalized rule-path specificity, not the length of URL text consumed by a wildcard. Unanchored
trailing `*` adds no specificity; internal `*` and terminal `$` count as rule characters, and equal specificity prefers
Allow. Thus `Allow: /*` cannot override `Disallow: /private` for `/private/page`. Matching user-agent groups are merged,
and the same permission rule applies to initial pages and redirects.
Reserved escapes remain distinct from literal separators in both rules and URLs. For example, an Allow for
`/private/public` does not authorize `/private%2Fpublic`; encoded query delimiters also remain data. Unreserved
escapes still compare equally to their literal characters. A misplaced end anchor follows `failClosedOnRobotsError`.

---

## CurlCommand

Invokes the system `curl` binary via `subprocess.Popen` with `shell=False` (no shell injection). Each `args` element is
variable-substituted. See `Nodes/CurlCommand.md` for the security notes (curl can read/write local files via
`file://`, `@file`, and `-o`).

| Property | Type | Default | Description |
|---|---|---|---|
| `args` | Array of Strings | required | curl arguments; `curl` is prepended automatically. Each element supports **[var]**. |
| `timeout` | Number | 30 | Process timeout in seconds (must be a positive number). |
| `outputFormat` | String | `"stdout"` | `"stdout"`, `"stdout+stderr"`, or `"full"` (JSON envelope with returncode). |
| `onError` | String | `"raise"` | `"raise"` aborts on non-zero exit/timeout; `"return"` emits the result/error. |
| `proxy` | String | None | Proxy URL; prepended as `-x <proxy>`. **[var]** |
| `maxResponseBytes` | Int | 10485760 | Injects curl `--max-filesize <bytes>` unless the author already set one. `0` disables injection. |
| `blockOptionInjection` | Bool | false | When true, rejects an `args` element that resolves (via substitution) to a leading-`-` value (curl option) or leading-`@` value (`@file` data read, e.g. `-d @/etc/passwd`) unless its template literally started with that character (blocks curl-option and local-file-read injection from untrusted variables; prefer `--data-raw` for variable-fed bodies). |

---

## MCPToolCall

Deterministically invokes a single tool on a named MCP server (the LLM is not in the loop). The server, tool, and
arguments are chosen by the workflow author.

| Property | Type | Default | Description |
|---|---|---|---|
| `server` | String | required | Name of a server config in `Public/Configs/MCPServers/` (without `.json`). **[var]** |
| `tool` | String | required | The MCP tool to invoke. **[var]** |
| `arguments` | Object | `{}` | Tool arguments; string values support **[var]**. |
| `timeout` | Number | 30 | Overall timeout in seconds (bounds connect + initialize + call; must be positive). |
| `onError` | String | `"raise"` | `"raise"` aborts on failure; `"return"` emits the error string. |

## ConversationChunkProcessor

Runs a child workflow once per complete chunk of new conversation messages. Required workflowName selects the child;
chunkSize controls the group size, lookbackMessages withholds the freshest tail, and scoped_variables follow the
chunk text as child inputs. Use Discussion_Directory for cursorDirectory and mutable returnFile paths.
The cursor records one last-message hash per completed chunk. See the
[complete node guide](../User_Documentation/Setup/Workflow_Details/Nodes/ConversationChunkProcessor.md).
