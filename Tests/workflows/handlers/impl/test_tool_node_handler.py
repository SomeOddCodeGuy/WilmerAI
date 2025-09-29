from unittest.mock import MagicMock

import pytest

# Code under test
from Middleware.workflows.handlers.impl.tool_node_handler import ToolNodeHandler
from Middleware.workflows.models.execution_context import ExecutionContext


# --- Fixtures ---

@pytest.fixture
def mock_dependencies(mocker):
    """Mocks the dependencies of ToolNodeHandler for isolated testing."""
    # Mock the tool classes to prevent their __init__ from running real logic
    mocker.patch('Middleware.workflows.handlers.impl.tool_node_handler.SlowButQualityRAGTool')
    mocker.patch('Middleware.workflows.handlers.impl.tool_node_handler.OfflineWikiApiClient')

    # Mock the dynamic module loader function
    mock_run_dynamic_module = mocker.patch('Middleware.workflows.handlers.impl.tool_node_handler.run_dynamic_module')

    # Mock the variable service, a required dependency for the base handler
    mock_variable_service = MagicMock()
    # A simple side_effect to simulate variable resolution
    mock_variable_service.apply_variables = MagicMock(side_effect=lambda s, c, **kwargs: f"resolved_{s}")

    return {
        "workflow_manager": MagicMock(),
        "workflow_variable_service": mock_variable_service,
        "run_dynamic_module": mock_run_dynamic_module
    }


@pytest.fixture
def tool_node_handler(mock_dependencies):
    """Provides a ToolNodeHandler instance with mocked dependencies."""
    handler = ToolNodeHandler(
        workflow_manager=mock_dependencies["workflow_manager"],
        workflow_variable_service=mock_dependencies["workflow_variable_service"]
    )
    # Replace the actual tool instances with mocks for fine-grained control in tests
    handler.slow_but_quality_rag_service = MagicMock()
    handler.offline_wiki_api_client = MagicMock()
    return handler


@pytest.fixture
def execution_context(mock_dependencies):
    """Provides a base ExecutionContext object for tests."""
    return ExecutionContext(
        request_id="test_req_id",
        workflow_id="test_wf_id",
        discussion_id="test_disc_id",
        config={},  # To be customized in each test
        messages=[{"role": "user", "content": "hello world"}],
        stream=False,
        workflow_variable_service=mock_dependencies["workflow_variable_service"]
    )


# --- Test Cases ---

def test_tool_node_handler_initialization(mock_dependencies):
    """
    Tests that the ToolNodeHandler initializes its service clients correctly.
    """
    handler = ToolNodeHandler(
        workflow_manager=mock_dependencies["workflow_manager"],
        workflow_variable_service=mock_dependencies["workflow_variable_service"]
    )
    # These assertions verify that the __init__ method correctly instantiates the tool classes
    assert handler.slow_but_quality_rag_service is not None
    assert handler.offline_wiki_api_client is not None


@pytest.mark.parametrize(
    "node_type, expected_method_to_call",
    [
        ("PythonModule", "_handle_python_module"),
        ("OfflineWikiApiFullArticle", "_handle_offline_wiki_node"),
        ("OfflineWikiApiBestFullArticle", "_handle_offline_wiki_node"),
        ("OfflineWikiApiTopNFullArticles", "_handle_offline_wiki_node"),
        ("OfflineWikiApiPartialArticle", "_handle_offline_wiki_node"),
        ("ConversationalKeywordSearchPerformerTool", "_perform_keyword_search"),
        ("MemoryKeywordSearchPerformerTool", "_perform_keyword_search"),
        ("SlowButQualityRAG", "_perform_slow_but_quality_rag"),
    ]
)
def test_handle_routes_to_correct_method(tool_node_handler, execution_context, mocker, node_type,
                                         expected_method_to_call):
    """
    Tests that the main handle() method correctly routes to the appropriate private method based on node type.
    """
    execution_context.config = {"type": node_type}
    mock_method = mocker.patch.object(tool_node_handler, expected_method_to_call, return_value="mocked_return")

    result = tool_node_handler.handle(execution_context)

    mock_method.assert_called_once_with(execution_context)
    assert result == "mocked_return"


