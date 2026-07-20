# tests/workflows/tools/test_offline_researcher_api_tool.py

from unittest.mock import Mock

import pytest
import requests

from Middleware.workflows.tools.offline_researcher_api_tool import (
    NO_INFORMATION_FOUND_MESSAGE,
    OfflineResearcherApiClient,
)


@pytest.fixture
def mock_get_user_config(mocker):
    return mocker.patch(
        'Middleware.workflows.tools.offline_researcher_api_tool.get_user_config'
    )


@pytest.fixture
def mock_requests_post(mocker):
    return mocker.patch('requests.post')


# --- Initialization ---

def test_init_with_full_config(mock_get_user_config):
    mock_get_user_config.return_value = {
        'useOfflineResearcherApi': True,
        'offlineResearcherApiHost': 'testhost.local',
        'offlineResearcherApiPort': 1234,
    }
    client = OfflineResearcherApiClient()
    assert client.use_offline_researcher_api is True
    assert client.base_url == "http://testhost.local:1234"


def test_init_api_disabled_in_config(mock_get_user_config):
    mock_get_user_config.return_value = {'useOfflineResearcherApi': False}
    client = OfflineResearcherApiClient(activate=True)
    assert client.use_offline_researcher_api is False


def test_init_with_empty_config_uses_defaults(mock_get_user_config):
    mock_get_user_config.return_value = {}
    client = OfflineResearcherApiClient()
    assert client.use_offline_researcher_api is False
    assert client.base_url == "http://127.0.0.1:8890"


def test_init_with_empty_config_uses_constructor_args(mock_get_user_config):
    mock_get_user_config.return_value = {}
    client = OfflineResearcherApiClient(activate=True, baseurl='custom.host', port=4242)
    assert client.use_offline_researcher_api is True
    assert client.base_url == "http://custom.host:4242"


# --- search() ---

def test_search_short_circuits_when_disabled(mock_get_user_config, mock_requests_post):
    mock_get_user_config.return_value = {'useOfflineResearcherApi': False}
    client = OfflineResearcherApiClient()

    result = client.search("anything", mode="quick")

    mock_requests_post.assert_not_called()
    assert result["status"] == "error"
    assert result["reason"] == "offline_researcher_disabled"
    assert result["answer"] is None
    assert result["no_information_found"] is False
    assert result["sources"] == []


def test_search_success_quick_omits_max_iterations(mock_get_user_config, mock_requests_post):
    mock_get_user_config.return_value = {'useOfflineResearcherApi': True}
    body = {
        "status": "answered",
        "answer": "It's a decorator.",
        "no_information_found": False,
        "sources": [{"book": "wikipedia_en", "title": "Decorator"}],
    }
    mock_requests_post.return_value = Mock(status_code=200, json=lambda: body)

    client = OfflineResearcherApiClient()
    result = client.search("what is a decorator?", mode="quick", timeout_seconds=240)

    mock_requests_post.assert_called_once_with(
        "http://127.0.0.1:8890/search",
        json={"query": "what is a decorator?", "mode": "quick"},
        timeout=(5, 240),
    )
    assert result == body


def test_search_passes_max_iterations_when_provided(mock_get_user_config, mock_requests_post):
    mock_get_user_config.return_value = {'useOfflineResearcherApi': True}
    mock_requests_post.return_value = Mock(status_code=200, json=lambda: {"status": "answered"})

    client = OfflineResearcherApiClient()
    client.search("deep dive on X", mode="deep", max_iterations=5, timeout_seconds=900)

    mock_requests_post.assert_called_once_with(
        "http://127.0.0.1:8890/search",
        json={"query": "deep dive on X", "mode": "deep", "max_iterations": 5},
        timeout=(5, 900),
    )


def test_search_short_timeout_clamps_connect_phase(mock_get_user_config, mock_requests_post):
    # The connect timeout is min(5, timeout_seconds); with timeout_seconds=2 the
    # connect phase is clamped down to 2 rather than the 5-second default.
    mock_get_user_config.return_value = {'useOfflineResearcherApi': True}
    mock_requests_post.return_value = Mock(status_code=200, json=lambda: {"status": "answered"})

    client = OfflineResearcherApiClient()
    client.search("anything", mode="quick", timeout_seconds=2)

    mock_requests_post.assert_called_once_with(
        "http://127.0.0.1:8890/search",
        json={"query": "anything", "mode": "quick"},
        timeout=(2, 2),
    )


def test_search_without_timeout_passes_none(mock_get_user_config, mock_requests_post):
    # When no timeout_seconds is given, no timeout tuple is synthesized at all.
    mock_get_user_config.return_value = {'useOfflineResearcherApi': True}
    mock_requests_post.return_value = Mock(status_code=200, json=lambda: {"status": "answered"})

    client = OfflineResearcherApiClient()
    client.search("anything", mode="quick")

    mock_requests_post.assert_called_once_with(
        "http://127.0.0.1:8890/search",
        json={"query": "anything", "mode": "quick"},
        timeout=None,
    )


def test_search_handles_timeout(mock_get_user_config, mock_requests_post):
    mock_get_user_config.return_value = {'useOfflineResearcherApi': True}
    mock_requests_post.side_effect = requests.exceptions.Timeout("slow")

    client = OfflineResearcherApiClient()
    result = client.search("anything", mode="quick", timeout_seconds=5)

    assert result["status"] == "error"
    assert result["reason"] == "timeout"


def test_search_handles_connection_error(mock_get_user_config, mock_requests_post):
    mock_get_user_config.return_value = {'useOfflineResearcherApi': True}
    mock_requests_post.side_effect = requests.exceptions.ConnectionError("no route")

    client = OfflineResearcherApiClient()
    result = client.search("anything", mode="quick", timeout_seconds=5)

    assert result["status"] == "error"
    assert result["reason"] == "transport_error"


def test_search_handles_non_200(mock_get_user_config, mock_requests_post):
    mock_get_user_config.return_value = {'useOfflineResearcherApi': True}
    mock_requests_post.return_value = Mock(status_code=503, text="LLM down")

    client = OfflineResearcherApiClient()
    result = client.search("anything", mode="quick", timeout_seconds=5)

    assert result["status"] == "error"
    assert result["reason"] == "http_503"


def test_search_handles_non_json_200(mock_get_user_config, mock_requests_post):
    # A 200 with a non-JSON body must degrade to an error envelope rather than
    # letting json()'s ValueError escape and break the "always returns an envelope"
    # contract.
    mock_get_user_config.return_value = {'useOfflineResearcherApi': True}
    bad = Mock(status_code=200)
    bad.json.side_effect = ValueError("not json")
    mock_requests_post.return_value = bad

    client = OfflineResearcherApiClient()
    result = client.search("anything", mode="quick", timeout_seconds=5)

    assert result["status"] == "error"
    assert result["reason"] == "invalid_json"
    assert result["answer"] is None
    assert result["sources"] == []


def test_no_information_found_sentinel_constant():
    # The literal is part of the service's stable contract; pinning it here
    # so an accidental rename inside the client trips this test.
    assert NO_INFORMATION_FOUND_MESSAGE == "No pertinent information was found in the search"
