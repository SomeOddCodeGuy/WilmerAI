"""Credential boundaries for HTTP redirects used by configured transports."""

from urllib.parse import urljoin

import requests


SENSITIVE_HEADERS = frozenset({
    "authorization", "cookie", "proxy-authorization", "x-api-key", "api-key",
})


def resolve_redirect_url(base_url: str, location: str) -> str:
    """Resolve a Location header using Requests-compatible text decoding.

    Args:
        base_url (str): URL of the redirecting response.
        location (str): HTTP Location header decoded as Latin-1 by the transport.

    Returns:
        str: Resolved destination, still subject to the caller's URL policy.

    Raises:
        ValueError: If the destination cannot be parsed or decoded.
    """
    # Match Requests' interpretation of UTF-8 bytes carried in HTTP headers.
    return urljoin(base_url, location.encode('latin-1').decode('utf-8'))


def disable_session_redirects(session: requests.Session) -> None:
    """Disable implicit redirect preparation on a session owned by one fetch.

    Requests prepares Response.next even with allow_redirects=False. That step
    consumes the redirect body, bypassing application size and deadline checks.

    Args:
        session (requests.Session): Private single-hop session to configure.
    """
    session.resolve_redirects = lambda *args, **kwargs: iter(())


def request_without_redirects(*, cookie_jar=None, **kwargs) -> requests.Response:
    """Return a single-hop response whose close also releases its private session.

    Args:
        cookie_jar: Optional cookie jar shared only by hops of one operation.
        **kwargs: Requests request arguments; redirects are always disabled.

    Returns:
        requests.Response: Caller-owned streamed response, with no implicit body read.
    """
    session = requests.sessions.Session()
    if cookie_jar is not None:
        session.cookies = cookie_jar
    disable_session_redirects(session)
    try:
        kwargs['allow_redirects'] = False
        response = session.request(**kwargs)
    except BaseException:
        session.close()
        raise
    original_close = response.close
    closed = False

    def close():
        """Close the response and its private session at most once."""
        nonlocal closed
        if closed:
            return
        closed = True
        try:
            original_close()
        finally:
            session.close()

    response.close = close
    return response


def redirect_method_and_body(method, data, headers, status):
    """Rebuild method, body and entity headers with Requests redirect semantics.

    Args:
        method (str): Current HTTP method.
        data: Current request body.
        headers (dict): Current request headers.
        status (int): Redirect status code.

    Returns:
        tuple: Next method, body and copied headers.
    """
    request = requests.PreparedRequest()
    request.method = method
    response = requests.Response()
    response.status_code = status
    requests.sessions.SessionRedirectMixin().rebuild_method(request, response)
    headers = dict(headers or {})
    if status not in (307, 308):
        data = None
        headers = {k: v for k, v in headers.items()
                   if k.lower() not in {'content-length', 'content-type', 'transfer-encoding'}}
    return request.method, data, headers


def should_strip_credentials(old_url: str, new_url: str) -> bool:
    """Apply Requests' host, scheme and effective-port authentication boundary.

    Args:
        old_url (str): URL of the redirecting request.
        new_url (str): Resolved destination URL.

    Returns:
        bool: Whether credentials must be removed before following the redirect.
    """
    return requests.sessions.SessionRedirectMixin().should_strip_auth(old_url, new_url)


def protect_session_redirects(session: requests.Session) -> None:
    """Extend a session's redirect auth handling to provider API keys and cookies.

    Args:
        session (requests.Session): Session whose redirect authentication hook is
            updated in place while retaining its original authentication handling.
    """
    original_rebuild_auth = session.rebuild_auth

    def rebuild_auth(prepared_request, response):
        """Apply authentication rebuilding and strip credentials across trust boundaries.

        Args:
            prepared_request (requests.PreparedRequest): Redirect request whose headers are
                updated in place.
            response (requests.Response): Redirecting response with the source request URL.
        """
        original_rebuild_auth(prepared_request, response)
        if should_strip_credentials(response.request.url, prepared_request.url):
            for name in list(prepared_request.headers):
                if name.lower() in SENSITIVE_HEADERS:
                    del prepared_request.headers[name]

    session.rebuild_auth = rebuild_auth
