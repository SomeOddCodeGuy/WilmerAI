"""Publisher-cautious retrieval for the WebPageFetch workflow node."""

import datetime
import hashlib
import ipaddress
import math
import re
import threading
import time
import zlib
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, fields
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Dict, FrozenSet, Optional, Tuple
from urllib import robotparser
from urllib.parse import quote, urlsplit, urlunsplit

import requests
import urllib3

from Middleware.utilities.network_security_utils import check_url_allowed
from Middleware.exceptions.early_termination_exception import EarlyTerminationException
from Middleware.services.cancellation_service import cancellation_service
from Middleware.utilities.redirect_policy import disable_session_redirects, resolve_redirect_url
from Middleware.utilities.sensitive_logging_utils import get_sensitive_logger

logger = get_sensitive_logger(__name__)

WEB_PAGE_ROBOTS_TOKEN = requests.utils.default_user_agent().split("/", 1)[0]

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_ROBOTS_ABSENT_STATUSES = frozenset({404, 410})
_ROBOTS_DENIED_STATUSES = frozenset({401, 403})
_RETRY_AFTER_STATUSES = frozenset({429, 503})
_DEFAULT_PORTS = {"http": 80, "https": 443}
_READ_CHUNK_SIZE = 65536
_REQUEST_ID = ContextVar("web_page_fetch_request_id", default=None)
_CACHE_CAPACITY = 1024
_ORIGIN_LOCK_COUNT = 64
_DOMAIN_LANE_COUNT = 1024
_UNRESERVED_URI_CHARACTERS = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
)


def _normalize_robots_path(path: str, *, pattern: bool = False) -> str:
    """Normalize robots comparison text without decoding reserved URI escapes.

    Args:
        path (str): Path and optional query, excluding origin and fragment.
        pattern (bool): Whether literal stars and dollar signs are rule syntax.

    Returns:
        str: Comparison text with uppercase escapes and decoded unreserved bytes.
    """
    safe = "/" + ("*$" if pattern else "")

    def normalize_piece(value):
        """Normalize one URI component while preserving reserved escapes.

        Args:
            value (str): Path or query fragment to normalize.

        Returns:
            str: Escaped comparison text.
        """
        def replace(match):
            """Normalize a percent escape or literal URI segment.

            Args:
                match (re.Match): Percent escape, literal segment, or unmatched percent sign.

            Returns:
                str: Normalized escape or quoted literal text.
            """
            token = match.group()
            if len(token) == 3 and token.startswith("%"):
                character = chr(int(token[1:], 16))
                return character if character in _UNRESERVED_URI_CHARACTERS else token.upper()
            return quote(token, safe=safe)

        return re.sub(r"%[0-9a-fA-F]{2}|[^%]+|%", replace, value)

    path, separator, query = path.partition("?")
    normalized = normalize_piece(path)
    if separator:
        normalized += "?" + re.sub(r"[^=&]+", lambda match: normalize_piece(match.group()), query)
    return normalized


class _RobotsParser(robotparser.RobotFileParser):
    """Retain group/directive parsing while preserving URI comparison escapes."""

    def can_fetch(self, useragent: str, url: str) -> bool:
        """Evaluate the selected group's rules against the normalized URI.

        Args:
            useragent (str): Product token whose rules apply.
            url (str): URL to check, already canonical for transport in the service.

        Returns:
            bool: Whether the applicable policy permits this URL.
        """
        if self.disallow_all:
            return False
        if self.allow_all:
            return True
        if not self.last_checked:
            return False
        parts = urlsplit(url)
        path = parts.path
        if "?" in url.split("#", 1)[0]:
            path += "?" + parts.query
        path = _normalize_robots_path(path) or "/"
        if path == "/robots.txt":
            return True
        entry = self._find_entry(useragent)
        return entry is None or entry.allowance(path)


