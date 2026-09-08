### **Feature Guide: Per-User Encryption and Data Isolation**

> **Warning: losing the API key means losing access to encrypted data permanently.** WilmerAI does not store the key
> and has no key reset, recovery key, backdoor, or other mechanism to recover that data. Encrypted backups also need
> the original key. Before enabling encryption, save the exact API key securely, retain the original workflow-selection
> name, and make a separate backup of your existing files.

**Encryption is off by default.** Only the JSON boolean `"encryptUsingApiKey": true`, together with an API key in
the request, enables it.

WilmerAI supports directory isolation and optional encryption for discussion files when a client sends an API key in
the `Authorization` header. Built-in conversation data is stored in the key's directory scope. Workflow-authored state
uses the same scope when its file path starts with `{Discussion_Directory}`.

API keys serve as client storage namespace secrets. They do not select a WilmerAI workflow and WilmerAI does not
validate them as login credentials. When a key is present, it determines which directory discussion files are stored
in. Directory isolation activates automatically; encryption requires an additional configuration setting.

-----

## How It Works

### Enabling Data Isolation

To enable client data isolation, configure each front-end application to send its own
`Authorization: Bearer <key>` header with every request to WilmerAI. Use a different high-entropy value for each
independent client. The key does not need to be registered in WilmerAI. It causes built-in discussion files, and custom
workflow files rooted at `{Discussion_Directory}`, to use a subdirectory derived from a hash of the key.

### Enabling Encryption

Data isolation alone does not encrypt files; they remain plaintext JSON, just stored in separate directories. To also
encrypt files at rest, add the following setting to your user configuration file (under
`Public/Configs/Users/<workflow-selection>.json`):

```json
{
  "encryptUsingApiKey": true
}
```

When this is set to `true` and an API key is present, all discussion JSON files are encrypted using a key derived from
the API key. When `false` (the default), files are stored as plaintext regardless of whether an API key is sent.

