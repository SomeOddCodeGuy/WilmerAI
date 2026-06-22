# tests/utilities/test_network_security_utils.py

import socket

import pytest

from Middleware.utilities import network_security_utils as nsu


def _addrinfo(ip):
    """Builds a getaddrinfo-shaped result for a single IPv4/IPv6 address."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]


# --- no-op when neither control is enabled ---

def test_no_policy_is_noop_and_does_no_dns(mocker):
    gai = mocker.patch.object(nsu.socket, "getaddrinfo")
    assert nsu.check_url_allowed("http://anything.internal/") is None
    gai.assert_not_called()


# --- blockPrivateAddresses on IP literals (no DNS) ---

@pytest.mark.parametrize("url", [
    "http://127.0.0.1/",
    "http://10.0.0.5/",
    "http://192.168.1.50/",
    "http://172.16.0.1/",
    "http://169.254.169.254/latest/meta-data/",  # cloud metadata
    "http://[::1]/",                               # IPv6 loopback
    "http://0.0.0.0/",
])
def test_block_private_rejects_internal_ip_literals(url, mocker):
    gai = mocker.patch.object(nsu.socket, "getaddrinfo")
    reason = nsu.check_url_allowed(url, block_private_addresses=True)
    assert reason is not None
    gai.assert_not_called()  # an IP literal is classified without resolving


def test_block_private_allows_public_ip_literal(mocker):
    gai = mocker.patch.object(nsu.socket, "getaddrinfo")
    assert nsu.check_url_allowed("http://8.8.8.8/", block_private_addresses=True) is None
    gai.assert_not_called()


def test_block_private_rejects_ipv4_mapped_ipv6_literal(mocker):
    mocker.patch.object(nsu.socket, "getaddrinfo")
    # ::ffff:127.0.0.1 must be unwrapped and judged by the v4 rules.
    assert nsu.check_url_allowed("http://[::ffff:127.0.0.1]/", block_private_addresses=True) is not None


# --- blockPrivateAddresses on hostnames (DNS resolution mocked) ---

def test_block_private_rejects_hostname_resolving_to_private(mocker):
    mocker.patch.object(nsu.socket, "getaddrinfo", return_value=_addrinfo("10.1.2.3"))
    assert nsu.check_url_allowed("http://intranet.example/", block_private_addresses=True) is not None


def test_block_private_allows_hostname_resolving_to_public(mocker):
    mocker.patch.object(nsu.socket, "getaddrinfo", return_value=_addrinfo("93.184.216.34"))
    assert nsu.check_url_allowed("http://example.com/", block_private_addresses=True) is None


def test_block_private_unresolvable_host_is_rejected(mocker):
    mocker.patch.object(nsu.socket, "getaddrinfo", side_effect=socket.gaierror("no such host"))
    reason = nsu.check_url_allowed("http://nope.invalid/", block_private_addresses=True)
    assert reason is not None and "could not be resolved" in reason


# --- allowedHosts ---

def test_allowed_hosts_permits_listed_host_case_insensitively():
    assert nsu.check_url_allowed("http://Example.COM/x", allowed_hosts=["example.com"]) is None


def test_allowed_hosts_rejects_unlisted_host():
    reason = nsu.check_url_allowed("http://evil.net/", allowed_hosts=["example.com"])
    assert reason is not None and "allowedHosts" in reason


def test_allowed_hosts_does_not_resolve_dns(mocker):
    gai = mocker.patch.object(nsu.socket, "getaddrinfo")
    nsu.check_url_allowed("http://example.com/", allowed_hosts=["example.com"])
    gai.assert_not_called()


def test_both_controls_must_pass(mocker):
    # On the allowlist, but resolves to a private IP -> still rejected.
    mocker.patch.object(nsu.socket, "getaddrinfo", return_value=_addrinfo("10.0.0.9"))
    reason = nsu.check_url_allowed(
        "http://example.com/", block_private_addresses=True, allowed_hosts=["example.com"]
    )
    assert reason is not None


# --- non-global ranges beyond the classic private set (CVE-2024-4032 hardening) ---
# These have is_private == False but is_global == False, so they are caught by the
# "not globally routable" rule rather than the named-family checks.

@pytest.mark.parametrize("url", [
    "http://100.64.0.0/",         # CGNAT shared address space (RFC 6598)
    "http://100.64.1.1/",
    "http://100.127.255.255/",
    "http://192.0.2.1/",          # TEST-NET-1 (RFC 5737)
    "http://198.18.0.5/",         # inter-network benchmarking (RFC 2544)
    "http://203.0.113.7/",        # TEST-NET-3 (RFC 5737)
    "http://240.0.0.1/",          # reserved for future use
])
def test_block_private_rejects_non_global_ip_literals(url, mocker):
    gai = mocker.patch.object(nsu.socket, "getaddrinfo")
    assert nsu.check_url_allowed(url, block_private_addresses=True) is not None
    gai.assert_not_called()  # still classified without a DNS lookup


def test_block_private_rejects_cgnat_hostname(mocker):
    mocker.patch.object(nsu.socket, "getaddrinfo", return_value=_addrinfo("100.64.5.5"))
    assert nsu.check_url_allowed("http://shared.example/", block_private_addresses=True) is not None


# --- explicit address-classification contract ---
# Pins the exact addresses the guard must reject / permit, independent of which
# ipaddress predicate fires. If the running interpreter mis-classifies any of these
# (e.g. a pre-3.11.9 build affected by CVE-2024-4032), these tests fail loudly rather
# than silently opening an SSRF hole.
_MUST_REJECT = [
    "127.0.0.1", "10.0.0.5", "192.168.1.50", "172.16.0.1", "169.254.169.254",
    "0.0.0.0", "::1", "::ffff:127.0.0.1",
    "100.64.0.0", "100.64.1.1", "100.127.255.255",
    "192.0.2.1", "198.18.0.5", "203.0.113.7", "240.0.0.1", "fd00::1", "fe80::1",
]
_MUST_ALLOW = ["8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700:4700::1111"]


@pytest.mark.parametrize("ip", _MUST_REJECT)
def test_block_private_rejects_known_non_public_addresses(ip, mocker):
    gai = mocker.patch.object(nsu.socket, "getaddrinfo")
    host = f"[{ip}]" if ":" in ip else ip
    assert nsu.check_url_allowed(f"http://{host}/", block_private_addresses=True) is not None
    gai.assert_not_called()


@pytest.mark.parametrize("ip", _MUST_ALLOW)
def test_block_private_allows_known_public_addresses(ip, mocker):
    gai = mocker.patch.object(nsu.socket, "getaddrinfo")
    host = f"[{ip}]" if ":" in ip else ip
    assert nsu.check_url_allowed(f"http://{host}/", block_private_addresses=True) is None
    gai.assert_not_called()


# --- malformed input ---

def test_url_without_host_is_rejected_when_policy_active():
    assert nsu.check_url_allowed("not-a-url", block_private_addresses=True) is not None
