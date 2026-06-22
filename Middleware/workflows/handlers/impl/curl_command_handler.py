# /Middleware/workflows/handlers/impl/curl_command_handler.py

import json
import logging
import re
import subprocess
import threading
from typing import Any, Dict, FrozenSet, List

from Middleware.utilities.network_security_utils import check_url_allowed
from Middleware.utilities.streaming_utils import stream_static_content
from Middleware.workflows.handlers.base.base_workflow_node_handler import BaseHandler
from Middleware.workflows.models.execution_context import ExecutionContext

logger = logging.getLogger(__name__)

_READ_CHUNK_SIZE = 65536
_DEFAULT_TIMEOUT_SECONDS = 30
# Schemes that may be introduced into an arg via variable substitution while the
# (default-on) scheme-injection guard is active. Any other explicit scheme (file,
# ftp, scp, dict, gopher, ldap, smtp, ...) introduced by substitution is rejected:
# curl would otherwise read a local file or reach an internal service. A two-or-more
# character scheme is required so a Windows drive letter ("C:\path") is not flagged.
_ALLOWED_SUBSTITUTED_SCHEMES = frozenset({"http", "https"})
_SCHEME_PREFIX_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]+):")
# Default download-size cap (bytes) injected as curl's native `--max-filesize`
# when the author has not specified one. Set `maxResponseBytes` to 0 (or a
# negative number) on the node to disable injection.
_DEFAULT_MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MiB
_MAX_FILESIZE_FLAGS = ("--max-filesize",)
_VALID_OUTPUT_FORMATS = ("stdout", "stdout+stderr", "full")
_VALID_ON_ERROR = ("raise", "return")
_CURL_BINARY = "curl"

# --- SSRF address-guard URL detection (used only when blockPrivateAddresses or
# allowedHosts is enabled) ---
# curl options that consume the FOLLOWING argument as their value, so that value is not
# itself a URL position. Not exhaustive, but covers the common value-taking flags; an
# unrecognized option is treated as NOT consuming a value, which errs toward checking an
# extra arg (a harmless false rejection) rather than skipping a real URL (an SSRF
# bypass). "--url" is handled separately because its value IS a URL to validate.
_CURL_VALUE_OPTIONS = frozenset({
    "-H", "--header", "-d", "--data", "--data-raw", "--data-binary", "--data-urlencode",
    "-F", "--form", "--form-string", "-o", "--output", "-A", "--user-agent",
    "-e", "--referer", "-b", "--cookie", "-c", "--cookie-jar", "-u", "--user",
    "-U", "--proxy-user", "-x", "--proxy", "--preproxy", "-T", "--upload-file",
    "-E", "--cert", "--cert-type", "--key", "--key-type", "--pass", "--cacert", "--capath",
    "-K", "--config", "-X", "--request", "--connect-to", "--resolve", "--max-filesize",
    "--max-redirs", "--max-time", "-m", "--connect-timeout", "--retry", "--retry-delay",
    "--retry-max-time", "-r", "--range", "-w", "--write-out", "-D", "--dump-header",
    "--interface", "--limit-rate", "-y", "--speed-time", "-Y", "--speed-limit",
    "-z", "--time-cond", "--socks5", "--socks5-hostname", "--socks4", "--socks4a",
})
_CURL_URL_OPTION = "--url"
# A leading "<scheme>://"; distinguishes an explicit-scheme URL from a schemeless one.
_URL_SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*)://")
# A bare authority token that looks like host[:port] (or a bracketed IPv6 literal). A
# schemeless arg whose leading token matches is a URL curl fetches over http; a token
# that does not match (e.g. "-", an empty value) is not treated as a URL.
_HOSTISH_RE = re.compile(r"^(?:\[[0-9A-Fa-f:]+\]|[A-Za-z0-9][A-Za-z0-9._\-]*)(?::\d+)?$")