def test_handle_raises_for_unknown_type(tool_node_handler, execution_context):
    """
    Tests that the handle() method raises a ValueError for an unrecognized node type.
    """
    execution_context.config = {"type": "UnknownToolType"}
    with pytest.raises(ValueError, match="Unknown tool node type: UnknownToolType"):
        tool_node_handler.handle(execution_context)


# --- Tests for _handle_python_module ---

def test_handle_python_module_success(tool_node_handler, execution_context, mock_dependencies):
    """
    Tests the successful execution of a PythonModule node with args and kwargs.
    """
    execution_context.config = {
        "type": "PythonModule",
        "module_path": "/path/to/module.py",
        "args": ["first_arg", "{var1}"],
        "kwargs": {"key1": "value1", "key2": "{var2}"}
    }
    mock_dependencies["run_dynamic_module"].return_value = "dynamic module success"

    result = tool_node_handler._handle_python_module(execution_context)

    # Verify that variables were applied to args and kwargs
    variable_service = tool_node_handler.workflow_variable_service
    assert variable_service.apply_variables.call_count == 4

    # Instead of asserting the exact context object, we inspect the calls made to the mock.
    # This is robust against the `deepcopy` used in the implementation.
    calls = variable_service.apply_variables.call_args_list

    # 1. Extract the first argument (the string to be resolved) from each call.
    called_strings = [c.args[0] for c in calls]

    # 2. Assert that all expected strings were processed. The order of calls to kwargs is not guaranteed.
    assert "first_arg" in called_strings
    assert "{var1}" in called_strings
    assert "value1" in called_strings
    assert "{var2}" in called_strings

    # 3. Assert that the second argument was always an instance of ExecutionContext.
    for c in calls:
        assert isinstance(c.args[1], ExecutionContext)
        # You can optionally add a sanity check on the content of the copied context
        assert c.args[1].request_id == "test_req_id"

    # Verify the dynamic module runner was called with resolved values
    expected_args = ('resolved_first_arg', 'resolved_{var1}')
    expected_kwargs = {'key1': 'resolved_value1', 'key2': 'resolved_{var2}'}
    mock_dependencies["run_dynamic_module"].assert_called_once_with(
        "/path/to/module.py", *expected_args, **expected_kwargs
    )
    assert result == "dynamic module success"


def test_handle_python_module_raises_no_module_path(tool_node_handler, execution_context):
    """
    Tests that a ValueError is raised if 'module_path' is missing from the config.
    """
    execution_context.config = {"type": "PythonModule"}  # Missing module_path
    with pytest.raises(ValueError, match="No 'module_path' specified for PythonModule node."):
        tool_node_handler._handle_python_module(execution_context)


# --- Tests for _handle_offline_wiki_node ---

@pytest.mark.parametrize(
    "node_type, client_method, client_return_value, expected_result",
    [
        # Best Full Article
        ("OfflineWikiApiBestFullArticle", "get_top_full_wiki_article_by_prompt", ["Best article text"],
         "Best article text"),
        ("OfflineWikiApiBestFullArticle", "get_top_full_wiki_article_by_prompt", [],
         "No additional information provided about 'resolved_Test Query'"),
        # Full Article (Fallback)
        ("OfflineWikiApiFullArticle", "get_full_wiki_article_by_prompt", ["Full article text"], "Full article text"),
        ("OfflineWikiApiFullArticle", "get_full_wiki_article_by_prompt", [],
         "No article found for 'resolved_Test Query'."),
    ]
)
def test_handle_offline_wiki_node_simple_cases(tool_node_handler, execution_context, node_type, client_method,
                                               client_return_value, expected_result):
    """
    Tests various simple Offline Wikipedia node types that return a single string.
    """
    execution_context.config = {"type": node_type, "promptToSearch": "Test Query"}
    mock_client_method = getattr(tool_node_handler.offline_wiki_api_client, client_method)
    mock_client_method.return_value = client_return_value

    result = tool_node_handler._handle_offline_wiki_node(execution_context)

    mock_client_method.assert_called_once_with("resolved_Test Query")
    assert result == expected_result


