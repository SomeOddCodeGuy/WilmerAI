# Tests/llmapis/test_llm_api_concurrency_gate.py

"""
Unit tests for the endpoint-level concurrency gate inside LlmApiService.

When `instance_global_variables.CONCURRENCY_LEVEL == "endpoint"`, the per-instance
semaphore must be held for the duration of the outbound LLM call (covering both
streaming iteration and non-streaming returns), released exactly once on success,
exception, or generator close, and released *before* a failover delegates to a
backup service so the backup's own acquire does not deadlock at limit=1.

When the level is anything else (default "wilmer"), the gate must be a no-op so
the legacy WSGI-level gate remains the sole concurrency control.
"""

import json
import threading
from unittest.mock import MagicMock, mock_open, patch

import pytest

from Middleware.common import instance_global_variables
from Middleware.llmapis.llm_api import LlmApiService


PRIMARY_CONFIG = {
    "endpoint": "http://primary:1234",
    "apiKey": "primary_key",
    "modelNameToSendToAPI": "primary-model",
    "apiTypeConfigFileName": "openAIChatCompletion",
    "dontIncludeModel": False,
    "backupEndpointName": "BACKUP",
}

BACKUP_CONFIG = {
    "endpoint": "http://backup:1234",
    "apiKey": "backup_key",
    "modelNameToSendToAPI": "backup-model",
    "apiTypeConfigFileName": "openAIChatCompletion",
    "dontIncludeModel": False,
}

PLAIN_CONFIG = {
    "endpoint": "http://plain:1234",
    "apiKey": "plain_key",
    "modelNameToSendToAPI": "plain-model",
    "apiTypeConfigFileName": "openAIChatCompletion",
    "dontIncludeModel": False,
}

MOCK_API_TYPE_CONFIG = {
    "type": "openAIChatCompletion",
    "presetType": "OpenAI",
    "streamPropertyName": "stream",
    "maxNewTokensPropertyName": "max_tokens",
}

MOCK_PRESET = {"temperature": 0.7}


def _resolver(configs_by_name):
    def _r(name):
        if name not in configs_by_name:
            raise FileNotFoundError(name)
        return configs_by_name[name]
    return _r


@pytest.fixture
def base_mocks(mocker):
    """Patch config lookups, preset file IO, and the concrete handler factory."""
    mocker.patch("Middleware.llmapis.llm_api.get_api_type_config", return_value=MOCK_API_TYPE_CONFIG)
    mocker.patch("Middleware.llmapis.llm_api.get_openai_preset_path", return_value="/fake/preset.json")
    # Preset names here are folder presets, not endpoints with a presetSamplers block.
    mocker.patch("Middleware.llmapis.llm_api.try_get_endpoint_config", return_value=None)
    mocker.patch("os.path.exists", return_value=True)
    mocker.patch("builtins.open", mock_open(read_data=json.dumps(MOCK_PRESET)))


@pytest.fixture
def single_chain(mocker, base_mocks):
    """Primary -> Backup endpoint chain."""
    mocker.patch(
        "Middleware.llmapis.llm_api.get_endpoint_config",
        side_effect=_resolver({"PRIMARY": PRIMARY_CONFIG, "BACKUP": BACKUP_CONFIG}),
    )
    mocker.patch("Middleware.llmapis.llm_api.OpenAiApiHandler")


@pytest.fixture
def plain_endpoint(mocker, base_mocks):
    """Single endpoint, no backup."""
    mocker.patch(
        "Middleware.llmapis.llm_api.get_endpoint_config",
        side_effect=_resolver({"PLAIN": PLAIN_CONFIG}),
    )
    mocker.patch("Middleware.llmapis.llm_api.OpenAiApiHandler")


@pytest.fixture
def gate_env():
    """
    Provides a controlled (semaphore, level) pair for each test and guarantees
    that the module-level CONCURRENCY_LEVEL and _request_semaphore are restored
    after the test, even on failure. Tests opt in to a level by calling
    `gate_env.set(level, limit)`.
    """

    class _GateEnv:
        def __init__(self):
            self._original_level = instance_global_variables.CONCURRENCY_LEVEL
            self._original_limit = instance_global_variables.CONCURRENCY_LIMIT
            self._original_timeout = instance_global_variables.CONCURRENCY_TIMEOUT
            self._original_sem = instance_global_variables._request_semaphore
            self.semaphore = None

        def set(self, level, limit=1, timeout=5):
            instance_global_variables.CONCURRENCY_LEVEL = level
            instance_global_variables.CONCURRENCY_LIMIT = limit
            instance_global_variables.CONCURRENCY_TIMEOUT = timeout
            if limit > 0:
                self.semaphore = threading.BoundedSemaphore(limit)
                instance_global_variables._request_semaphore = self.semaphore
            else:
                self.semaphore = None
                instance_global_variables._request_semaphore = None

        def restore(self):
            instance_global_variables.CONCURRENCY_LEVEL = self._original_level
            instance_global_variables.CONCURRENCY_LIMIT = self._original_limit
            instance_global_variables.CONCURRENCY_TIMEOUT = self._original_timeout
            instance_global_variables._request_semaphore = self._original_sem

    env = _GateEnv()
    try:
        yield env
    finally:
        env.restore()


