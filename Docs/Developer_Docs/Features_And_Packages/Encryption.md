### **Developer Guide: Per-User Encryption and API Key Directory Isolation**

> **EXPERIMENTAL. MAKE AN INDEPENDENT BACKUP BEFORE ENABLING ENCRYPTION.** Encryption is disabled by default. Keep your original API key
> and exact workflow-selection name; existing encrypted files require both. Disabling encryption does not decrypt existing files.

This guide provides a deep dive into the architecture and implementation of WilmerAI's per-user encryption and
directory isolation feature. When a client sends an `Authorization: Bearer <key>` header, built-in discussion state is
stored in the key's directory scope. Workflow-authored state uses the same scope when its path starts with
`{Discussion_Directory}`. Supported built-in files are encrypted at rest when encryption is enabled.

-----

## 1\. Overview

WilmerAI is often deployed as a shared middleware instance serving multiple users or front-end applications. The
encryption and isolation feature addresses two concerns in this scenario:

- **Directory Isolation**: API keys act as client storage namespace secrets. Each key's built-in discussion files
  (memories, chat summaries, timestamps, vision cache, condensation trackers, context compactor state) are stored under
  a subdirectory derived from a hash of the key. Workflow files rooted at `{Discussion_Directory}` use that same
  directory. This prevents file collisions between different keys even if they share the same `discussionId`.

- **File Encryption**: All discussion JSON files can be encrypted at rest using Fernet symmetric encryption. The
  encryption key is derived from the API key itself, so only a client with the correct API key can read the data.
  Encryption is gated by the `encryptUsingApiKey` user configuration setting (default: `false`). When disabled, files
  are stored as plaintext even if an API key is present.

Directory isolation activates automatically when an `Authorization: Bearer <key>` header is present on the incoming
HTTP request. File encryption additionally requires `encryptUsingApiKey: true` in the selected workflow config. The
Bearer value is not validated as a login credential. When no key is present, clients using the same `discussionId`
share the same directory.

SQLite database encryption is not included in this implementation. The vector memory databases
(`<id>_vector_memory.db`) and the locking database remain unencrypted. Encrypting SQLite requires compiling against
SQLCipher (a third-party encrypted SQLite fork), which introduces native build dependencies and significantly
complicates cross-platform distribution. This is deferred as a non-trivial task.

-----

## 2\. Key Files

| File | Responsibility |
|------|----------------|
| `Middleware/utilities/encryption_utils.py` | Core encryption module. Contains key derivation, hashing, encrypt/decrypt functions. |
| `Middleware/utilities/sensitive_logging_utils.py` | Thread-local redaction context and sensitive logging helpers. Prevents user content from appearing in logs when redaction is active (via encryption or the `redactLogOutput` config setting). |
| `Middleware/utilities/file_utils.py` | All JSON file I/O. Every read/write function accepts an optional `encryption_key` parameter. |
| `Middleware/utilities/config_utils.py` | Path resolution. `get_discussion_file_path()` and all derived path functions accept an optional `api_key_hash` parameter for directory isolation. Also provides `get_encrypt_using_api_key()` (reads `encryptUsingApiKey`) and `get_redact_log_output()` (reads `redactLogOutput`). |
| `Middleware/workflows/models/execution_context.py` | The `ExecutionContext` dataclass carries `api_key: Optional[str]` so all node handlers can access it. |
| `Middleware/api/api_helpers.py` | Shared `extract_api_key()` function that reads the `Authorization: Bearer` header. |
| `Middleware/api/handlers/impl/openai_api_handler.py` | OpenAI-compatible API endpoints. Calls `api_helpers.extract_api_key()`. |
| `Middleware/api/handlers/impl/ollama_api_handler.py` | Ollama-compatible API endpoints. Calls `api_helpers.extract_api_key()`. |
| `Middleware/api/workflow_gateway.py` | Passes the API key from the API layer to the `WorkflowManager`. |
| `Middleware/workflows/managers/workflow_manager.py` | Passes the API key to the `WorkflowProcessor`. |
| `Middleware/workflows/processors/workflows_processor.py` | Stores the API key as `self.api_key` and threads it into `ExecutionContext` and all services that need it. |
| `Middleware/workflows/managers/workflow_variable_manager.py` | Exposes the resolved canonical directory as `{Discussion_Directory}` without exposing the raw key or its hash. |

