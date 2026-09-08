import io

import pytest
import requests

from Middleware.llmapis.handlers.base.base_api_transport import BaseApiTransport


@pytest.mark.parametrize("destination, retained", [
    ("https://other.test/result", False),
    ("http://api.test/result", False),
    ("https://api.test:8443/result", False),
    ("https://api.test/result", True),
])
def test_llm_transport_redirects_protect_provider_credentials(mocker, destination, retained):
    """Exercise real Requests redirect preparation against an in-memory adapter."""
    mocker.patch("Middleware.llmapis.handlers.base.base_api_transport.get_connect_timeout", return_value=1)
    transport = BaseApiTransport("https://api.test", "test", {"x-api-key": "test", "Authorization": "Bearer test"})
    transport.session.trust_env = False
    sent = []

    class Adapter(requests.adapters.BaseAdapter):
        def send(self, request, **kwargs):
            sent.append(request)
            response = requests.Response()
            response.request = request
            response.url = request.url
            response.status_code = 307 if len(sent) == 1 else 200
            response.raw = io.BytesIO(b'{}')
            if len(sent) == 1:
                response.headers["Location"] = destination
            return response

        def close(self):
            pass

    transport.session.mount("https://", Adapter())
    transport.session.mount("http://", Adapter())
    try:
        with transport.session.post("https://api.test/start", headers=transport.headers, json={}) as result:
            assert result.status_code == 200
        assert len(sent) == 2
        assert ("x-api-key" in sent[1].headers) is retained
        assert ("Authorization" in sent[1].headers) is retained
    finally:
        transport.session.close()