def test_handle_offline_wiki_partial_article_success(tool_node_handler, execution_context):
    """
    Tests the specific logic for the OfflineWikiApiPartialArticle node with successful results.
    """
    execution_context.config = {
        "type": "OfflineWikiApiPartialArticle",
        "promptToSearch": "AI Summary",
        "percentile": 0.7,
        "num_results": 2
    }
    client_return = [
        {"title": "Summary One", "text": "This is the first summary."},
        {"title": "Summary Two", "text": "This is the second summary."}
    ]
    tool_node_handler.offline_wiki_api_client.get_wiki_summary_by_prompt.return_value = client_return

    result = tool_node_handler._handle_offline_wiki_node(execution_context)

    tool_node_handler.offline_wiki_api_client.get_wiki_summary_by_prompt.assert_called_once_with(
        "resolved_AI Summary", percentile=0.7, num_results=2
    )

    expected_output = "Title: Summary One\nThis is the first summary.\n\n--- END SUMMARY ---\n\nTitle: Summary Two\nThis is the second summary."
    assert result == expected_output


def test_handle_offline_wiki_partial_article_no_results(tool_node_handler, execution_context):
    """
    Tests the 'no results' case for the Partial Article node.
    """
    execution_context.config = {"type": "OfflineWikiApiPartialArticle", "promptToSearch": "Obscure Summary"}
    tool_node_handler.offline_wiki_api_client.get_wiki_summary_by_prompt.return_value = []

    result = tool_node_handler._handle_offline_wiki_node(execution_context)

    assert result == "No summary found for 'resolved_Obscure Summary'."


def test_handle_offline_wiki_top_n_articles(tool_node_handler, execution_context):
    """
    Tests the specific logic for the OfflineWikiApiTopNFullArticles node.
    """
    execution_context.config = {
        "type": "OfflineWikiApiTopNFullArticles",
        "promptToSearch": "AI History",
        "percentile": 0.8,
        "num_results": 15,
        "top_n_articles": 2
    }
    client_return = [
        {"title": "Deep Learning", "text": "Text about DL."},
        {"title": "Transformers", "text": "Text about transformers."}
    ]
    tool_node_handler.offline_wiki_api_client.get_top_n_full_wiki_articles_by_prompt.return_value = client_return

    result = tool_node_handler._handle_offline_wiki_node(execution_context)

    tool_node_handler.offline_wiki_api_client.get_top_n_full_wiki_articles_by_prompt.assert_called_once_with(
        "resolved_AI History", percentile=0.8, num_results=15, top_n_articles=2
    )

    expected_output = "Title: Deep Learning\nText about DL.\n\n--- END ARTICLE ---\n\nTitle: Transformers\nText about transformers."
    assert result == expected_output


def test_handle_offline_wiki_top_n_articles_no_results(tool_node_handler, execution_context):
    """
    Tests the 'no results' case for the TopN articles node.
    """
    execution_context.config = {"type": "OfflineWikiApiTopNFullArticles", "promptToSearch": "Obscure Topic"}
    tool_node_handler.offline_wiki_api_client.get_top_n_full_wiki_articles_by_prompt.return_value = []

    result = tool_node_handler._handle_offline_wiki_node(execution_context)

    assert result == "No articles found for 'resolved_Obscure Topic' in the offline database."


def test_handle_offline_wiki_node_raises_no_prompt(tool_node_handler, execution_context):
    """
    Tests that a ValueError is raised if 'promptToSearch' is missing.
    """
    execution_context.config = {"type": "OfflineWikiApiFullArticle"}  # Missing promptToSearch
    with pytest.raises(ValueError, match="No 'promptToSearch' specified for OfflineWikiApi node."):
        tool_node_handler._handle_offline_wiki_node(execution_context)


def test_handle_offline_wiki_node_handles_exception(tool_node_handler, execution_context):
    """
    Tests that exceptions from the API client are caught and a user-friendly message is returned.
    """
    execution_context.config = {"type": "OfflineWikiApiFullArticle", "promptToSearch": "Test Query"}
    tool_node_handler.offline_wiki_api_client.get_full_wiki_article_by_prompt.side_effect = Exception("API is down")

    result = tool_node_handler._handle_offline_wiki_node(execution_context)

    assert result == "I'm sorry, I couldn't find any Wikipedia information about 'resolved_Test Query'."


