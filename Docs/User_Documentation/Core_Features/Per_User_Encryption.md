### **Feature Guide: Per-User Encryption and Data Isolation**

WilmerAI supports directory isolation and optional encryption for discussion files when a client sends an API key in
the `Authorization` header. This ensures that each user's conversation data (memories, chat summaries, timestamps, and
related state) is stored separately and, when encryption is enabled, encrypted at rest.

API keys serve as user identifiers. When an API key is present, it determines which directory discussion files are
stored in, effectively treating each unique API key as a distinct user. Directory isolation activates automatically
when an API key is present. Encryption requires an additional configuration setting.

-----

## How It Works

### Enabling Data Isolation

To enable per-user data isolation, configure your front-end application to send an `Authorization: Bearer <key>` header
with every request to WilmerAI. The key can be any non-empty string -- it does not need to match any specific format or
be registered anywhere in WilmerAI's configuration. This causes all discussion files to be stored in a subdirectory
derived from a hash of the API key.

### Enabling Encryption

Data isolation alone does not encrypt files -- they remain plaintext JSON, just stored in separate directories. To also
encrypt files at rest, add the following setting to your user configuration file (under
`Public/Configs/Users/<username>.json`):

```json
{
  "encryptUsingApiKey": true
}
```

When this is set to `true` and an API key is present, all discussion JSON files are encrypted using a key derived from
the API key. When `false` (the default), files are stored as plaintext regardless of whether an API key is sent.

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

**Directory isolation** always applies when an API key is present. Discussion files are stored in a subdirectory derived
from a hash of the API key. This prevents different API keys from reading or overwriting each other's files, even if
they share the same `discussionId`.

```
Without API key:
  {discussionDirectory}/{discussion_id}/memories.json

With API key:
  {discussionDirectory}/{a1b2c3d4e5f6g7h8}/{discussion_id}/memories.json
```

The hash (`a1b2c3d4e5f6g7h8` in the example above) is a 16-character hex string derived from the API key. The raw API
key never appears in file paths or on disk.

**File encryption** applies only when `encryptUsingApiKey` is `true` in the user config. When enabled, all discussion
JSON files are encrypted using the API key before being written to disk. The encryption uses industry-standard Fernet
symmetric encryption (AES-128-CBC with HMAC-SHA256 authentication). Only a request carrying the same API key can
decrypt and read those files.

### Files That Are Encrypted

All discussion-specific JSON files are encrypted when `encryptUsingApiKey` is `true` and an API key is present:

- Memory files (long-term conversation memory chunks)
- Chat summary files (rolling conversation summaries)
- Timestamp files (time tracking for conversation turns)
- Vision response cache files
- Condensation tracker files
- Context compactor state files

### Log Redaction

When encryption is enabled, WilmerAI automatically redacts sensitive content from all logging output (both terminal
and log files). Prompts, LLM responses, payload data, and other user-generated text are replaced with a short
`[Redacted]` marker. Operational logs (request IDs, timing data, node execution summaries) remain visible for
debugging purposes.

This ensures that even if someone has access to the terminal or log files, they cannot see the content of an
encrypted user's conversations.