class WebPageFetchError(Exception):
    """Describes a policy, transport, or HTTP failure during page retrieval."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        headers: Optional[Dict[str, str]] = None,
        url: Optional[str] = None,
    ) -> None:
        """Attach available HTTP metadata to a page-fetch failure.

        Args:
            message (str): Failure description.
            status_code (Optional[int]): HTTP status, when a response was received.
            headers (Optional[Dict[str, str]]): Response headers suitable for caller output.
            url (Optional[str]): Destination associated with the failure.
        """
        super().__init__(message)
        self.status_code = status_code
        self.headers = headers
        self.url = url


@dataclass(frozen=True)
class WebPageFetchPolicy:
    """Validated policy and transport settings for one page-fetch operation."""

    timeout: float = 30
    proxies: Optional[Dict[str, str]] = None
    verify: Any = True
    respect_robots: bool = True
    fail_closed_on_robots_error: bool = True
    block_private_addresses: bool = True
    allowed_hosts: FrozenSet[str] = frozenset()
    restrict_ports: bool = True
    allowed_ports: FrozenSet[int] = frozenset()
    enable_domain_pacing: bool = True
    minimum_delay_seconds: float = 5
    max_pacing_wait_seconds: float = 300
    honor_crawl_delay: bool = True
    honor_request_rate: bool = True
    honor_retry_after: bool = True
    honor_forbidden_cooldown: bool = True
    robots_cache_seconds: float = 86400
    robots_failure_cache_seconds: float = 300
    forbidden_cooldown_seconds: float = 604800
    retry_after_fallback_seconds: float = 60
    allow_redirects: bool = True
    max_redirects: int = 5
    enforce_content_type: bool = True
    allowed_content_types: FrozenSet[str] = frozenset({
        "text/html",
        "application/xhtml+xml",
        "text/plain",
    })
    max_header_bytes: int = 128 * 1024
    max_transfer_bytes: int = 5 * 1024 * 1024
    max_decoded_bytes: int = 25 * 1024 * 1024


@dataclass(frozen=True)
class WebPageFetchResult:
    """The bounded final response returned by the page-fetch service."""

    status_code: int
    headers: Dict[str, str]
    body: bytes
    url: str

    @property
    def text(self) -> str:
        """Decode the body using Requests response-encoding rules.

        Returns:
            str: Body decoded from response headers or Requests encoding detection.
        """
        response = requests.Response()
        response.headers = requests.structures.CaseInsensitiveDict(self.headers)
        response._content = self.body
        response._content_consumed = True
        response.encoding = requests.utils.get_encoding_from_headers(response.headers)
        return response.text


@dataclass(frozen=True)
class _NormalizedUrl:
    url: str
    origin: str
    scheme: str
    hostname: str
    port: int


@dataclass
class _RobotsRecord:
    kind: str
    cached_at: float
    parser: Optional[robotparser.RobotFileParser] = None
    reason: Optional[str] = None


class _RobotsRule:
    """Keep parser matching while ranking rules independently of matched URL length."""

    def __init__(self, rule: robotparser.RuleLine, raw_path: Optional[str] = None) -> None:
        """Capture a parsed rule and its normalized path specificity.

        Args:
            rule (robotparser.RuleLine): Rule produced by the pinned parser.
            raw_path (Optional[str]): Original directive path before parser normalization.
        """
        if raw_path is not None:
            allowance = rule.allowance if raw_path else True
            rule = robotparser.RuleLine("/", allowance)
            path = re.sub(r"[*]{2,}", "*", raw_path)
            path = re.sub(r"[$][$*]+", "$", path)
            path = _normalize_robots_path(path, pattern=True)
            rule.fullmatch = path.endswith("$")
            rule.path = path.rstrip("$")
            if "$" in rule.path:
                raise ValueError("Robots end anchor must terminate the rule path")
            if "*" in rule.path:
                matcher = re.compile(robotparser.translate_pattern(rule.path), re.DOTALL)
                rule.matcher = matcher.fullmatch if rule.fullmatch else matcher.match
        self._rule = rule
        self.allowance = rule.allowance
        pattern = rule.path + ("$" if rule.fullmatch else "")
        # An unanchored trailing wildcard adds no restriction to a prefix rule.
        self._specificity = len(pattern.rstrip("*").encode("utf-8"))

    def applies_to(self, filename: str) -> int:
        """Return a stable positive rank for a match, or zero for no match.

        Args:
            filename (str): URL path normalized by the local robots parser.

        Returns:
            int: Rule-path byte length plus one when the parser matches it.
        """
        return self._specificity + 1 if self._rule.applies_to(filename) else 0

    def __str__(self) -> str:
        """Render the underlying robots directive.

        Returns:
            str: Parser representation of the rule.
        """
        return str(self._rule)


@dataclass
class _DomainLane:
    lock: threading.Lock = field(default_factory=threading.Lock)
    state_lock: threading.Lock = field(default_factory=threading.Lock)
    last_request_at: Optional[float] = None
    next_allowed_at: float = 0.0
    cooldown_until: float = 0.0
    cooldown_reason: Optional[str] = None


@dataclass
class _OpenResponse:
    session: requests.Session
    response: requests.Response
    deadline: float

    def close(self) -> None:
        """Close the response and release its session even if response cleanup fails."""
        try:
            self.response.close()
        finally:
            self.session.close()


class WebPageFetchService:
    """Coordinates robots policy, pacing, redirects, and bounded page reads.

    Instances hold only in-memory state. The default application instance is shared
    by every WorkflowManager so concurrent workflows use the same robots cache and
    domain lanes without writing a browsing history to disk.
    """

    def __init__(
        self,
        *,
        session_factory: Optional[Callable[[], requests.Session]] = None,
        monotonic: Optional[Callable[[], float]] = None,
        sleep: Optional[Callable[[float], None]] = None,
        wall_time: Optional[Callable[[], float]] = None,
        url_checker: Optional[Callable[..., Optional[str]]] = None,
    ) -> None:
        """Initialize shared in-memory fetch state and injectable transport dependencies.

        Args:
            session_factory (Optional[Callable[[], requests.Session]]): Factory for a fresh
                session per hop; defaults to requests.Session.
            monotonic (Optional[Callable[[], float]]): Clock for deadlines and cache ages;
                defaults to time.monotonic.
            sleep (Optional[Callable[[float], None]]): Wait function accepting seconds; defaults
                to time.sleep.
            wall_time (Optional[Callable[[], float]]): Unix timestamp clock for HTTP dates;
                defaults to time.time.
            url_checker (Optional[Callable]): Destination policy check returning a rejection
                reason or None; defaults to check_url_allowed.
        """
        self._session_factory = session_factory or requests.Session
        self._monotonic = monotonic or time.monotonic
        self._sleep = sleep or time.sleep
        self._wall_time = wall_time or time.time
        self._url_checker = url_checker or check_url_allowed
        self._state_lock = threading.RLock()
        self._robots_cache = OrderedDict()
        self._origin_locks: Dict[str, threading.Lock] = {}
        self._domain_lanes: Dict[str, _DomainLane] = {}

    def fetch(self, url: str, policy: WebPageFetchPolicy, *, request_id=None) -> WebPageFetchResult:
        """Fetches one page while applying the complete configured policy.

        Args:
            url (str): Absolute HTTP or HTTPS page URL.
            policy (WebPageFetchPolicy): Destination, publisher, and transport controls.
            request_id (Optional[str]): Request identifier for cancellation checks,
                or None when no request cancellation context is available.

        Returns:
            WebPageFetchResult: Final URL, status, filtered headers, and bounded body.

        Raises:
            WebPageFetchError: If a policy, transport, or response check fails.
            EarlyTerminationException: If the associated request is cancelled.
        """
        token = _REQUEST_ID.set(request_id)
        try:
            return self._fetch(url, policy)
        finally:
            _REQUEST_ID.reset(token)

    def _fetch(self, url: str, policy: WebPageFetchPolicy) -> WebPageFetchResult:
        """Follow a page request through policy checks and bounded redirect hops.

        Args:
            url (str): Initial page URL.
            policy (WebPageFetchPolicy): Destination, publisher, and response limits.

        Returns:
            WebPageFetchResult: Final successful response with a decoded body.

        Raises:
            WebPageFetchError: If retrieval or a policy check fails.
            EarlyTerminationException: If the request is cancelled.
        """
        current_url = url
        for redirect_count in range(policy.max_redirects + 1):
            self._check_cancelled()
            target = self._validate_url(current_url, policy)
            robots_record = self._robots_record_for(target, policy)
            robots_delay = self._enforce_robots(target, robots_record, policy)
            effective_delay = self._effective_delay(robots_delay, policy)
            self._pace(target, effective_delay, policy)

            opened = self._open_response(target.url, policy, for_robots=False)
            try:
                self._record_response_cooldown(target, opened.response, policy)
                self._check_header_limit(opened.response, policy.max_header_bytes)
                status_code = opened.response.status_code
                if status_code in _REDIRECT_STATUSES:
                    location = opened.response.headers.get("location")
                    if not policy.allow_redirects:
                        raise self._http_error(
                            "WebPageFetch received a redirect while redirects are disabled.",
                            target,
                            opened.response,
                        )
                    if not location:
                        raise self._http_error(
                            "WebPageFetch received a redirect without a Location header.",
                            target,
                            opened.response,
                        )
                    if redirect_count >= policy.max_redirects:
                        raise self._http_error(
                            f"WebPageFetch exceeded the maximum of {policy.max_redirects} redirects.",
                            target,
                            opened.response,
                        )
                    current_url = self._resolve_redirect_url(target.url, location)
                    continue

                if not 200 <= status_code < 300:
                    raise self._http_error(
                        f"WebPageFetch received HTTP status {status_code}.",
                        target,
                        opened.response,
                    )
                self._check_content_type(opened.response, policy)
                body = self._read_bounded_body(opened, policy)
                return WebPageFetchResult(
                    status_code=status_code,
                    headers=self._public_response_headers(opened.response.headers),
                    body=body,
                    url=target.url,
                )
            finally:
                opened.close()

        raise WebPageFetchError("WebPageFetch redirect processing ended unexpectedly.")

    def _validate_url(
        self,
        url: str,
        policy: WebPageFetchPolicy,
    ) -> _NormalizedUrl:
        """Normalizes and validates one page or robots destination.

        Args:
            url (str): Absolute HTTP or HTTPS destination to validate.
            policy (WebPageFetchPolicy): Port, host, and address restrictions to apply.

        Returns:
            _NormalizedUrl: Canonical URL and its origin, scheme, hostname, and port.

        Raises:
            WebPageFetchError: If the URL is malformed or violates the policy.
        """
        if not isinstance(url, str) or not url:
            raise WebPageFetchError("WebPageFetch requires a non-empty URL string.")
        if "\\" in url or any(character.isspace() or ord(character) < 32 for character in url):
            raise WebPageFetchError("WebPageFetch URL contains invalid whitespace or delimiters.")

        try:
            parts = urlsplit(url)
        except (ValueError, UnicodeError) as exc:
            raise WebPageFetchError("WebPageFetch URL could not be parsed.") from exc
        scheme = parts.scheme.lower()
        if scheme not in _DEFAULT_PORTS:
            raise WebPageFetchError("WebPageFetch permits only absolute http:// or https:// URLs.")
        if not parts.netloc or not parts.hostname:
            raise WebPageFetchError("WebPageFetch URL must include a hostname.")
        if parts.username is not None or parts.password is not None:
            raise WebPageFetchError("WebPageFetch URL must not contain embedded credentials.")
        try:
            explicit_port = parts.port
        except ValueError as exc:
            raise WebPageFetchError("WebPageFetch URL contains an invalid port.") from exc

        hostname = parts.hostname.rstrip(".").lower()
        if not hostname or "%" in hostname:
            raise WebPageFetchError("WebPageFetch URL contains an invalid hostname.")
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            try:
                hostname = hostname.encode("idna").decode("ascii")
            except UnicodeError as exc:
                raise WebPageFetchError("WebPageFetch URL contains an invalid hostname.") from exc

        port = explicit_port or _DEFAULT_PORTS[scheme]
        if policy.restrict_ports and (
            port != _DEFAULT_PORTS[scheme] and port not in policy.allowed_ports
        ):
            raise WebPageFetchError(
                f"WebPageFetch does not permit port {port}; add it to allowedPorts "
                "or disable restrictPorts."
            )

        display_host = f"[{hostname}]" if ":" in hostname else hostname
        include_port = port != _DEFAULT_PORTS[scheme]
        netloc = f"{display_host}:{port}" if include_port else display_host
        path = parts.path or "/"
        normalized_url = self._canonicalize_transport_url(
            urlunsplit((scheme, netloc, path, parts.query, "")))
        canonical_parts = urlsplit(normalized_url)
        hostname = canonical_parts.hostname
        port = canonical_parts.port or _DEFAULT_PORTS[canonical_parts.scheme]
        origin = f"{canonical_parts.scheme}://{canonical_parts.netloc}"

        reason = self._url_checker(
            normalized_url,
            policy.block_private_addresses,
            policy.allowed_hosts,
        )
        if reason:
            raise WebPageFetchError(f"WebPageFetch blocked a destination: {reason}.")
        return _NormalizedUrl(normalized_url, origin, scheme, hostname, port)

    @staticmethod
    def _canonicalize_transport_url(url: str) -> str:
        """Prepare a stable URL before authorizing a page or robots destination.

        Args:
            url (str): Structurally validated HTTP URL with normalized authority.

        Returns:
            str: URL that Requests preparation leaves unchanged.

        Raises:
            WebPageFetchError: If preparation fails or cannot reach a stable URL.
        """
        try:
            for _ in range(3):
                prepared = requests.PreparedRequest()
                prepared.prepare_url(url, None)
                if prepared.url == url:
                    return url
                # Decoding unreserved escapes can reveal dot segments for the next pass.
                url = prepared.url
        except (requests.exceptions.RequestException, ValueError, UnicodeError) as exc:
            raise WebPageFetchError("WebPageFetch URL could not be prepared for transport.") from exc
        raise WebPageFetchError("WebPageFetch URL did not stabilize during preparation.")

    @staticmethod
    def _resolve_redirect_url(base_url: str, location: str) -> str:
        """Resolves remote Location metadata within the fetch error contract.

        Args:
            base_url (str): Validated URL of the redirecting response.
            location (str): Remote Location header value.

        Returns:
            str: Resolved URL, subject to normal destination validation.

        Raises:
            WebPageFetchError: If the remote URL cannot be parsed.
        """
        try:
            return resolve_redirect_url(base_url, location)
        except (ValueError, UnicodeError) as exc:
            raise WebPageFetchError("WebPageFetch redirect URL could not be parsed.") from exc

    def _robots_record_for(
        self,
        target: _NormalizedUrl,
        policy: WebPageFetchPolicy,
    ) -> Optional[_RobotsRecord]:
        """Get robots policy while serializing cache misses for the same policy key.

        Args:
            target (_NormalizedUrl): Validated page destination.
            policy (WebPageFetchPolicy): Robots and retrieval controls.

        Returns:
            Optional[_RobotsRecord]: Cached or fetched policy, or None when robots checks are
                disabled.
        """
        if not policy.respect_robots:
            return None

        cached = self._cached_robots(target.origin, policy)
        if cached is not None:
            return cached
        cache_key = self._robots_key(target.origin, policy)
        origin_lock = self._origin_lock(cache_key)
        with self._bounded_lock(origin_lock, policy.max_pacing_wait_seconds):
            cached = self._cached_robots(target.origin, policy)
            if cached is not None:
                return cached
            record = self._fetch_robots_record(target, policy)
            with self._state_lock:
                self._robots_cache[cache_key] = record
                while len(self._robots_cache) > _CACHE_CAPACITY:
                    self._robots_cache.popitem(last=False)
            return record

    @staticmethod
    def _robots_key(origin, policy):
        """Do not reuse permission established under a different fetch policy.

        Args:
            origin (str): Canonical origin whose robots policy is cached.
            policy (WebPageFetchPolicy): Complete policy under which permission is checked.

        Returns:
            tuple: Origin and hashable policy values used as the robots cache key.
        """
        values = tuple(
            tuple(sorted(value.items())) if isinstance(value, dict) else value
            for value in (getattr(policy, item.name) for item in fields(policy))
        )
        return origin, values

    def _cached_robots(
        self,
        origin: str,
        policy: WebPageFetchPolicy,
    ) -> Optional[_RobotsRecord]:
        """Look up robots state using the caller policy and its cache lifetime.

        Args:
            origin (str): Canonical origin.
            policy (WebPageFetchPolicy): Cache identity and success/failure lifetimes.

        Returns:
            Optional[_RobotsRecord]: Unexpired record, or None for an absent or expired entry.
        """
        with self._state_lock:
            key = self._robots_key(origin, policy)
            record = self._robots_cache.get(key)
            if record is None:
                return None
            ttl = (
                policy.robots_cache_seconds
                if record.kind in ("rules", "absent")
                else policy.robots_failure_cache_seconds
            )
            if ttl > 0 and self._monotonic() - record.cached_at < ttl:
                self._robots_cache.move_to_end(key)
                return record
            self._robots_cache.pop(key, None)
            return None

    def _fetch_robots_record(
        self,
        target: _NormalizedUrl,
        policy: WebPageFetchPolicy,
    ) -> _RobotsRecord:
        """Retrieve robots directives with destination checks on each redirect.

        Args:
            target (_NormalizedUrl): Page origin whose robots.txt is requested.
            policy (WebPageFetchPolicy): Transport, pacing, redirect, and size controls.

        Returns:
            _RobotsRecord: Parsed rules, absence, denial, or retrieval failure with a cache
                timestamp.

        Raises:
            WebPageFetchError: If domain pacing rejects the request.
            EarlyTerminationException: If the request is cancelled.
        """
        current_url = f"{target.origin}/robots.txt"
        for redirect_count in range(policy.max_redirects + 1):
            try:
                robots_target = self._validate_url(current_url, policy)
            except WebPageFetchError as exc:
                return _RobotsRecord(
                    kind="failure",
                    cached_at=self._monotonic(),
                    reason=str(exc),
                )
            delay = policy.minimum_delay_seconds if policy.enable_domain_pacing else 0
            self._pace(robots_target, delay, policy)
            try:
                opened = self._open_response(robots_target.url, policy, for_robots=True)
            except WebPageFetchError as exc:
                return _RobotsRecord(
                    kind="failure",
                    cached_at=self._monotonic(),
                    reason=str(exc),
                )
            try:
                self._record_response_cooldown(robots_target, opened.response, policy)
                self._check_header_limit(opened.response, policy.max_header_bytes)
                status_code = opened.response.status_code
                if status_code in _REDIRECT_STATUSES:
                    location = opened.response.headers.get("location")
                    if (not policy.allow_redirects or not location
                            or redirect_count >= policy.max_redirects):
                        return _RobotsRecord(
                            kind="failure",
                            cached_at=self._monotonic(),
                            reason="robots.txt redirect could not be followed safely",
                        )
                    current_url = self._resolve_redirect_url(robots_target.url, location)
                    continue
                if status_code in _ROBOTS_ABSENT_STATUSES:
                    return _RobotsRecord(kind="absent", cached_at=self._monotonic())
                if status_code in _ROBOTS_DENIED_STATUSES:
                    return _RobotsRecord(
                        kind="denied",
                        cached_at=self._monotonic(),
                        reason=f"robots.txt returned HTTP {status_code}",
                    )
                if not 200 <= status_code < 300:
                    return _RobotsRecord(
                        kind="failure",
                        cached_at=self._monotonic(),
                        reason=f"robots.txt returned HTTP {status_code}",
                    )
                try:
                    body = self._read_bounded_body(opened, policy)
                    parser = self._parse_robots(body)
                except WebPageFetchError as exc:
                    return _RobotsRecord(
                        kind="failure",
                        cached_at=self._monotonic(),
                        reason=str(exc),
                    )
                return _RobotsRecord(
                    kind="rules",
                    cached_at=self._monotonic(),
                    parser=parser,
                )
            except WebPageFetchError as exc:
                return _RobotsRecord(
                    kind="failure",
                    cached_at=self._monotonic(),
                    reason=str(exc),
                )
            finally:
                opened.close()

        return _RobotsRecord(
            kind="failure",
            cached_at=self._monotonic(),
            reason="robots.txt redirect limit exceeded",
        )

    @staticmethod
    def _parse_robots(body: bytes) -> robotparser.RobotFileParser:
        """Parse UTF-8 robots directives while preserving URI escape semantics.

        Args:
            body (bytes): Bounded, decompressed robots.txt content.

        Returns:
            robotparser.RobotFileParser: Parser with normalized rule matching and specificity.

        Raises:
            WebPageFetchError: If encoding or recognized directives are invalid.
        """
        try:
            text = body.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as exc:
            raise WebPageFetchError("robots.txt is not valid UTF-8.") from exc

        saw_user_agent = False
        parser_lines = []
        rule_paths = {}
        for raw_line in text.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            if ":" not in line:
                raise WebPageFetchError("robots.txt contains a malformed directive.")
            field_name, value = line.split(":", 1)
            field_name = field_name.strip().lower()
            value = value.strip()
            if not field_name:
                raise WebPageFetchError("robots.txt contains a malformed directive.")
            if field_name == "user-agent":
                if not value:
                    raise WebPageFetchError("robots.txt contains an empty User-agent directive.")
                saw_user_agent = True
            elif field_name in ("allow", "disallow", "crawl-delay", "request-rate"):
                if not saw_user_agent:
                    raise WebPageFetchError(
                        f"robots.txt contains {field_name} before a User-agent group."
                    )
                if field_name == "crawl-delay" and not (
                    value.isascii() and value.isdigit() and math.isfinite(float(value))
                ):
                    raise WebPageFetchError(
                        "robots.txt contains an invalid Crawl-delay directive."
                    )
                if field_name == "request-rate":
                    parts = value.split("/", 1)
                    if (
                        len(parts) != 2
                        or not all(part.strip().isascii() and part.strip().isdigit()
                                   and math.isfinite(float(part)) for part in parts)
                        or any(not part.strip().lstrip("0") for part in parts)
                    ):
                        raise WebPageFetchError(
                            "robots.txt contains an invalid Request-rate directive."
                        )
            if field_name in ("allow", "disallow"):
                # Inert paths let the pinned parser form groups without losing
                # encoded separators before the local rule adapter sees them.
                placeholder = f"/rule-{len(rule_paths)}"
                rule_paths[placeholder] = value
                line = f"{field_name}: {placeholder}"
            parser_lines.append(line)

        parser = _RobotsParser()
        try:
            parser.parse(parser_lines)
            # Merged groups can own distinct entries; adapt both views without
            # changing global parser classes or the matching/Allow-tie behavior.
            entries = {id(entry): entry for entry in (*parser.entries, *parser.groups.values())}
            for entry in entries.values():
                entry.rulelines = [_RobotsRule(rule, rule_paths[rule.path]) for rule in entry.rulelines]
        except (ValueError, UnicodeError) as exc:
            raise WebPageFetchError("robots.txt contains an invalid directive value.") from exc
        return parser

    def _enforce_robots(
        self,
        target: _NormalizedUrl,
        record: Optional[_RobotsRecord],
        policy: WebPageFetchPolicy,
    ) -> float:
        """Check page permission and derive the enabled robots timing constraints.

        Args:
            target (_NormalizedUrl): Page destination to authorize.
            record (Optional[_RobotsRecord]): Robots state, or None when checks are disabled.
            policy (WebPageFetchPolicy): Failure handling and timing-directive controls.

        Returns:
            float: Required delay in seconds, or zero when no timing rule applies.

        Raises:
            WebPageFetchError: If access is denied or permission cannot be established under a
                fail-closed policy.
        """
        if record is None or record.kind == "absent":
            return 0
        if record.kind == "denied":
            raise WebPageFetchError(f"WebPageFetch denied by robots policy: {record.reason}.")
        if record.kind == "failure":
            if policy.fail_closed_on_robots_error:
                raise WebPageFetchError(
                    f"WebPageFetch could not establish robots permission: {record.reason}."
                )
            logger.warning(
                "WebPageFetch proceeding because failClosedOnRobotsError is false: %s",
                record.reason,
            )
            return 0

        parser = record.parser
        if parser is None or not parser.can_fetch(WEB_PAGE_ROBOTS_TOKEN, target.url):
            raise WebPageFetchError("WebPageFetch target is disallowed by robots.txt.")

        delays = [0.0]
        if policy.honor_crawl_delay:
            crawl_delay = parser.crawl_delay(WEB_PAGE_ROBOTS_TOKEN)
            if crawl_delay is not None:
                delays.append(float(crawl_delay))
        if policy.honor_request_rate:
            request_rate = parser.request_rate(WEB_PAGE_ROBOTS_TOKEN)
            if request_rate is not None and request_rate.requests > 0:
                delays.append(float(request_rate.seconds) / request_rate.requests)
        return max(delays)

    @staticmethod
    def _effective_delay(robots_delay: float, policy: WebPageFetchPolicy) -> float:
        """Combine publisher timing with the configured minimum request interval.

        Args:
            robots_delay (float): Delay in seconds derived from robots directives.
            policy (WebPageFetchPolicy): Domain pacing switch and minimum interval.

        Returns:
            float: Required interval in seconds, or zero when pacing is disabled.
        """
        if not policy.enable_domain_pacing:
            return 0
        return max(policy.minimum_delay_seconds, robots_delay)

    def _pace(
        self,
        target: _NormalizedUrl,
        delay_seconds: float,
        policy: WebPageFetchPolicy,
    ) -> None:
        """Reserve the next domain request slot within the caller wait budget.

        Args:
            target (_NormalizedUrl): Destination whose domain lane is shared.
            delay_seconds (float): Minimum interval between requests in seconds.
            policy (WebPageFetchPolicy): Maximum permitted pacing wait.

        Raises:
            WebPageFetchError: If the domain is cooling down or the wait budget is exceeded.
            EarlyTerminationException: If the request is cancelled while waiting.
        """
        lane = self._domain_lane(target.hostname)
        wait_started = self._monotonic()
        with self._bounded_lock(lane.lock, policy.max_pacing_wait_seconds):
            while True:
                self._check_cancelled()
                with lane.state_lock:
                    now = self._monotonic()
                    if lane.cooldown_until > now:
                        remaining = lane.cooldown_until - now
                        reason = lane.cooldown_reason or "remote-server cooldown"
                        raise WebPageFetchError(
                            f"WebPageFetch domain is cooling down for another {remaining:.1f} "
                            f"seconds after {reason}."
                        )
                    required_at = lane.next_allowed_at
                    if lane.last_request_at is not None:
                        required_at = max(required_at, lane.last_request_at + delay_seconds)
                    wait_seconds = max(0.0, required_at - now)
                    if wait_seconds + now - wait_started > policy.max_pacing_wait_seconds:
                        raise WebPageFetchError(
                            f"WebPageFetch required pacing wait of {wait_seconds:.1f} seconds "
                            f"exceeds maxPacingWaitSeconds ({policy.max_pacing_wait_seconds})."
                        )
                    if wait_seconds <= 0:
                        lane.last_request_at = now
                        lane.next_allowed_at = now + max(0.0, delay_seconds)
                        return
                # Cooldown writers never wait behind this sleep. Recheck on wake.
                self._cancellable_sleep(wait_seconds)

    def _record_response_cooldown(
        self,
        target: _NormalizedUrl,
        response: requests.Response,
        policy: WebPageFetchPolicy,
    ) -> None:
        """Record enabled publisher cooldowns from an HTTP response.

        Args:
            target (_NormalizedUrl): Responding destination.
            response (requests.Response): Status and Retry-After metadata to inspect.
            policy (WebPageFetchPolicy): Cooldown switches, durations, and fallback delay.
        """
        if response.status_code == 403 and policy.honor_forbidden_cooldown:
            self._set_cooldown(
                target.hostname,
                policy.forbidden_cooldown_seconds,
                "HTTP 403",
                wait_timeout=policy.max_pacing_wait_seconds,
            )
            return
        if response.status_code in _RETRY_AFTER_STATUSES and policy.honor_retry_after:
            retry_after_value = response.headers.get("retry-after")
            # Restriction state is recorded even when the header collection is rejected.
            if retry_after_value is not None and len(retry_after_value) > 128:
                retry_after_value = None
            retry_after = self._retry_after_seconds(
                retry_after_value,
                policy.retry_after_fallback_seconds,
            )
            self._set_cooldown(
                target.hostname,
                retry_after,
                f"HTTP {response.status_code}",
                wait_timeout=policy.max_pacing_wait_seconds,
            )

    def _set_cooldown(self, hostname: str, seconds: float, reason: str, *, wait_timeout=300) -> None:
        """Extend a domain cooldown without shortening an existing restriction.

        Args:
            hostname (str): Host whose domain lane receives the restriction.
            seconds (float): Cooldown duration from the current monotonic time.
            reason (str): Diagnostic label for the publisher restriction.
            wait_timeout (float): Accepted caller wait budget; unused because recording a
                received restriction is independent of that budget.
        """
        lane = self._domain_lane(hostname)
        # Received publisher restrictions survive the caller's cancellation/budget.
        # This lock protects only short in-memory updates, never waits or I/O.
        with lane.state_lock:
            until = self._monotonic() + max(0.0, seconds)
            if until > lane.cooldown_until:
                lane.cooldown_until = until
                lane.cooldown_reason = reason

    def _retry_after_seconds(self, value: Optional[str], fallback: float) -> float:
        """Interpret Retry-After as a delay or an HTTP date.

        Args:
            value (Optional[str]): Response header, when present.
            fallback (float): Delay used for absent or unparseable values.

        Returns:
            float: Nonnegative delay in seconds, or the supplied fallback.
        """
        if value:
            stripped = value.strip()
            try:
                if stripped.isascii() and stripped.isdigit():
                    return float(stripped)
                parsed = parsedate_to_datetime(stripped)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=datetime.timezone.utc)
                return max(0.0, parsed.timestamp() - self._wall_time())
            except (TypeError, ValueError, OverflowError):
                pass
        return fallback

    def _open_response(
        self,
        url: str,
        policy: WebPageFetchPolicy,
        *,
        for_robots: bool,
    ) -> _OpenResponse:
        """Open one streamed GET with a private session and no implicit redirects.

        Args:
            url (str): Validated destination URL.
            policy (WebPageFetchPolicy): Timeout, proxy, and TLS settings.
            for_robots (bool): Whether to request plain text for robots.txt.

        Returns:
            _OpenResponse: Caller-owned response, session, and monotonic read deadline.

        Raises:
            WebPageFetchError: If the HTTP request fails.
            EarlyTerminationException: If the request is cancelled before opening.
        """
        headers = {
            "Accept": "text/plain" if for_robots else (
                "text/html, application/xhtml+xml, text/plain;q=0.9"
            ),
            "Accept-Encoding": "gzip, deflate",
            "Connection": "close",
        }
        self._check_cancelled()
        session = self._session_factory()
        disable_session_redirects(session)
        session.trust_env = False
        session.headers.clear()
        session.headers.update(requests.utils.default_headers())
        session.cookies.clear()
        started_at = self._monotonic()
        timeout = urllib3.util.Timeout(
            total=policy.timeout,
            connect=policy.timeout,
            read=policy.timeout,
        )
        try:
            response = session.request(
                method="GET",
                url=url,
                headers=headers,
                timeout=timeout,
                proxies=policy.proxies,
                verify=policy.verify,
                allow_redirects=False,
                stream=True,
            )
        except requests.exceptions.RequestException as exc:
            session.close()
            raise WebPageFetchError("WebPageFetch request failed before receiving a response.") from exc
        except BaseException:
            session.close()
            raise
        return _OpenResponse(session, response, started_at + policy.timeout)

    def _read_bounded_body(
        self,
        opened: _OpenResponse,
        policy: WebPageFetchPolicy,
    ) -> bytes:
        """Read and decompress a response under transfer, decoded-size, and time limits.

        Args:
            opened (_OpenResponse): Open response and deadline; the caller retains cleanup
                ownership.
            policy (WebPageFetchPolicy): Transfer and decoded-body byte limits.

        Returns:
            bytes: Complete decoded response body.

        Raises:
            WebPageFetchError: If limits, framing, content encoding, or reads fail.
            EarlyTerminationException: If the request is cancelled.
        """
        response = opened.response
        content_length = response.headers.get("content-length")
        if content_length and content_length.isascii() and content_length.isdigit():
            try:
                announced_length = int(content_length)
            except ValueError as exc:
                raise WebPageFetchError("WebPageFetch Content-Length could not be parsed.") from exc
            if announced_length > policy.max_transfer_bytes:
                raise WebPageFetchError(
                    "WebPageFetch response exceeds maxTransferBytes.",
                    status_code=response.status_code,
                )

        content_encoding = response.headers.get("content-encoding", "").strip().lower()
        if content_encoding in ("", "identity"):
            decoder = None
            deflate_prefix = None
        elif content_encoding == "gzip":
            decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
            deflate_prefix = None
        elif content_encoding == "deflate":
            decoder = None
            deflate_prefix = bytearray()
        else:
            raise WebPageFetchError(
                f"WebPageFetch does not support Content-Encoding {content_encoding!r}."
            )

        transferred = 0
        decoded = bytearray()
        try:
            while True:
                self._check_cancelled()
                if self._monotonic() > opened.deadline:
                    raise WebPageFetchError("WebPageFetch response exceeded its total timeout.")
                read = getattr(response.raw, "read1", response.raw.read)
                chunk = read(_READ_CHUNK_SIZE, decode_content=False)
                self._check_cancelled()
                if self._monotonic() > opened.deadline:
                    raise WebPageFetchError("WebPageFetch response exceeded its total timeout.")
                if not chunk:
                    break
                transferred += len(chunk)
                if transferred > policy.max_transfer_bytes:
                    raise WebPageFetchError("WebPageFetch response exceeds maxTransferBytes.")
                if decoder is None:
                    if deflate_prefix is not None:
                        deflate_prefix.extend(chunk)
                        if len(deflate_prefix) < 2:
                            continue
                        prefix = bytes(deflate_prefix)
                        deflate_prefix = None
                        decoder = zlib.decompressobj(
                            zlib.MAX_WBITS
                            if self._has_zlib_wrapper(prefix)
                            else -zlib.MAX_WBITS
                        )
                        self._decompress_into(
                            decoded,
                            decoder,
                            prefix,
                            policy.max_decoded_bytes,
                        )
                        continue
                    self._append_decoded(decoded, chunk, policy.max_decoded_bytes)
                    continue
                self._decompress_into(decoded, decoder, chunk, policy.max_decoded_bytes)

            if deflate_prefix is not None:
                raise WebPageFetchError(
                    "WebPageFetch response body is not a complete compressed stream."
                )
            if decoder is not None:
                remaining = policy.max_decoded_bytes - len(decoded)
                flushed = decoder.flush(max(1, remaining + 1))
                self._append_decoded(decoded, flushed, policy.max_decoded_bytes)
                if not decoder.eof:
                    raise WebPageFetchError("WebPageFetch response body is not a complete compressed stream.")
                if decoder.unused_data:
                    raise WebPageFetchError(
                        "WebPageFetch response body contains trailing compressed data."
                    )
        except WebPageFetchError:
            raise
        except (
            OSError,
            ValueError,
            zlib.error,
            requests.exceptions.RequestException,
            urllib3.exceptions.HTTPError,
        ) as exc:
            raise WebPageFetchError("WebPageFetch could not read or decompress the response.") from exc
        return bytes(decoded)

    @staticmethod
    def _has_zlib_wrapper(prefix: bytes) -> bool:
        """Returns whether a deflate payload starts with a valid zlib header.

        Args:
            prefix (bytes): Payload prefix containing at least two bytes.

        Returns:
            bool: Whether the compression-method and header-checksum checks pass.
        """
        first, second = prefix[0], prefix[1]
        return first & 0x0F == zlib.DEFLATED and (first << 8 | second) % 31 == 0

    @staticmethod
    def _decompress_into(
        decoded: bytearray,
        decoder: Any,
        chunk: bytes,
        max_decoded_bytes: int,
    ) -> None:
        """Append decompressed bytes without exceeding the decoded-body limit.

        Args:
            decoded (bytearray): Accumulated output, updated in place.
            decoder (Any): Active zlib decompression object.
            chunk (bytes): Next compressed input chunk.
            max_decoded_bytes (int): Maximum total decoded bytes.

        Raises:
            WebPageFetchError: If decoded output exceeds the limit.
            zlib.error: If compressed input is invalid.
        """
        pending = chunk
        while pending:
            remaining = max_decoded_bytes - len(decoded)
            piece = decoder.decompress(pending, max(1, remaining + 1))
            WebPageFetchService._append_decoded(decoded, piece, max_decoded_bytes)
            pending = decoder.unconsumed_tail
            if pending and len(decoded) >= max_decoded_bytes:
                raise WebPageFetchError("WebPageFetch response exceeds maxDecodedBytes.")

    @staticmethod
    def _append_decoded(decoded: bytearray, piece: bytes, max_decoded_bytes: int) -> None:
        """Append a decoded fragment within the total body budget.

        Args:
            decoded (bytearray): Accumulated body, updated in place.
            piece (bytes): Decoded fragment.
            max_decoded_bytes (int): Maximum total body size.

        Raises:
            WebPageFetchError: If the fragment would exceed the budget.
        """
        if len(decoded) + len(piece) > max_decoded_bytes:
            raise WebPageFetchError("WebPageFetch response exceeds maxDecodedBytes.")
        decoded.extend(piece)

    @staticmethod
    def _check_header_limit(response: requests.Response, max_header_bytes: int) -> None:
        """Reject response headers exceeding the configured byte estimate.

        Args:
            response (requests.Response): Status and headers to measure.
            max_header_bytes (int): Maximum estimated status-line and header bytes.

        Raises:
            WebPageFetchError: If the estimated header size exceeds the limit.
        """
        total = len(f"HTTP {response.status_code}\r\n".encode("ascii")) + 2
        for name, value in response.headers.items():
            total += len(str(name).encode("iso-8859-1", errors="replace"))
            total += len(str(value).encode("iso-8859-1", errors="replace")) + 4
        if total > max_header_bytes:
            raise WebPageFetchError(
                "WebPageFetch response headers exceed maxHeaderBytes.",
                status_code=response.status_code,
            )

    @staticmethod
    def _check_content_type(response: requests.Response, policy: WebPageFetchPolicy) -> None:
        """Enforce the configured response media-type allowlist.

        Args:
            response (requests.Response): Response supplying Content-Type.
            policy (WebPageFetchPolicy): Enforcement switch and allowed media types.

        Raises:
            WebPageFetchError: If enforcement is enabled and the media type is absent or
                disallowed.
        """
        if not policy.enforce_content_type:
            return
        value = response.headers.get("content-type", "")
        media_type = value.split(";", 1)[0].strip().lower()
        if media_type not in policy.allowed_content_types:
            label = media_type or "missing"
            raise WebPageFetchError(
                f"WebPageFetch rejected Content-Type {label!r}.",
                status_code=response.status_code,
            )

    @staticmethod
    def _public_response_headers(headers: Any) -> Dict[str, str]:
        """Exclude Set-Cookie from response metadata exposed to workflows.

        Args:
            headers (Any): Mapping of response header names to values.

        Returns:
            Dict[str, str]: String-valued headers with Set-Cookie omitted.
        """
        return {
            str(name): str(value)
            for name, value in headers.items()
            if str(name).lower() != "set-cookie"
        }

    @staticmethod
    def _http_error(
        message: str,
        target: _NormalizedUrl,
        response: requests.Response,
    ) -> WebPageFetchError:
        """Build a fetch error with filtered HTTP response metadata.

        Args:
            message (str): Failure description.
            target (_NormalizedUrl): Destination associated with the response.
            response (requests.Response): HTTP status and headers.

        Returns:
            WebPageFetchError: Failure carrying status, filtered headers, and URL.
        """
        return WebPageFetchError(
            message,
            status_code=response.status_code,
            headers=WebPageFetchService._public_response_headers(response.headers),
            url=target.url,
        )

    def _origin_lock(self, origin: str) -> threading.Lock:
        """Get the shared lock bucket for a robots cache key.

        Args:
            origin (Any): Origin or composite robots cache key to serialize.

        Returns:
            threading.Lock: Lock shared by keys assigned to the same fixed bucket.
        """
        origin = self._state_bucket(repr(origin), _ORIGIN_LOCK_COUNT)
        with self._state_lock:
            lock = self._origin_locks.get(origin)
            if lock is None:
                lock = threading.Lock()
                self._origin_locks[origin] = lock
            return lock

    def _domain_lane(self, hostname: str) -> _DomainLane:
        """Get persistent pacing state for the destination domain bucket.

        Args:
            hostname (str): Validated hostname or IP address.

        Returns:
            _DomainLane: Shared request timing and cooldown state.
        """
        key = self._state_bucket(self._registrable_domain_lane(hostname), _DOMAIN_LANE_COUNT)
        with self._state_lock:
            lane = self._domain_lanes.get(key)
            if lane is None:
                lane = _DomainLane()
                self._domain_lanes[key] = lane
            return lane

    @staticmethod
    def _state_bucket(key: str, count: int) -> int:
        # Fixed buckets bound state without forgetting active pacing or cooldowns.
        """Map a state key into a fixed bucket set.

        Args:
            key (str): Stable state identifier.
            count (int): Positive number of available buckets.

        Returns:
            int: Bucket index from zero through count minus one.
        """
        return int.from_bytes(hashlib.sha256(key.encode()).digest()[:8]) % count

    @staticmethod
    def _check_cancelled() -> None:
        """Check the request identifier held by the current fetch context.

        Raises:
            EarlyTerminationException: If cancellation is registered for this request.
        """
        request_id = _REQUEST_ID.get()
        if request_id and cancellation_service.is_cancelled(request_id):
            raise EarlyTerminationException("WebPageFetch request was cancelled.")

    def _cancellable_sleep(self, seconds: float) -> None:
        """Wait for an interval while polling active request cancellation.

        Args:
            seconds (float): Requested wait duration.

        Raises:
            EarlyTerminationException: If the request is cancelled.
        """
        deadline = self._monotonic() + seconds
        while True:
            self._check_cancelled()
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                return
            self._sleep(min(remaining, 0.1) if _REQUEST_ID.get() else remaining)

    @contextmanager
    def _bounded_lock(self, lock, timeout):
        """Hold a lock after acquiring it within a cancellable wait budget.

        Args:
            lock: Lock supporting nonblocking acquisition and release.
            timeout (float): Maximum acquisition wait in seconds.

        Yields:
            None: Control while the lock is held; exit always releases it.

        Raises:
            WebPageFetchError: If acquisition exceeds the wait budget.
            EarlyTerminationException: If the request is cancelled before acquisition.
        """
        deadline = self._monotonic() + timeout
        while True:
            self._check_cancelled()
            if lock.acquire(blocking=False):
                break
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                raise WebPageFetchError("WebPageFetch lock wait exceeds maxPacingWaitSeconds.")
            self._sleep(min(remaining, 0.05))
        try:
            yield
        finally:
            lock.release()

    @staticmethod
    def _registrable_domain_lane(hostname: str) -> str:
        """Returns a conservative offline domain lane key.

        Without downloading a Public Suffix List, the final two labels are used.
        This is exact for common one-label suffixes and deliberately over-groups
        multi-label suffixes such as co.uk. Over-grouping reduces throughput but
        never gives related hosts more request lanes than intended.

        Args:
            hostname (str): Validated destination hostname or IP address.

        Returns:
            str: Normalized IP address or conservative domain key for shared pacing.
        """
        try:
            return str(ipaddress.ip_address(hostname))
        except ValueError:
            labels = [label for label in hostname.rstrip(".").lower().split(".") if label]
            return ".".join(labels[-2:]) if len(labels) >= 2 else hostname.lower()


_default_service: Optional[WebPageFetchService] = None
_default_service_lock = threading.Lock()


def get_default_web_page_fetch_service() -> WebPageFetchService:
    """Get the lazily initialized process-wide page-fetch service.

    Returns:
        WebPageFetchService: Shared robots cache and domain pacing service.
    """
    global _default_service
    if _default_service is None:
        with _default_service_lock:
            if _default_service is None:
                _default_service = WebPageFetchService()
    return _default_service