-----

## 3\. Architecture

### API Key Extraction

Both the OpenAI and Ollama API handlers call the shared `extract_api_key()` function in `api_helpers.py` to read
the `Authorization` header from the incoming Flask request:

```python
def extract_api_key() -> Optional[str]:
    auth = flask_request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        key = auth[7:].strip()
        return key if key else None
    return None
```

The extracted key (or `None`) is passed as the `api_key` parameter through the entire call chain:

```
API Handler -> workflow_gateway.handle_user_prompt() -> WorkflowManager -> WorkflowProcessor -> ExecutionContext
```

### Key Derivation (`encryption_utils.py`)

The module provides two derivation functions from a raw API key string:

1. **`hash_api_key(api_key) -> str`**: Returns the first 16 hex characters of the SHA-256 hash. Used for directory
   naming. The truncation to 16 characters keeps directory names short while providing sufficient collision resistance
   for the practical number of API keys a single instance would serve.

2. **`derive_fernet_key(api_key, username=None) -> bytes`**: Derives a Fernet-compatible 32-byte encryption key
   using PBKDF2 with:
   - Algorithm: SHA-256
   - Iterations: 100,000
   - Salt: Per-user when ``username`` is provided (``WilmerAI-v1-{sha256(username)}``), or a fixed fallback
     (``WilmerAI-encryption-salt-v1``) when ``username`` is None.
   - Output: URL-safe base64-encoded 32-byte key

The per-user salt ensures that even if two users happen to use the same API key string, they derive different
encryption keys. The ``get_encryption_key_if_available`` convenience helper automatically fetches the current
username via ``get_current_username()`` and passes it to ``derive_fernet_key``. The fixed fallback salt exists for
standalone or testing scenarios where no username is available. The iteration count of 100,000 adds computational
cost to brute-force attempts.

In current deployments, this "username" is the selected file under `Public/Configs/Users`, which commonly represents a
workflow selection rather than a human identity. Directory scope depends only on the API-key hash, but the encryption
key also depends on this selection. Consequently, the same key and discussion ID can resolve to one directory while
different workflow selections derive incompatible encryption keys. Until a versioned key-derivation migration removes
that coupling, encrypted discussions must keep using the same selected user config.

Two convenience wrappers handle the common pattern of "derive if present, else None":

- `get_encryption_key_if_available(api_key) -> Optional[bytes]`: Returns a Fernet key only if `api_key` is
  non-empty **and** `encryptUsingApiKey` is `true` in the user config. This function internally calls
  `config_utils.get_encrypt_using_api_key()` to check the config.
- `get_api_key_hash_if_available(api_key) -> Optional[str]`: Returns the directory hash whenever an API key is
  present. This is independent of the encryption config setting.

### Lazy Loading

The `cryptography` library is lazily imported on first use via `_ensure_cryptography()`. This means that when no API
key is present, the library is never imported and there is zero runtime cost. The lazy loading pattern uses module-level
sentinel variables (`_Fernet`, `_PBKDF2HMAC`, `_hashes`) that are populated on the first call to any encryption
function.

### Directory Isolation (`config_utils.py`)

The `get_discussion_file_path()` function is the central path-building function for all discussion files. It accepts
an optional `api_key_hash` parameter:

```python
def get_discussion_file_path(discussion_id, file_name, api_key_hash=None):
    # Without api_key_hash:
    #   {discussions_root}/{discussion_id}/{file_name}.json
    #
    # With api_key_hash:
    #   {discussions_root}/{api_key_hash}/{discussion_id}/{file_name}.json
    #
    # {discussions_root} is resolved via get_discussion_folder_path() in the
    # following order: --DiscussionDirectory CLI flag > discussionDirectory
    # user config > {get_root_public_directory()}/DiscussionIds/. The public
    # root resolves to --PublicDirectory when set, else {project_root}/Public/.
    # Legacy folder stickiness keeps existing discussions at their pre-refactor
    # location ({project_root}/Public/DiscussionIds/).
```