class CurlCommandHandler(BaseHandler):
    """
    Handles the execution of 'CurlCommand' nodes.

    Invokes the system `curl` binary via `subprocess.Popen` with `shell=False`. Arguments
    are supplied as a JSON list and each element is variable-substituted before being
    passed to curl. Returns curl's stdout (default), stdout+stderr, or a full payload
    with returncode.

    Note on the SSRF address guard (`blockPrivateAddresses` / `allowedHosts`): it is
    best-effort here, not a hard boundary. The host is validated in Python
    (`check_url_allowed` parses with `urlsplit` and resolves with `getaddrinfo`), but the
    raw arg string is then handed to `curl`, which re-parses the URL and re-resolves DNS
    itself — so the component validated is not the component that connects. URL-parser
    divergence (e.g. alternate IP encodings, unusual delimiters) and DNS rebinding can
    therefore slip past it; `--max-redirs 0` (injected while the guard is active) closes
    only the redirect-bounce vector. For untrusted/conversation-derived URLs prefer the
    WebFetch node, which validates and connects in the same stack. See the CurlCommand
    user docs ("SSRF address guard") for the full rationale.
    """

    def handle(self, context: ExecutionContext) -> Any:
        """
        Executes a curl command as configured on the node and returns the result.

        Args:
            context (ExecutionContext): The central object containing all runtime data for the node.

        Returns:
            Any: A string payload (stdout, combined output, or JSON-serialized envelope),
                 or a streaming generator wrapping that payload when `context.stream` is True.

        Raises:
            ValueError: If required config is missing, malformed, has an invalid enum
                value, `timeout`/`maxResponseBytes` is not numeric, `timeout` is
                non-positive, `blockOptionInjection` is not a boolean, or (when
                `blockOptionInjection` is enabled) a substituted arg resolves to a
                curl option or an `@`-prefixed local-file data value.
            FileNotFoundError: If the `curl` binary is not on PATH.
            subprocess.TimeoutExpired: When `onError` is "raise" and curl exceeds `timeout`.
            RuntimeError: When `onError` is "raise" and curl exits with a non-zero status.
        """
        config = context.config

        args_template = config.get("args")
        if args_template is None:
            raise ValueError("CurlCommand node requires an 'args' field (a JSON list).")
        if not isinstance(args_template, list):
            raise ValueError("CurlCommand 'args' must be a JSON list of strings.")

        timeout = self._validate_timeout(config.get("timeout", _DEFAULT_TIMEOUT_SECONDS))
        output_format = config.get("outputFormat", "stdout")
        on_error = config.get("onError", "raise")
        proxy_template = config.get("proxy")
        max_bytes = self._validate_max_bytes(config.get("maxResponseBytes", _DEFAULT_MAX_RESPONSE_BYTES))
        block_option_injection = self._validate_bool(
            config.get("blockOptionInjection", False), "blockOptionInjection"
        )
        # Scheme-injection guard is ON by default (safe-by-default): a variable that
        # expands into a non-http(s) URL scheme is rejected. Set allowSchemeInjection
        # to true to fully open this up.
        allow_scheme_injection = self._validate_bool(
            config.get("allowSchemeInjection", False), "allowSchemeInjection"
        )
        # SSRF address guard (opt-in, both default off): blockPrivateAddresses rejects
        # http(s) URL args that target a private/internal/link-local address, and
        # allowedHosts restricts them to a host allowlist. See _resolve_args.
        block_private = self._validate_bool(
            config.get("blockPrivateAddresses", False), "blockPrivateAddresses"
        )
        allowed_hosts = self._resolve_allowed_hosts(config.get("allowedHosts"), context)

        if output_format not in _VALID_OUTPUT_FORMATS:
            raise ValueError(
                f"CurlCommand 'outputFormat' must be one of {_VALID_OUTPUT_FORMATS}; got {output_format!r}."
            )
        if on_error not in _VALID_ON_ERROR:
            raise ValueError(
                f"CurlCommand 'onError' must be one of {_VALID_ON_ERROR}; got {on_error!r}."
            )

        resolved_args = self._resolve_args(
            args_template, context, block_option_injection, allow_scheme_injection,
            block_private, allowed_hosts
        )
        proxy_args = self._resolve_proxy_args(proxy_template, context)
        max_filesize_args = self._max_filesize_args(resolved_args, max_bytes)
        redirect_guard_args = self._redirect_guard_args(resolved_args, block_private, allowed_hosts)
        command: List[str] = [
            _CURL_BINARY, *max_filesize_args, *redirect_guard_args, *proxy_args, *resolved_args
        ]

        logger.debug("CurlCommand running %r (timeout=%s, outputFormat=%s)",
                     command, timeout, output_format)

        return self._execute(command, timeout, max_bytes, on_error, output_format, context)

    def _execute(
        self,
        command: List[str],
        timeout: float,
        max_bytes: int,
        on_error: str,
        output_format: str,
        context: ExecutionContext,
    ) -> Any:
        """Runs curl, streaming stdout so the body is bounded at ``max_bytes`` in-process.

        ``subprocess.run`` buffers all of curl's stdout into memory regardless of any
        cap, and curl's native ``--max-filesize`` only aborts when the server advertises
        an over-cap ``Content-Length`` — a chunked or unknown-length response slips past
        it. To bound memory for real, stdout is read incrementally with a running byte
        total and the process is killed the instant it exceeds the cap. stderr is drained
        concurrently (and bounded to the same cap) so a chatty diagnostic stream cannot
        fill its pipe and deadlock the stdout read. The injected ``--max-filesize``
        remains as a cheaper early-abort for the advertised-length case.

        Args:
            command (List[str]): The full curl command line, including the binary.
            timeout (float): Seconds to wait for curl before killing it.
            max_bytes (int): In-process response cap in bytes; non-positive disables it.
            on_error (str): "raise" to raise on failure, "return" to format an error payload.
            output_format (str): One of "stdout", "stdout+stderr", or "full".
            context (ExecutionContext): The central object containing all runtime data for the node.

        Returns:
            Any: The formatted result string, or a streaming generator wrapping it when
                ``context.stream`` is True.

        Raises:
            FileNotFoundError: If the ``curl`` binary is not on PATH.
            subprocess.TimeoutExpired: When ``on_error`` is "raise" and curl exceeds ``timeout``.
            RuntimeError: When ``on_error`` is "raise" and the response exceeds the cap or
                curl exits with a non-zero status.
        """
        cap = max_bytes if max_bytes > 0 else 0
        try:
            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
            )
        except FileNotFoundError:
            logger.error("CurlCommand could not find the 'curl' binary on PATH.")
            raise

        stdout_box: Dict[str, Any] = {}
        stderr_box: Dict[str, Any] = {}
        out_thread = threading.Thread(
            target=self._read_body, args=(proc, cap, stdout_box), daemon=True
        )
        err_thread = threading.Thread(
            target=self._read_diagnostic, args=(proc.stderr, cap, stderr_box), daemon=True
        )
        out_thread.start()
        err_thread.start()

        timed_out = False
        try:
            # Returns promptly once curl exits — including when _read_body kills it
            # on a cap breach — and otherwise after `timeout` seconds.
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            proc.wait()
        finally:
            out_thread.join()
            err_thread.join()
            self._close_stream(proc.stdout)
            self._close_stream(proc.stderr)

        stdout_text = stdout_box.get("data", b"").decode("utf-8", errors="replace")
        stderr_text = stderr_box.get("data", b"").decode("utf-8", errors="replace")

        if timed_out:
            logger.warning("CurlCommand timed out after %ss", timeout)
            exc = subprocess.TimeoutExpired(command, timeout, output=stdout_text, stderr=stderr_text)
            if on_error == "raise":
                raise exc
            return self._maybe_stream(self._format_timeout(exc, output_format, timeout), context)

        if stdout_box.get("truncated"):
            message = f"CurlCommand response exceeded the {cap}-byte cap (maxResponseBytes)."
            logger.warning("CurlCommand aborted: %s", message)
            if on_error == "raise":
                raise RuntimeError(message)
            return self._maybe_stream(
                self._format_cap_exceeded(message, stdout_text, stderr_text, output_format), context
            )

        completed = subprocess.CompletedProcess(command, proc.returncode, stdout_text, stderr_text)
        if completed.returncode != 0 and on_error == "raise":
            raise RuntimeError(
                f"CurlCommand exited with status {completed.returncode}: {completed.stderr.strip()}"
            )

        return self._maybe_stream(self._format_result(completed, output_format), context)

    @staticmethod
    def _read_body(proc: "subprocess.Popen", cap: int, box: Dict[str, Any]) -> None:
        """Reads curl's stdout into ``box['data']``, killing curl if it exceeds ``cap``.

        Runs on its own thread. Exceeding the cap sets ``box['truncated']`` and kills
        the process so the download stops rather than buffering an unbounded body.
        ``cap == 0`` disables the bound (reads to EOF).

        Args:
            proc (subprocess.Popen): The running curl process whose stdout is read.
            cap (int): Maximum bytes to retain; non-positive reads to EOF unbounded.
            box (Dict[str, Any]): Output box; ``data`` gets the bytes and ``truncated``
                the over-cap flag.
        """
        chunks: List[bytes] = []
        total = 0
        truncated = False
        stream = proc.stdout
        try:
            while True:
                chunk = stream.read(_READ_CHUNK_SIZE)
                if not chunk:
                    break
                if cap > 0 and total + len(chunk) > cap:
                    chunks.append(chunk[: cap - total])
                    truncated = True
                    proc.kill()
                    break
                chunks.append(chunk)
                total += len(chunk)
        except (OSError, ValueError):
            # The pipe can be torn down mid-read when the process is killed; keep
            # whatever was captured rather than raising from the reader thread.
            pass
        finally:
            box["data"] = b"".join(chunks)
            box["truncated"] = truncated

    @staticmethod
    def _read_diagnostic(stream: Any, cap: int, box: Dict[str, Any]) -> None:
        """Reads curl's stderr into ``box['data']``, keeping at most ``cap`` bytes.

        Runs on its own thread and always drains to EOF (discarding any overflow past
        the cap) so a verbose stderr cannot fill its pipe buffer and deadlock the
        stdout read. Unlike the body stream, an over-cap stderr is silently truncated
        and does not abort curl.

        Args:
            stream (Any): The process stderr stream to read.
            cap (int): Maximum bytes to retain; non-positive keeps everything.
            box (Dict[str, Any]): Output box; ``data`` gets the bytes and ``truncated``
                the over-cap flag.
        """
        chunks: List[bytes] = []
        total = 0
        truncated = False
        try:
            while True:
                chunk = stream.read(_READ_CHUNK_SIZE)
                if not chunk:
                    break
                if cap <= 0:
                    chunks.append(chunk)
                    continue
                remaining = cap - total
                if remaining > 0:
                    chunks.append(chunk[:remaining])
                    total += min(len(chunk), remaining)
                if len(chunk) > remaining:
                    truncated = True
        except (OSError, ValueError):
            pass
        finally:
            box["data"] = b"".join(chunks)
            box["truncated"] = truncated

    @staticmethod
    def _close_stream(stream: Any) -> None:
        """Closes a process stream, ignoring errors from an already-torn-down pipe.

        Args:
            stream (Any): The stream to close; ``None`` is a no-op.
        """
        try:
            if stream is not None:
                stream.close()
        except (OSError, ValueError):
            pass

    def _resolve_args(
        self,
        args_template: List[Any],
        context: ExecutionContext,
        block_option_injection: bool = False,
        allow_scheme_injection: bool = False,
        block_private: bool = False,
        allowed_hosts: FrozenSet[str] = frozenset(),
    ) -> List[str]:
        """Variable-substitutes each arg and enforces the injection and SSRF guards.

        Each template element is rendered with workflow variables, then checked (per the
        enabled guards) for option-like ('-') values, '@'-prefixed local-file data values,
        injected non-http(s) URL schemes, and disallowed http(s) addresses.

        Args:
            args_template (List[Any]): The raw args list from the node config.
            context (ExecutionContext): The central object containing all runtime data for the node.
            block_option_injection (bool): Reject substituted '-' or '@'-leading values.
            allow_scheme_injection (bool): Permit substituted non-http(s) URL schemes.
            block_private (bool): Reject http(s) args targeting private/internal addresses.
            allowed_hosts (FrozenSet[str]): Allowlist of lowercased hosts for http(s) args.

        Returns:
            List[str]: The resolved, validated argument values in template order.

        Raises:
            ValueError: If a substituted arg violates the option, data-file, scheme, or
                address guard.
        """
        address_guard_active = block_private or bool(allowed_hosts)
        resolved: List[str] = []
        for item in args_template:
            template_str = str(item)
            resolved_value = self.workflow_variable_service.apply_variables(template_str, context)
            # With shell=False there is no shell injection, but curl's own
            # options are still active. An untrusted variable (e.g. {userInput}) that
            # expands into a value starting with '-' would be parsed as a curl flag
            # (-o writes files, -K/--config reads a config file, -d @file / file://
            # read local files for exfil). When enabled, reject a resolved arg that
            # starts with '-' unless the author's template literally started with '-'
            # (i.e. the flag was written by the author, not injected via a variable).
            if (
                block_option_injection
                and resolved_value.startswith("-")
                and not template_str.startswith("-")
            ):
                raise ValueError(
                    "CurlCommand blocked an option-like argument produced by variable "
                    f"substitution: {resolved_value!r} (from template {template_str!r}). "
                    "A substituted value starting with '-' is treated by curl as an option. "
                    "Disable 'blockOptionInjection' if this is intentional."
                )
            # Data-file injection guard (shares the blockOptionInjection opt-in). curl
            # reads a local file when a data/upload/form value begins with '@'
            # (e.g. -d @/etc/passwd, --data-binary @file, -T @file). With shell=False
            # this is not shell injection, but a substituted '@'-leading value still
            # turns an intended data slot into a local-file read/exfil that the '-'
            # guard above does not catch. As with that guard, an '@' the author wrote
            # literally in the template is intentional and allowed; only one introduced
            # by substitution is blocked. Authors who want to send variable content
            # literally should use --data-raw, which does not honor a leading '@'.
            if (
                block_option_injection
                and resolved_value.startswith("@")
                and not template_str.startswith("@")
            ):
                raise ValueError(
                    "CurlCommand blocked an '@'-prefixed argument produced by variable "
                    f"substitution: {resolved_value!r} (from template {template_str!r}). "
                    "curl reads a local file when a data/upload value begins with '@' "
                    "(e.g. -d @file), so a substituted '@' value can read or exfiltrate a "
                    "local file. Use '--data-raw' to send variable content literally, or "
                    "disable 'blockOptionInjection' if this is intentional."
                )
            # Scheme-injection guard (ON by default). A value whose URL scheme was
            # introduced by substitution and is not http/https (e.g. file://, ftp://,
            # dict://, gopher://) lets curl read a local file or reach an internal
            # service. A scheme written literally by the author is intentional and
            # allowed; only an injected one is blocked.
            if not allow_scheme_injection:
                injected_scheme = self._injected_dangerous_scheme(template_str, resolved_value)
                if injected_scheme:
                    raise ValueError(
                        f"CurlCommand blocked a '{injected_scheme}:' URL produced by variable "
                        f"substitution: {resolved_value!r} (from template {template_str!r}). "
                        "Only http/https schemes may be introduced via substitution; a scheme "
                        "like file://, ftp://, scp://, dict://, or gopher:// can read local files "
                        "or reach internal services. Write the scheme literally in the args "
                        "template, or set 'allowSchemeInjection': true to permit substituted schemes."
                    )
            resolved.append(resolved_value)

        # SSRF address guard (post-resolution pass): validate every arg curl will treat
        # as a URL. Done after resolution so curl's argument grammar can be honored -- a
        # schemeless arg in a URL position (e.g. "169.254.169.254/...", which curl fetches
        # over http) is checked too, not only args carrying an explicit http(s):// scheme,
        # and an option's value (e.g. the "10.0.0.1" in "-d 10.0.0.1") is not mistaken for
        # a URL. Applies whether a URL was author-written or substituted, since both reach
        # the network.
        if address_guard_active:
            for candidate in self._url_targets(resolved):
                reason = check_url_allowed(candidate, block_private, allowed_hosts)
                if reason:
                    raise ValueError(
                        f"CurlCommand blocked a request to a disallowed address: {reason}. "
                        "Adjust the URL, extend 'allowedHosts', or disable 'blockPrivateAddresses'."
                    )
        return resolved

    def _url_targets(self, resolved_args: List[str]) -> List[str]:
        """Returns the http(s) URLs among the resolved args that curl will fetch.

        Walks the args the way curl parses them: an option that consumes the next
        argument hides that value (it is not a URL), ``--url``/``--url=`` name a URL
        explicitly, and any remaining positional argument is a URL curl fetches (a
        schemeless value defaults to http). Each is normalized to its http(s) form;
        non-http(s) schemes are skipped (the scheme-injection guard governs those).

        Args:
            resolved_args (List[str]): The variable-substituted argument values.

        Returns:
            List[str]: http(s) URL strings to validate against the address policy.
        """
        targets: List[str] = []
        i = 0
        n = len(resolved_args)
        while i < n:
            arg = resolved_args[i]
            if arg == _CURL_URL_OPTION:  # "--url" <value>: the next arg is the URL
                if i + 1 < n:
                    candidate = self._address_target(resolved_args[i + 1])
                    if candidate:
                        targets.append(candidate)
                i += 2
                continue
            if arg.startswith("--url="):
                candidate = self._address_target(arg[len("--url="):])
                if candidate:
                    targets.append(candidate)
                i += 1
                continue
            if arg in _CURL_VALUE_OPTIONS:  # option whose next arg is a value, not a URL
                i += 2
                continue
            if arg.startswith("-") and arg != "-":  # any other flag (boolean/--foo=bar/combined)
                i += 1
                continue
            candidate = self._address_target(arg)  # positional arg: a URL curl will fetch
            if candidate:
                targets.append(candidate)
            i += 1
        return targets

    @staticmethod
    def _address_target(arg: str) -> str:
        """Returns the http(s) URL form of a curl URL argument for address checking.

        An explicit http/https URL is returned unchanged. A schemeless value whose
        leading authority looks like a host[:port] is fetched by curl over http, so it
        is returned with an ``http://`` prefix. Any other value -- a non-http(s) scheme
        (governed by the scheme-injection guard) or a token that is not host-like --
        returns '' and is not address-checked.

        Args:
            arg (str): A single resolved URL-position argument.

        Returns:
            str: The http(s) URL to validate, or '' if the arg is not an http(s) target.
        """
        match = _URL_SCHEME_RE.match(arg)
        if match:
            return arg if match.group(1).lower() in ("http", "https") else ""
        authority = re.split(r"[/?#]", arg, maxsplit=1)[0]
        if _HOSTISH_RE.match(authority):
            return "http://" + arg
        return ""

    @staticmethod
    def _redirect_guard_args(
        resolved_args: List[str], block_private: bool, allowed_hosts: FrozenSet[str]
    ) -> List[str]:
        """Pins curl to zero redirects when the address guard is active.

        curl resolves and follows redirects itself, so a redirect target cannot be
        re-validated in-process the way WebFetch does. Disabling redirects keeps the
        guard's guarantee honest (a 3xx cannot bounce the request to an unvalidated,
        possibly internal host). No-op when the guard is off or the author already set
        their own --max-redirs.

        Args:
            resolved_args (List[str]): The resolved curl arguments, inspected for an
                existing --max-redirs.
            block_private (bool): Whether the private-address guard is enabled.
            allowed_hosts (FrozenSet[str]): The host allowlist; non-empty enables the guard.

        Returns:
            List[str]: ``['--max-redirs', '0']`` when the guard is active and unset,
                otherwise an empty list.
        """
        if not (block_private or allowed_hosts):
            return []
        if any(a == "--max-redirs" or a.startswith("--max-redirs=") for a in resolved_args):
            return []
        return ["--max-redirs", "0"]

    def _resolve_allowed_hosts(
        self, allowed_hosts_template: Any, context: ExecutionContext
    ) -> FrozenSet[str]:
        """Resolves the optional ``allowedHosts`` allowlist to a set of lowercased hosts.

        Absent (``None``) means no allowlist (empty set). Each entry supports variable
        substitution so an allowlist can be sourced from a workflow variable.

        Args:
            allowed_hosts_template (Any): The raw ``allowedHosts`` config (``None`` or a list).
            context (ExecutionContext): The central object containing all runtime data for the node.

        Returns:
            FrozenSet[str]: The resolved, lowercased, non-empty host entries.

        Raises:
            ValueError: If ``allowedHosts`` is provided but is not a list.
        """
        if allowed_hosts_template is None:
            return frozenset()
        if not isinstance(allowed_hosts_template, list):
            raise ValueError("CurlCommand 'allowedHosts' must be a JSON list of host strings.")
        resolved = set()
        for entry in allowed_hosts_template:
            value = self.workflow_variable_service.apply_variables(str(entry), context).strip().lower()
            if value:
                resolved.add(value)
        return frozenset(resolved)

    @staticmethod
    def _injected_dangerous_scheme(template_str: str, resolved_value: str) -> str:
        """Returns the URL scheme (e.g. 'file') if substitution introduced a non-http(s)
        scheme the author's template did not already carry; otherwise an empty string.

        A scheme the author wrote literally (the template starts with the same scheme)
        is treated as intentional and is not flagged.

        Args:
            template_str (str): The raw arg template before substitution.
            resolved_value (str): The arg value after variable substitution.

        Returns:
            str: The injected non-http(s) scheme (lowercased), or '' if none was introduced.
        """
        match = _SCHEME_PREFIX_RE.match(resolved_value.strip())
        if not match:
            return ""
        scheme = match.group(1).lower()
        if scheme in _ALLOWED_SUBSTITUTED_SCHEMES:
            return ""
        template_match = _SCHEME_PREFIX_RE.match(template_str.strip())
        if template_match and template_match.group(1).lower() == scheme:
            return ""
        return scheme

    @staticmethod
    def _validate_bool(value: Any, field: str) -> bool:
        """Validates a boolean config field, mirroring the node's other field validations.

        Args:
            value (Any): The configured value to validate.
            field (str): The config field name, used in the error message.

        Returns:
            bool: The validated boolean value.

        Raises:
            ValueError: If ``value`` is not a boolean.
        """
        if not isinstance(value, bool):
            raise ValueError(f"CurlCommand '{field}' must be a boolean (true/false); got {value!r}.")
        return value

    @staticmethod
    def _validate_max_bytes(value: Any) -> int:
        """Coerces the configured download cap to an integer number of bytes.

        ``0`` (or any non-positive value) disables ``--max-filesize`` injection.

        Args:
            value (Any): The configured ``maxResponseBytes`` value to coerce.

        Returns:
            int: The cap as an integer number of bytes.

        Raises:
            ValueError: If ``value`` is a boolean or cannot be parsed as an integer.
        """
        if isinstance(value, bool):
            raise ValueError(f"CurlCommand 'maxResponseBytes' must be an integer; got {value!r}.")
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"CurlCommand 'maxResponseBytes' must be an integer; got {value!r}.")
        return value

    @staticmethod
    def _max_filesize_args(resolved_args: List[str], max_bytes: int) -> List[str]:
        """Returns ``['--max-filesize', '<bytes>']`` unless capping is off or already set.

        Uses curl's native ``--max-filesize`` so a download larger than the cap is
        aborted. Skipped when the author already supplied their own value.

        Args:
            resolved_args (List[str]): The resolved curl arguments, inspected for an
                existing --max-filesize.
            max_bytes (int): The cap in bytes; non-positive disables injection.

        Returns:
            List[str]: The ``--max-filesize`` flag pair, or an empty list when skipped.
        """
        if max_bytes <= 0:
            return []
        if any(arg in _MAX_FILESIZE_FLAGS or arg.startswith("--max-filesize=") for arg in resolved_args):
            return []
        return ["--max-filesize", str(max_bytes)]

    def _resolve_proxy_args(self, proxy_template: Any, context: ExecutionContext) -> List[str]:
        """Resolves the optional ``proxy`` config into curl's ``-x`` proxy arguments.

        Absent (``None``) or empty after substitution means no proxy (empty list). The
        proxy string supports variable substitution.

        Args:
            proxy_template (Any): The raw ``proxy`` config (``None`` or a string URL).
            context (ExecutionContext): The central object containing all runtime data for the node.

        Returns:
            List[str]: ``['-x', '<proxy>']`` when a proxy is set, otherwise an empty list.

        Raises:
            ValueError: If ``proxy`` is provided but is not a string.
        """
        if proxy_template is None:
            return []
        if not isinstance(proxy_template, str):
            raise ValueError(
                "CurlCommand 'proxy' must be a string URL (e.g., 'socks5://host:1080')."
            )
        resolved = self.workflow_variable_service.apply_variables(proxy_template, context)
        if not resolved:
            return []
        return ["-x", resolved]

    @staticmethod
    def _validate_timeout(value: Any) -> float:
        """Coerces the configured timeout to a positive number of seconds.

        Mirrors the node's other up-front field validations so a non-numeric
        or non-positive value raises a clear ``ValueError`` instead of an
        opaque ``TypeError`` from ``proc.wait(timeout=...)``.

        Args:
            value (Any): The configured ``timeout`` value to coerce.

        Returns:
            float: The timeout as a positive number of seconds.

        Raises:
            ValueError: If ``value`` is a boolean, non-numeric, or non-positive.
        """
        if isinstance(value, bool):
            raise ValueError(f"CurlCommand 'timeout' must be a number of seconds; got {value!r}.")
        if not isinstance(value, (int, float)):
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"CurlCommand 'timeout' must be a number of seconds; got {value!r}.")
        if value <= 0:
            raise ValueError(f"CurlCommand 'timeout' must be a positive number of seconds; got {value!r}.")
        return value

    @staticmethod
    def _format_result(completed: subprocess.CompletedProcess, output_format: str) -> str:
        """Formats a completed curl run per ``output_format``.

        Args:
            completed (subprocess.CompletedProcess): The finished curl process result.
            output_format (str): "stdout", "stdout+stderr", or "full" (JSON envelope).

        Returns:
            str: The raw stdout, the combined stdout+stderr, or a JSON envelope with
                stdout, stderr, and returncode.
        """
        if output_format == "stdout":
            return completed.stdout
        if output_format == "stdout+stderr":
            return f"{completed.stdout}{completed.stderr}"
        return json.dumps({
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "returncode": completed.returncode,
        })

    @staticmethod
    def _format_timeout(exc: subprocess.TimeoutExpired, output_format: str, timeout: Any) -> str:
        """Formats a timeout outcome per ``output_format`` for the ``onError`` "return" path.

        Args:
            exc (subprocess.TimeoutExpired): The timeout exception carrying any partial output.
            output_format (str): "stdout", "stdout+stderr", or "full" (JSON envelope).
            timeout (Any): The timeout value, used in the error message.

        Returns:
            str: A plain message, or a JSON envelope with partial output and the error
                when ``output_format`` is "full".
        """
        message = f"curl timed out after {timeout} seconds"
        if output_format == "full":
            return json.dumps({
                "stdout": exc.stdout or "",
                "stderr": exc.stderr or "",
                "returncode": None,
                "error": message,
            })
        return message

    @staticmethod
    def _format_cap_exceeded(message: str, stdout: str, stderr: str, output_format: str) -> str:
        """Formats a cap-exceeded outcome per ``output_format`` for the "return" path.

        Args:
            message (str): The human-readable cap-exceeded message.
            stdout (str): The captured (truncated) stdout text.
            stderr (str): The captured stderr text.
            output_format (str): "stdout", "stdout+stderr", or "full" (JSON envelope).

        Returns:
            str: The message, or a JSON envelope with the captured output and the error
                when ``output_format`` is "full".
        """
        if output_format == "full":
            return json.dumps({
                "stdout": stdout,
                "stderr": stderr,
                "returncode": None,
                "error": message,
            })
        return message

    @staticmethod
    def _maybe_stream(payload: str, context: ExecutionContext) -> Any:
        """Wraps the payload in a streaming generator when the node is streaming.

        Args:
            payload (str): The fully formed result string.
            context (ExecutionContext): The central object containing all runtime data for the node.

        Returns:
            Any: A streaming generator over ``payload`` when ``context.stream`` is True,
                otherwise ``payload`` unchanged.
        """
        if context.stream:
            return stream_static_content(payload)
        return payload
