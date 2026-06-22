# Tests/llmapis/test_llm_api_failover.py

"""
Unit tests for the endpoint failover behaviour in LlmApiService.

Covers:
- Non-streaming and streaming failover paths
- Multi-hop chains (primary -> backup -> second backup)
- Cycle detection (direct, self-loop, deep loop)
- Absence of a backup preserves original retry behaviour
- suppress_retries is threaded into handler construction when a backup exists
- Visited set threads through the chain
- is_busy_flag and close() lifecycle across failovers
- Logging output on each hop
"""

import json
import socket
from unittest.mock import MagicMock, mock_open, patch

import pytest
import requests

from Middleware.llmapis.handlers.base.base_llm_api_handler import LlmApiHandler
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

SECOND_BACKUP_CONFIG = {
    "endpoint": "http://backup2:1234",
    "apiKey": "backup2_key",
    "modelNameToSendToAPI": "backup2-model",
    "apiTypeConfigFileName": "openAIChatCompletion",
    "dontIncludeModel": False,
}

NO_BACKUP_CONFIG = {
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


def _make_config_resolver(configs_by_name):
    """Returns a side_effect function for get_endpoint_config keyed by endpoint name."""

    def _resolver(name):
        if name not in configs_by_name:
            raise FileNotFoundError(f"Missing mock config for '{name}'")
        return configs_by_name[name]

    return _resolver


@pytest.fixture
def base_mocks(mocker):
    """
    Common mocks: API type, preset path, file existence, preset file open, and
    the handler factory patch so we don't actually instantiate concrete handlers.
    """
    mocker.patch("Middleware.llmapis.llm_api.get_api_type_config", return_value=MOCK_API_TYPE_CONFIG)
    mocker.patch("Middleware.llmapis.llm_api.get_openai_preset_path", return_value="/fake/preset.json")
    # These preset names are folder presets, not endpoints carrying a presetSamplers
    # block, so the endpoint probe returns None and resolution falls to the folder file.
    mocker.patch("Middleware.llmapis.llm_api.try_get_endpoint_config", return_value=None)
    mocker.patch("os.path.exists", return_value=True)
    mocker.patch("builtins.open", mock_open(read_data=json.dumps(MOCK_PRESET)))


@pytest.fixture
def single_chain(mocker, base_mocks):
    """Primary -> Backup. Handler factory is patched."""
    mocker.patch(
        "Middleware.llmapis.llm_api.get_endpoint_config",
        side_effect=_make_config_resolver({
            "PRIMARY": PRIMARY_CONFIG,
            "BACKUP": BACKUP_CONFIG,
        }),
    )
    mocker.patch("Middleware.llmapis.llm_api.LlmApiService.create_api_handler")


@pytest.fixture
def three_chain(mocker, base_mocks):
    """Primary -> Backup -> SecondBackup."""
    primary = {**PRIMARY_CONFIG, "backupEndpointName": "BACKUP"}
    backup = {**BACKUP_CONFIG, "backupEndpointName": "BACKUP2"}
    second = {**SECOND_BACKUP_CONFIG}
    mocker.patch(
        "Middleware.llmapis.llm_api.get_endpoint_config",
        side_effect=_make_config_resolver({
            "PRIMARY": primary,
            "BACKUP": backup,
            "BACKUP2": second,
        }),
    )
    mocker.patch("Middleware.llmapis.llm_api.LlmApiService.create_api_handler")


@pytest.fixture
def no_backup(mocker, base_mocks):
    """Endpoint with no backupEndpointName."""
    mocker.patch(
        "Middleware.llmapis.llm_api.get_endpoint_config",
        side_effect=_make_config_resolver({"PLAIN": NO_BACKUP_CONFIG}),
    )
    mocker.patch("Middleware.llmapis.llm_api.LlmApiService.create_api_handler")


@pytest.fixture
def direct_cycle(mocker, base_mocks):
    """A -> B -> A (cycle)."""
    a = {**PRIMARY_CONFIG, "backupEndpointName": "B"}
    b = {**BACKUP_CONFIG, "backupEndpointName": "A"}
    mocker.patch(
        "Middleware.llmapis.llm_api.get_endpoint_config",
        side_effect=_make_config_resolver({"A": a, "B": b}),
    )
    mocker.patch("Middleware.llmapis.llm_api.LlmApiService.create_api_handler")


@pytest.fixture
def self_cycle(mocker, base_mocks):
    """A -> A (self-loop)."""
    a = {**PRIMARY_CONFIG, "backupEndpointName": "A"}
    mocker.patch(
        "Middleware.llmapis.llm_api.get_endpoint_config",
        side_effect=_make_config_resolver({"A": a}),
    )
    mocker.patch("Middleware.llmapis.llm_api.LlmApiService.create_api_handler")


# ----------------------------------------------------------------------------
# Construction & configuration
# ----------------------------------------------------------------------------

class TestFailoverConstruction:
    def test_has_backup_true_when_configured(self, single_chain):
        service = LlmApiService(endpoint="PRIMARY", presetname="p", max_tokens=128)
        assert service._has_backup is True
        assert service._backup_endpoint_name == "BACKUP"

    def test_has_backup_false_when_absent(self, no_backup):
        service = LlmApiService(endpoint="PLAIN", presetname="p", max_tokens=128)
        assert service._has_backup is False
        assert service._backup_endpoint_name is None

    def test_empty_string_backup_treated_as_no_backup(self, mocker, base_mocks):
        cfg = {**NO_BACKUP_CONFIG, "backupEndpointName": ""}
        mocker.patch(
            "Middleware.llmapis.llm_api.get_endpoint_config",
            side_effect=_make_config_resolver({"X": cfg}),
        )
        mocker.patch("Middleware.llmapis.llm_api.LlmApiService.create_api_handler")

        service = LlmApiService(endpoint="X", presetname="p", max_tokens=128)
        assert service._has_backup is False
        assert service._backup_endpoint_name is None

    def test_null_backup_treated_as_no_backup(self, mocker, base_mocks):
        cfg = {**NO_BACKUP_CONFIG, "backupEndpointName": None}
        mocker.patch(
            "Middleware.llmapis.llm_api.get_endpoint_config",
            side_effect=_make_config_resolver({"X": cfg}),
        )
        mocker.patch("Middleware.llmapis.llm_api.LlmApiService.create_api_handler")

        service = LlmApiService(endpoint="X", presetname="p", max_tokens=128)
        assert service._has_backup is False

    def test_visited_set_starts_with_self(self, no_backup):
        service = LlmApiService(endpoint="PLAIN", presetname="p", max_tokens=128)
        assert service._visited_endpoints == {"PLAIN"}

    def test_visited_set_preserves_caller_set(self, single_chain):
        service = LlmApiService(
            endpoint="BACKUP", presetname="p", max_tokens=128,
            _visited_endpoints={"PRIMARY"},
        )
        assert service._visited_endpoints == {"PRIMARY", "BACKUP"}

    def test_visited_set_is_copied_not_shared(self, single_chain):
        external = {"PRIMARY"}
        service = LlmApiService(
            endpoint="BACKUP", presetname="p", max_tokens=128,
            _visited_endpoints=external,
        )
        assert service._visited_endpoints is not external
        assert external == {"PRIMARY"}


# ----------------------------------------------------------------------------
# backupPresetName resolution
# ----------------------------------------------------------------------------

class TestBackupPresetName:
    def test_backup_preset_name_none_by_default(self, single_chain):
        service = LlmApiService(endpoint="PRIMARY", presetname="primary_preset", max_tokens=128)
        assert service._backup_preset_name is None

    def test_backup_inherits_primary_preset_name_by_default(self, single_chain):
        """With no backupPresetName, the backup loads the originating preset name."""
        service = LlmApiService(endpoint="PRIMARY", presetname="primary_preset", max_tokens=128)
        backup = service._build_backup_service()
        assert backup._endpoint_name == "BACKUP"
        assert backup._presetname == "primary_preset"

    def test_backup_uses_backup_preset_name_when_set(self, mocker, base_mocks):
        """A configured backupPresetName overrides the inherited preset name so a
        heterogeneous backup can point at a preset that exists for its own API type."""
        primary = {**PRIMARY_CONFIG, "backupPresetName": "claude_preset"}
        mocker.patch(
            "Middleware.llmapis.llm_api.get_endpoint_config",
            side_effect=_make_config_resolver({"PRIMARY": primary, "BACKUP": BACKUP_CONFIG}),
        )
        mocker.patch("Middleware.llmapis.llm_api.LlmApiService.create_api_handler")

        service = LlmApiService(endpoint="PRIMARY", presetname="primary_preset", max_tokens=128)
        assert service._backup_preset_name == "claude_preset"

        backup = service._build_backup_service()
        assert backup._presetname == "claude_preset"

    def test_empty_backup_preset_name_falls_back_to_primary(self, mocker, base_mocks):
        primary = {**PRIMARY_CONFIG, "backupPresetName": ""}
        mocker.patch(
            "Middleware.llmapis.llm_api.get_endpoint_config",
            side_effect=_make_config_resolver({"PRIMARY": primary, "BACKUP": BACKUP_CONFIG}),
        )
        mocker.patch("Middleware.llmapis.llm_api.LlmApiService.create_api_handler")

        service = LlmApiService(endpoint="PRIMARY", presetname="primary_preset", max_tokens=128)
        assert service._backup_preset_name is None

        backup = service._build_backup_service()
        assert backup._presetname == "primary_preset"


# ----------------------------------------------------------------------------
# Failover egress guard (safe-by-default: block off-machine prompt egress)
# ----------------------------------------------------------------------------

class TestFailoverEgressGuard:
    def _service(self, mocker, backup_cfg):
        mocker.patch(
            "Middleware.llmapis.llm_api.get_endpoint_config",
            side_effect=_make_config_resolver({"PRIMARY": PRIMARY_CONFIG, "BACKUP": backup_cfg}),
        )
        mocker.patch("Middleware.llmapis.llm_api.LlmApiService.create_api_handler")
        return LlmApiService(endpoint="PRIMARY", presetname="p", max_tokens=128)

    # 8.8.8.8 (Google public DNS) is used only as a known globally-routable IP. The
    # RFC-5737 doc ranges can't be used here: Python 3.13's ipaddress.is_private treats
    # them as not-globally-reachable, so they'd classify as 'local'.
    def test_public_ip_backup_blocked_without_flag(self, mocker, base_mocks):
        service = self._service(mocker, {**BACKUP_CONFIG, "endpoint": "http://8.8.8.8:443"})
        with pytest.raises(RuntimeError, match="off-machine"):
            service._build_backup_service()

    def test_public_ip_backup_allowed_with_flag(self, mocker, base_mocks):
        service = self._service(
            mocker,
            {**BACKUP_CONFIG, "endpoint": "http://8.8.8.8:443", "allowRemoteBackup": True},
        )
        backup = service._build_backup_service()
        assert backup._endpoint_name == "BACKUP"

    def test_private_ip_backup_allowed_silently(self, mocker, base_mocks, caplog):
        service = self._service(mocker, {**BACKUP_CONFIG, "endpoint": "http://192.168.1.50:1234"})
        with caplog.at_level("WARNING", logger="Middleware.llmapis.llm_api"):
            backup = service._build_backup_service()
        assert backup._endpoint_name == "BACKUP"
        assert not any("egress" in r.getMessage().lower() for r in caplog.records)

    def test_loopback_backup_allowed_silently(self, mocker, base_mocks, caplog):
        service = self._service(mocker, {**BACKUP_CONFIG, "endpoint": "http://127.0.0.1:1234"})
        with caplog.at_level("WARNING", logger="Middleware.llmapis.llm_api"):
            service._build_backup_service()
        assert not any("egress" in r.getMessage().lower() for r in caplog.records)

    def test_hostname_backup_allowed_but_logged(self, mocker, base_mocks, caplog):
        # An unresolvable hostname cannot be classified, so it is allowed but logged
        # (a transient DNS failure must not block a legitimate failover).
        mocker.patch(
            "Middleware.llmapis.llm_api.socket.getaddrinfo",
            side_effect=socket.gaierror("name resolution failed"),
        )
        service = self._service(mocker, {**BACKUP_CONFIG, "endpoint": "http://cloud-host:443"})
        with caplog.at_level("WARNING", logger="Middleware.llmapis.llm_api"):
            backup = service._build_backup_service()
        assert backup._endpoint_name == "BACKUP"
        assert any("egress" in r.getMessage().lower() for r in caplog.records)

    def test_hostname_resolving_to_public_blocked_without_flag(self, mocker, base_mocks):
        # A hostname that resolves to a public address is off-machine egress, so it is
        # gated by allowRemoteBackup just like a public IP literal.
        mocker.patch(
            "Middleware.llmapis.llm_api.socket.getaddrinfo",
            return_value=[(0, 0, 0, "", ("8.8.8.8", 0))],
        )
        service = self._service(mocker, {**BACKUP_CONFIG, "endpoint": "http://api.example.com:443"})
        with pytest.raises(RuntimeError, match="off-machine"):
            service._build_backup_service()

    def test_hostname_resolving_to_private_allowed_silently(self, mocker, base_mocks, caplog):
        # A hostname that resolves only to a private address keeps the prompt on the LAN.
        mocker.patch(
            "Middleware.llmapis.llm_api.socket.getaddrinfo",
            return_value=[(0, 0, 0, "", ("10.1.2.3", 0))],
        )
        service = self._service(mocker, {**BACKUP_CONFIG, "endpoint": "http://intranet.local:443"})
        with caplog.at_level("WARNING", logger="Middleware.llmapis.llm_api"):
            backup = service._build_backup_service()
        assert backup._endpoint_name == "BACKUP"
        assert not any("egress" in r.getMessage().lower() for r in caplog.records)


# ----------------------------------------------------------------------------
# suppress_retries threading
# ----------------------------------------------------------------------------

class TestSuppressRetriesWiring:
    def test_suppress_retries_passed_true_when_backup_present(self, mocker, base_mocks):
        mocker.patch(
            "Middleware.llmapis.llm_api.get_endpoint_config",
            side_effect=_make_config_resolver({
                "PRIMARY": PRIMARY_CONFIG, "BACKUP": BACKUP_CONFIG,
            }),
        )
        mock_handler_cls = mocker.patch("Middleware.llmapis.llm_api.OpenAiApiHandler")

        LlmApiService(endpoint="PRIMARY", presetname="p", max_tokens=128)

        kwargs = mock_handler_cls.call_args.kwargs
        assert kwargs["suppress_retries"] is True

    def test_suppress_retries_false_when_no_backup(self, mocker, base_mocks):
        mocker.patch(
            "Middleware.llmapis.llm_api.get_endpoint_config",
            side_effect=_make_config_resolver({"PLAIN": NO_BACKUP_CONFIG}),
        )
        mock_handler_cls = mocker.patch("Middleware.llmapis.llm_api.OpenAiApiHandler")

        LlmApiService(endpoint="PLAIN", presetname="p", max_tokens=128)

        kwargs = mock_handler_cls.call_args.kwargs
        assert kwargs["suppress_retries"] is False

    def test_suppress_retries_true_on_middle_of_chain(self, mocker, base_mocks):
        primary = {**PRIMARY_CONFIG, "backupEndpointName": "BACKUP"}
        backup = {**BACKUP_CONFIG, "backupEndpointName": "BACKUP2"}
        second = dict(SECOND_BACKUP_CONFIG)
        mocker.patch(
            "Middleware.llmapis.llm_api.get_endpoint_config",
            side_effect=_make_config_resolver({
                "PRIMARY": primary, "BACKUP": backup, "BACKUP2": second,
            }),
        )
        mock_handler_cls = mocker.patch("Middleware.llmapis.llm_api.OpenAiApiHandler")

        LlmApiService(endpoint="BACKUP", presetname="p", max_tokens=128)

        # BACKUP has its own backup (BACKUP2), so retries should be suppressed here too.
        assert mock_handler_cls.call_args.kwargs["suppress_retries"] is True

    def test_suppress_retries_false_on_tail_of_chain(self, mocker, base_mocks):
        primary = {**PRIMARY_CONFIG, "backupEndpointName": "BACKUP"}
        backup = {**BACKUP_CONFIG, "backupEndpointName": "BACKUP2"}
        second = dict(SECOND_BACKUP_CONFIG)  # No further backup.
        mocker.patch(
            "Middleware.llmapis.llm_api.get_endpoint_config",
            side_effect=_make_config_resolver({
                "PRIMARY": primary, "BACKUP": backup, "BACKUP2": second,
            }),
        )
        mock_handler_cls = mocker.patch("Middleware.llmapis.llm_api.OpenAiApiHandler")

        LlmApiService(endpoint="BACKUP2", presetname="p", max_tokens=128)

        # Tail of the chain: retries remain enabled.
        assert mock_handler_cls.call_args.kwargs["suppress_retries"] is False


# ----------------------------------------------------------------------------
# Non-streaming failover
# ----------------------------------------------------------------------------

class TestNonStreamingFailover:
    def test_primary_success_no_failover(self, single_chain):
        service = LlmApiService(endpoint="PRIMARY", presetname="p", max_tokens=128, stream=False)
        handler = MagicMock()
        handler.handle_non_streaming.return_value = "primary response"
        service._api_handler = handler

        response = service.get_response_from_llm(prompt="hi")

        assert response == "primary response"
        handler.handle_non_streaming.assert_called_once()
        assert service.is_busy() is False

    def test_primary_fails_backup_succeeds(self, single_chain):
        service = LlmApiService(endpoint="PRIMARY", presetname="p", max_tokens=128, stream=False)
        primary_handler = MagicMock()
        primary_handler.handle_non_streaming.side_effect = requests.exceptions.ConnectionError("boom")
        service._api_handler = primary_handler

        backup_service = MagicMock(spec=LlmApiService)
        backup_service.get_response_from_llm.return_value = "backup response"
        with patch.object(LlmApiService, "_build_backup_service", return_value=backup_service):
            response = service.get_response_from_llm(prompt="hi")

        assert response == "backup response"
        backup_service.get_response_from_llm.assert_called_once()

    def test_failover_triggered_on_any_exception_type(self, single_chain):
        for exc in [
            requests.exceptions.ConnectionError("conn"),
            requests.exceptions.Timeout("timeout"),
            ValueError("bad"),
            RuntimeError("rt"),
            OSError("os"),
        ]:
            service = LlmApiService(endpoint="PRIMARY", presetname="p", max_tokens=128, stream=False)
            primary_handler = MagicMock()
            primary_handler.handle_non_streaming.side_effect = exc
            service._api_handler = primary_handler

            backup_service = MagicMock(spec=LlmApiService)
            backup_service.get_response_from_llm.return_value = "ok"
            with patch.object(LlmApiService, "_build_backup_service", return_value=backup_service):
                assert service.get_response_from_llm(prompt="hi") == "ok", f"exc={type(exc).__name__}"

    def test_no_backup_exception_propagates(self, no_backup):
        service = LlmApiService(endpoint="PLAIN", presetname="p", max_tokens=128, stream=False)
        handler = MagicMock()
        handler.handle_non_streaming.side_effect = requests.exceptions.ConnectionError("down")
        service._api_handler = handler

        with pytest.raises(requests.exceptions.ConnectionError, match="down"):
            service.get_response_from_llm(prompt="hi")

        handler.close.assert_called_once()
        assert service.is_busy() is False

    def test_failover_closes_primary_handler_before_delegating(self, single_chain):
        service = LlmApiService(endpoint="PRIMARY", presetname="p", max_tokens=128, stream=False)
        primary_handler = MagicMock()
        primary_handler.handle_non_streaming.side_effect = ValueError("boom")
        service._api_handler = primary_handler

        backup_service = MagicMock(spec=LlmApiService)
        backup_service.get_response_from_llm.return_value = "ok"
        with patch.object(LlmApiService, "_build_backup_service", return_value=backup_service):
            service.get_response_from_llm(prompt="hi")

        primary_handler.close.assert_called_once()

    def test_failover_passes_original_conversation_not_mutated_copy(self, single_chain):
        service = LlmApiService(endpoint="PRIMARY", presetname="p", max_tokens=128, stream=False)
        primary_handler = MagicMock()
        primary_handler.handle_non_streaming.side_effect = ValueError("boom")
        service._api_handler = primary_handler

        original_conversation = [{"role": "user", "content": "hi", "images": ["b64"]}]
        backup_service = MagicMock(spec=LlmApiService)
        backup_service.get_response_from_llm.return_value = "ok"
        with patch.object(LlmApiService, "_build_backup_service", return_value=backup_service):
            service.get_response_from_llm(conversation=original_conversation, llm_takes_images=True)

        delegated_conversation = backup_service.get_response_from_llm.call_args.kwargs["conversation"]
        # The backup gets the unmodified original conversation; it will apply its own endpoint config.
        assert delegated_conversation is original_conversation
        assert "images" in delegated_conversation[0]

    def test_delegate_kwargs_forwarded(self, single_chain):
        service = LlmApiService(endpoint="PRIMARY", presetname="p", max_tokens=128, stream=False)
        primary_handler = MagicMock()
        primary_handler.handle_non_streaming.side_effect = ValueError("x")
        service._api_handler = primary_handler

        backup_service = MagicMock(spec=LlmApiService)
        backup_service.get_response_from_llm.return_value = "ok"
        tools = [{"type": "function", "function": {"name": "t"}}]
        tool_choice = "auto"
        with patch.object(LlmApiService, "_build_backup_service", return_value=backup_service):
            service.get_response_from_llm(
                system_prompt="sys", prompt="hi",
                request_id="rid-1", tools=tools, tool_choice=tool_choice,
            )

        call_kwargs = backup_service.get_response_from_llm.call_args.kwargs
        assert call_kwargs["system_prompt"] == "sys"
        assert call_kwargs["prompt"] == "hi"
        assert call_kwargs["request_id"] == "rid-1"
        assert call_kwargs["tools"] is tools
        assert call_kwargs["tool_choice"] == "auto"


# ----------------------------------------------------------------------------
# Streaming failover
# ----------------------------------------------------------------------------

class TestStreamingFailover:
    def test_primary_stream_success_no_failover(self, single_chain):
        service = LlmApiService(endpoint="PRIMARY", presetname="p", max_tokens=128, stream=True)
        def gen():
            yield {"token": "a"}
            yield {"token": "b"}
        primary_handler = MagicMock()
        primary_handler.handle_streaming.return_value = gen()
        service._api_handler = primary_handler

        result = list(service.get_response_from_llm(prompt="hi"))

        assert result == [{"token": "a"}, {"token": "b"}]
        primary_handler.close.assert_called_once()

    def test_stream_failover_before_first_token(self, single_chain):
        service = LlmApiService(endpoint="PRIMARY", presetname="p", max_tokens=128, stream=True)

        def failing_gen():
            raise requests.exceptions.ConnectionError("cannot reach primary")
            yield  # pragma: no cover - unreachable, keeps this a generator

        primary_handler = MagicMock()
        primary_handler.handle_streaming.return_value = failing_gen()
        service._api_handler = primary_handler

        def backup_gen():
            yield {"token": "from"}
            yield {"token": " backup"}

        backup_service = MagicMock(spec=LlmApiService)
        backup_service.get_response_from_llm.return_value = backup_gen()
        with patch.object(LlmApiService, "_build_backup_service", return_value=backup_service):
            result = list(service.get_response_from_llm(prompt="hi"))

        assert result == [{"token": "from"}, {"token": " backup"}]
        backup_service.get_response_from_llm.assert_called_once()

    def test_stream_failure_after_first_token_reraises(self, single_chain):
        service = LlmApiService(endpoint="PRIMARY", presetname="p", max_tokens=128, stream=True)

        def partial_gen():
            yield {"token": "partial"}
            raise requests.exceptions.ConnectionError("dropped mid-stream")

        primary_handler = MagicMock()
        primary_handler.handle_streaming.return_value = partial_gen()
        service._api_handler = primary_handler

        backup_service = MagicMock(spec=LlmApiService)
        backup_service.get_response_from_llm.return_value = iter([{"token": "should not be called"}])

        with patch.object(LlmApiService, "_build_backup_service", return_value=backup_service):
            gen = service.get_response_from_llm(prompt="hi")
            first = next(gen)
            assert first == {"token": "partial"}
            with pytest.raises(requests.exceptions.ConnectionError, match="dropped mid-stream"):
                next(gen)

        backup_service.get_response_from_llm.assert_not_called()

    def test_stream_failure_no_backup_propagates(self, no_backup):
        service = LlmApiService(endpoint="PLAIN", presetname="p", max_tokens=128, stream=True)

        def failing_gen():
            raise ValueError("nope")
            yield  # pragma: no cover

        primary_handler = MagicMock()
        primary_handler.handle_streaming.return_value = failing_gen()
        service._api_handler = primary_handler

        with pytest.raises(ValueError, match="nope"):
            list(service.get_response_from_llm(prompt="hi"))

        primary_handler.close.assert_called_once()

    def test_stream_empty_response_no_failover(self, single_chain):
        """If the primary yields nothing and exits cleanly, no failover; no error."""
        service = LlmApiService(endpoint="PRIMARY", presetname="p", max_tokens=128, stream=True)

        def empty_gen():
            return
            yield  # pragma: no cover

        primary_handler = MagicMock()
        primary_handler.handle_streaming.return_value = empty_gen()
        service._api_handler = primary_handler

        backup_service = MagicMock(spec=LlmApiService)
        with patch.object(LlmApiService, "_build_backup_service", return_value=backup_service):
            result = list(service.get_response_from_llm(prompt="hi"))

        assert result == []
        backup_service.get_response_from_llm.assert_not_called()


# ----------------------------------------------------------------------------
# Multi-hop chains
# ----------------------------------------------------------------------------

class TestChainedFailover:
    def _make_failing_service(self, endpoint_name, exc):
        """Helper: returns an LlmApiService whose handler raises on call."""
        service = LlmApiService(endpoint=endpoint_name, presetname="p", max_tokens=128, stream=False)
        handler = MagicMock()
        handler.handle_non_streaming.side_effect = exc
        service._api_handler = handler
        return service

    def test_three_hop_chain_third_succeeds(self, three_chain):
        """A fails, B fails, C succeeds. Exercises real nested LlmApiService
        instantiation (not mocked _build_backup_service)."""
        call_sequence = []

        def make_handler(name):
            h = MagicMock()

            def side_effect(**kw):
                call_sequence.append(name)
                if name in ("PRIMARY", "BACKUP"):
                    raise requests.exceptions.ConnectionError(f"{name} down")
                return f"{name} ok"

            h.handle_non_streaming.side_effect = side_effect
            return h

        created = {}

        def fake_create(self):
            created[self._endpoint_name] = make_handler(self._endpoint_name)
            return created[self._endpoint_name]

        with patch.object(LlmApiService, "create_api_handler", fake_create):
            service = LlmApiService(endpoint="PRIMARY", presetname="p", max_tokens=128, stream=False)
            response = service.get_response_from_llm(prompt="hi")

        assert response == "BACKUP2 ok"
        assert call_sequence == ["PRIMARY", "BACKUP", "BACKUP2"]

    def test_full_chain_failure_raises_final_exception(self, three_chain):
        def make_handler(name):
            h = MagicMock()
            h.handle_non_streaming.side_effect = RuntimeError(f"{name} dead")
            return h

        def fake_create(self):
            return make_handler(self._endpoint_name)

        with patch.object(LlmApiService, "create_api_handler", fake_create):
            service = LlmApiService(endpoint="PRIMARY", presetname="p", max_tokens=128, stream=False)
            with pytest.raises(RuntimeError, match="BACKUP2 dead"):
                service.get_response_from_llm(prompt="hi")

    def test_visited_set_accumulates_through_chain(self, three_chain):
        observed_visited = []

        def fake_create(self):
            observed_visited.append((self._endpoint_name, set(self._visited_endpoints)))
            h = MagicMock()
            if self._endpoint_name == "BACKUP2":
                h.handle_non_streaming.return_value = "ok"
            else:
                h.handle_non_streaming.side_effect = ValueError(f"{self._endpoint_name} fails")
            return h

        with patch.object(LlmApiService, "create_api_handler", fake_create):
            service = LlmApiService(endpoint="PRIMARY", presetname="p", max_tokens=128, stream=False)
            service.get_response_from_llm(prompt="hi")

        # Each subsequent service receives the accumulated visited set.
        names = [name for name, _ in observed_visited]
        visiteds = [v for _, v in observed_visited]
        assert names == ["PRIMARY", "BACKUP", "BACKUP2"]
        assert visiteds[0] == {"PRIMARY"}
        assert visiteds[1] == {"PRIMARY", "BACKUP"}
        assert visiteds[2] == {"PRIMARY", "BACKUP", "BACKUP2"}

    def test_stream_failover_across_two_hops(self, three_chain):
        """Streaming: A fails pre-first-token, B fails pre-first-token, C yields."""
        def fake_create(self):
            h = MagicMock()
            name = self._endpoint_name
            if name in ("PRIMARY", "BACKUP"):
                def failing_gen():
                    raise requests.exceptions.ConnectionError(f"{name} unreachable")
                    yield  # pragma: no cover
                h.handle_streaming.return_value = failing_gen()
            else:
                def ok_gen():
                    yield {"token": "final"}
                h.handle_streaming.return_value = ok_gen()
            return h

        with patch.object(LlmApiService, "create_api_handler", fake_create):
            service = LlmApiService(endpoint="PRIMARY", presetname="p", max_tokens=128, stream=True)
            result = list(service.get_response_from_llm(prompt="hi"))

        assert result == [{"token": "final"}]


# ----------------------------------------------------------------------------
# Cycle detection
# ----------------------------------------------------------------------------

class TestCycleDetection:
    def test_direct_cycle_raises(self, direct_cycle):
        """A -> B -> A: once A fails, B runs, B tries A, cycle is detected."""
        def fake_create(self):
            h = MagicMock()
            h.handle_non_streaming.side_effect = ValueError(f"{self._endpoint_name} fails")
            return h

        with patch.object(LlmApiService, "create_api_handler", fake_create):
            service = LlmApiService(endpoint="A", presetname="p", max_tokens=128, stream=False)
            with pytest.raises(RuntimeError, match="Failover cycle detected"):
                service.get_response_from_llm(prompt="hi")

    def test_self_cycle_raises(self, self_cycle):
        """A -> A: A fails, it tries A again, cycle is detected."""
        def fake_create(self):
            h = MagicMock()
            h.handle_non_streaming.side_effect = ValueError("A fails")
            return h

        with patch.object(LlmApiService, "create_api_handler", fake_create):
            service = LlmApiService(endpoint="A", presetname="p", max_tokens=128, stream=False)
            with pytest.raises(RuntimeError, match="Failover cycle detected"):
                service.get_response_from_llm(prompt="hi")

    def test_cycle_error_mentions_offending_endpoint(self, direct_cycle):
        def fake_create(self):
            h = MagicMock()
            h.handle_non_streaming.side_effect = ValueError("fail")
            return h

        with patch.object(LlmApiService, "create_api_handler", fake_create):
            service = LlmApiService(endpoint="A", presetname="p", max_tokens=128, stream=False)
            with pytest.raises(RuntimeError) as exc_info:
                service.get_response_from_llm(prompt="hi")

            # Cycle error should name at least one endpoint in the chain.
            msg = str(exc_info.value)
            assert "A" in msg
            assert "backupEndpointName" in msg

    def test_build_backup_service_detects_cycle_directly(self, direct_cycle):
        """Exercise _build_backup_service in isolation without running a request."""
        service = LlmApiService(endpoint="A", presetname="p", max_tokens=128, stream=False)
        # Simulate that B is already visited (as if we're already in B's context).
        service._visited_endpoints.add("B")
        service._backup_endpoint_name = "B"
        with pytest.raises(RuntimeError, match="Failover cycle detected"):
            service._build_backup_service()


# ----------------------------------------------------------------------------
# Lifecycle: is_busy_flag and close()
# ----------------------------------------------------------------------------

class TestFailoverLifecycle:
    def test_is_busy_clears_after_successful_failover(self, single_chain):
        service = LlmApiService(endpoint="PRIMARY", presetname="p", max_tokens=128, stream=False)
        primary_handler = MagicMock()
        primary_handler.handle_non_streaming.side_effect = ValueError("boom")
        service._api_handler = primary_handler

        backup_service = MagicMock(spec=LlmApiService)
        backup_service.get_response_from_llm.return_value = "ok"
        with patch.object(LlmApiService, "_build_backup_service", return_value=backup_service):
            service.get_response_from_llm(prompt="hi")

        assert service.is_busy() is False

    def test_is_busy_clears_after_exhausted_chain(self, three_chain):
        def fake_create(self):
            h = MagicMock()
            h.handle_non_streaming.side_effect = ValueError("dead")
            return h

        with patch.object(LlmApiService, "create_api_handler", fake_create):
            service = LlmApiService(endpoint="PRIMARY", presetname="p", max_tokens=128, stream=False)
            with pytest.raises(ValueError):
                service.get_response_from_llm(prompt="hi")
            assert service.is_busy() is False

    def test_primary_handler_close_called_exactly_once_on_failover(self, single_chain):
        service = LlmApiService(endpoint="PRIMARY", presetname="p", max_tokens=128, stream=False)
        primary_handler = MagicMock()
        primary_handler.handle_non_streaming.side_effect = ValueError("x")
        service._api_handler = primary_handler

        backup_service = MagicMock(spec=LlmApiService)
        backup_service.get_response_from_llm.return_value = "ok"
        with patch.object(LlmApiService, "_build_backup_service", return_value=backup_service):
            service.get_response_from_llm(prompt="hi")

        primary_handler.close.assert_called_once()

    def test_stream_failover_closes_primary_handler(self, single_chain):
        service = LlmApiService(endpoint="PRIMARY", presetname="p", max_tokens=128, stream=True)

        def failing_gen():
            raise requests.exceptions.ConnectionError("boom")
            yield  # pragma: no cover

        primary_handler = MagicMock()
        primary_handler.handle_streaming.return_value = failing_gen()
        service._api_handler = primary_handler

        def backup_gen():
            yield {"token": "ok"}

        backup_service = MagicMock(spec=LlmApiService)
        backup_service.get_response_from_llm.return_value = backup_gen()
        with patch.object(LlmApiService, "_build_backup_service", return_value=backup_service):
            list(service.get_response_from_llm(prompt="hi"))

        primary_handler.close.assert_called_once()


# ----------------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------------

class TestFailoverLogging:
    def test_failover_logs_warning_with_endpoint_names(self, single_chain, caplog):
        service = LlmApiService(endpoint="PRIMARY", presetname="p", max_tokens=128, stream=False)
        primary_handler = MagicMock()
        primary_handler.handle_non_streaming.side_effect = requests.exceptions.ConnectionError("gone")
        service._api_handler = primary_handler

        backup_service = MagicMock(spec=LlmApiService)
        backup_service.get_response_from_llm.return_value = "ok"
        with patch.object(LlmApiService, "_build_backup_service", return_value=backup_service):
            with caplog.at_level("WARNING", logger="Middleware.llmapis.llm_api"):
                service.get_response_from_llm(prompt="hi")

        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any("PRIMARY" in r.getMessage() and "BACKUP" in r.getMessage() for r in warnings)
        assert any("ConnectionError" in r.getMessage() for r in warnings)

    def test_each_hop_in_chain_logs_warning(self, three_chain, caplog):
        def fake_create(self):
            h = MagicMock()
            if self._endpoint_name == "BACKUP2":
                h.handle_non_streaming.return_value = "ok"
            else:
                h.handle_non_streaming.side_effect = ValueError(f"{self._endpoint_name} down")
            return h

        with patch.object(LlmApiService, "create_api_handler", fake_create):
            with caplog.at_level("WARNING", logger="Middleware.llmapis.llm_api"):
                service = LlmApiService(endpoint="PRIMARY", presetname="p", max_tokens=128, stream=False)
                service.get_response_from_llm(prompt="hi")

        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        # There should be one warning per hop: PRIMARY->BACKUP and BACKUP->BACKUP2.
        failover_warnings = [r for r in warnings if "Failover:" in r.getMessage()]
        assert len(failover_warnings) == 2
        assert any("PRIMARY" in r.getMessage() and "BACKUP" in r.getMessage() and "BACKUP2" not in r.getMessage()
                   for r in failover_warnings)
        assert any("BACKUP" in r.getMessage() and "BACKUP2" in r.getMessage() for r in failover_warnings)

    def test_stream_post_token_failure_logs_error_cannot_failover(self, single_chain, caplog):
        service = LlmApiService(endpoint="PRIMARY", presetname="p", max_tokens=128, stream=True)

        def partial_gen():
            yield {"token": "partial"}
            raise ValueError("broke")

        primary_handler = MagicMock()
        primary_handler.handle_streaming.return_value = partial_gen()
        service._api_handler = primary_handler

        backup_service = MagicMock(spec=LlmApiService)
        with patch.object(LlmApiService, "_build_backup_service", return_value=backup_service):
            with caplog.at_level("ERROR", logger="Middleware.llmapis.llm_api"):
                with pytest.raises(ValueError):
                    list(service.get_response_from_llm(prompt="hi"))

        errors = [r for r in caplog.records if r.levelname == "ERROR"]
        assert any("after tokens were emitted" in r.getMessage() for r in errors)


# ----------------------------------------------------------------------------
# Base handler suppress_retries wiring
# ----------------------------------------------------------------------------

class _ConcreteHandler(LlmApiHandler):
    def _get_api_endpoint_url(self):
        return "http://x"

    def _prepare_payload(self, conversation, system_prompt, prompt, *, tools=None, tool_choice=None):
        return {}

    def _process_stream_data(self, data_str):
        return {"token": data_str, "finish_reason": None}

    def _parse_non_stream_response(self, response_json):
        return response_json.get("text", "")


class TestBaseHandlerSuppressRetries:
    def test_default_suppress_retries_false(self):
        h = _ConcreteHandler(
            base_url="http://x", api_key="k", gen_input={}, model_name="m",
            headers={}, stream=False, api_type_config={}, endpoint_config={},
            max_tokens=100,
        )
        assert h.suppress_retries is False

    def test_suppress_retries_true_stores_flag(self):
        h = _ConcreteHandler(
            base_url="http://x", api_key="k", gen_input={}, model_name="m",
            headers={}, stream=False, api_type_config={}, endpoint_config={},
            max_tokens=100, suppress_retries=True,
        )
        assert h.suppress_retries is True

    def test_suppress_retries_affects_adapter_retry_total(self):
        h = _ConcreteHandler(
            base_url="http://x", api_key="k", gen_input={}, model_name="m",
            headers={}, stream=False, api_type_config={}, endpoint_config={},
            max_tokens=100, suppress_retries=True,
        )
        adapter = h.session.get_adapter("http://x")
        assert adapter.max_retries.total == 0

    def test_default_adapter_retry_total_is_five(self):
        h = _ConcreteHandler(
            base_url="http://x", api_key="k", gen_input={}, model_name="m",
            headers={}, stream=False, api_type_config={}, endpoint_config={},
            max_tokens=100, suppress_retries=False,
        )
        adapter = h.session.get_adapter("http://x")
        assert adapter.max_retries.total == 5

    @patch("requests.Session.post")
    def test_non_streaming_single_attempt_when_suppress_retries_true(self, mock_post):
        h = _ConcreteHandler(
            base_url="http://x", api_key="k", gen_input={}, model_name="m",
            headers={}, stream=False, api_type_config={}, endpoint_config={},
            max_tokens=100, suppress_retries=True,
        )
        mock_post.side_effect = requests.exceptions.ConnectionError("down")

        with pytest.raises(requests.exceptions.ConnectionError):
            h.handle_non_streaming(prompt="hi")

        assert mock_post.call_count == 1

    @patch("requests.Session.post")
    def test_non_streaming_three_attempts_when_suppress_retries_false(self, mock_post):
        h = _ConcreteHandler(
            base_url="http://x", api_key="k", gen_input={}, model_name="m",
            headers={}, stream=False, api_type_config={}, endpoint_config={},
            max_tokens=100, suppress_retries=False,
        )
        mock_post.side_effect = requests.exceptions.ConnectionError("down")

        with pytest.raises(requests.exceptions.ConnectionError):
            h.handle_non_streaming(prompt="hi")

        assert mock_post.call_count == 3