All derived path functions propagate this parameter:

- `get_discussion_memory_file_path(discussion_id, api_key_hash=None)`
- `get_discussion_chat_summary_file_path(discussion_id, api_key_hash=None)`
- `get_discussion_timestamp_file_path(discussion_id, api_key_hash=None)`
- `get_discussion_condensation_tracker_file_path(discussion_id, api_key_hash=None)`
- `get_discussion_vision_responses_file_path(discussion_id, api_key_hash=None)`
- `get_discussion_context_compactor_old_file_path(discussion_id, api_key_hash=None)`
- `get_discussion_context_compactor_oldest_file_path(discussion_id, api_key_hash=None)`

The hash-based subdirectory is created automatically by `os.makedirs()` when files are first written.

`WorkflowVariableManager.generate_variables()` exposes the same directory to operator-authored workflows as
`{Discussion_Directory}`. It delegates to `get_discussion_folder_path(context.discussion_id,
api_key_hash=context.api_key_hash)`. The variable is resolved lazily, cannot be overridden by a user-wide variable, and
raises `ValueError` when referenced without a discussion ID. This fail-closed behavior prevents a missing ID from
turning a path such as `{Discussion_Directory}/state.md` into a shared or filesystem-root path. The raw API key and hash
are intentionally not exposed as workflow variables.

### File Encryption (`file_utils.py`)

Two internal helper functions handle all encrypted I/O:

#### `_read_json_file(file_path, encryption_key=None)`

When `encryption_key` is provided:
1. Reads the file as raw bytes.
2. Attempts Fernet decryption.
3. Parses the decrypted bytes as JSON.
4. **Fallback**: If decryption fails with `InvalidToken`, `ValueError`, or `UnicodeDecodeError`, falls back to
   reading the file as plaintext JSON. This enables transparent migration of existing unencrypted files. The
   exception types are intentionally narrow so that unrelated errors (e.g., `PermissionError`, `MemoryError`) are
   not silently swallowed.

When `encryption_key` is `None`:
- Reads the file as plaintext JSON (original behavior).

#### `_write_json_file(file_path, data, encryption_key=None)`

Before replacing an existing file, the writer reads it through `_read_json_file` with the supplied key. An incompatible
key, disabled encryption on ciphertext, invalid JSON, or an I/O error aborts the write and preserves the existing file.
This applies to direct timestamp, tracker, and vision-cache writes as well as read-modify-write memory operations.

Built-in JSON and state-document existence checks use `_path_exists`, which calls `Path.stat()` and treats only
`FileNotFoundError` as absence. Other metadata errors propagate before reading defaults or replacing files, including
state backups. Python 3.14's `Path.exists()` suppresses these errors and must not be used for these preservation checks.

When `encryption_key` is provided:
1. Serializes data to JSON bytes.
2. Encrypts with Fernet.
3. Writes the encrypted bytes to disk.

When `encryption_key` is `None`:
- Writes plaintext JSON (original behavior).

Every public file I/O function in `file_utils.py` accepts and passes through an `encryption_key` parameter:

- `ensure_json_file_exists()` (via its read/write path)
- `read_chunks_with_hashes()`
- `write_chunks_with_hashes()`
- `update_chunks_with_hashes()`
- `load_timestamp_file()`
- `save_timestamp_file()`
- `read_condensation_tracker()`
- `write_condensation_tracker()`
- `read_vision_responses()`
- `write_vision_responses()`

### Graceful Fallback (Plaintext-to-Encrypted Migration)

The `_read_json_file` fallback supports enabling `encryptUsingApiKey` in an already keyed directory.
Existing plaintext files are read successfully because the decryption
failure triggers a plaintext fallback. On the next write, the file is encrypted. From that point on, the file is
encrypted and only readable with the correct API key.

