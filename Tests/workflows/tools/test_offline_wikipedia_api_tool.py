# tests/workflows/tools/test_offline_wikipedia_api_tool.py

from unittest.mock import Mock

import pytest

# The path to the module containing the class to be tested
from Middleware.workflows.tools.offline_wikipedia_api_tool import OfflineWikiApiClient


# --- Fixtures -----------------------------------------------------------------

@pytest.fixture
def mock_get_user_config(mocker):
    """Fixture to mock the get_user_config utility function."""
    # Mocks the function at its source location to ensure all calls are intercepted
    return mocker.patch('Middleware.workflows.tools.offline_wikipedia_api_tool.get_user_config')


@pytest.fixture
def mock_requests_get(mocker):
    """Fixture to mock requests.get to prevent actual HTTP calls."""
    return mocker.patch('requests.get')


# --- Test Cases ---------------------------------------------------------------

## 1. Initialization (__init__) Tests

def test_init_with_full_config(mock_get_user_config):
    """
    Tests that the client initializes correctly when the user config
    provides all necessary values.
    """
    mock_get_user_config.return_value = {
        'useOfflineWikiApi': True,
        'offlineWikiApiHost': 'testhost.local',
        'offlineWikiApiPort': 9999
    }
    client = OfflineWikiApiClient()
    assert client.use_offline_wiki_api is True
    assert client.base_url == "http://testhost.local:9999"


def test_init_api_disabled_in_config(mock_get_user_config):
    """
    Tests that the client is disabled if the user config specifies it,
    regardless of constructor parameters.
    """
    mock_get_user_config.return_value = {'useOfflineWikiApi': False}
    client = OfflineWikiApiClient(activateWikiApi=True)
    assert client.use_offline_wiki_api is False


def test_init_with_empty_config_uses_defaults(mock_get_user_config):
    """
    Tests that the client falls back to default values when the user
    config is empty or missing keys.
    """
    mock_get_user_config.return_value = {}
    client = OfflineWikiApiClient()
    assert client.use_offline_wiki_api is False
    assert client.base_url == "http://127.0.0.1:5728"


def test_init_with_empty_config_uses_constructor_args(mock_get_user_config):
    """
    Tests that constructor arguments are used as fallbacks when the
    user config is empty.
    """
    mock_get_user_config.return_value = {}
    client = OfflineWikiApiClient(activateWikiApi=True, baseurl='custom.host', port=1111)
    assert client.use_offline_wiki_api is True
    assert client.base_url == "http://custom.host:1111"


# --- 2. `get_full_article_by_title` Tests -----------------------------------

def test_get_full_article_by_title_api_disabled(mock_get_user_config):
    """Tests that the method returns a default message if the API is disabled."""
    mock_get_user_config.return_value = {'useOfflineWikiApi': False}
    client = OfflineWikiApiClient()
    result = client.get_full_article_by_title("any title")
    assert result == "No additional information provided"


def test_get_full_article_by_title_success(mock_get_user_config, mock_requests_get):
    """Tests a successful API call that returns an article."""
    mock_get_user_config.return_value = {'useOfflineWikiApi': True}
    mock_response = Mock(status_code=200)
    mock_response.json.return_value = {'text': 'This is the article content.'}
    mock_requests_get.return_value = mock_response

    client = OfflineWikiApiClient()
    result = client.get_full_article_by_title("Test Title")

    mock_requests_get.assert_called_once_with("http://127.0.0.1:5728/articles/Test Title")
    assert result == "This is the article content."


def test_get_full_article_by_title_not_found(mock_get_user_config, mock_requests_get):
    """Tests the handling of a 404 Not Found response."""
    mock_get_user_config.return_value = {'useOfflineWikiApi': True}
    mock_requests_get.return_value = Mock(status_code=404)

    client = OfflineWikiApiClient()
    result = client.get_full_article_by_title("Missing Title")

    expected_message = "No article found with title 'Missing Title'. The information may not be available in the offline database."
    assert result == expected_message


def test_get_full_article_by_title_server_error(mock_get_user_config, mock_requests_get):
    """Tests that a non-200/404 status code raises an exception."""
    mock_get_user_config.return_value = {'useOfflineWikiApi': True}
    mock_requests_get.return_value = Mock(status_code=500, text="Server Error")

    client = OfflineWikiApiClient()
    with pytest.raises(Exception, match="Error: 500, Server Error"):
        client.get_full_article_by_title("Any Title")


# --- 3. `get_wiki_summary_by_prompt` Tests ----------------------------------

def test_get_wiki_summary_by_prompt_api_disabled(mock_get_user_config):
    """Tests summary retrieval is skipped when the API is disabled."""
    mock_get_user_config.return_value = {'useOfflineWikiApi': False}
    client = OfflineWikiApiClient()
    result = client.get_wiki_summary_by_prompt("any prompt")
    assert result == [{"title": "Offline Wiki Disabled", "text": "No additional information provided"}]


