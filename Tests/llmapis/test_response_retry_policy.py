"""Count real adapter attempts with synthetic HTTP exchanges and no network access."""

import io
import json

import pytest
import requests
from urllib3.exceptions import ConnectTimeoutError, NewConnectionError, ProtocolError
from urllib3.response import HTTPResponse

from Middleware.exceptions.invalid_llm_response_error import InvalidLlmResponseError
from Middleware.llmapis.handlers.base.base_api_transport import BaseApiTransport
from Middleware.llmapis.llm_api import LlmApiService
from Middleware.services.cancellation_service import cancellation_service


@pytest.fixture
def exchange(mocker):
    attempts = []
    responses = []
    services = []
    state = {"failure": None, "status": 200, "body": {"choices": [{"message": {"content": "ok"}}]},
             "backup": False, "interrupt": None}

    def endpoint(name):
        assert name in ("primary", "backup")
        return {"endpoint": "http://127.0.0.1:1/" + name,
                "apiTypeConfigFileName": "test", "dontIncludeModel": True,
                "presetSamplers": {"temperature": 1},
                **({"backupEndpointName": "backup"} if state["backup"] and name == "primary" else {})}

    mocker.patch("Middleware.llmapis.llm_api.get_endpoint_config", side_effect=endpoint)
    mocker.patch("Middleware.llmapis.llm_api.try_get_endpoint_config", side_effect=endpoint)
    mocker.patch("Middleware.llmapis.llm_api.get_api_type_config", return_value={
        "type": "openAIChatCompletion", "presetType": "test", "streamPropertyName": "stream",
        "samplerFieldMap": {"temperature": "temperature"}})
    real_init = requests.Session.__init__

    def session_init(session):
        real_init(session)
        session.trust_env = False

    mocker.patch.object(requests.Session, "__init__", session_init)
    mocker.patch("socket.socket.connect", side_effect=AssertionError("Network forbidden"))
    mocker.patch("socket.getaddrinfo", side_effect=AssertionError("DNS forbidden"))
    wait = mocker.patch.object(BaseApiTransport, "_wait_before_retry", return_value=True)

    def make_request(pool, conn, method, url, **kwargs):
        assert method == "POST"
        attempts.append(url)
        is_backup = url.startswith("/backup/")
        if not is_backup and state["failure"]:
            raise state["failure"](conn)
        body = {"choices": [{"message": {"content": "backup"}}]} if is_backup else state["body"]
        stream = json.loads(kwargs["body"])["stream"]
        if stream:
            token = "backup" if is_backup else "ok"
            encoded = ('data: ' + json.dumps({"choices": [{"delta": {"content": token},
                        "finish_reason": None}]}) + '\n\ndata: ' + json.dumps({"choices": [
                        {"delta": {}, "finish_reason": "stop"}]}) + '\n\n').encode()
        else:
            encoded = body if isinstance(body, bytes) else json.dumps(body).encode()
        response = HTTPResponse(body=io.BytesIO(encoded), status=200 if is_backup else state["status"],
                                headers={"Content-Type": "application/json"}, preload_content=False)
        if not is_backup and state["interrupt"]:
            def interrupted_stream(*args, **kw):
                if state["interrupt"] == "after":
                    yield b'data: {"choices":[{"delta":{"content":"visible"},"finish_reason":null}]}\n\n'
                raise ProtocolError("synthetic interruption")
            response.stream = interrupted_stream
        responses.append(response)
        return response

    mocker.patch("urllib3.connectionpool.HTTPConnectionPool._make_request", new=make_request)

    def service(stream=False, suppress=False):
        result = LlmApiService("primary", "primary", 32, stream=stream)
        result._api_handler.suppress_retries = suppress or state["backup"]
        services.append(result)
        return result

    yield state, attempts, responses, service, wait
    for item in services:
        item.close()
    cancellation_service.acknowledge_cancellation("retry-policy-test")