Enabling encryption on an already keyed directory encrypts its readable plaintext files on their next write.
Starting to send an API key instead selects a new keyed directory; it does not inherit previously unkeyed data.

`read_plain_text_file` tries decryption and permits UTF-8 plaintext migration only when the raw bytes do not resemble
a Fernet token. `looks_like_fernet_token` recognizes the usual prefix (including truncated tokens) and a complete binary
envelope. Missing or incompatible keys therefore cannot turn recognizable ciphertext into state-document workflow input.
Arbitrary corruption cannot always be distinguished from arbitrary plaintext; independent backups are still required.

`write_plain_text_file` validates the current file and any existing backup with the supplied key before replacement.
It prepares the new encrypted bytes before changing the backup, then atomically writes the previous raw contents to the
backup and the new contents to the current file. A failed backup write preserves both existing versions. Backup bytes
retain their previous encryption format, so a plaintext-to-encrypted transition initially leaves a plaintext backup.

-----

## 4\. Data Flow

The following diagram shows how the API key flows through the system for a single request:

```
Client sends: Authorization: Bearer sk-my-secret-key
                    |
                    v
    API Handler (extract_api_key)
    api_key = "sk-my-secret-key"
                    |
                    v
    workflow_gateway.handle_user_prompt(..., api_key=api_key)
                    |
                    v
    WorkflowManager.handle_conversation(..., api_key=api_key)
                    |
                    v
    WorkflowProcessor.__init__(..., api_key=api_key)
    self.api_key = "sk-my-secret-key"
                    |
                    v
    WorkflowProcessor.execute()
        |
        +---> ExecutionContext(api_key=self.api_key)
        |         |
        |         +--> Node Handlers, Tools, Services
        |                  |
        |                  +--> config_utils: api_key_hash = hash_api_key(api_key) -> "a1b2c3d4e5f6g7h8"
        |                  |    Path: {discussionDir}/a1b2c3d4e5f6g7h8/{discussion_id}/memories.json
        |                  |
        |                  +--> file_utils: encryption_key = derive_fernet_key(api_key, username)
        |                       Read/Write with Fernet encryption
        |
        +---> TimestampService, LockingService (also receive api_key)
```

### Where Encryption Key and Hash Are Derived

The encryption key and API key hash are computed once in `WorkflowProcessor.__init__` and cached on the
`ExecutionContext` as `encryption_key` and `api_key_hash`. This avoids repeated PBKDF2 derivation (100,000
iterations per call) during a single request:

```python
# In WorkflowProcessor.__init__:
self.encryption_key = get_encryption_key_if_available(api_key) if api_key else None
self.api_key_hash = get_api_key_hash_if_available(api_key) if api_key else None

# In ExecutionContext (set by WorkflowProcessor):
encryption_key: Optional[bytes] = None
api_key_hash: Optional[str] = None
```

All downstream consumers (node handlers, services, tools) access these cached values directly from the context
rather than re-deriving them:

```python
encryption_key = context.encryption_key
api_key_hash = context.api_key_hash
```

The raw `api_key` is still carried on the `ExecutionContext` for cases where a new `WorkflowProcessor` must be
created (e.g., sub-workflows, memory parser workflows), since each new processor performs its own derivation.

-----

## 5\. Scope and Limitations

### What Is Encrypted

All JSON discussion files written through `file_utils.py`:
- Memory files (`_memories.json`)
- Chat summary files (`_chat_summary.json`)
- Timestamp files (`_timestamps.json`)
- Vision response cache files (`_vision_responses.json`)
- Condensation tracker files (`_condensation_tracker.json`)
- Context compactor state files (`_context_compactor_old.json`, `_context_compactor_oldest.json`)

The built-in `state_document.md` and its `.bak` backup also use optional Fernet encryption through the text-file
helpers. Custom workflow text files remain plaintext.

### What Is NOT Encrypted