# ----------------------------------------------------------------------------
# Wilmer mode: the LLM-call gate is a no-op
# ----------------------------------------------------------------------------

class TestWilmerModeGate:
    def test_non_streaming_does_not_touch_semaphore(self, plain_endpoint, gate_env):
        gate_env.set("wilmer", limit=1)
        sem = gate_env.semaphore
        sem.acquire()  # exhaust — would block any acquire attempt

        service = LlmApiService(endpoint="PLAIN", presetname="p", max_tokens=16, stream=False)
        handler = MagicMock()
        handler.handle_non_streaming.return_value = "ok"
        service._api_handler = handler

        # If wilmer mode tried to acquire, the exhausted semaphore would block
        # until CONCURRENCY_TIMEOUT and raise TimeoutError. Instead the call
        # should return immediately.
        assert service.get_response_from_llm(prompt="hi") == "ok"

        sem.release()

    def test_streaming_does_not_touch_semaphore(self, plain_endpoint, gate_env):
        gate_env.set("wilmer", limit=1)
        sem = gate_env.semaphore
        sem.acquire()  # exhaust

        service = LlmApiService(endpoint="PLAIN", presetname="p", max_tokens=16, stream=True)
        handler = MagicMock()
        handler.handle_streaming.return_value = iter(["a", "b"])
        service._api_handler = handler

        chunks = list(service.get_response_from_llm(prompt="hi"))
        assert chunks == ["a", "b"]

        sem.release()


# ----------------------------------------------------------------------------
# Endpoint mode: the LLM-call gate is held during the outbound call
# ----------------------------------------------------------------------------

class TestEndpointModeNonStreaming:
    def test_gate_held_during_handler_call(self, plain_endpoint, gate_env):
        gate_env.set("endpoint", limit=1)
        sem = gate_env.semaphore

        observed = {"acquired_during_call": None}

        def fake_handle_non_streaming(**kwargs):
            # While the handler is executing the gate must be held.
            observed["acquired_during_call"] = not sem.acquire(blocking=False)
            return "ok"

        service = LlmApiService(endpoint="PLAIN", presetname="p", max_tokens=16, stream=False)
        handler = MagicMock()
        handler.handle_non_streaming.side_effect = fake_handle_non_streaming
        service._api_handler = handler

        result = service.get_response_from_llm(prompt="hi")
        assert result == "ok"
        assert observed["acquired_during_call"] is True
        # Released after return
        assert sem.acquire(blocking=False)
        sem.release()

    def test_gate_released_on_handler_exception_when_no_backup(self, plain_endpoint, gate_env):
        gate_env.set("endpoint", limit=1)
        sem = gate_env.semaphore

        service = LlmApiService(endpoint="PLAIN", presetname="p", max_tokens=16, stream=False)
        handler = MagicMock()
        handler.handle_non_streaming.side_effect = RuntimeError("boom")
        service._api_handler = handler

        with pytest.raises(RuntimeError, match="boom"):
            service.get_response_from_llm(prompt="hi")

        # Gate released so a future caller can proceed
        assert sem.acquire(blocking=False)
        sem.release()

    def test_gate_timeout_raises_timeout_error(self, plain_endpoint, gate_env):
        gate_env.set("endpoint", limit=1, timeout=0.1)
        sem = gate_env.semaphore
        sem.acquire()  # exhaust — caller will time out

        service = LlmApiService(endpoint="PLAIN", presetname="p", max_tokens=16, stream=False)
        handler = MagicMock()
        service._api_handler = handler

        with pytest.raises(TimeoutError, match="LLM call slot"):
            service.get_response_from_llm(prompt="hi")

        # Handler must not have been called — we never got a slot
        handler.handle_non_streaming.assert_not_called()

        sem.release()

    def test_gate_timeout_closes_handler_session(self, plain_endpoint, gate_env):
        """A gate-acquire TimeoutError must still close() the handler so its
        requests.Session (and its pooled keep-alive sockets) is not leaked
        (PASS2-003). The acquire sits outside the inner try, so before the fix the
        inner finally that calls close() never ran on this path."""
        gate_env.set("endpoint", limit=1, timeout=0.1)
        sem = gate_env.semaphore
        sem.acquire()  # exhaust — caller will time out

        service = LlmApiService(endpoint="PLAIN", presetname="p", max_tokens=16, stream=False)
        handler = MagicMock()
        service._api_handler = handler

        with pytest.raises(TimeoutError, match="LLM call slot"):
            service.get_response_from_llm(prompt="hi")

        # Session closed despite never entering the handler call; busy flag cleared.
        handler.close.assert_called_once()
        assert service.is_busy_flag is False

        sem.release()

    def test_failover_releases_gate_before_delegating(self, single_chain, gate_env):
        """Critical: at limit=1, if we held the gate while delegating to the
        backup, the backup's own acquire would block until our timeout. The
        backup must see an immediately-available slot."""
        gate_env.set("endpoint", limit=1)
        sem = gate_env.semaphore

        observed = {"sem_free_when_backup_called": None}

        service = LlmApiService(endpoint="PRIMARY", presetname="p", max_tokens=16, stream=False)
        primary_handler = MagicMock()
        primary_handler.handle_non_streaming.side_effect = ValueError("primary down")
        service._api_handler = primary_handler

        backup_service = MagicMock(spec=LlmApiService)

        def backup_call(**kwargs):
            # Confirm the parent released its slot before delegating.
            observed["sem_free_when_backup_called"] = sem.acquire(blocking=False)
            if observed["sem_free_when_backup_called"]:
                sem.release()
            return "from backup"

        backup_service.get_response_from_llm.side_effect = backup_call

        with patch.object(LlmApiService, "_build_backup_service", return_value=backup_service):
            assert service.get_response_from_llm(prompt="hi") == "from backup"

        assert observed["sem_free_when_backup_called"] is True
        # And after the whole call, the gate is fully released
        assert sem.acquire(blocking=False)
        sem.release()