def consume(service):
    result = service.get_response_from_llm(prompt="Synthetic test.", request_id="retry-policy-test")
    return list(result) if service.stream else result


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("suppress, expected", [(False, 3), (True, 1)])
@pytest.mark.parametrize("failure", ["connect", "connect_timeout", "503"])
def test_one_budget_counts_actual_adapter_attempts(exchange, stream, suppress, expected, failure):
    state, attempts, responses, factory, wait = exchange
    if failure == "connect":
        state["failure"] = lambda conn: NewConnectionError(conn, "synthetic refusal")
    elif failure == "connect_timeout":
        state["failure"] = lambda conn: ConnectTimeoutError("synthetic connect timeout")
    else:
        state["status"] = 503
    service = factory(stream, suppress)
    with pytest.raises(requests.exceptions.RequestException):
        consume(service)
    assert len(attempts) == expected
    assert wait.call_count == expected - 1
    assert all(response.closed for response in responses)
    assert not service.is_busy_flag
    assert "retry-policy-test" not in cancellation_service._abort_callbacks


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("status", [400, 401, 429, 501])
def test_unselected_http_errors_are_not_replayed(exchange, stream, status):
    state, attempts, responses, factory, wait = exchange
    state["status"] = status
    with pytest.raises(requests.exceptions.HTTPError):
        consume(factory(stream))
    assert len(attempts) == 1
    wait.assert_not_called()
    assert responses[0].closed


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("error_type", [requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError,
                                        requests.exceptions.SSLError])
def test_ambiguous_or_configuration_errors_are_not_replayed(exchange, mocker, stream, error_type):
    _, _, _, factory, wait = exchange
    service = factory(stream)
    post = mocker.patch.object(service._api_handler.session, "post", side_effect=error_type("synthetic error"))
    with pytest.raises(error_type):
        consume(service)
    post.assert_called_once()
    wait.assert_not_called()


@pytest.mark.parametrize("backup", [False, True])
def test_invalid_json_is_decoded_once_and_response_closed(exchange, backup):
    state, attempts, responses, factory, wait = exchange
    state["body"] = b'not JSON'
    state["backup"] = backup
    if backup:
        assert consume(factory()) == "backup"
        assert len(attempts) == 2
    else:
        with pytest.raises(requests.exceptions.JSONDecodeError):
            consume(factory())
        assert len(attempts) == 1
    assert all(response.closed for response in responses)
    wait.assert_not_called()


@pytest.mark.parametrize("body", [None, {}, {"choices": []}, {"choices": [None]},
                                   {"choices": [{"message": []}]},
                                   {"choices": [{"message": {"content": 7}}]},
                                   {"choices": [{"message": {"tool_calls": "invalid"}}]}])
@pytest.mark.parametrize("backup", [False, True])
def test_invalid_envelope_raises_or_uses_configured_backup(exchange, body, backup):
    state, attempts, responses, factory, wait = exchange
    state.update(body=body, backup=backup)
    if backup:
        assert consume(factory()) == "backup"
        assert len(attempts) == 2 and attempts[-1].startswith("/backup/")
    else:
        with pytest.raises(InvalidLlmResponseError):
            consume(factory())
        assert len(attempts) == 1
    wait.assert_not_called()
    assert all(response.closed for response in responses)


@pytest.mark.parametrize("message", [{}, {"content": ""}, {"content": None},
                                      {"content": None, "tool_calls": [{"id": "call_1", "type": "function",
                                       "function": {"name": "add_numbers", "arguments": '{"a":1,"b":2}'}}]}])
def test_valid_empty_or_tool_only_response_does_not_fail_over(exchange, message):
    state, attempts, _, factory, _ = exchange
    state.update(body={"choices": [{"message": message}]}, backup=True)
    result = consume(factory())
    if message.get("tool_calls"):
        assert result["tool_calls"] == message["tool_calls"]
    else:
        assert result == ""
    assert len(attempts) == 1