- **SQLite databases**: The vector memory database (`_vector_memory.db`) and the locking database remain unencrypted.
  SQLite encryption requires SQLCipher or a similar native-compiled fork, which adds cross-platform build complexity.
  Vector memory databases also store readable memory text and metadata, not only embeddings. Locking databases may
  contain discussion IDs. Protect their directories accordingly. See section 7 for implementation considerations.
- **Configuration files**: User configs, workflow configs, endpoint configs, and all files under `Public/Configs/` are
  not encrypted. These are system configuration, not per-user discussion data.
- **Custom text files**: `GetCustomFile`, `SaveCustomFile`, and `ConversationChunkProcessor` files are plaintext. Using
  `{Discussion_Directory}` gives them the canonical API-key directory scope, but does not encrypt their content.
- **Log files**: Application logs remain plaintext. However, when encryption is enabled, sensitive content (prompts,
  LLM responses, payloads) is redacted from logs. See section 5.1 below.

### Backwards Compatibility

- Requests without an `Authorization` header produce no encryption and no directory isolation. Behavior is identical
  to previous versions.
- Existing unencrypted files are readable even after encryption is enabled, thanks to the decryption fallback in
  `_read_json_file`. They are transparently encrypted on the next write.
- Starting to send an API key creates a new keyed directory. Keyed requests do not fall back to unkeyed files. Any
  intended data must be copied into the keyed scope explicitly so a client cannot inherit legacy shared state.

### Discussion File Directory Layout Migration

All discussion files have been consolidated into per-discussion-id subdirectories. The central
`get_discussion_file_path()` function in `config_utils.py` handles backwards compatibility:

1. It first checks for the new nested path: `{dir}/{discussion_id}/{file_name}.json`
2. If that file does not exist, it checks for a legacy flat file: `{dir}/{discussion_id}_{file_name}.json`
3. If the legacy file exists, its path is returned (no automatic move)
4. If neither exists, the new nested path is returned (new files are always created in the nested structure)

Existing flat files remain readable and continue to be written at their resolved flat path. Normal saves do not move
them. New files use nested storage; an existing nested file takes precedence. Relocating legacy files is an explicit
operator migration performed while the server is stopped.

With API key isolation, the layout adds a hash-based subdirectory:
`{dir}/{api_key_hash}/{discussion_id}/{file_name}.json`. The legacy fallback does not apply in this case since
API key isolation is a new feature with no pre-existing files.

-----

## 5.1\. Sensitive Log Redaction

Log redaction activates when either of the following is true:

- **Encryption is enabled**: `encryptUsingApiKey: true` in the user config and an API key is present on the request.
- **Explicit redaction**: `redactLogOutput: true` in the user config. This activates redaction for all requests,
  regardless of whether an API key is present or encryption is enabled.

When active, all logging statements that could contain user content are automatically redacted. This prevents
prompts, LLM responses, and payload data from appearing in terminal output or log files.

### Key Files

| File | Responsibility |
|------|----------------|
| `Middleware/utilities/sensitive_logging_utils.py` | Thread-local redaction context and sensitive logging helpers. |
| `Middleware/utilities/config_utils.py` | `get_redact_log_output()` reads the `redactLogOutput` user config setting. |

### Architecture

The module uses Python's `threading.local()` to track a per-request boolean flag indicating whether the current
request should have its log output redacted. Under Eventlet, `threading.local()` is monkey-patched to be
greenlet-local, so each greenlet has its own context.

**Context lifecycle:**

1. The OpenAI chat/completions and Ollama chat/generate handlers call `begin_request_privacy()` before parsing
   request data or selecting a user. This provisionally redacts diagnostics, including early failures and rejected
   user selections. Once a user is identified, `resolve_request_privacy()` applies that user's policy: active if
   (a) an API key is present and `get_encrypt_using_api_key()` is true, or (b) `get_redact_log_output()` is true.
   Payload logging and lazy sanitization occur only after this decision and shared-workflow validation.
2. For Eventlet greenlets and streaming generators that run outside the original request context, the redaction
   state is captured before spawning and re-set inside the new greenlet/generator. This follows the same pattern
   used for `captured_workflow_override`.