class TestEndpointModeStreaming:
    def test_gate_held_across_all_streamed_chunks(self, plain_endpoint, gate_env):
        gate_env.set("endpoint", limit=1)
        sem = gate_env.semaphore

        service = LlmApiService(endpoint="PLAIN", presetname="p", max_tokens=16, stream=True)
        handler = MagicMock()
        handler.handle_streaming.return_value = iter(["c1", "c2", "c3"])
        service._api_handler = handler

        gen = service.get_response_from_llm(prompt="hi")

        # Before iteration starts, semaphore should still be free — the gate
        # is acquired inside the generator on first next().
        assert sem.acquire(blocking=False)
        sem.release()

        first = next(gen)
        assert first == "c1"
        # Now the gate is held
        assert not sem.acquire(blocking=False)

        # Consume the rest
        assert next(gen) == "c2"
        assert not sem.acquire(blocking=False)
        assert next(gen) == "c3"
        # Generator is not exhausted until StopIteration; gate still held
        assert not sem.acquire(blocking=False)

        # Drain to completion
        with pytest.raises(StopIteration):
            next(gen)

        # Released after exhaustion
        assert sem.acquire(blocking=False)
        sem.release()

    def test_streaming_gate_timeout_raises_timeout_error(self, plain_endpoint, gate_env):
        """At limit=1 with the only slot exhausted, the streaming path must raise
        TimeoutError on the first next() (the gate is acquired inside the generator),
        never start the backend stream, and leak no permit."""
        gate_env.set("endpoint", limit=1, timeout=0.1)
        sem = gate_env.semaphore
        sem.acquire()  # exhaust — the streaming caller will time out

        service = LlmApiService(endpoint="PLAIN", presetname="p", max_tokens=16, stream=True)
        handler = MagicMock()
        handler.handle_streaming.return_value = iter(["c1", "c2"])
        service._api_handler = handler

        gen = service.get_response_from_llm(prompt="hi")

        with pytest.raises(TimeoutError, match="LLM call slot"):
            next(gen)

        # The backend stream must never have started — we never got a slot.
        handler.handle_streaming.assert_not_called()

        # Release the originally-held slot; the gate must now be fully free,
        # proving the timed-out attempt leaked no permit.
        sem.release()
        assert sem.acquire(blocking=False)
        sem.release()

    def test_gate_released_on_generator_close(self, plain_endpoint, gate_env):
        gate_env.set("endpoint", limit=1)
        sem = gate_env.semaphore

        def producer():
            yield "x"
            yield "y"
            yield "z"

        service = LlmApiService(endpoint="PLAIN", presetname="p", max_tokens=16, stream=True)
        handler = MagicMock()
        handler.handle_streaming.return_value = producer()
        service._api_handler = handler

        gen = service.get_response_from_llm(prompt="hi")
        assert next(gen) == "x"
        assert not sem.acquire(blocking=False)

        gen.close()  # caller abandons stream

        assert sem.acquire(blocking=False)
        sem.release()

    def test_gate_released_on_exception_mid_stream(self, plain_endpoint, gate_env):
        gate_env.set("endpoint", limit=1)
        sem = gate_env.semaphore

        def exploding():
            yield "ok"
            raise RuntimeError("mid-stream")

        service = LlmApiService(endpoint="PLAIN", presetname="p", max_tokens=16, stream=True)
        handler = MagicMock()
        handler.handle_streaming.return_value = exploding()
        service._api_handler = handler

        gen = service.get_response_from_llm(prompt="hi")
        assert next(gen) == "ok"
        with pytest.raises(RuntimeError, match="mid-stream"):
            next(gen)

        assert sem.acquire(blocking=False)
        sem.release()

    def test_streaming_failover_releases_gate_before_delegating(self, single_chain, gate_env):
        gate_env.set("endpoint", limit=1)
        sem = gate_env.semaphore

        observed = {"sem_free_when_backup_called": None}

        def failing_gen():
            if False:
                yield  # pragma: no cover  — make this a generator
            raise ValueError("primary down before first token")

        service = LlmApiService(endpoint="PRIMARY", presetname="p", max_tokens=16, stream=True)
        primary_handler = MagicMock()
        primary_handler.handle_streaming.return_value = failing_gen()
        service._api_handler = primary_handler

        backup_service = MagicMock(spec=LlmApiService)

        def backup_call(**kwargs):
            observed["sem_free_when_backup_called"] = sem.acquire(blocking=False)
            if observed["sem_free_when_backup_called"]:
                sem.release()
            return iter(["backup-chunk"])

        backup_service.get_response_from_llm.side_effect = backup_call

        with patch.object(LlmApiService, "_build_backup_service", return_value=backup_service):
            chunks = list(service.get_response_from_llm(prompt="hi"))

        assert chunks == ["backup-chunk"]
        assert observed["sem_free_when_backup_called"] is True
        assert sem.acquire(blocking=False)
        sem.release()


