"""Real Requests redirect preparation and Flask relay using a memory-only adapter."""
import io
from unittest.mock import Mock

from flask import Flask
import pytest
import requests

from Middleware.api.handlers.impl.wilmer_proxy_openai_api_handler import WilmerProxyOpenAIApiHandler
from Middleware.wilmer_proxy.config import WilmerProxyConfig, WilmerProxyModelConfig, WilmerProxyUpstreamConfig
from Middleware.wilmer_proxy.transport import WilmerProxyTransport


@pytest.fixture
def memory_transport(monkeypatch):
    original_session = requests.Session
    responses, sent, sessions = [], [], []
    state = {'location': None, 'header': 'Location'}

    class Adapter(requests.adapters.BaseAdapter):
        def send(self, request, **kwargs):
            sent.append(request)
            response = requests.Response()
            response.status_code = 302 if state['location'] else 200
            response.url = request.url
            response.request = request
            response.raw = io.BytesIO(b'ordinary upstream body')
            if state['location']:
                response.headers[state['header']] = state['location']
            response.close = Mock(wraps=response.close)
            responses.append(response)
            return response

        def close(self):
            pass

    def factory():
        session = original_session()
        session.mount('https://', Adapter())
        session.close = Mock(wraps=session.close)
        sessions.append(session)
        return session

    monkeypatch.setattr(requests, 'Session', factory)
    upstream = WilmerProxyUpstreamConfig(name='test', base_url='https://example.com',
        authorization_mode='omit', connect_timeout_seconds=1, read_timeout_seconds=1)
    try:
        yield state, upstream, sent, responses, sessions
    finally:
        for response in responses:
            response.close()
        for session in sessions:
            session.close()


@pytest.mark.parametrize('location', [None, '/next', 'http://['])
def test_proxy_leaves_redirect_body_and_metadata_to_caller(memory_transport, location):
    state, upstream, sent, responses, sessions = memory_transport
    state['location'] = location
    session, response = WilmerProxyTransport().open_request('POST', '/v1/chat/completions',
        b'{"stream":true}', {}, upstream)
    assert len(sent) == 1
    assert not response._content_consumed
    assert response.raw.tell() == 0
    assert response.content == b'ordinary upstream body'
    response.close()
    session.close()
    response.close.assert_called_once()
    session.close.assert_called_once()


@pytest.mark.parametrize('stream,header,location,retained', [
    (False, 'Location', 'http://[', False),
    (True, 'Location', 'http://[', False),
    (True, 'Content-Location', 'http://[', False),
    (True, 'Location', '/next', True),
])
def test_proxy_api_relays_status_body_and_serializable_url_headers(memory_transport, stream,
                                                                 header, location, retained):
    state, upstream, sent, responses, sessions = memory_transport
    state.update(location=location, header=header)
    config = WilmerProxyConfig(name='test', upstreams={'test': upstream}, models={
        'general': WilmerProxyModelConfig(public_name='general', upstream='test', target_model='target')})
    app = Flask('proxy-redirect-test')
    app.config['TESTING'] = True
    WilmerProxyOpenAIApiHandler(config, WilmerProxyTransport()).register_routes(app)
    with app.test_client() as client:
        result = client.post('/v1/chat/completions', json={'model': 'general', 'stream': stream})
        try:
            assert result.status_code == 302
            assert result.headers.get(header) == (location if retained else None)
            assert result.data == b'ordinary upstream body'
            assert len(sent) == 1
        finally:
            result.close()
    responses[0].close.assert_called_once()
    sessions[0].close.assert_called_once()