3. The `finally` block in each API handler's `post()` method calls `clear_encryption_context()`.
4. `set_encryption_context(True)` also records the decision on Flask's request-local `g`. The Flask error logger
   filter uses this retained flag after view cleanup and removes message arguments, exception text and stack details.
   Only `resolve_request_privacy(False)` clears the provisional Flask marker when ordinary logging is selected.
   A new request receives a fresh flag; clearing thread state does not expose an earlier private view exception.
5. Streaming WSGI iterators restore the captured state for each advance and close, then restore their caller's
   previous state. Escaping private exceptions have generic messages and suppressed chains for server-side tracebacks.

**Logging helpers:**

- `sensitive_log(logger, level, msg, *args, **kwargs)`: Logs normally when redaction is inactive; emits a short
  `[Redacted]` placeholder when active.
- `sensitive_log_lazy(logger, level, msg, *arg_fns)`: Like `sensitive_log`, but accepts zero-arg callables instead
  of pre-computed values. The callables are only invoked when redaction is inactive, avoiding expensive
  serialization (e.g., `json.dumps`) when the result would be redacted anyway. Used at API handler entry points
  where request payloads would otherwise be serialized unconditionally.
- `log_prompt_content(logger, label, content)`: Replaces the common three-line separator pattern
  (`***...` / `Formatted_Prompt: ...` / `***...`) with a single redacted marker when active.

### What Is Redacted

All log statements that could contain user text have been converted to use the sensitive logging helpers:

- **Formatted prompts**: The full conversation text logged before each LLM call (in `base_chat_completions_handler`,
  `base_completions_handler`, `ollama_chat_api_handler`).
- **LLM output**: The raw response text logged after each LLM call (in `base_llm_api_handler`,
  `workflows_processor`, `prompt_categorization_service`).
- **Payload dumps**: Debug-level payload logging in all handler classes.
- **Request data**: Sanitized request payloads logged at API handler entry points.
- **Post-processing output**: Cleaned response text in `streaming_utils`.
- **Auxiliary content**: Message hashing content (`hashing_utils`), parsed conversations
  (`prompt_extraction_utils`), memory search keywords (`memory_service`), generation prompts
  (`timestamp_service`, `workflows_processor`, `response_handler`), and Claude prefill content
  (`claude_api_handler`).

All built-in Middleware module loggers use `get_sensitive_logger()`, including provider parsers, native MCP,
memory chunking and summary writes, image fallback, shared services and API callers. Caller re-logging therefore honors the same policy as the node that first reported the
error. Raw stderr traceback calls are avoided. Some operational messages from these adapters are also replaced with
the redaction marker; ordinary diagnostics remain available when redaction is disabled. Custom Python modules must
use these helpers themselves; arbitrary print calls and independent loggers are outside this policy.

### How to Add New Sensitive Log Statements

When adding a log statement that could contain user content:

```python
from Middleware.utilities.sensitive_logging_utils import get_sensitive_logger, sensitive_log, sensitive_log_lazy, log_prompt_content

logger = get_sensitive_logger(__name__)

# For general sensitive content:
sensitive_log(logger, logging.INFO, "Some content: %s", user_content)

# When args are expensive to compute (e.g., JSON serialization):
sensitive_log_lazy(logger, logging.DEBUG,
                   "Request data: %s",
                   lambda: json.dumps(sanitize(data)))

# For the "Formatted_Prompt" / "Output from the LLM" separator pattern:
log_prompt_content(logger, "My Label", content_string)
```

Use `sensitive_log_lazy` when one or more arguments involve expensive computation (serialization, formatting). The
lambdas are only called when the message will actually be emitted, avoiding unnecessary work when the content would
be redacted.

Use `get_sensitive_logger()` for built-in module loggers so every severity and exception path honors the current
request policy. Direct logging methods on that adapter are protected. Third-party library loggers, startup print
messages and operator scripts with independent loggers are outside this boundary. Thread or greenlet callbacks
must still capture and restore the request context as described above.