@pytest.mark.parametrize("when, backup", [("before", False), ("before", True), ("after", True)])
def test_stream_interruption_never_retries_same_endpoint(exchange, when, backup):
    state, attempts, responses, factory, wait = exchange
    state.update(interrupt=when, backup=backup)
    service = factory(stream=True)
    gen = service.get_response_from_llm(prompt="Synthetic test.", request_id="retry-policy-test")
    if when == "after":
        assert next(gen)["token"] == "visible"
    if when == "before" and backup:
        assert list(gen)[0]["token"] == "backup"
        assert len(attempts) == 2
    else:
        with pytest.raises(requests.exceptions.ChunkedEncodingError):
            list(gen)
        assert len(attempts) == 1
    assert all(response.closed for response in responses)
    assert "retry-policy-test" not in cancellation_service._abort_callbacks
    assert not service.is_busy_flag
    wait.assert_not_called()


@pytest.mark.parametrize("stream", [False, True])
def test_cancellation_during_real_backoff_prevents_next_post(exchange, mocker, stream):
    state, attempts, responses, factory, wait = exchange
    mocker.stop(wait)
    state["status"] = 503
    def cancel(_):
        cancellation_service.request_cancellation("retry-policy-test")
    sleep = mocker.patch("Middleware.llmapis.handlers.base.base_api_transport.time.sleep", side_effect=cancel)
    result = consume(factory(stream))
    assert result == ([] if stream else "")
    assert len(attempts) == 1
    sleep.assert_called_once()
    assert responses[0].closed
    assert "retry-policy-test" not in cancellation_service._abort_callbacks


def test_backoff_is_short_and_increases_between_attempts(mocker):
    clock = [0.0]
    mocker.patch("Middleware.llmapis.handlers.base.base_api_transport.time.monotonic", side_effect=lambda: clock[0])
    mocker.patch("Middleware.llmapis.handlers.base.base_api_transport.time.sleep",
                 side_effect=lambda delay: clock.__setitem__(0, clock[0] + delay))
    assert BaseApiTransport._wait_before_retry(0, None)
    assert clock[0] == pytest.approx(0.25)
    assert BaseApiTransport._wait_before_retry(1, None)
    assert clock[0] == pytest.approx(0.75)


@pytest.mark.parametrize("stream", [False, True])
def test_retry_success_preserves_output_and_releases_failed_response(exchange, stream):
    state, attempts, responses, factory, wait = exchange
    state["status"] = 503
    def recover(*_):
        assert responses[0].closed
        state["status"] = 200
        return True
    wait.side_effect = recover
    result = consume(factory(stream))
    if stream:
        assert result[0]["token"] == "ok"
    else:
        assert result == "ok"
    assert len(attempts) == 2
    assert all(response.closed for response in responses)


@pytest.mark.parametrize("stream", [False, True])
def test_precancelled_request_does_not_use_primary_or_backup(exchange, stream):
    state, attempts, _, factory, _ = exchange
    state["backup"] = True
    cancellation_service.request_cancellation("retry-policy-test")
    assert consume(factory(stream)) == ([] if stream else "")
    assert not attempts


@pytest.mark.parametrize("stream", [False, True])
def test_configured_backup_bypasses_primary_retry_wait(exchange, stream):
    state, attempts, responses, factory, wait = exchange
    state.update(status=503, backup=True)
    result = consume(factory(stream))
    if stream:
        assert result[0]["token"] == "backup"
    else:
        assert result == "backup"
    assert len(attempts) == 2
    assert attempts[0].startswith("/primary/") and attempts[1].startswith("/backup/")
    assert all(response.closed for response in responses)
    wait.assert_not_called()


def test_invalid_envelope_error_does_not_embed_response_body(exchange, caplog):
    state, attempts, _, factory, _ = exchange
    state["body"] = {"error": "synthetic-private-response"}
    with pytest.raises(InvalidLlmResponseError) as error:
        consume(factory())
    assert "synthetic-private-response" not in str(error.value)
    assert "synthetic-private-response" not in caplog.text
    assert len(attempts) == 1