# ----------------------------------------------------------------------------
# Cross-mode: the same Wilmer instance can run many concurrent requests in
# endpoint mode, with the LLM calls themselves serialized.
# ----------------------------------------------------------------------------

class TestEndpointModeConcurrency:
    def test_two_concurrent_callers_serialize_at_llm_call(self, plain_endpoint, gate_env):
        """Caller A enters the handler; caller B blocks at acquire until A returns."""
        gate_env.set("endpoint", limit=1, timeout=5)
        sem = gate_env.semaphore

        a_entered_handler = threading.Event()
        a_may_return = threading.Event()
        b_entered_handler = threading.Event()

        def a_handler(**kwargs):
            a_entered_handler.set()
            a_may_return.wait(timeout=5)
            return "A done"

        def b_handler(**kwargs):
            b_entered_handler.set()
            return "B done"

        service_a = LlmApiService(endpoint="PLAIN", presetname="p", max_tokens=16, stream=False)
        ha = MagicMock(); ha.handle_non_streaming.side_effect = a_handler
        service_a._api_handler = ha

        service_b = LlmApiService(endpoint="PLAIN", presetname="p", max_tokens=16, stream=False)
        hb = MagicMock(); hb.handle_non_streaming.side_effect = b_handler
        service_b._api_handler = hb

        results = {}

        def run_a():
            results["a"] = service_a.get_response_from_llm(prompt="a")

        def run_b():
            results["b"] = service_b.get_response_from_llm(prompt="b")

        ta = threading.Thread(target=run_a)
        tb = threading.Thread(target=run_b)
        ta.start()
        assert a_entered_handler.wait(timeout=5)
        # A is inside the handler holding the gate. Start B; it must NOT enter
        # the handler until A releases.
        tb.start()
        assert not b_entered_handler.wait(timeout=0.3)

        # Let A finish, B should now proceed
        a_may_return.set()
        ta.join(timeout=5)
        assert b_entered_handler.wait(timeout=5)
        tb.join(timeout=5)

        assert results == {"a": "A done", "b": "B done"}