`CancellationService.register_abort_callback()` captures the registering request's redaction flag in its stored
callable. Both immediate and deferred invocation run through `_invoke_abort_callback()`, outside the registry lock.
That helper combines the captured flag with the invoking caller's flag using logical OR. Callback diagnostics and
the service's own exception logging therefore remain private when either request requires it. The helper restores
the caller's thread/greenlet-local flag in `finally`, including control-flow interruption, and reapplies the effective
policy before logging an exception from a callback that changed the context. Flask retains its error-redaction marker
for the enclosing request after private callback work. No API key, prompt or complete request context is captured.

-----

## 6\. Dependency: `cryptography` Library

The `cryptography` library (`cryptography==50.0.0` in `requirements.txt`) is the sole new
dependency. It is licensed under the Apache 2.0 / BSD 3-Clause dual license. License files are included in
`ThirdParty-Licenses/cryptography/`.

The library provides:
- `cryptography.fernet.Fernet`: Symmetric encryption using AES-128-CBC with HMAC-SHA256 for authentication.
- `cryptography.hazmat.primitives.kdf.pbkdf2.PBKDF2HMAC`: Key derivation from the API key.

-----

## 7\. How to Extend

### Adding Encryption to a New File Type

If you add a new discussion-specific file (e.g., a new type of state file):

1. **Add a path function** in `config_utils.py` that delegates to `get_discussion_file_path()` with the appropriate
   `file_name` and the `api_key_hash` parameter:

   ```python
   def get_discussion_my_new_file_path(discussion_id, api_key_hash=None):
       return get_discussion_file_path(discussion_id, 'my_new_file', api_key_hash=api_key_hash)
   ```

2. **Add read/write functions** in `file_utils.py` that accept `encryption_key` and delegate to `_read_json_file` /
   `_write_json_file`:

   ```python
   def read_my_new_file(filepath: str, encryption_key: Optional[bytes] = None) -> Dict:
       file_path = Path(filepath)
       if not file_path.exists():
           return {}
       return _read_json_file(file_path, encryption_key)

   def write_my_new_file(filepath: str, data: Dict, encryption_key: Optional[bytes] = None) -> None:
       file_path = Path(filepath)
       file_path.parent.mkdir(parents=True, exist_ok=True)
       _write_json_file(file_path, data, encryption_key)
   ```

3. **Thread the parameters** from the `ExecutionContext` at the call site:

   ```python
   from Middleware.utilities.encryption_utils import (
       get_encryption_key_if_available,
       get_api_key_hash_if_available,
   )

   api_key_hash = get_api_key_hash_if_available(context.api_key)
   encryption_key = get_encryption_key_if_available(context.api_key)
   filepath = get_discussion_my_new_file_path(context.discussion_id, api_key_hash=api_key_hash)
   data = read_my_new_file(filepath, encryption_key=encryption_key)
   ```

### Changing the Key Derivation

To change the PBKDF2 parameters (iterations, salt format, algorithm), modify `derive_fernet_key()` in
`encryption_utils.py`. Be aware that changing these parameters will make all previously encrypted files unreadable
unless a migration path is implemented. The decryption fallback only handles the plaintext-to-encrypted transition,
not changes in encryption parameters. Similarly, if a user renames their WilmerAI username, the per-user salt
changes and their previously encrypted files require the original selection to remain readable. Preserve the existing
parameters and selection when reading those files.

### The `encryptUsingApiKey` Config Setting

The `encryptUsingApiKey` boolean in the user config (default: `false`) controls whether `get_encryption_key_if_available`
returns a key or `None`. Directory isolation via `get_api_key_hash_if_available` is unaffected by this setting; it
always returns a hash when an API key is present.

Only a JSON boolean is accepted when the setting is non-null. Strings such as `"false"`, numbers, and collections raise
`ValueError` instead of being interpreted through Python truthiness. Missing or null settings remain disabled.
Key derivation parameters and API-key hashing must remain compatible with existing files. The application has no
key storage or recovery mechanism; encrypted files require their original API key.

