# /Middleware/utilities/network_security_utils.py

import ipaddress
import socket
from typing import Iterable, Optional
from urllib.parse import urlsplit

# Address families we refuse to reach, each paired with the ``ipaddress``
# predicate that detects it. Ordered most-specific-first so the label we hand
# back is the most informative one when an address matches several families
# (e.g. 169.254.169.254 is reported as link-local rather than private).
_NON_PUBLIC_FAMILIES = (
    ("is_loopback", "loopback"),
    ("is_link_local", "link-local"),  # 169.254.0.0/16 — incl. the cloud metadata endpoint
    ("is_unspecified", "unspecified"),
    ("is_multicast", "multicast"),
    ("is_reserved", "reserved"),
    ("is_private", "private"),  # RFC1918 10/172.16/192.168 and friends
)


def _non_public_family(ip) -> Optional[str]:
    """Classifies an address, returning why it must not be reached or None if it is fine.

    The block decision is "not globally routable": any address whose ``is_global`` is
    False is rejected. That is deliberately broader than the named families below -- it
    also catches shared CGNAT space (100.64.0.0/10), the IETF TEST-NET / documentation /
    benchmarking ranges, and future-reserved space, none of which ``is_private`` flags
    (e.g. 100.64.0.0/10 has both is_private and is_global False). The family table is
    consulted first only to attach a precise label; a non-global address that matches no
    named family is reported generically as ``"non-global"``.

    IPv4-mapped IPv6 addresses (``::ffff:a.b.c.d``) are unwrapped first so the decision is
    made about the IPv4 address the socket would actually reach.

    Correctness depends on the interpreter's ``ipaddress`` classification, which was wrong
    for several of these ranges before the CVE-2024-4032 fix (Python 3.11.9 / 3.12.4 /
    3.13). The address-level regression tests pin the exact behavior relied on here.

    Args:
        ip (ipaddress.IPv4Address | ipaddress.IPv6Address): The address to judge.

    Returns:
        Optional[str]: A short reason label (e.g. ``"loopback"`` or ``"non-global"``) when
            the address must not be reached, or None when it is a routable public address.
    """
    mapped = getattr(ip, "ipv4_mapped", None)
    candidate = mapped if mapped is not None else ip
    for attr, label in _NON_PUBLIC_FAMILIES:
        if getattr(candidate, attr):
            return label
    if not candidate.is_global:
        return "non-global"
    return None


def _addresses_for_host(host: str):
    """Expands a host into the concrete addresses the policy must screen.

    An IP literal denotes exactly itself and needs no name resolution; anything
    else is handed to the OS resolver and every answer is screened.

    Args:
        host (str): An IP literal or a hostname taken from the URL.

    Returns:
        tuple: ``(addresses, via_dns)`` where ``addresses`` is a list of
            ``ipaddress`` objects and ``via_dns`` is True only when the resolver
            was consulted (so callers can phrase the rejection accordingly).

    Raises:
        socket.gaierror: If a hostname cannot be resolved.
    """
    try:
        return [ipaddress.ip_address(host)], False
    except ValueError:
        pass
    # info[4][0] is the address string; drop any IPv6 zone id ("fe80::1%eth0").
    addresses = [
        ipaddress.ip_address(info[4][0].split("%")[0])
        for info in socket.getaddrinfo(host, None)
    ]
    return addresses, True


def check_url_allowed(
    url: str,
    block_private_addresses: bool = False,
    allowed_hosts: Optional[Iterable[str]] = None,
) -> Optional[str]:
    """Returns a human-readable reason string if ``url`` violates the address policy, else None.

    The two controls are independent and additive (both must pass when both are set):

    - ``allowed_hosts``: when non-empty, the URL host must match (case-insensitive) one
      of the listed hosts; any other host is rejected. This needs no DNS lookup.
    - ``block_private_addresses``: the host is rejected if it is, or resolves to, an
      address that is not globally routable -- loopback/link-local/private/reserved/
      multicast/unspecified, plus shared CGNAT space (100.64.0.0/10) and the TEST-NET/
      documentation ranges. This is what blocks SSRF to 127.0.0.1, the 169.254.169.254
      cloud-metadata endpoint, and the 10/172.16/192.168 ranges.

    When neither control is enabled the function is a no-op and returns None, so callers
    pay nothing (and make no DNS call) unless an operator has opted in.

    Note: ``block_private_addresses`` resolves the hostname here, but the OS resolves it
    again at connect time, so a hostile DNS that answers public-then-private (DNS
    rebinding) can still slip past. Pin to fixed names with ``allowed_hosts`` when that
    residual risk matters.

    Args:
        url (str): The URL whose host is validated.
        block_private_addresses (bool): When True, reject a host that is, or
            resolves to, a non-globally-routable address (loopback/link-local/
            private/reserved/multicast/unspecified, plus CGNAT and TEST-NET space).
            Defaults to False.
        allowed_hosts (Optional[Iterable[str]]): When non-empty, the host must
            match (case-insensitively) one of these; any other host is rejected.
            Defaults to None.

    Returns:
        Optional[str]: A human-readable reason string if the URL violates the
            address policy, or None if it is allowed (or both controls are off).
    """
    allowed = (
        {h.strip().lower() for h in allowed_hosts if h and h.strip()}
        if allowed_hosts
        else set()
    )
    if not (allowed or block_private_addresses):
        return None

    host = urlsplit(url).hostname
    if not host:
        return f"could not determine a host from URL {url!r}"

    if allowed and host.lower() not in allowed:
        return f"host {host!r} is not in the configured allowedHosts list"

    if block_private_addresses:
        try:
            addresses, via_dns = _addresses_for_host(host)
        except socket.gaierror:
            return f"host {host!r} could not be resolved"
        for ip in addresses:
            family = _non_public_family(ip)
            if family is None:
                continue
            if via_dns:
                return f"host {host!r} resolves to a {family} address ({ip})"
            return f"host {host!r} is a {family} address"

    return None
