from typing import Mapping

import requests

from Middleware.wilmer_proxy.config import WilmerProxyUpstreamConfig
from Middleware.utilities.redirect_policy import disable_session_redirects


from Middleware.utilities.sensitive_logging_utils import get_sensitive_logger

logger = get_sensitive_logger(__name__)


class WilmerProxyTransport:
    """Opens non-retrying HTTP requests to operator-configured Wilmer upstreams."""

    @staticmethod
    def _build_headers(incoming_headers: Mapping[str, str],
                       upstream: WilmerProxyUpstreamConfig) -> dict:
        """Apply the upstream authentication and client-header forwarding policy.

        Args:
            incoming_headers (Mapping[str, str]): Client headers from the active request.
            upstream (WilmerProxyUpstreamConfig): Validated authorization and forwarding
                settings.

        Returns:
            dict: Headers for the upstream JSON request.
        """
        headers = {
            "Content-Type": incoming_headers.get("Content-Type", "application/json"),
            "Accept-Encoding": "identity",
        }

        accept = incoming_headers.get("Accept")
        if accept:
            headers["Accept"] = accept

        if upstream.authorization_mode == "passthrough":
            authorization = incoming_headers.get("Authorization")
            if authorization:
                headers["Authorization"] = authorization
        elif upstream.authorization_mode == "configured":
            headers["Authorization"] = f"Bearer {upstream.api_key}"

        for header_name in upstream.forward_headers:
            value = incoming_headers.get(header_name)
            if value is not None:
                headers[header_name] = value
        return headers

    def open_request(self, method: str, path: str, body: bytes,
                     incoming_headers: Mapping[str, str], upstream: WilmerProxyUpstreamConfig):
        """Opens one streaming-capable upstream request.

        The caller owns the returned session and response and must close both.
        Redirects and retries are deliberately disabled so a generation request
        cannot be repeated or have its authorization header sent to another host.

        Args:
            method (str): HTTP method.
            path (str): Canonical OpenAI path beginning with ``/``.
            body (bytes): Complete mapped request body.
            incoming_headers (Mapping[str, str]): Client request headers.
            upstream (WilmerProxyUpstreamConfig): Validated target and policy.

        Returns:
            tuple: ``(requests.Session, requests.Response)``.
        """
        session = requests.Session()
        session.trust_env = False
        disable_session_redirects(session)
        url = f"{upstream.base_url}{path}"
        headers = self._build_headers(incoming_headers, upstream)
        logger.info(
            "WilmerProxy relaying %s %s to configured upstream '%s'",
            method,
            path,
            upstream.name,
        )
        try:
            response = session.request(
                method=method,
                url=url,
                headers=headers,
                data=body,
                stream=True,
                allow_redirects=False,
                timeout=(upstream.connect_timeout_seconds, upstream.read_timeout_seconds),
                verify=upstream.verify_tls,
            )
            return session, response
        except BaseException:
            session.close()
            raise