def test_get_wiki_summary_by_prompt_success(mock_get_user_config, mock_requests_get):
    """Tests a successful call to the /summaries endpoint."""
    mock_get_user_config.return_value = {'useOfflineWikiApi': True}
    mock_response = Mock(status_code=200)
    expected_response = [{'title': 'Summary 1', 'text': 'Content 1'}, {'title': 'Summary 2', 'text': 'Content 2'}]
    mock_response.json.return_value = expected_response
    mock_requests_get.return_value = mock_response

    client = OfflineWikiApiClient()
    result = client.get_wiki_summary_by_prompt("AI history", percentile=0.6, num_results=2)

    expected_params = {'prompt': 'AI history', 'percentile': 0.6, 'num_results': 2}
    mock_requests_get.assert_called_once_with("http://127.0.0.1:5728/summaries", params=expected_params)
    assert result == expected_response


def test_get_wiki_summary_by_prompt_not_found(mock_get_user_config, mock_requests_get):
    """Tests the handling of a 404 response from the /summaries endpoint."""
    mock_get_user_config.return_value = {'useOfflineWikiApi': True}
    mock_requests_get.return_value = Mock(status_code=404)

    client = OfflineWikiApiClient()
    result = client.get_wiki_summary_by_prompt("Obscure topic")

    expected_message = [{
        "title": "Not Found",
        "text": "No summaries found for 'Obscure topic'. The information may not be available in the offline database."
    }]
    assert result == expected_message


# --- 4. `get_full_wiki_article_by_prompt` (Deprecated) Tests --------------

def test_get_full_wiki_article_by_prompt_success(mock_get_user_config, mock_requests_get):
    """Tests a successful call to the /articles endpoint."""
    mock_get_user_config.return_value = {'useOfflineWikiApi': True}
    mock_response = Mock(status_code=200)
    mock_response.json.return_value = [{'text': 'Full article 1'}, {'text': 'Full article 2'}]
    mock_requests_get.return_value = mock_response

    client = OfflineWikiApiClient()
    result = client.get_full_wiki_article_by_prompt("Roman Empire", num_results=2)

    expected_params = {'prompt': 'Roman Empire', 'percentile': 0.5, 'num_results': 2}
    mock_requests_get.assert_called_once_with("http://127.0.0.1:5728/articles", params=expected_params)
    assert result == ['Full article 1', 'Full article 2']


# --- 5. `get_top_full_wiki_article_by_prompt` Tests -----------------------

def test_get_top_full_wiki_article_by_prompt_success(mock_get_user_config, mock_requests_get):
    """Tests a successful call to the /top_article endpoint."""
    mock_get_user_config.return_value = {'useOfflineWikiApi': True}
    mock_response = Mock(status_code=200)
    mock_response.json.return_value = {'title': 'Top Article', 'text': 'This is the best article.'}
    mock_requests_get.return_value = mock_response

    client = OfflineWikiApiClient()
    result = client.get_top_full_wiki_article_by_prompt("Best match for AI")

    expected_params = {'prompt': 'Best match for AI', 'percentile': 0.5, 'num_results': 10}
    mock_requests_get.assert_called_once_with("http://127.0.0.1:5728/top_article", params=expected_params)
    assert result == ["This is the best article."]


def test_get_top_full_wiki_article_by_prompt_not_found(mock_get_user_config, mock_requests_get):
    """Tests the handling of a 404 response from the /top_article endpoint."""
    mock_get_user_config.return_value = {'useOfflineWikiApi': True}
    mock_requests_get.return_value = Mock(status_code=404)

    client = OfflineWikiApiClient()
    result = client.get_top_full_wiki_article_by_prompt("No good matches")

    expected_message = [
        "No article found for 'No good matches'. The information may not be available in the offline database."]
    assert result == expected_message


# --- 6. `get_top_n_full_wiki_articles_by_prompt` Tests --------------------

def test_get_top_n_full_wiki_articles_by_prompt_success(mock_get_user_config, mock_requests_get):
    """
    Tests a successful call to the /top_n_articles endpoint.
    Verifies that it returns the full list of dictionary objects.
    """
    mock_get_user_config.return_value = {'useOfflineWikiApi': True}
    mock_response = Mock(status_code=200)
    expected_payload = [
        {'title': 'Article 1', 'text': 'Content 1'},
        {'title': 'Article 2', 'text': 'Content 2'}
    ]
    mock_response.json.return_value = expected_payload
    mock_requests_get.return_value = mock_response

    client = OfflineWikiApiClient()
    result = client.get_top_n_full_wiki_articles_by_prompt("Python programming", top_n_articles=2)

    expected_params = {
        'prompt': 'Python programming',
        'percentile': 0.5,
        'num_results': 10,
        'num_top_articles': 2
    }
    mock_requests_get.assert_called_once_with("http://127.0.0.1:5728/top_n_articles", params=expected_params)
    assert result == expected_payload


def test_get_top_n_full_wiki_articles_by_prompt_not_found(mock_get_user_config, mock_requests_get):
    """Tests the handling of a 404 response from the /top_n_articles endpoint."""
    mock_get_user_config.return_value = {'useOfflineWikiApi': True}
    mock_requests_get.return_value = Mock(status_code=404)

    client = OfflineWikiApiClient()
    result = client.get_top_n_full_wiki_articles_by_prompt("Unfindable topic")

    expected_message = [
        "No articles found for 'Unfindable topic'. The information may not be available in the offline database."]
    assert result == expected_message