Use a JSON boolean, not a quoted string such as `"false"`; invalid types are rejected. Existing plaintext in the same
storage scope remains readable and is encrypted when next written. Merely reading it does not modify it. Files
already encrypted require the original API key and workflow selection; disabling the setting does not decrypt them.
Follow [Changing or Removing Encryption](#changing-or-removing-encryption) before turning it off.

**Example request with an API key:**

```bash
curl -X POST http://localhost:5006/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer my-secret-key" \
  -d '{
    "model": "my-workflow",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

**Example request without an API key (original behavior):**

```bash
curl -X POST http://localhost:5006/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "my-workflow",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

When no API key is sent, WilmerAI behaves exactly as it did before this feature was added. Files are stored in the
original directory structure and remain plaintext.

### What Happens When an API Key Is Present

**Directory isolation** always applies to built-in state when an API key is present. Discussion files are stored in a
subdirectory derived from a hash of the key. Workflow-authored state receives this behavior only when its path uses
`{Discussion_Directory}`. Files configured with an unrelated absolute path or a path built from only `{Discussion_Id}`
bypass this boundary.

```
Without API key:
  {discussionDirectory}/{discussion_id}/memories.json

With API key:
  {discussionDirectory}/{a1b2c3d4e5f6g7h8}/{discussion_id}/memories.json
```

The hash (`a1b2c3d4e5f6g7h8` in the example above) is a 16-character hex string derived from the API key. The raw API
key never appears in file paths or on disk.

For workflow file nodes, use the canonical variable rather than reconstructing this layout:

```json
{
  "type": "SaveCustomFile",
  "filepath": "{Discussion_Directory}/workflow_state.md",
  "content": "{agent1Output}"
}
```

`{Discussion_Directory}` fails closed when the request has no discussion ID. The raw API key and key hash are not
exposed to workflows.

**File encryption** applies only when `encryptUsingApiKey` is `true` in the user config. When enabled, all discussion
JSON files are encrypted using the API key before being written to disk. The encryption uses industry-standard Fernet
symmetric encryption (AES-128-CBC with HMAC-SHA256 authentication). Only a request carrying the same API key can
decrypt and read those files when it also selects the same workflow configuration.

### Files That Are Encrypted

All discussion-specific JSON files are encrypted when `encryptUsingApiKey` is `true` and an API key is present:

- Memory files (long-term conversation memory chunks)
- Chat summary files (rolling conversation summaries)
- Timestamp files (time tracking for conversation turns)
- Vision response cache files
- Condensation tracker files
- Context compactor state files

The built-in `state_document.md` is also encrypted under these settings. Its `.bak` file preserves the previous version's
bytes, so it is encrypted when that previous version was encrypted; the first backup after opt-in can still be plaintext.
Custom text files and SQLite databases do not inherit this encryption.

### Log Redaction

When encryption is enabled, WilmerAI automatically redacts sensitive content from built-in request logging (both terminal
and log files). Prompts, LLM responses, payload data, and other user-generated text are replaced with a short
`[Redacted]` marker. Operational logs (request IDs, timing data, node execution summaries) remain visible for
debugging purposes.

Built-in provider parsers, native MCP calls, memory chunking and summary writes, image fallback, shipped MCP helpers and retrieval tools use the same request redaction policy. Redacted diagnostics omit exception and stack details. CurlCommand never logs its command arguments. Operator-provided PythonModule scripts must use WilmerAI's sensitive logging helpers to apply this policy to their own logs. Independent third-party logging and startup messages are outside this request logging boundary.

OpenAI chat/completions and Ollama chat/generate requests redact diagnostics while user selection is pending.
After selection, payload logging follows that user's privacy setting. Private payloads are not serialized for logging,
and early errors or rejected user selections remain redacted. Subsequent ordinary requests retain normal diagnostics.

Log redaction can also be enabled independently of encryption by setting `"redactLogOutput": true` in your user
configuration file. This is useful if you want to suppress sensitive content from logs without enabling file
encryption. When this setting is active, all requests have their log output redacted, regardless of whether an
API key is present. See the [Log Redaction Without Encryption](#log-redaction-without-encryption) section below.

Cancellation cleanup keeps the original generation request's redaction setting, including when a separate cancellation
request triggers it. Cleanup errors and the cancellation service's own error logs follow that setting. An already
private cancelling request also stays private; ordinary requests retain normal diagnostic output.

### Files That Are NOT Encrypted

- **SQLite databases**: The vector memory database and the workflow locking database remain unencrypted. Encrypting
  SQLite at rest is non-trivial: it typically requires compiling against SQLCipher (a third-party encrypted SQLite
  fork), which introduces native build dependencies and complicates cross-platform distribution. This is a known
  limitation. The vector database contains readable memory text and metadata as well as embeddings. The workflow
  locking database may contain discussion IDs. Protect these files separately when encryption at rest is required.
- **Configuration files**: All files under `Public/Configs/` (users, workflows, endpoints, presets, etc.) are not
  encrypted. These are system configuration, not per-user conversation data.
- **Custom text files**: `GetCustomFile`, `SaveCustomFile`, and `ConversationChunkProcessor` files are plaintext even
  when their paths use `{Discussion_Directory}`. The variable gives them directory isolation, not encryption at rest.

-----

## Backwards Compatibility

This feature is designed for transparent adoption:

- **Adding a key creates a new storage scope**: Keyed requests intentionally do not fall back to old unkeyed files.
  Copy data into the new key-hash directory only after deciding which client should own it. This prevents a keyed
  request from silently reading legacy shared state.

- **Mixed-mode operation**: Some clients can send an API key while others do not. Each operates independently.
  Clients without an API key continue to use the original directory structure with plaintext files.

- **Key and workflow-selection consistency**: The encryption key is tied to both the API key string and the selected
  file under `Public/Configs/Users`. If a client changes either value, it cannot read files encrypted with the previous
  combination. Directory isolation itself uses only the API-key hash, so changing the workflow
  selection can otherwise point at the same files with an incompatible encryption key.

- **Read errors**: If a built-in discussion file or state-document backup cannot be read, its update stops. Check
  file permissions and the original encryption settings, or recover from an independent backup.

- **Backups**: Keep independent backups as well as the state document's previous-version backup. The first backup
  after enabling encryption can still contain the previous plaintext; protect pre-encryption copies separately.

### Discussion File Directory Layout Migration

WilmerAI has consolidated all discussion files into per-discussion-id subdirectories. Previously, some files
(particularly timestamps) were stored as flat files in the discussion directory root:

```
Old layout (flat files):
  {discussionDirectory}/{discussion_id}_timestamps.json
  {discussionDirectory}/{discussion_id}_memories.json

New layout (nested directories):
  {discussionDirectory}/{discussion_id}/timestamps.json
  {discussionDirectory}/{discussion_id}/memories.json

New layout with API key isolation:
  {discussionDirectory}/{api_key_hash}/{discussion_id}/timestamps.json
  {discussionDirectory}/{api_key_hash}/{discussion_id}/memories.json
```

For unkeyed legacy data, WilmerAI checks the nested path first, then an existing flat file. An existing flat file
continues to be read and written at that location. New files use nested storage; normal writes do not move old files.
Move legacy files explicitly while the server is stopped if you want to consolidate their layout. Keyed requests
remain isolated from unkeyed data.

-----

## Setting Up Your Front-End

### Open WebUI

In Open WebUI, you can configure the API key in the connection settings. When adding a WilmerAI connection (as an
OpenAI-compatible endpoint), set the API key field to any value. Open WebUI will automatically include it as a
`Bearer` token in every request.

### SillyTavern

In SillyTavern, the API key field in the connection settings is sent as the `Authorization: Bearer` header. Enter a
unique high-entropy value to enable directory isolation. Encryption also requires `encryptUsingApiKey: true`.

### Custom Scripts

For custom integrations, add the `Authorization` header to your HTTP requests:

```python
import requests

response = requests.post(
    "http://localhost:5006/v1/chat/completions",
    headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer my-secret-key",
    },
    json={
        "model": "my-workflow",
        "messages": [{"role": "user", "content": "Hello"}],
    },
)
```

-----

## Log Redaction Without Encryption

If you want to redact sensitive content from logs but do not need file encryption or per-user directory isolation,
add the following to your selected workflow configuration file
(`Public/Configs/Users/<workflow-selection>.json`):

```json
{
  "redactLogOutput": true
}
```

When this is set to `true`, all requests, whether or not they include an API key, have their sensitive log
output redacted. Prompts, LLM responses, and payload data are replaced with `[Redacted]` markers in both terminal
and file logs. This setting operates independently of `encryptUsingApiKey`: you can use either, both, or neither.

This is useful for single-user setups where you do not need encryption or directory isolation but still want to
prevent sensitive content from appearing in logs (for example, when logs are shipped to a centralized logging system
or when the terminal is visible to others).

-----

## Important Considerations

- **Key management**: WilmerAI does not store or validate API keys. The key is used solely for encryption and
  directory isolation. If you lose the key, the encrypted files cannot be recovered. There is no key reset mechanism.

- **Key format**: The API key can be any non-empty string. There are no format requirements. However, using a
  sufficiently long and random string is recommended for security (e.g., 32+ characters).

- **Performance**: The encryption overhead is negligible for the JSON files used by WilmerAI's discussion system.
  The `cryptography` library is lazily loaded, so there is zero overhead when no API key is present.

- **Multiple clients, same instance**: Each independent client or trust domain should use a different API key. Built-in
  data and workflow files based on `{Discussion_Directory}` then occupy separate directories even when the clients use
  the same `discussionId`. This does not authenticate the caller; anyone who knows a key can select that storage scope.

- **Supported endpoints**: Both the OpenAI-compatible endpoints (`/v1/chat/completions`, `/v1/completions`) and the
  Ollama-compatible endpoints (`/api/chat`, `/api/generate`) support API key extraction.

-----

## Changing or Removing Encryption

> **Caution:** Earlier versions included optional rekey/decryption scripts, now **deprecated and removed**. These
> manually run scripts targeted the **API-key-hash subdirectory beneath the configured discussion directory** and
> never ran automatically at startup. Rekeying processed JSON files, `state_document.md`, and `state_document.md.bak`
> throughout that subtree.
> If unrelated files matching those names or extensions had been stored there, they could also have been encrypted.
> Directory links could redirect the target, and renaming the hash directory changed paths for files inside it.
>
> Older copies of these scripts should no longer be used. A more guided replacement with clearer safeguards is
> planned for a future release to reduce the possibility of user error.

Keep the original API key and exact workflow-selection name while using existing encrypted discussions. Changing
either can make those files inaccessible. Setting `encryptUsingApiKey` to `false` does not decrypt existing files;
removing the Bearer key selects a different storage namespace and does not move the data.

Preserve a complete independent backup before changing encryption settings. Normal reads can still decrypt existing
files with their original key and workflow selection. An encrypted backup also requires its original key.