Log redaction can also be enabled independently of encryption by setting `"redactLogOutput": true` in your user
configuration file. This is useful if you want to suppress sensitive content from logs without enabling file
encryption. When this setting is active, all requests have their log output redacted, regardless of whether an
API key is present. See the [Log Redaction Without Encryption](#log-redaction-without-encryption) section below.

### Files That Are NOT Encrypted

- **SQLite databases**: The vector memory database and the workflow locking database remain unencrypted. Encrypting
  SQLite at rest is non-trivial -- it typically requires compiling against SQLCipher (a third-party encrypted SQLite
  fork), which introduces native build dependencies and complicates cross-platform distribution. This is a known
  limitation. In practice, vector embeddings do not directly expose conversation text, but the workflow locking
  database may contain discussion IDs.
- **Configuration files**: All files under `Public/Configs/` (users, workflows, endpoints, presets, etc.) are not
  encrypted. These are system configuration, not per-user conversation data.

-----

## Backwards Compatibility

This feature is designed for transparent adoption:

- **No migration required**: Existing unencrypted discussion files are readable even after you start sending an API
  key. The system automatically detects whether a file is encrypted or plaintext and handles both. The first time an
  existing file is updated, it is transparently encrypted.

- **Mixed-mode operation**: Some clients can send an API key while others do not. Each operates independently.
  Clients without an API key continue to use the original directory structure with plaintext files.

- **Key consistency**: The encryption is tied to the specific API key string and the WilmerAI username. If a client
  changes its API key, it will not be able to read files encrypted with the previous key. Each API key effectively
  creates a separate, isolated data partition. If you change your WilmerAI username, you will need to re-key your
  encrypted files using the re-key script (see below).

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

This migration is fully backwards compatible. When WilmerAI looks for a discussion file, it first checks for the
new nested path. If that file does not exist, it checks for a legacy flat file at the old path. If a legacy file is
found, it is read from the old location. New files and updated files are always written to the new nested location.
No manual migration is required -- old files will continue to be read until they are naturally superseded.

-----

## Setting Up Your Front-End

### Open WebUI

In Open WebUI, you can configure the API key in the connection settings. When adding a WilmerAI connection (as an
OpenAI-compatible endpoint), set the API key field to any value. Open WebUI will automatically include it as a
`Bearer` token in every request.

### SillyTavern

In SillyTavern, the API key field in the connection settings is sent as the `Authorization: Bearer` header. Enter
any value to enable encryption.

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
add the following to your user configuration file (`Public/Configs/Users/<username>.json`):

```json
{
  "redactLogOutput": true
}
```

When this is set to `true`, all requests -- whether or not they include an API key -- have their sensitive log
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

- **Multiple users, same instance**: This feature is designed for shared WilmerAI instances. Each user (or front-end
  application) can use a different API key, and their discussion data will be fully isolated and independently
  encrypted. Two users can even use the same `discussionId` without conflict, as their files are in separate
  directories.

- **Supported endpoints**: Both the OpenAI-compatible endpoints (`/v1/chat/completions`, `/v1/completions`) and the
  Ollama-compatible endpoints (`/api/chat`, `/api/generate`) support API key extraction.

-----

## Changing or Removing Encryption

WilmerAI includes scripts in the `Scripts/` directory to re-key or decrypt existing files. These scripts use the
project's virtual environment, so no additional installs are needed.

### Before You Start

**Stop the WilmerAI server before running the rekey or decrypt scripts.** Running these scripts while the server is
active may cause data corruption if WilmerAI reads or writes discussion files during the re-key process.

**Back up your discussion files before running the rekey or decrypt scripts.** These scripts modify files in-place.
If the process is interrupted or something goes wrong, your original encrypted files may not be recoverable without
a backup. The script will prompt you to confirm you have backed up (or offer to create a backup automatically), but
it is safest to do this yourself beforehand.

### Passing API Keys Securely

The rekey script accepts API keys via command-line arguments (`--api-key`, `--new-api-key`), but command-line
arguments are visible to other users on the same machine via `ps` or Task Manager. For better security, pass your
keys via environment variables instead:

**macOS / Linux:**

```bash
export WILMER_API_KEY="old-key-here"
export WILMER_NEW_API_KEY="new-key-here"
./Scripts/rekey_encrypted_files.sh --user myuser
```

**Windows (PowerShell):**

```powershell
$env:WILMER_API_KEY = "old-key-here"
$env:WILMER_NEW_API_KEY = "new-key-here"
Scripts\rekey_encrypted_files.bat --user myuser
```

When both an environment variable and a command-line argument are provided, the command-line argument takes
precedence.

### Re-keying (changing your API key)

If you need to change your API key, run the re-key script to decrypt all files with the old key and re-encrypt them
with the new key. The directory is automatically renamed to match the new key's hash.

**macOS / Linux:**

```bash
./Scripts/rekey_encrypted_files.sh --user myuser --api-key "old-key-here" --new-api-key "new-key-here"
```

**Windows:**

```bat
Scripts\rekey_encrypted_files.bat --user myuser --api-key "old-key-here" --new-api-key "new-key-here"
```

### Decrypting (removing encryption)

To decrypt all files and leave them as plaintext (for example, before disabling `encryptUsingApiKey`), run the
script without `--new-api-key`:

**macOS / Linux:**

```bash
./Scripts/rekey_encrypted_files.sh --user myuser --api-key "your-key-here"
```

**Windows:**

```bat
Scripts\rekey_encrypted_files.bat --user myuser --api-key "your-key-here"
```

This decrypts all files in place. Files that are already plaintext are left unchanged. After decrypting, you can set
`encryptUsingApiKey` to `false` in your user config (or remove the setting entirely) and your data will remain
accessible.