# --- Tests for _perform_keyword_search ---

def test_perform_keyword_search_success(tool_node_handler, execution_context):
    """
    Tests a successful keyword search with a specified target.
    """
    execution_context.config = {
        "keywords": "search for this",
        "searchTarget": "RecentMemories"
    }
    tool_node_handler.slow_but_quality_rag_service.perform_keyword_search.return_value = "found results"

    result = tool_node_handler._perform_keyword_search(execution_context)

    tool_node_handler.workflow_variable_service.apply_variables.assert_called_once_with("search for this",
                                                                                        execution_context)
    tool_node_handler.slow_but_quality_rag_service.perform_keyword_search.assert_called_once_with(
        "resolved_search for this", "RecentMemories", execution_context
    )
    assert result == "found results"


def test_perform_keyword_search_default_target(tool_node_handler, execution_context):
    """
    Tests that keyword search defaults to 'CurrentConversation' when target is not specified.
    """
    execution_context.config = {"keywords": "some keywords"}
    tool_node_handler.slow_but_quality_rag_service.perform_keyword_search.return_value = "default target results"

    result = tool_node_handler._perform_keyword_search(execution_context)

    tool_node_handler.slow_but_quality_rag_service.perform_keyword_search.assert_called_once_with(
        "resolved_some keywords", "CurrentConversation", execution_context
    )
    assert result == "default target results"


def test_perform_keyword_search_returns_exception_on_no_keywords(tool_node_handler, execution_context):
    """
    Tests that an Exception object is returned if 'keywords' are missing.
    """
    execution_context.config = {}  # Missing keywords

    result = tool_node_handler._perform_keyword_search(execution_context)

    assert isinstance(result, Exception)
    assert str(result) == "No keywords specified in Keyword Search node"


# --- Tests for _perform_slow_but_quality_rag ---

def test_perform_slow_but_quality_rag_success(tool_node_handler, execution_context):
    """
    Tests a successful call to the Slow But Quality RAG tool.
    """
    execution_context.config = {
        "ragTarget": "{some_variable}",
        "ragType": "some_type",
        "prompt": "rag_prompt",
        "systemPrompt": "rag_system_prompt"
    }
    tool_node_handler.slow_but_quality_rag_service.perform_rag_on_conversation_chunk.return_value = "RAG output"

    result = tool_node_handler._perform_slow_but_quality_rag(execution_context)

    # Verify variables were resolved
    variable_service = tool_node_handler.workflow_variable_service
    assert variable_service.apply_variables.call_count == 3
    variable_service.apply_variables.assert_any_call("rag_prompt", execution_context)
    variable_service.apply_variables.assert_any_call("rag_system_prompt", execution_context)
    variable_service.apply_variables.assert_any_call("{some_variable}", execution_context)

    # Verify service was called with resolved values
    tool_node_handler.slow_but_quality_rag_service.perform_rag_on_conversation_chunk.assert_called_once_with(
        "resolved_rag_system_prompt", "resolved_rag_prompt", "resolved_{some_variable}", execution_context
    )
    assert result == "RAG output"


def test_perform_slow_but_quality_rag_returns_exception_on_no_target(tool_node_handler, execution_context):
    """
    Tests that an Exception is returned if 'ragTarget' is missing.
    """
    execution_context.config = {"ragType": "some_type"}  # Missing ragTarget
    result = tool_node_handler._perform_slow_but_quality_rag(execution_context)
    assert isinstance(result, Exception)
    assert str(result) == "No rag target specified in Slow But Quality RAG node"


def test_perform_slow_but_quality_rag_returns_exception_on_no_type(tool_node_handler, execution_context):
    """
    Tests that an Exception is returned if 'ragType' is missing.
    """
    execution_context.config = {"ragTarget": "some_target"}  # Missing ragType
    result = tool_node_handler._perform_slow_but_quality_rag(execution_context)
    assert isinstance(result, Exception)
    assert str(result) == "No rag type specified in Slow But Quality RAG node"
