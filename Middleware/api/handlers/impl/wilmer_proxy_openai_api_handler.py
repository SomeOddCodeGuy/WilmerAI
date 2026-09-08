import json
import time
from typing import Dict, Tuple

import requests
from flask import Response, jsonify, request
from werkzeug.urls import iri_to_uri

from Middleware.api.handlers.base.base_api_handler import BaseApiHandler
from Middleware.wilmer_proxy.config import WilmerProxyConfig, load_wilmer_proxy_config
from Middleware.wilmer_proxy.transport import WilmerProxyTransport


from Middleware.utilities.sensitive_logging_utils import get_sensitive_logger

logger = get_sensitive_logger(__name__)

_RESPONSE_HEADERS_TO_REMOVE = frozenset({
    "connection",
    "content-encoding",
    "content-length",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
})


def _reject_nonstandard_json_constant(value: str):
    """Reject JSON constants outside the JSON specification.

    Args:
        value (str): Non-finite constant encountered by the JSON decoder.

    Raises:
        ValueError: Always, because NaN and Infinity are not accepted.
    """
    raise ValueError(f"Non-standard JSON constant is not allowed: {value}")


class WilmerProxyOpenAIApiHandler(BaseApiHandler):
    """OpenAI-compatible allowlisting relay used only in WilmerProxy mode."""

    SUPPORTED_MODES = frozenset({"wilmerproxy"})

    def __init__(self, wilmer_proxy_config: WilmerProxyConfig = None,
                 transport: WilmerProxyTransport = None):
        """Initialize the model allowlist and upstream transport.

        Args:
            wilmer_proxy_config (WilmerProxyConfig, optional): Validated configuration; omitted
                values load the CLI-selected configuration.
            transport (WilmerProxyTransport, optional): Upstream request transport; defaults to
                a new WilmerProxyTransport.
        """
        self.wilmer_proxy_config = wilmer_proxy_config or load_wilmer_proxy_config()
        self.transport = transport or WilmerProxyTransport()

    @staticmethod
    def _error(message: str, status: int, code: str, param: str = None) -> Tuple[Response, int]:
        """Build an OpenAI-compatible error response.

        Args:
            message (str): Client-facing explanation.
            status (int): HTTP status determining the client or proxy error category.
            code (str): Machine-readable error code.
            param (str, optional): Invalid request field, when applicable.

        Returns:
            Tuple[Response, int]: JSON error response and HTTP status.
        """
        return jsonify({
            "error": {
                "message": message,
                "type": "invalid_request_error" if status < 500 else "wilmer_proxy_error",
                "param": param,
                "code": code,
            }
        }), status

    def _models_response(self) -> Response:
        """List the public model aliases available through this proxy.

        Returns:
            Response: OpenAI-compatible JSON model list.
        """
        created = int(time.time())
        return jsonify({
            "object": "list",
            "data": [
                {
                    "id": public_name,
                    "object": "model",
                    "created": created,
                    "owned_by": "wilmerproxy",
                }
                for public_name in self.wilmer_proxy_config.models
            ],
        })

    def _prepare_request_body(self) -> Tuple[bytes, object, bool, object]:
        """Validate the active Flask request and map its public model alias.

        Returns:
            tuple: Encoded JSON body, selected model configuration, streaming flag, and error
                response. On validation failure, the first three values are empty bytes, None,
                and False; on success, the error is None.
        """
        raw_body = request.get_data(cache=False)
        try:
            payload = json.loads(
                raw_body,
                parse_constant=_reject_nonstandard_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return b"", None, False, self._error("The request body must be valid JSON.", 400, "invalid_json")

        if not isinstance(payload, dict):
            return b"", None, False, self._error("The request body must be a JSON object.", 400, "invalid_json")

        public_model = payload.get("model")
        if not isinstance(public_model, str) or not public_model:
            return b"", None, False, self._error(
                "The 'model' field is required and must be a non-empty string.",
                400,
                "invalid_model",
                "model",
            )

        model_config = self.wilmer_proxy_config.models.get(public_model)
        if model_config is None:
            return b"", None, False, self._error(
                f"Model '{public_model}' is not available through this WilmerProxy instance.",
                404,
                "model_not_found",
                "model",
            )

        payload["model"] = model_config.target_model
        try:
            mapped_body = json.dumps(
                payload,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError):
            return b"", None, False, self._error(
                "The request body contains invalid JSON values.", 400, "invalid_json")
        return mapped_body, model_config, payload.get("stream") is True, None

    @staticmethod
    def _response_headers(upstream_response) -> Dict[str, str]:
        """Select upstream headers suitable for a decoded WSGI response.

        Args:
            upstream_response (requests.Response): Response supplying the headers.

        Returns:
            Dict[str, str]: Headers without hop-by-hop or encoded-body metadata, with URL values
                normalized for Werkzeug.
        """
        connection_headers = {
            token.strip().lower()
            for name, value in upstream_response.headers.items()
            if name.lower() == "connection"
            for token in value.split(",")
        }
        headers = {
            name: value
            for name, value in upstream_response.headers.items()
            if name.lower() not in _RESPONSE_HEADERS_TO_REMOVE | connection_headers
        }
        for name in list(headers):
            if name.lower() in {"location", "content-location"}:
                try:
                    headers[name] = iri_to_uri(headers[name])
                except (ValueError, UnicodeError):
                    # Werkzeug otherwise fails after handing ownership to the WSGI response.
                    del headers[name]
                    logger.warning("WilmerProxy omitted an invalid upstream URL response header.")
        return headers

    @staticmethod
    def _close_upstream(session, upstream_response) -> None:
        """Release the upstream response and its owning session.

        Args:
            session (requests.Session): Session to close even if response cleanup fails.
            upstream_response (requests.Response): Response whose body resources are released
                first.
        """
        try:
            upstream_response.close()
        finally:
            session.close()

    def _relay_response(self, session, upstream_response, client_requested_stream: bool) -> Response:
        """Build a downstream response that owns upstream cleanup.

        Args:
            session (requests.Session): Session owning the upstream request.
            upstream_response (requests.Response): Open response to relay.
            client_requested_stream (bool): Whether successful responses should stream; HTTP
                errors are buffered.

        Returns:
            Response: Buffered or streaming response preserving upstream status and permitted
                headers.
        """
        headers = self._response_headers(upstream_response)
        status = upstream_response.status_code

        if not client_requested_stream or status >= 400:
            try:
                body = upstream_response.content
            finally:
                self._close_upstream(session, upstream_response)
            return Response(body, status=status, headers=headers)

        upstream_closed = False

        def close_upstream():
            """Close the upstream resources at most once across iterator and response teardown."""
            nonlocal upstream_closed
            if not upstream_closed:
                upstream_closed = True
                self._close_upstream(session, upstream_response)

        def generate():
            """Relay body chunks while retaining cleanup ownership.

            Yields:
                bytes: Non-empty upstream body chunks.
            """
            try:
                for chunk in upstream_response.iter_content(chunk_size=16384):
                    if chunk:
                        yield chunk
            finally:
                close_upstream()

        # Werkzeug's closing iterator also handles disconnects before the first yield.
        response = Response(generate(), status=status, headers=headers)
        response.call_on_close(close_upstream)
        return response

    def _relay_post(self, upstream_path: str):
        """Route the active generation request to its allowlisted upstream.

        Args:
            upstream_path (str): Canonical chat or text completions path.

        Returns:
            Union[Response, Tuple[Response, int]]: Relayed response, validation error, or 502
                error when the upstream request fails.
        """
        mapped_body, model_config, client_requested_stream, error_response = self._prepare_request_body()
        if error_response is not None:
            return error_response

        upstream = self.wilmer_proxy_config.upstreams[model_config.upstream]
        try:
            session, upstream_response = self.transport.open_request(
                method="POST",
                path=upstream_path,
                body=mapped_body,
                incoming_headers=request.headers,
                upstream=upstream,
            )
        except requests.RequestException as exc:
            logger.error(
                "WilmerProxy request to configured upstream '%s' failed with %s",
                upstream.name,
                type(exc).__name__,
            )
            return self._error(
                f"The configured upstream '{upstream.name}' could not complete the request.",
                502,
                "upstream_unavailable",
            )

        return self._relay_response(session, upstream_response, client_requested_stream)

    def register_routes(self, app) -> None:
        """Registers the OpenAI-compatible paths served by WilmerProxy mode.

        Args:
            app (Flask): Application receiving the model-list and generation routes.
        """
        app.add_url_rule(
            "/v1/models", endpoint="wilmer_proxy_v1_models",
            view_func=self._models_response, methods=["GET"])
        app.add_url_rule(
            "/models", endpoint="wilmer_proxy_models",
            view_func=self._models_response, methods=["GET"])
        app.add_url_rule(
            "/v1/chat/completions", endpoint="wilmer_proxy_v1_chat_completions",
            view_func=lambda: self._relay_post("/v1/chat/completions"), methods=["POST"])
        app.add_url_rule(
            "/chat/completions", endpoint="wilmer_proxy_chat_completions",
            view_func=lambda: self._relay_post("/v1/chat/completions"), methods=["POST"])
        app.add_url_rule(
            "/v1/completions", endpoint="wilmer_proxy_v1_completions",
            view_func=lambda: self._relay_post("/v1/completions"), methods=["POST"])
        app.add_url_rule(
            "/completions", endpoint="wilmer_proxy_completions",
            view_func=lambda: self._relay_post("/v1/completions"), methods=["POST"])