The config check is performed inside `get_encryption_key_if_available` via a lazy import of
`config_utils.get_encrypt_using_api_key()`. This means all existing call sites (which call
`get_encryption_key_if_available(context.api_key)`) automatically respect the config without changes.

### Reading Existing Encrypted Files

Runtime encryption remains opt-in and occurs during individual built-in file writes. It does not recursively scan
or encrypt a directory. Existing ciphertext remains readable with the original API key and workflow selection;
`decrypt_bytes` remains the low-level in-memory primitive used by those readers. Disabling encryption does not
convert ciphertext to plaintext or move files between key namespaces.

### Adding SQLite Encryption

This is a known limitation that is non-trivial to address. The core difficulty is that Python's built-in `sqlite3`
module does not support encryption. Encrypting SQLite databases at rest requires one of the following approaches, each
with significant trade-offs:

1. **SQLCipher via `pysqlcipher3`**: The most common approach. SQLCipher is a fork of SQLite that adds transparent
   AES-256 encryption. However, it requires compiling native C code against the SQLCipher library, which must be
   installed separately on each platform. This introduces system-level dependencies (`libsqlcipher-dev` on Linux,
   Homebrew `sqlcipher` on macOS, manual builds on Windows) and breaks the current pure-pip install workflow.

2. **`sqleet` or similar lightweight forks**: Smaller alternatives to SQLCipher exist, but they have the same
   fundamental issue: they require replacing the SQLite engine, which means native compilation.

3. **Application-level encryption of blobs**: Encrypt individual column values before insertion and decrypt after
   retrieval. This avoids native dependencies but breaks FTS5 full-text search (the index would contain ciphertext,
   not searchable terms), which is central to the vector memory system.

If this is pursued, the likely approach would be:

1. Using `pysqlcipher3` (or vendoring a pre-built SQLCipher binary per platform).
2. Deriving a database-specific key from the API key (possibly reusing `derive_fernet_key` or a separate derivation).
3. Modifying `vector_db_utils.py` to open databases with `PRAGMA key = ...`.
4. Modifying `locking_service.py` for the locking database.
5. Providing a migration path for existing unencrypted databases.

-----

## 8\. Testing

Tests for the encryption utilities are in `Tests/utilities/test_encryption_utils.py` and
`Tests/utilities/test_sensitive_logging_utils.py`, and are also integrated into existing test files that test
`file_utils.py` and `config_utils.py`. The encryption-related test patterns include:

- Verifying that `derive_fernet_key` produces deterministic output for the same input.
- Verifying that `hash_api_key` produces a 16-character hex string.
- Verifying round-trip encrypt/decrypt.
- Verifying the plaintext fallback in `_read_json_file` when decryption fails.
- Verifying that file I/O functions work correctly with and without encryption keys.
- Verifying that `get_discussion_file_path` produces isolated paths when `api_key_hash` is provided.

The encryption tests use the real `cryptography` library for core operations (key derivation, encrypt, decrypt) and
mock only `config_utils` functions to avoid filesystem dependencies.

The sensitive logging tests (`test_sensitive_logging_utils.py`) cover:
- Thread-local context isolation between threads.
- `sensitive_log` emitting content when inactive and redacting when active.
- `log_prompt_content` emitting separator lines when inactive and a single redacted marker when active.
- Context toggling during a sequence of log calls.

### Extension diagnostics and atomic writes

CurlCommand omits command arguments from diagnostics even when content redaction is disabled. Its errors, the shipped
MCP helper chain, and built-in web/wiki/research tool diagnostics use get_sensitive_logger. The adapter routes all
levels through the current request redaction context. Redacted exception calls suppress exception and stack details
as well as the message. Custom Python modules must use the same helpers for request-sensitive diagnostics.

The shared atomic byte writer retries short writes until all bytes are written, then fsyncs and replaces the destination.
A zero-progress write or write error preserves the previous destination and removes the temporary file.
