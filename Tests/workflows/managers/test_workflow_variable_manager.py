from unittest.mock import MagicMock, patch

import pytest

from Middleware.workflows.managers.workflow_variable_manager import WorkflowVariableManager
from Middleware.workflows.models.execution_context import ExecutionContext

@pytest.fixture
def mock_llm_handler() -> MagicMock:
    """Provides a mock LLM handler for testing."""
    handler = MagicMock()
    handler.prompt_template_file_name = "test_template.json"
    handler.takes_message_collection = True
    return handler

# --- MODIFIED FIXTURE ---
# The fixture is updated to provide agent_inputs as a dictionary,
# which is the format that revealed the original bug.
@pytest.fixture
def mock_context(mock_llm_handler) -> MagicMock:
    """Provides a mock ExecutionContext with dictionary-based agent_inputs."""
    context = MagicMock(spec=ExecutionContext)
    context.config = {"jinja2": False}
    context.workflow_config = {"custom_var": "custom_value", "nodes": []}
    context.discussion_id = "test_discussion_123"
    context.messages = [{"role": "user", "content": "Hello"}]
    context.llm_handler = mock_llm_handler
    context.agent_outputs = {"agent1Output": "Output from node 1"}
    # This is the key change: agent_inputs is now a dictionary.
    context.agent_inputs = {
        "agent1Input": "Input from parent workflow",
        "agent2Input": "Second input from parent"
    }
    context.api_key = None
    context.encryption_key = None
    context.api_key_hash = None
    return context

@pytest.fixture(autouse=True)
def _mock_conversation_format_config(mocker):
    """Mocks the user-level conversation formatting config for all tests in this module."""
    mocker.patch(
        'Middleware.workflows.managers.workflow_variable_manager.get_separate_conversation_in_variables',
        return_value=False
    )
    mocker.patch(
        'Middleware.workflows.managers.workflow_variable_manager.get_conversation_separation_delimiter',
        return_value='\n'
    )


@pytest.fixture(autouse=True)
def _hermetic_user_config(mocker):
    """Isolate from the real user config file. The token-based conversation variables
    resolve clampPromptToContextWindow (node -> endpoint -> user) via the shared
    config_utils.is_context_clamp_enabled, whose user level calls get_user_config();
    default it to an empty dict (clamp OFF) so tests do not depend on machine state."""
    mocker.patch('Middleware.utilities.config_utils.get_user_config', return_value={})
    # workflow_variable_manager imports get_user_config by name (for the 'userWideWorkflowVariables'
    # shared-variable feature), so patch that local reference too.
    mocker.patch('Middleware.workflows.managers.workflow_variable_manager.get_user_config', return_value={})


# --- userWideWorkflowVariables: user-config shared variables (single source of truth) ---

def test_workflow_variables_from_user_config_resolve(mocker, mock_context):
    """A 'userWideWorkflowVariables' dict in the user config is exposed as {placeholders}
    available to every workflow (the single knob for shared state-file paths)."""
    mocker.patch(
        'Middleware.workflows.managers.workflow_variable_manager.get_user_config',
        return_value={"userWideWorkflowVariables": {"opencodePlansDir": "/data/plans"}},
    )
    mock_context.messages = []  # skip conversation-variable generation (no template files in tests)
    manager = WorkflowVariableManager()
    assert manager.apply_variables("dir is {opencodePlansDir}", mock_context) == "dir is /data/plans"


def test_workflow_variables_are_lowest_precedence(mocker, mock_context):
    """A userWideWorkflowVariables key can never shadow a built-in or a workflow-config key.
    mock_context.workflow_config defines custom_var and the context has a discussion_id;
    both must win over the user-config values of the same name."""
    mocker.patch(
        'Middleware.workflows.managers.workflow_variable_manager.get_user_config',
        return_value={"userWideWorkflowVariables": {"custom_var": "FROM_USER", "Discussion_Id": "HACKED"}},
    )
    mock_context.messages = []
    manager = WorkflowVariableManager()
    result = manager.apply_variables("{custom_var}|{Discussion_Id}", mock_context)
    assert result == "custom_value|test_discussion_123"


def test_workflow_variables_absent_or_malformed_is_noop(mocker, mock_context):
    """No 'userWideWorkflowVariables' key (or a non-dict one) simply adds nothing, no error."""
    mocker.patch(
        'Middleware.workflows.managers.workflow_variable_manager.get_user_config',
        return_value={"port": 5070, "userWideWorkflowVariables": "not-a-dict"},
    )
    mock_context.messages = []
    manager = WorkflowVariableManager()
    assert manager.apply_variables("hello {custom_var}", mock_context) == "hello custom_value"


def test_workflow_variables_nested_path_resolves(mocker, mock_context):
    """The real OpenCode wiring: a workflow-level path key whose value references
    {opencodePlansDir} resolves via the second substitution pass."""
    mocker.patch(
        'Middleware.workflows.managers.workflow_variable_manager.get_user_config',
        return_value={"userWideWorkflowVariables": {"opencodePlansDir": "/data/plans"}},
    )
    mock_context.messages = []
    mock_context.workflow_config = {
        "scratchpad_file": "{opencodePlansDir}/current_scratchpad.txt",
        "nodes": [],
    }
    manager = WorkflowVariableManager()
    result = manager.apply_variables("{scratchpad_file}", mock_context)
    assert result == "/data/plans/current_scratchpad.txt"

@patch('Middleware.workflows.managers.workflow_variable_manager.TimestampService')
@patch('Middleware.workflows.managers.workflow_variable_manager.MemoryService')
def test_init_and_set_categories(MockMemoryService, MockTimestampService):
    """
    Tests that the constructor correctly initializes services and sets category attributes from kwargs.
    """
    kwargs = {
        "category_list": ["cat1", "cat2"],
        "category_descriptions": "desc1, desc2",
        "some_other_kwarg": "ignore_me"  # Should be ignored
    }

    manager = WorkflowVariableManager(**kwargs)

    MockMemoryService.assert_called_once()
    MockTimestampService.assert_called_once()
    assert manager.category_list == ["cat1", "cat2"]
    assert manager.category_descriptions == "desc1, desc2"
    assert not hasattr(manager, "some_other_kwarg")
    assert manager.categoriesSeparatedByOr is None  # Should be None if not provided

    # Test initialization without any category kwargs
    manager_no_kwargs = WorkflowVariableManager()
    assert manager_no_kwargs.category_list is None

def test_extract_additional_attributes():
    """
    Tests that only predefined, non-None category attributes are extracted.
    """
    kwargs = {
        "category_list": ["cat1"],
        "categoryNameBulletpoints": "- cat1",
        "category_descriptions": None  # Should be ignored
    }
    manager = WorkflowVariableManager(**kwargs)

    attributes = manager.extract_additional_attributes()

    expected_attributes = {
        "category_list": ["cat1"],
        "categoryNameBulletpoints": "- cat1"
    }
    assert attributes == expected_attributes

    manager_empty = WorkflowVariableManager()
    empty_attributes = manager_empty.extract_additional_attributes()
    assert empty_attributes == {}

def test_generate_conversation_turn_variables(mocker):
    """
    Tests that conversation turn variables are generated by calling the correct utility functions.
    """
    mock_extract_str = mocker.patch(
        'Middleware.workflows.managers.workflow_variable_manager.extract_last_n_turns_as_string',
        side_effect=lambda messages, n, *args, **kwargs: f"raw_string_n{n}")
    mock_get_formatted_str = mocker.patch(
        'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string',
        side_effect=lambda messages, n, *args, **kwargs: f"templated_string_n{n}")

    mock_handler = MagicMock()
    mock_handler.prompt_template_file_name = "test.json"
    mock_handler.takes_message_collection = True  # This sets include_sysmes to True

    messages = [{"role": "user", "content": "Test"}]

    result = WorkflowVariableManager.generate_conversation_turn_variables(
        originalMessages=messages,
        llm_handler=mock_handler,
        remove_all_system_override=False
    )

    assert result["chat_user_prompt_last_one"] == "raw_string_n1"
    assert result["templated_user_prompt_last_one"] == "templated_string_n1"
    assert result["chat_user_prompt_last_twenty"] == "raw_string_n20"
    assert result["templated_user_prompt_last_twenty"] == "templated_string_n20"

    mock_extract_str.assert_any_call(messages, 1, True, False,
                                     add_role_tags=False, separator='\n')
    mock_get_formatted_str.assert_any_call(
        messages, 1,
        template_file_name="test.json",
        isChatCompletion=True
    )

def test_process_conversation_turn_variables(mocker, mock_llm_handler):
    """
    Tests that conversation strings are correctly templated based on the key and llm_handler presence.
    """
    mocker.patch(
        'Middleware.workflows.managers.workflow_variable_manager.get_chat_template_name',
        return_value="chat_template.json")
    mock_format_prompt = mocker.patch(
        'Middleware.workflows.managers.workflow_variable_manager.format_templated_prompt',
        side_effect=lambda text, handler, template: f"formatted_{text}_with_{template}")

    prompts = {
        "chat_user_prompt_last_one": "hello",
        "templated_user_prompt_last_one": "world"
    }

    result = WorkflowVariableManager.process_conversation_turn_variables(prompts, mock_llm_handler)

    assert result["chat_user_prompt_last_one"] == "formatted_hello_with_chat_template.json"
    assert result["templated_user_prompt_last_one"] == "formatted_world_with_test_template.json"

    mock_format_prompt.reset_mock()
    result_no_handler = WorkflowVariableManager.process_conversation_turn_variables(prompts, None)

    assert result_no_handler["templated_user_prompt_last_one"] == "formatted_world_with_chat_template.json"
    mock_format_prompt.assert_any_call("world", None, "chat_template.json")

# This test specifically validates that agent_inputs provided as a dictionary
# are correctly processed and added to the final variables map. This test
# would have failed with the buggy code.
def test_generate_variables_handles_agent_inputs_dictionary(mock_context, mocker):
    """
    Tests that agent_inputs provided as a dictionary are correctly added to the variables.
    This is the regression test for the bug where dictionary iteration was incorrect.
    """
    manager = WorkflowVariableManager()

    # Mock the internal dependency that was trying to access the file system.
    # This keeps the test isolated to only the logic within generate_variables.
    mocker.patch.object(
        manager,
        'generate_conversation_turn_variables',
        return_value={"mock_convo_var": "mock_value"}
    )

    # We also need to mock this utility function called inside generate_variables
    mocker.patch(
        'Middleware.workflows.managers.workflow_variable_manager.format_system_prompts',
        return_value={}
    )
    mocker.patch(
        'Middleware.workflows.managers.workflow_variable_manager.extract_last_n_turns_as_string',
        return_value="raw_n_messages"
    )
    mocker.patch(
        'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string',
        return_value="templated_n_messages"
    )
    mocker.patch(
        'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_by_estimated_token_limit_as_string',
        return_value="raw_token_limit"
    )
    mocker.patch(
        'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_by_estimated_token_limit_as_string',
        return_value="templated_token_limit"
    )
    mocker.patch(
        'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_with_min_messages_and_token_limit_as_string',
        return_value=""
    )
    mocker.patch(
        'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_with_min_messages_and_token_limit_as_string',
        return_value=""
    )

    variables = manager.generate_variables(mock_context)

    # Check that the dictionary from the fixture was correctly unpacked.
    assert 'agent1Input' in variables
    assert variables['agent1Input'] == "Input from parent workflow"
    assert 'agent2Input' in variables
    assert variables['agent2Input'] == "Second input from parent"

    # Also ensure that agent_outputs were not lost in the process
    assert 'agent1Output' in variables
    assert variables['agent1Output'] == "Output from node 1"

# --- REFACTORED AND CLEANED UP TEST ---
# The original test was convoluted. This version is cleaner and acts as a
# good integration test for the entire generate_variables method, now using
# the updated fixture with dictionary-based agent_inputs.
def test_generate_variables_integration(mocker, mock_context):
    """
    Tests the main variable aggregation logic, ensuring all sources are combined correctly.
    """
    mocker.patch('Middleware.workflows.managers.workflow_variable_manager.datetime')
    manager = WorkflowVariableManager()

    mock_ts_service = MagicMock()
    mock_ts_service.get_time_context_summary.return_value = "time_summary"
    manager.timestamp_service = mock_ts_service

    mocker.patch.object(manager, 'generate_conversation_turn_variables',
                        return_value={"chat_user_prompt_last_one": "hello"})
    mocker.patch.object(manager, 'extract_additional_attributes', return_value={"category_list": ["test"]})
    mocker.patch('Middleware.workflows.managers.workflow_variable_manager.format_system_prompts',
                 return_value={"templated_system_prompt": "system prompt"})
    mocker.patch('Middleware.workflows.managers.workflow_variable_manager.extract_last_n_turns_as_string',
                 return_value="raw_n_messages")
    mocker.patch('Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string',
                 return_value="templated_n_messages")
    mocker.patch('Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_by_estimated_token_limit_as_string',
                 return_value="raw_token_limit")
    mocker.patch('Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_by_estimated_token_limit_as_string',
                 return_value="templated_token_limit")
    mocker.patch('Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_with_min_messages_and_token_limit_as_string',
                 return_value="raw_combo")
    mocker.patch('Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_with_min_messages_and_token_limit_as_string',
                 return_value="templated_combo")

    variables = manager.generate_variables(mock_context)

    assert 'todays_date_pretty' in variables
    assert variables['custom_var'] == 'custom_value'
    assert 'nodes' not in variables
    assert variables['time_context_summary'] == "time_summary"
    assert variables['chat_user_prompt_last_one'] == "hello"
    assert variables['templated_system_prompt'] == "system prompt"
    assert variables['agent1Output'] == "Output from node 1"
    assert variables['agent1Input'] == "Input from parent workflow"  # Now correctly asserts the dict value
    assert variables['agent2Input'] == "Second input from parent"
    assert variables['category_list'] == ["test"]
    assert variables['chat_user_prompt_n_messages'] == "raw_n_messages"
    assert variables['templated_user_prompt_n_messages'] == "templated_n_messages"

    mock_ts_service.get_time_context_summary.assert_called_once_with("test_discussion_123", encryption_key=None, api_key_hash=None)

def test_apply_variables_standard_format(mocker, mock_context):
    """
    Tests variable substitution using standard Python string.format().
    """
    manager = WorkflowVariableManager()
    mocker.patch.object(manager, 'generate_variables', return_value={"name": "Wilmer", "action": "testing"})
    prompt = "My name is {name} and I am {action}."
    mock_context.config = {'jinja2': False}

    result = manager.apply_variables(prompt, mock_context)

    assert result == "My name is Wilmer and I am testing."
    manager.generate_variables.assert_called_once_with(mock_context, None, prompt=prompt)

def test_apply_variables_jinja2_format(mocker, mock_context):
    """
    Tests variable substitution using the Jinja2 templating engine.
    """
    manager = WorkflowVariableManager()
    mocker.patch.object(manager, 'generate_variables', return_value={"user_name": "Tester"})
    mock_context.config = {'jinja2': True}
    mock_context.messages = [{'role': 'user', 'content': 'Hi'}]
    prompt = "Summary for {{ user_name }}:\n{% for msg in messages %}- {{ msg.role }}\n{% endfor %}"
    expected_output = "Summary for Tester:\n- user\n"

    result = manager.apply_variables(prompt, mock_context)

    assert result == expected_output

# --- NEW JINJA2 TESTS ---

def test_apply_variables_jinja2_with_agent_io_and_conditional(mocker, mock_context):
    """
    Tests Jinja2 rendering with a complex template involving agent inputs,
    agent outputs, and conditional logic, reflecting a real-world use case.
    """
    manager = WorkflowVariableManager()

    # Setup the variables that would be returned by generate_variables
    test_variables = {
        "agent1Output": "SUCCESS",
        "agent2Input": "Initial Data From Parent",
        "agent3Output": "NO_TITLE_FOUND"  # for testing the 'else' branch
    }
    mocker.patch.object(manager, 'generate_variables', return_value=test_variables)
    mock_context.config = {'jinja2': True}

    prompt_if = "{% if agent1Output == 'SUCCESS' %}Data: {{ agent2Input }}{% else %}Error{% endif %}"
    result_if = manager.apply_variables(prompt_if, mock_context)
    assert result_if == "Data: Initial Data From Parent"

    prompt_else = "{% if agent3Output != 'NO_TITLE_FOUND' %}Title: {{ agent3Output }}{% else %}No Title Provided{% endif %}"
    result_else = manager.apply_variables(prompt_else, mock_context)
    assert result_else == "No Title Provided"

def test_apply_variables_key_error_fallback(mocker, mock_context):
    """
    Tests that standard formatting gracefully fails and logs a warning on a KeyError.
    """
    mock_log_warning = mocker.patch('Middleware.workflows.managers.workflow_variable_manager.logger.warning')
    manager = WorkflowVariableManager()
    mocker.patch.object(manager, 'generate_variables', return_value={"name": "Wilmer"})
    mock_context.config = {'jinja2': False}
    prompt = "Hello {name}, this is an {undefined_key}."

    result = manager.apply_variables(prompt, mock_context)

    assert result == prompt
    mock_log_warning.assert_called_once()
    assert "A key error occurred" in mock_log_warning.call_args[0][0]


def test_agent_output_braces_escaped_in_variables(mocker, mock_context):
    """
    Tests that curly braces in agent output values are sentinel-escaped
    before entering the variables dict, preventing str.format() from
    crashing on JSON-like content (e.g., tool call data loaded via
    GetCustomFile).
    """
    manager = WorkflowVariableManager()
    mock_context.agent_outputs = {
        "agent1Output": 'tool: {"fn": {"args": "{\\"x\\": 1}"}}'
    }
    mock_context.agent_inputs = None
    mock_context.messages = None  # Skip conversation variable generation

    variables = manager.generate_variables(mock_context)

    # The value should contain sentinel tokens, not raw braces
    assert "__WILMER_L_CURLY__" in variables["agent1Output"]
    assert "__WILMER_R_CURLY__" in variables["agent1Output"]
    # Raw braces should NOT appear in the escaped value
    assert "{" not in variables["agent1Output"]
    assert "}" not in variables["agent1Output"]


def test_agent_input_braces_escaped_in_variables(mocker, mock_context):
    """
    Tests that curly braces in agent input values are sentinel-escaped.
    """
    manager = WorkflowVariableManager()
    mock_context.agent_outputs = {}
    mock_context.agent_inputs = {
        "agent1Input": '{"key": "value"}'
    }
    mock_context.messages = None  # Skip conversation variable generation

    variables = manager.generate_variables(mock_context)

    assert "__WILMER_L_CURLY__" in variables["agent1Input"]
    assert "{" not in variables["agent1Input"]


def test_apply_variables_with_braces_in_agent_output(mocker, mock_context):
    """
    End-to-end test: agent output containing JSON braces is substituted
    into a prompt via apply_variables() without crashing, and the final
    result has real braces restored.
    """
    manager = WorkflowVariableManager()
    json_value = '{"function": {"name": "test", "arguments": "{\\"x\\": 1}"}}'
    # Mock generate_variables to return sentinel-escaped value (as the real
    # implementation now does), plus the variable key for format resolution.
    escaped_value = json_value.replace("{", "__WILMER_L_CURLY__").replace("}", "__WILMER_R_CURLY__")
    mocker.patch.object(manager, 'generate_variables', return_value={
        "agent1Output": escaped_value
    })
    mock_context.config = {'jinja2': False}

    prompt = "Result: {agent1Output}"
    result = manager.apply_variables(prompt, mock_context)

    # Braces should be restored in the final output
    assert json_value in result


# --- NEW TESTS FOR apply_early_variables METHOD ---
# These tests verify the functionality we added to support early variable
# substitution for endpointName and preset fields

class TestApplyEarlyVariables:
    """Tests for the apply_early_variables method that handles early substitution without llm_handler."""

    def test_apply_early_variables_with_agent_inputs(self):
        """Tests that agent input variables are correctly substituted."""
        manager = WorkflowVariableManager()
        agent_inputs = {
            "agent1Input": "MyEndpoint",
            "agent2Input": "MyPreset"
        }
        prompt = "{agent1Input}/{agent2Input}"

        result = manager.apply_early_variables(prompt, agent_inputs=agent_inputs)

        assert result == "MyEndpoint/MyPreset"

    def test_apply_early_variables_with_workflow_config(self):
        """Tests that workflow config variables are correctly substituted."""
        manager = WorkflowVariableManager()
        workflow_config = {
            "endpoint": "TestEndpoint",
            "preset": "TestPreset",
            "nodes": ["should_be_ignored"]  # nodes should be excluded
        }
        prompt = "{endpoint}_with_{preset}"

        result = manager.apply_early_variables(prompt, workflow_config=workflow_config)

        assert result == "TestEndpoint_with_TestPreset"

    def test_apply_early_variables_with_both_sources(self):
        """Tests that both agent inputs and workflow config variables work together."""
        manager = WorkflowVariableManager()
        agent_inputs = {"agent1Input": "Dynamic"}
        workflow_config = {"baseUrl": "https://api.example.local"}
        prompt = "{baseUrl}/v1/{agent1Input}"

        result = manager.apply_early_variables(
            prompt,
            agent_inputs=agent_inputs,
            workflow_config=workflow_config
        )

        assert result == "https://api.example.local/v1/Dynamic"

    def test_apply_early_variables_missing_variable(self, mocker):
        """Tests that missing variables are handled gracefully with partial substitution and warning."""
        mock_logger = mocker.patch('Middleware.workflows.managers.workflow_variable_manager.logger.warning')
        manager = WorkflowVariableManager()
        agent_inputs = {"agent1Input": "Present"}
        prompt = "{agent1Input}/{missingVariable}"

        result = manager.apply_early_variables(prompt, agent_inputs=agent_inputs)

        assert result == "Present/{missingVariable}"  # Partial substitution - substitutes what it can
        mock_logger.assert_called_once()
        assert "Variables not available for early substitution" in mock_logger.call_args[0][0]

    def test_apply_early_variables_no_variables_in_prompt(self):
        """Tests that prompts without variables are returned unchanged."""
        manager = WorkflowVariableManager()
        agent_inputs = {"agent1Input": "Value"}
        prompt = "StaticEndpointName"

        result = manager.apply_early_variables(prompt, agent_inputs=agent_inputs)

        assert result == "StaticEndpointName"

    def test_apply_early_variables_empty_inputs(self):
        """Tests that empty inputs don't cause errors."""
        manager = WorkflowVariableManager()
        prompt = "{agent1Input}"

        result = manager.apply_early_variables(prompt, agent_inputs=None, workflow_config=None)

        assert result == "{agent1Input}"  # Returns original since no variables available

    def test_apply_early_variables_malformed_brackets(self, mocker):
        """Tests that malformed variable syntax is handled gracefully."""
        mock_logger = mocker.patch('Middleware.workflows.managers.workflow_variable_manager.logger.warning')
        manager = WorkflowVariableManager()
        agent_inputs = {"agent1Input": "Value"}
        prompt = "{agent1Input} and {unclosed and {{double}}"

        result = manager.apply_early_variables(prompt, agent_inputs=agent_inputs)

        # Should handle the valid variable and return original for invalid parts
        mock_logger.assert_called()
        assert "Error during early variable substitution" in mock_logger.call_args[0][0]

    def test_apply_early_variables_complex_template_pattern(self):
        """Tests a complex real-world pattern with multiple variables."""
        manager = WorkflowVariableManager()
        agent_inputs = {
            "agent1Input": "General-Fast-Endpoint",
            "agent2Input": "Factual_Preset"
        }
        workflow_config = {
            "version": "v1",
            "environment": "production"
        }
        prompt = "{environment}/{version}/{agent1Input}?preset={agent2Input}"

        result = manager.apply_early_variables(
            prompt,
            agent_inputs=agent_inputs,
            workflow_config=workflow_config
        )

        assert result == "production/v1/General-Fast-Endpoint?preset=Factual_Preset"

    def test_apply_early_variables_nodes_excluded_from_workflow_config(self):
        """Tests that 'nodes' key is properly excluded from workflow config."""
        manager = WorkflowVariableManager()
        workflow_config = {
            "validKey": "validValue",
            "nodes": [{"type": "Standard"}]  # Should be excluded
        }
        prompt = "{validKey} and {nodes}"

        result = manager.apply_early_variables(prompt, workflow_config=workflow_config)

        # validKey should work, nodes should not
        assert "{nodes}" in result  # nodes variable should remain unsubstituted
        assert "validValue" in result

    def test_apply_early_variables_priority_when_duplicate_keys(self):
        """Tests that agent_inputs take priority over workflow_config when keys conflict."""
        manager = WorkflowVariableManager()
        agent_inputs = {"endpoint": "FromAgent"}
        workflow_config = {"endpoint": "FromWorkflow"}
        prompt = "{endpoint}"

        result = manager.apply_early_variables(
            prompt,
            agent_inputs=agent_inputs,
            workflow_config=workflow_config
        )

        # agent_inputs should override workflow_config
        assert result == "FromAgent"

    def test_apply_early_variables_special_characters_in_values(self):
        """Tests that special characters in values don't break substitution."""
        manager = WorkflowVariableManager()
        agent_inputs = {
            "agent1Input": "endpoint-with-dash_and_underscore.v1",
            "agent2Input": "preset@2.0"
        }
        prompt = "{agent1Input}:{agent2Input}"

        result = manager.apply_early_variables(prompt, agent_inputs=agent_inputs)

        assert result == "endpoint-with-dash_and_underscore.v1:preset@2.0"

    def test_apply_early_variables_numeric_values(self):
        """Tests that numeric values in the config are handled correctly."""
        manager = WorkflowVariableManager()
        workflow_config = {
            "port": 8080,
            "version": 2
        }
        prompt = "http://localhost:{port}/api/v{version}"

        result = manager.apply_early_variables(prompt, workflow_config=workflow_config)

        assert result == "http://localhost:8080/api/v2"

    def test_apply_early_variables_none_values(self):
        """Tests that None values in inputs are handled correctly."""
        manager = WorkflowVariableManager()
        agent_inputs = {
            "agent1Input": None,
            "agent2Input": "NotNone"
        }
        prompt = "{agent1Input}/{agent2Input}"

        result = manager.apply_early_variables(prompt, agent_inputs=agent_inputs)

        assert result == "None/NotNone"  # None is converted to string "None"

# --- TESTS FOR NEW VARIABLES: Discussion_Id AND YYYY_MM_DD ---

class TestDiscussionIdAndDateVariables:
    """Tests for the Discussion_Id and YYYY_MM_DD variables added for filepath support."""

    def test_generate_variables_includes_discussion_id(self, mocker, mock_context):
        """Tests that Discussion_Id variable is populated from the context's discussion_id."""
        manager = WorkflowVariableManager()
        mock_context.discussion_id = "my-unique-conversation-123"

        mocker.patch.object(manager, 'generate_conversation_turn_variables', return_value={})
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.format_system_prompts', return_value={})
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.extract_last_n_turns_as_string', return_value="")
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string', return_value="")
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_by_estimated_token_limit_as_string', return_value="")
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_by_estimated_token_limit_as_string', return_value="")
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_with_min_messages_and_token_limit_as_string', return_value="")
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_with_min_messages_and_token_limit_as_string', return_value="")

        variables = manager.generate_variables(mock_context)

        assert 'Discussion_Id' in variables
        assert variables['Discussion_Id'] == "my-unique-conversation-123"

    def test_generate_variables_discussion_id_empty_when_none(self, mocker, mock_context):
        """Tests that Discussion_Id is an empty string when discussion_id is None."""
        manager = WorkflowVariableManager()
        mock_context.discussion_id = None

        mocker.patch.object(manager, 'generate_conversation_turn_variables', return_value={})
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.format_system_prompts', return_value={})
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.extract_last_n_turns_as_string', return_value="")
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string', return_value="")
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_by_estimated_token_limit_as_string', return_value="")
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_by_estimated_token_limit_as_string', return_value="")
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_with_min_messages_and_token_limit_as_string', return_value="")
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_with_min_messages_and_token_limit_as_string', return_value="")

        variables = manager.generate_variables(mock_context)

        assert 'Discussion_Id' in variables
        assert variables['Discussion_Id'] == ''

    def test_generate_variables_includes_yyyy_mm_dd(self, mocker, mock_context):
        """Tests that YYYY_MM_DD variable is generated in the correct format."""
        from datetime import datetime
        mock_datetime = mocker.patch('Middleware.workflows.managers.workflow_variable_manager.datetime')
        mock_now = MagicMock()
        mock_now.strftime.side_effect = lambda fmt: {
            '%B %d, %Y': 'December 07, 2025',
            '%Y-%m-%d': '2025-12-07',
            '%Y_%m_%d': '2025_12_07',
            '%I:%M %p': '03:30 PM',
            '%H:%M': '15:30',
            '%B': 'December',
            '%A': 'Sunday',
            '%d': '07'
        }.get(fmt, fmt)
        mock_datetime.now.return_value = mock_now

        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_conversation_turn_variables', return_value={})
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.format_system_prompts', return_value={})
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.extract_last_n_turns_as_string', return_value="")
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string', return_value="")
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_by_estimated_token_limit_as_string', return_value="")
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_by_estimated_token_limit_as_string', return_value="")
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_with_min_messages_and_token_limit_as_string', return_value="")
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_with_min_messages_and_token_limit_as_string', return_value="")

        variables = manager.generate_variables(mock_context)

        assert 'YYYY_MM_DD' in variables
        assert variables['YYYY_MM_DD'] == '2025_12_07'

    def test_apply_variables_with_discussion_id_in_filepath(self, mocker, mock_context):
        """Tests that Discussion_Id can be substituted in a filepath-like string."""
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_variables', return_value={
            'Discussion_Id': 'conv-456',
            'YYYY_MM_DD': '2025_12_07'
        })
        mock_context.config = {'jinja2': False}
        filepath_template = "/data/sessions/{Discussion_Id}/notes.txt"

        result = manager.apply_variables(filepath_template, mock_context)

        assert result == "/data/sessions/conv-456/notes.txt"

    def test_apply_variables_with_yyyy_mm_dd_in_filepath(self, mocker, mock_context):
        """Tests that YYYY_MM_DD can be substituted in a filepath-like string."""
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_variables', return_value={
            'Discussion_Id': 'conv-789',
            'YYYY_MM_DD': '2025_12_07'
        })
        mock_context.config = {'jinja2': False}
        filepath_template = "/logs/{YYYY_MM_DD}_actions.txt"

        result = manager.apply_variables(filepath_template, mock_context)

        assert result == "/logs/2025_12_07_actions.txt"

    def test_apply_variables_with_both_variables_in_filepath(self, mocker, mock_context):
        """Tests that both Discussion_Id and YYYY_MM_DD can be used together in a filepath."""
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_variables', return_value={
            'Discussion_Id': 'session-abc',
            'YYYY_MM_DD': '2025_12_07'
        })
        mock_context.config = {'jinja2': False}
        filepath_template = "/data/{YYYY_MM_DD}/{Discussion_Id}_output.txt"

        result = manager.apply_variables(filepath_template, mock_context)

        assert result == "/data/2025_12_07/session-abc_output.txt"

    def test_apply_variables_empty_discussion_id_in_filepath(self, mocker, mock_context):
        """Tests that an empty Discussion_Id results in empty string substitution."""
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_variables', return_value={
            'Discussion_Id': '',
            'YYYY_MM_DD': '2025_12_07'
        })
        mock_context.config = {'jinja2': False}
        filepath_template = "/data/{Discussion_Id}_notes.txt"

        result = manager.apply_variables(filepath_template, mock_context)

        assert result == "/data/_notes.txt"

# --- TESTS FOR NESTED VARIABLE RESOLUTION ---

class TestNestedVariableResolution:
    """Tests for the second-pass variable resolution that handles nested variables.
    This covers the case where a workflow-level variable's value itself contains
    placeholders (e.g., a filepath variable containing {Discussion_Id}).
    """

    def test_nested_variable_in_workflow_config(self, mocker, mock_context):
        """Tests that a workflow config variable containing {Discussion_Id} is fully resolved."""
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_variables', return_value={
            'user_profile_file': '/data/{Discussion_Id}/user_profile.txt',
            'Discussion_Id': 'test-discussion-42'
        })
        mock_context.config = {'jinja2': False}

        result = manager.apply_variables("{user_profile_file}", mock_context)

        assert result == "/data/test-discussion-42/user_profile.txt"

    def test_nested_variable_with_multiple_placeholders(self, mocker, mock_context):
        """Tests nested resolution with multiple placeholders in the intermediate value."""
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_variables', return_value={
            'log_path': '/logs/{YYYY_MM_DD}/{Discussion_Id}_output.txt',
            'Discussion_Id': 'conv-123',
            'YYYY_MM_DD': '2025_12_07'
        })
        mock_context.config = {'jinja2': False}

        result = manager.apply_variables("{log_path}", mock_context)

        assert result == "/logs/2025_12_07/conv-123_output.txt"

    def test_no_nested_variables_still_works(self, mocker, mock_context):
        """Tests that prompts without nested variables are unaffected by the second pass."""
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_variables', return_value={
            'Discussion_Id': 'conv-456'
        })
        mock_context.config = {'jinja2': False}

        result = manager.apply_variables("/data/{Discussion_Id}/file.txt", mock_context)

        assert result == "/data/conv-456/file.txt"

    def test_nested_variable_second_pass_keyerror_is_safe(self, mocker, mock_context):
        """Tests that an unresolvable variable in the second pass doesn't crash."""
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_variables', return_value={
            'my_path': '/data/{undefined_var}/file.txt',
        })
        mock_context.config = {'jinja2': False}

        result = manager.apply_variables("{my_path}", mock_context)

        assert result == "/data/{undefined_var}/file.txt"

    def test_nested_variable_real_world_workflow_pattern(self, mocker, mock_context):
        """Tests the exact pattern from the bug report: workflow-level filepath variables
        containing {Discussion_Id} used in GetCustomFile nodes."""
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_variables', return_value={
            'persona_file': '/tmp/test_data/{Discussion_Id}/persona.txt',
            'user_profile_file': '/tmp/test_data/{Discussion_Id}/user_profile.txt',
            'style_guide_file': '/tmp/test_data/{Discussion_Id}/style_guide.txt',
            'Discussion_Id': 'test-discussion-42'
        })
        mock_context.config = {'jinja2': False}

        assert manager.apply_variables("{persona_file}", mock_context) == \
            "/tmp/test_data/test-discussion-42/persona.txt"
        assert manager.apply_variables("{user_profile_file}", mock_context) == \
            "/tmp/test_data/test-discussion-42/user_profile.txt"
        assert manager.apply_variables("{style_guide_file}", mock_context) == \
            "/tmp/test_data/test-discussion-42/style_guide.txt"

# --- TESTS FOR CONFIGURABLE N-MESSAGES VARIABLES ---

class TestNMessagesVariables:
    """Tests for the configurable {chat_user_prompt_n_messages} and {templated_user_prompt_n_messages} variables."""

    def test_n_messages_variable_with_explicit_config(self, mocker, mock_context):
        """Tests that nMessagesToIncludeInVariable reads from config and generates the correct variables."""
        manager = WorkflowVariableManager()
        mock_context.config = {'jinja2': False, 'nMessagesToIncludeInVariable': 15}

        mocker.patch.object(manager, 'generate_conversation_turn_variables', return_value={})
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.format_system_prompts', return_value={})

        mock_extract = mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_n_turns_as_string',
            return_value="raw_n15"
        )
        mock_formatted = mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string',
            return_value="templated_n15"
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_by_estimated_token_limit_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_by_estimated_token_limit_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_with_min_messages_and_token_limit_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_with_min_messages_and_token_limit_as_string',
            return_value=""
        )

        variables = manager.generate_variables(mock_context)

        assert variables['chat_user_prompt_n_messages'] == "raw_n15"
        assert variables['templated_user_prompt_n_messages'] == "templated_n15"

        # Verify extract was called with n=15
        mock_extract.assert_called_with(
            mocker.ANY, 15, True, None,
            add_role_tags=False, separator='\n'
        )
        mock_formatted.assert_called_with(
            mocker.ANY, 15,
            template_file_name="test_template.json",
            isChatCompletion=True
        )

    def test_n_messages_variable_defaults_to_five(self, mocker, mock_context):
        """Tests that nMessagesToIncludeInVariable defaults to 5 when not in config."""
        manager = WorkflowVariableManager()
        mock_context.config = {'jinja2': False}  # No nMessagesToIncludeInVariable

        mocker.patch.object(manager, 'generate_conversation_turn_variables', return_value={})
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.format_system_prompts', return_value={})

        mock_extract = mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_n_turns_as_string',
            return_value="raw_n5"
        )
        mock_formatted = mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string',
            return_value="templated_n5"
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_by_estimated_token_limit_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_by_estimated_token_limit_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_with_min_messages_and_token_limit_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_with_min_messages_and_token_limit_as_string',
            return_value=""
        )

        variables = manager.generate_variables(mock_context)

        assert variables['chat_user_prompt_n_messages'] == "raw_n5"
        assert variables['templated_user_prompt_n_messages'] == "templated_n5"

        # Verify extract was called with default n=5
        mock_extract.assert_called_with(
            mocker.ANY, 5, True, None,
            add_role_tags=False, separator='\n'
        )
        mock_formatted.assert_called_with(
            mocker.ANY, 5,
            template_file_name="test_template.json",
            isChatCompletion=True
        )

    def test_n_messages_variable_with_none_config(self, mocker, mock_context):
        """Tests that n-messages variables default to 5 when config is None."""
        manager = WorkflowVariableManager()
        mock_context.config = None

        mocker.patch.object(manager, 'generate_conversation_turn_variables', return_value={})
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.format_system_prompts', return_value={})

        mock_extract = mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_n_turns_as_string',
            return_value="raw_default"
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string',
            return_value="templated_default"
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_by_estimated_token_limit_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_by_estimated_token_limit_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_with_min_messages_and_token_limit_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_with_min_messages_and_token_limit_as_string',
            return_value=""
        )

        variables = manager.generate_variables(mock_context)

        assert variables['chat_user_prompt_n_messages'] == "raw_default"
        assert variables['templated_user_prompt_n_messages'] == "templated_default"
        mock_extract.assert_called_with(mocker.ANY, 5, True, None,
                                        add_role_tags=False, separator='\n')

    def test_n_messages_variable_usable_in_standard_format(self, mocker, mock_context):
        """Tests that the n-messages variable can be used with standard str.format()."""
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_variables', return_value={
            'chat_user_prompt_n_messages': 'Hello from last N messages',
            'templated_user_prompt_n_messages': 'Templated N messages'
        })
        mock_context.config = {'jinja2': False}
        prompt = "Recent: {chat_user_prompt_n_messages}"

        result = manager.apply_variables(prompt, mock_context)

        assert result == "Recent: Hello from last N messages"

    def test_n_messages_variable_usable_in_jinja2(self, mocker, mock_context):
        """Tests that the n-messages variable can be used with Jinja2 templating."""
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_variables', return_value={
            'chat_user_prompt_n_messages': 'N messages content'
        })
        mock_context.config = {'jinja2': True}
        mock_context.messages = []
        prompt = "Content: {{ chat_user_prompt_n_messages }}"

        result = manager.apply_variables(prompt, mock_context)

        assert result == "Content: N messages content"

class TestEstimatedTokenLimitVariables:
    """Tests for the configurable {chat_user_prompt_estimated_token_limit} and
    {templated_user_prompt_estimated_token_limit} variables."""

    def test_token_limit_variable_with_explicit_config(self, mocker, mock_context):
        """Tests that estimatedTokensToIncludeInVariable reads from config and generates the correct variables."""
        manager = WorkflowVariableManager()
        mock_context.config = {'jinja2': False, 'estimatedTokensToIncludeInVariable': 5000}

        mocker.patch.object(manager, 'generate_conversation_turn_variables', return_value={})
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.format_system_prompts', return_value={})
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_n_turns_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string',
            return_value=""
        )

        mock_extract_token = mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_by_estimated_token_limit_as_string',
            return_value="raw_token_5000"
        )
        mock_formatted_token = mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_by_estimated_token_limit_as_string',
            return_value="templated_token_5000"
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_with_min_messages_and_token_limit_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_with_min_messages_and_token_limit_as_string',
            return_value=""
        )

        variables = manager.generate_variables(mock_context)

        assert variables['chat_user_prompt_estimated_token_limit'] == "raw_token_5000"
        assert variables['templated_user_prompt_estimated_token_limit'] == "templated_token_5000"

        # Verify extract was called with token_limit=5000
        mock_extract_token.assert_called_with(
            mocker.ANY, 5000, True, None,
            add_role_tags=False, separator='\n'
        )
        mock_formatted_token.assert_called_with(
            mocker.ANY, 5000,
            template_file_name="test_template.json",
            isChatCompletion=True
        )

    def test_token_limit_variable_defaults_to_2048(self, mocker, mock_context):
        """Tests that estimatedTokensToIncludeInVariable defaults to 2048 when not in config."""
        manager = WorkflowVariableManager()
        mock_context.config = {'jinja2': False}  # No estimatedTokensToIncludeInVariable

        mocker.patch.object(manager, 'generate_conversation_turn_variables', return_value={})
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.format_system_prompts', return_value={})
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_n_turns_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string',
            return_value=""
        )

        mock_extract_token = mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_by_estimated_token_limit_as_string',
            return_value="raw_token_2048"
        )
        mock_formatted_token = mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_by_estimated_token_limit_as_string',
            return_value="templated_token_2048"
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_with_min_messages_and_token_limit_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_with_min_messages_and_token_limit_as_string',
            return_value=""
        )

        variables = manager.generate_variables(mock_context)

        assert variables['chat_user_prompt_estimated_token_limit'] == "raw_token_2048"
        assert variables['templated_user_prompt_estimated_token_limit'] == "templated_token_2048"

        # Verify extract was called with default token_limit=2048
        mock_extract_token.assert_called_with(
            mocker.ANY, 2048, True, None,
            add_role_tags=False, separator='\n'
        )
        mock_formatted_token.assert_called_with(
            mocker.ANY, 2048,
            template_file_name="test_template.json",
            isChatCompletion=True
        )

    def test_token_limit_variable_with_none_config(self, mocker, mock_context):
        """Tests that token-limit variables default to 2048 when config is None."""
        manager = WorkflowVariableManager()
        mock_context.config = None

        mocker.patch.object(manager, 'generate_conversation_turn_variables', return_value={})
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.format_system_prompts', return_value={})

        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_n_turns_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string',
            return_value=""
        )
        mock_extract_token = mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_by_estimated_token_limit_as_string',
            return_value="raw_token_default"
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_by_estimated_token_limit_as_string',
            return_value="templated_token_default"
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_with_min_messages_and_token_limit_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_with_min_messages_and_token_limit_as_string',
            return_value=""
        )

        variables = manager.generate_variables(mock_context)

        assert variables['chat_user_prompt_estimated_token_limit'] == "raw_token_default"
        assert variables['templated_user_prompt_estimated_token_limit'] == "templated_token_default"
        mock_extract_token.assert_called_with(mocker.ANY, 2048, True, None,
                                             add_role_tags=False, separator='\n')

    def test_token_limit_variable_usable_in_standard_format(self, mocker, mock_context):
        """Tests that the token-limit variable can be used with standard str.format()."""
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_variables', return_value={
            'chat_user_prompt_estimated_token_limit': 'Token-limited content here',
            'templated_user_prompt_estimated_token_limit': 'Templated token content'
        })
        mock_context.config = {'jinja2': False}
        prompt = "Recent: {chat_user_prompt_estimated_token_limit}"

        result = manager.apply_variables(prompt, mock_context)

        assert result == "Recent: Token-limited content here"

    def test_token_limit_variable_usable_in_jinja2(self, mocker, mock_context):
        """Tests that the token-limit variable can be used with Jinja2 templating."""
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_variables', return_value={
            'chat_user_prompt_estimated_token_limit': 'Token limit content'
        })
        mock_context.config = {'jinja2': True}
        mock_context.messages = []
        prompt = "Content: {{ chat_user_prompt_estimated_token_limit }}"

        result = manager.apply_variables(prompt, mock_context)

        assert result == "Content: Token limit content"

class TestMinMessagesMaxTokensVariables:
    """Tests for the configurable {chat_user_prompt_min_n_max_tokens} and
    {templated_user_prompt_min_n_max_tokens} variables."""

    def test_combo_variable_with_explicit_config(self, mocker, mock_context):
        """Tests that minMessagesInVariable and maxEstimatedTokensInVariable read from config."""
        manager = WorkflowVariableManager()
        mock_context.config = {
            'jinja2': False,
            'minMessagesInVariable': 10,
            'maxEstimatedTokensInVariable': 5000
        }

        mocker.patch.object(manager, 'generate_conversation_turn_variables', return_value={})
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.format_system_prompts', return_value={})
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_n_turns_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_by_estimated_token_limit_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_by_estimated_token_limit_as_string',
            return_value=""
        )

        mock_extract_combo = mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_with_min_messages_and_token_limit_as_string',
            return_value="raw_combo_10_5000"
        )
        mock_formatted_combo = mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_with_min_messages_and_token_limit_as_string',
            return_value="templated_combo_10_5000"
        )

        variables = manager.generate_variables(mock_context)

        assert variables['chat_user_prompt_min_n_max_tokens'] == "raw_combo_10_5000"
        assert variables['templated_user_prompt_min_n_max_tokens'] == "templated_combo_10_5000"

        # Verify extract was called with min_messages=10, max_tokens=5000
        mock_extract_combo.assert_called_with(
            mocker.ANY, 10, 5000, True, None,
            add_role_tags=False, separator='\n', budget_overrides_min=False
        )
        mock_formatted_combo.assert_called_with(
            mocker.ANY, 10, 5000,
            template_file_name="test_template.json",
            isChatCompletion=True, budget_overrides_min=False
        )

    def test_combo_variable_defaults(self, mocker, mock_context):
        """Tests that combo variables default to min_messages=5, max_tokens=2048 when not in config."""
        manager = WorkflowVariableManager()
        mock_context.config = {'jinja2': False}  # No combo config

        mocker.patch.object(manager, 'generate_conversation_turn_variables', return_value={})
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.format_system_prompts', return_value={})
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_n_turns_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_by_estimated_token_limit_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_by_estimated_token_limit_as_string',
            return_value=""
        )

        mock_extract_combo = mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_with_min_messages_and_token_limit_as_string',
            return_value="raw_combo_default"
        )
        mock_formatted_combo = mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_with_min_messages_and_token_limit_as_string',
            return_value="templated_combo_default"
        )

        variables = manager.generate_variables(mock_context)

        assert variables['chat_user_prompt_min_n_max_tokens'] == "raw_combo_default"
        assert variables['templated_user_prompt_min_n_max_tokens'] == "templated_combo_default"

        # Verify extract was called with defaults: min_messages=5, max_tokens=2048
        mock_extract_combo.assert_called_with(
            mocker.ANY, 5, 2048, True, None,
            add_role_tags=False, separator='\n', budget_overrides_min=False
        )
        mock_formatted_combo.assert_called_with(
            mocker.ANY, 5, 2048,
            template_file_name="test_template.json",
            isChatCompletion=True, budget_overrides_min=False
        )

    def test_combo_variable_with_none_config(self, mocker, mock_context):
        """Tests that combo variables default when config is None."""
        manager = WorkflowVariableManager()
        mock_context.config = None

        mocker.patch.object(manager, 'generate_conversation_turn_variables', return_value={})
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.format_system_prompts', return_value={})
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_n_turns_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_by_estimated_token_limit_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_by_estimated_token_limit_as_string',
            return_value=""
        )
        mock_extract_combo = mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_with_min_messages_and_token_limit_as_string',
            return_value="raw_combo_none"
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_with_min_messages_and_token_limit_as_string',
            return_value="templated_combo_none"
        )

        variables = manager.generate_variables(mock_context)

        assert variables['chat_user_prompt_min_n_max_tokens'] == "raw_combo_none"
        assert variables['templated_user_prompt_min_n_max_tokens'] == "templated_combo_none"
        mock_extract_combo.assert_called_with(mocker.ANY, 5, 2048, True, None,
                                             add_role_tags=False, separator='\n',
                                             budget_overrides_min=False)

    def test_combo_variable_usable_in_standard_format(self, mocker, mock_context):
        """Tests that the combo variable can be used with standard str.format()."""
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_variables', return_value={
            'chat_user_prompt_min_n_max_tokens': 'Combo content here',
            'templated_user_prompt_min_n_max_tokens': 'Templated combo content'
        })
        mock_context.config = {'jinja2': False}
        prompt = "Recent: {chat_user_prompt_min_n_max_tokens}"

        result = manager.apply_variables(prompt, mock_context)

        assert result == "Recent: Combo content here"

    def test_combo_variable_usable_in_jinja2(self, mocker, mock_context):
        """Tests that the combo variable can be used with Jinja2 templating."""
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_variables', return_value={
            'chat_user_prompt_min_n_max_tokens': 'Combo jinja content'
        })
        mock_context.config = {'jinja2': True}
        mock_context.messages = []
        prompt = "Content: {{ chat_user_prompt_min_n_max_tokens }}"

        result = manager.apply_variables(prompt, mock_context)

        assert result == "Content: Combo jinja content"

# --- TESTS FOR PROMPT-AWARE LOGGING AND EDGE CASES ---

class TestPromptAwareLogging:
    """Tests for the prompt-aware conditional logging in generate_variables."""

    def _setup_generate_variables_mocks(self, mocker, mock_context, config=None):
        """Helper to set up common mocks for generate_variables tests."""
        manager = WorkflowVariableManager()
        if config is not None:
            mock_context.config = config
        else:
            mock_context.config = {'jinja2': False}

        mocker.patch.object(manager, 'generate_conversation_turn_variables', return_value={})
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.format_system_prompts', return_value={})

        mock_extract_n = mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_n_turns',
            return_value=[{'role': 'user', 'content': 'test'}]
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_n_turns_as_string',
            return_value="raw"
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string',
            return_value="templated"
        )

        mock_extract_token = mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_by_estimated_token_limit',
            return_value=[{'role': 'user', 'content': 'test'}]
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_by_estimated_token_limit_as_string',
            return_value="raw_token"
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_by_estimated_token_limit_as_string',
            return_value="templated_token"
        )

        mock_extract_combo = mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_with_min_messages_and_token_limit',
            return_value=[{'role': 'user', 'content': 'test'}]
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_with_min_messages_and_token_limit_as_string',
            return_value="raw_combo"
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_with_min_messages_and_token_limit_as_string',
            return_value="templated_combo"
        )

        return manager, mock_extract_n, mock_extract_token, mock_extract_combo

    def test_n_messages_logging_fires_when_prompt_references_variable(self, mocker, mock_context):
        """Tests that extract_last_n_turns is called for logging when prompt references the variable."""
        manager, mock_extract_n, _, _ = self._setup_generate_variables_mocks(mocker, mock_context)

        manager.generate_variables(mock_context, prompt="Use {chat_user_prompt_n_messages} here")

        mock_extract_n.assert_called_once()

    def test_n_messages_logging_fires_for_templated_variant(self, mocker, mock_context):
        """Tests that logging fires when prompt references the templated variant."""
        manager, mock_extract_n, _, _ = self._setup_generate_variables_mocks(mocker, mock_context)

        manager.generate_variables(mock_context, prompt="Use {templated_user_prompt_n_messages} here")

        mock_extract_n.assert_called_once()

    def test_n_messages_logging_suppressed_when_prompt_omits_variable(self, mocker, mock_context):
        """Tests that extract_last_n_turns is NOT called when prompt doesn't reference the variable."""
        manager, mock_extract_n, _, _ = self._setup_generate_variables_mocks(mocker, mock_context)

        manager.generate_variables(mock_context, prompt="No reference here")

        mock_extract_n.assert_not_called()

    def test_n_messages_logging_suppressed_when_prompt_is_none(self, mocker, mock_context):
        """Tests that logging functions are not called when prompt is None."""
        manager, mock_extract_n, mock_extract_token, mock_extract_combo = (
            self._setup_generate_variables_mocks(mocker, mock_context)
        )

        manager.generate_variables(mock_context)

        mock_extract_n.assert_not_called()
        mock_extract_token.assert_not_called()
        mock_extract_combo.assert_not_called()

    def test_token_limit_logging_fires_when_prompt_references_variable(self, mocker, mock_context):
        """Tests that extract_last_turns_by_estimated_token_limit is called for logging."""
        manager, _, mock_extract_token, _ = self._setup_generate_variables_mocks(mocker, mock_context)

        manager.generate_variables(
            mock_context, prompt="Use {chat_user_prompt_estimated_token_limit} here"
        )

        mock_extract_token.assert_called_once()

    def test_combo_logging_fires_when_prompt_references_variable(self, mocker, mock_context):
        """Tests that extract_last_turns_with_min_messages_and_token_limit is called for logging."""
        manager, _, _, mock_extract_combo = self._setup_generate_variables_mocks(mocker, mock_context)

        manager.generate_variables(
            mock_context, prompt="Use {chat_user_prompt_min_n_max_tokens} here"
        )

        mock_extract_combo.assert_called_once()

class TestConfigEdgeCases:
    """Tests for config edge cases in generate_variables."""

    def _setup_mocks(self, mocker, mock_context):
        """Helper to set up common mocks."""
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_conversation_turn_variables', return_value={})
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.format_system_prompts', return_value={})

        mock_n = mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_n_turns_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string',
            return_value=""
        )
        mock_token = mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_by_estimated_token_limit_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_by_estimated_token_limit_as_string',
            return_value=""
        )
        mock_combo = mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_with_min_messages_and_token_limit_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_with_min_messages_and_token_limit_as_string',
            return_value=""
        )
        return manager, mock_n, mock_token, mock_combo

    def test_empty_dict_config_uses_defaults(self, mocker, mock_context):
        """Tests that an empty dict config {} uses default values for all configurable variables."""
        mock_context.config = {}
        manager, mock_n, mock_token, mock_combo = self._setup_mocks(mocker, mock_context)

        manager.generate_variables(mock_context)

        # Should use defaults: n=5, tokens=2048, min=5/max=2048
        mock_n.assert_called_with(mocker.ANY, 5, True, None,
                                  add_role_tags=False, separator='\n')
        mock_token.assert_called_with(mocker.ANY, 2048, True, None,
                                      add_role_tags=False, separator='\n')
        mock_combo.assert_called_with(mocker.ANY, 5, 2048, True, None,
                                      add_role_tags=False, separator='\n',
                                      budget_overrides_min=False)

    def test_partial_combo_config_only_min_messages(self, mocker, mock_context):
        """Tests that providing only minMessagesInVariable uses default for maxEstimatedTokensInVariable."""
        mock_context.config = {'minMessagesInVariable': 10}
        manager, _, _, mock_combo = self._setup_mocks(mocker, mock_context)

        manager.generate_variables(mock_context)

        mock_combo.assert_called_with(mocker.ANY, 10, 2048, True, None,
                                      add_role_tags=False, separator='\n',
                                      budget_overrides_min=False)

    def test_partial_combo_config_only_max_tokens(self, mocker, mock_context):
        """Tests that providing only maxEstimatedTokensInVariable uses default for minMessagesInVariable."""
        mock_context.config = {'maxEstimatedTokensInVariable': 4096}
        manager, _, _, mock_combo = self._setup_mocks(mocker, mock_context)

        manager.generate_variables(mock_context)

        mock_combo.assert_called_with(mocker.ANY, 5, 4096, True, None,
                                      add_role_tags=False, separator='\n',
                                      budget_overrides_min=False)

    def test_apply_variables_jinja2_passes_prompt_kwarg(self, mocker, mock_context):
        """Tests that apply_variables passes prompt= to generate_variables in the Jinja2 path."""
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_variables', return_value={"name": "test"})
        mock_context.config = {'jinja2': True}
        mock_context.messages = []
        prompt = "Hello {{ name }}"

        manager.apply_variables(prompt, mock_context)

        manager.generate_variables.assert_called_once_with(mock_context, None, prompt=prompt)

    def test_deepcopy_prevents_mutation_of_context_messages(self, mocker, mock_context):
        """Tests that context.messages are not mutated after generate_variables."""
        from copy import deepcopy
        original_messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        mock_context.messages = deepcopy(original_messages)

        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_conversation_turn_variables', return_value={})
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.format_system_prompts', return_value={})

        # Use real extraction functions but mock rough_estimate_token_length
        mocker.patch(
            'Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
            return_value=10
        )
        mocker.patch(
            'Middleware.utilities.prompt_template_utils.rough_estimate_token_length',
            return_value=10
        )
        mocker.patch(
            'Middleware.utilities.prompt_template_utils.load_template_from_json',
            return_value={}
        )

        manager.generate_variables(mock_context)

        assert mock_context.messages == original_messages


class TestAddUserAssistantTagsNodeLevel:
    """Tests for the node-level addUserAssistantTags config property."""

    def _setup_mocks(self, mocker, mock_context):
        """Helper to set up common mocks for generate_variables tests."""
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_conversation_turn_variables', return_value={})
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.format_system_prompts', return_value={})

        mock_n = mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_n_turns_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_by_estimated_token_limit_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_by_estimated_token_limit_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_with_min_messages_and_token_limit_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_with_min_messages_and_token_limit_as_string',
            return_value=""
        )
        return manager, mock_n

    def test_add_user_assistant_tags_true(self, mocker, mock_context):
        """Tests that addUserAssistantTags=True passes add_role_tags=True to extract functions."""
        mock_context.config = {'addUserAssistantTags': True}
        manager, mock_n = self._setup_mocks(mocker, mock_context)

        manager.generate_variables(mock_context)

        # Verify that generate_conversation_turn_variables was called with add_role_tags=True
        manager.generate_conversation_turn_variables.assert_called_once_with(
            originalMessages=mock_context.messages,
            llm_handler=mock_context.llm_handler,
            remove_all_system_override=None,
            add_role_tags=True,
            separator='\n',
            token_limit=None
        )
        # The configurable variable should also get add_role_tags=True
        mock_n.assert_called_with(mocker.ANY, 5, True, None,
                                  add_role_tags=True, separator='\n')

    def test_add_user_assistant_tags_false(self, mocker, mock_context):
        """Tests that addUserAssistantTags=False passes add_role_tags=False."""
        mock_context.config = {'addUserAssistantTags': False}
        manager, mock_n = self._setup_mocks(mocker, mock_context)

        manager.generate_variables(mock_context)

        manager.generate_conversation_turn_variables.assert_called_once_with(
            originalMessages=mock_context.messages,
            llm_handler=mock_context.llm_handler,
            remove_all_system_override=None,
            add_role_tags=False,
            separator='\n',
            token_limit=None
        )

    def test_add_user_assistant_tags_missing_defaults_false(self, mocker, mock_context):
        """Tests that missing addUserAssistantTags defaults to False."""
        mock_context.config = {'jinja2': False}
        manager, _ = self._setup_mocks(mocker, mock_context)

        manager.generate_variables(mock_context)

        manager.generate_conversation_turn_variables.assert_called_once_with(
            originalMessages=mock_context.messages,
            llm_handler=mock_context.llm_handler,
            remove_all_system_override=None,
            add_role_tags=False,
            separator='\n',
            token_limit=None
        )

    def test_add_user_assistant_tags_none_config(self, mocker, mock_context):
        """Tests that None config defaults add_role_tags to False."""
        mock_context.config = None
        manager, _ = self._setup_mocks(mocker, mock_context)

        manager.generate_variables(mock_context)

        manager.generate_conversation_turn_variables.assert_called_once_with(
            originalMessages=mock_context.messages,
            llm_handler=mock_context.llm_handler,
            remove_all_system_override=None,
            add_role_tags=False,
            separator='\n',
            token_limit=None
        )


class TestConversationSeparationConfig:
    """Tests for the user-level separateConversationInVariables and conversationSeparationDelimiter settings."""

    def _setup_mocks(self, mocker, mock_context):
        """Helper to set up common mocks."""
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_conversation_turn_variables', return_value={})
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.format_system_prompts', return_value={})
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_n_turns_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_by_estimated_token_limit_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_by_estimated_token_limit_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_with_min_messages_and_token_limit_as_string',
            return_value=""
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_with_min_messages_and_token_limit_as_string',
            return_value=""
        )
        return manager

    def test_separator_used_when_separate_conversation_true(self, mocker, mock_context):
        """Tests that the custom delimiter is used when separateConversationInVariables is True."""
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_separate_conversation_in_variables',
            return_value=True
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_conversation_separation_delimiter',
            return_value='\n*** END MESSAGE ***\n'
        )
        mock_context.config = {'jinja2': False}
        manager = self._setup_mocks(mocker, mock_context)

        manager.generate_variables(mock_context)

        manager.generate_conversation_turn_variables.assert_called_once_with(
            originalMessages=mock_context.messages,
            llm_handler=mock_context.llm_handler,
            remove_all_system_override=None,
            add_role_tags=False,
            separator='\n*** END MESSAGE ***\n',
            token_limit=None
        )

    def test_default_separator_when_separate_conversation_false(self, mocker, mock_context):
        """Tests that the default newline separator is used when separateConversationInVariables is False."""
        # autouse fixture already patches these to False / '\n'
        mock_context.config = {'jinja2': False}
        manager = self._setup_mocks(mocker, mock_context)

        manager.generate_variables(mock_context)

        manager.generate_conversation_turn_variables.assert_called_once_with(
            originalMessages=mock_context.messages,
            llm_handler=mock_context.llm_handler,
            remove_all_system_override=None,
            add_role_tags=False,
            separator='\n',
            token_limit=None
        )

    def test_combined_role_tags_and_custom_separator(self, mocker, mock_context):
        """Tests addUserAssistantTags=True combined with a custom separator."""
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_separate_conversation_in_variables',
            return_value=True
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_conversation_separation_delimiter',
            return_value='\n\n'
        )
        mock_context.config = {'addUserAssistantTags': True}
        manager = self._setup_mocks(mocker, mock_context)

        manager.generate_variables(mock_context)

        manager.generate_conversation_turn_variables.assert_called_once_with(
            originalMessages=mock_context.messages,
            llm_handler=mock_context.llm_handler,
            remove_all_system_override=None,
            add_role_tags=True,
            separator='\n\n',
            token_limit=None
        )


# --- TESTS FOR SENTINEL TOKEN RESTORATION ---

class TestSentinelTokenRestoration:
    """Tests that apply_variables restores __WILMER_L_CURLY__ and __WILMER_R_CURLY__
    sentinel tokens back to real curly braces in all code paths.

    The gateway replaces { and } with sentinel tokens to protect them from str.format().
    After variable substitution is complete, apply_variables must restore them so that
    downstream consumers (SaveCustomFile, LLM prompts, etc.) see real braces.
    """

    def test_standard_format_restores_sentinels_in_variable_values(self, mocker, mock_context):
        """Tests that sentinel tokens inside variable values are restored to real braces."""
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_variables', return_value={
            'chat_user_prompt_last_one': (
                'Here is some JSON: __WILMER_L_CURLY__"key": "value"__WILMER_R_CURLY__'
            )
        })
        mock_context.config = {'jinja2': False}
        prompt = "{chat_user_prompt_last_one}"

        result = manager.apply_variables(prompt, mock_context)

        assert result == 'Here is some JSON: {"key": "value"}'
        assert '__WILMER_L_CURLY__' not in result
        assert '__WILMER_R_CURLY__' not in result

    def test_standard_format_restores_sentinels_in_static_text(self, mocker, mock_context):
        """Tests that sentinel tokens in the prompt template itself are restored."""
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_variables', return_value={
            'name': 'Wilmer'
        })
        mock_context.config = {'jinja2': False}
        prompt = "Hello {name}, here is a brace: __WILMER_L_CURLY____WILMER_R_CURLY__"

        result = manager.apply_variables(prompt, mock_context)

        assert result == "Hello Wilmer, here is a brace: {}"

    def test_jinja2_path_restores_sentinels(self, mocker, mock_context):
        """Tests that sentinel tokens are restored when using the Jinja2 path."""
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_variables', return_value={
            'content': 'JSON: __WILMER_L_CURLY__"a": 1__WILMER_R_CURLY__'
        })
        mock_context.config = {'jinja2': True}
        mock_context.messages = []
        prompt = "Data: {{ content }}"

        result = manager.apply_variables(prompt, mock_context)

        assert result == 'Data: JSON: {"a": 1}'
        assert '__WILMER_L_CURLY__' not in result

    def test_keyerror_fallback_restores_sentinels(self, mocker, mock_context):
        """Tests that sentinel tokens are restored even when str.format() hits a KeyError."""
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.logger.warning')
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_variables', return_value={
            'name': 'Wilmer'
        })
        mock_context.config = {'jinja2': False}
        # {undefined_key} will cause a KeyError; the fallback returns the original prompt
        prompt = "Hello {name}, __WILMER_L_CURLY__data__WILMER_R_CURLY__ and {undefined_key}"

        result = manager.apply_variables(prompt, mock_context)

        # The KeyError fallback returns the original prompt with sentinels restored
        assert '__WILMER_L_CURLY__' not in result
        assert '__WILMER_R_CURLY__' not in result
        assert '{data}' in result

    def test_nested_variable_with_sentinels(self, mocker, mock_context):
        """Tests sentinel restoration when the second format pass resolves nested variables
        that contain sentinel tokens."""
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_variables', return_value={
            'my_template': 'func(__WILMER_L_CURLY____WILMER_R_CURLY__) called with {name}',
            'name': 'test'
        })
        mock_context.config = {'jinja2': False}
        prompt = "{my_template}"

        result = manager.apply_variables(prompt, mock_context)

        assert result == "func({}) called with test"

    def test_real_world_savecustomfile_scenario(self, mocker, mock_context):
        """Tests the exact bug scenario: chat_user_prompt_last_one contains a JSON/code
        payload where all curly braces were replaced with sentinel tokens by the gateway."""
        manager = WorkflowVariableManager()

        # Simulate what the gateway does to a message containing JSON
        sanitized_content = (
            '__WILMER_L_CURLY__\n'
            '  "nodes": [\n'
            '    __WILMER_L_CURLY__\n'
            '      "title": "Respond",\n'
            '      "type": "Standard"\n'
            '    __WILMER_R_CURLY__\n'
            '  ]\n'
            '__WILMER_R_CURLY__'
        )
        mocker.patch.object(manager, 'generate_variables', return_value={
            'chat_user_prompt_last_one': sanitized_content
        })
        mock_context.config = {'jinja2': False}
        prompt = "{chat_user_prompt_last_one}"

        result = manager.apply_variables(prompt, mock_context)

        expected = (
            '{\n'
            '  "nodes": [\n'
            '    {\n'
            '      "title": "Respond",\n'
            '      "type": "Standard"\n'
            '    }\n'
            '  ]\n'
            '}'
        )
        assert result == expected

    def test_no_sentinels_returns_unchanged(self, mocker, mock_context):
        """Tests that strings without sentinel tokens pass through unmodified."""
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_variables', return_value={
            'name': 'Wilmer'
        })
        mock_context.config = {'jinja2': False}
        prompt = "Hello {name}, no sentinels here."

        result = manager.apply_variables(prompt, mock_context)

        assert result == "Hello Wilmer, no sentinels here."

    def test_double_restore_is_idempotent(self, mocker, mock_context):
        """Tests that restoring sentinels on a string that already has real braces is safe.
        This matters because the LLM path calls return_brackets again in
        base_chat_completions_handler.py."""
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_variables', return_value={
            'data': 'already has {real} braces and __WILMER_L_CURLY__sentinel__WILMER_R_CURLY__'
        })
        mock_context.config = {'jinja2': False}
        prompt = "{data}"

        result = manager.apply_variables(prompt, mock_context)

        assert result == "already has {real} braces and {sentinel}"


class TestIncludeToolCallsInConversation:
    """Tests for the includeToolCallsInConversation node property."""

    @staticmethod
    def _apply_template_mocks(mocker):
        """Applies standard mocks for template-loading functions that would hit disk."""
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_chat_template_name',
            return_value="chat"
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.format_system_prompts',
            return_value={}
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string',
            return_value="templated"
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_by_estimated_token_limit_as_string',
            return_value="templated"
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_with_min_messages_and_token_limit_as_string',
            return_value="templated"
        )

    def test_tool_calls_included_when_enabled(self, mock_context, mocker):
        """When includeToolCallsInConversation is true, tool call text appears in conversation variables."""
        self._apply_template_mocks(mocker)
        mock_context.config = {"jinja2": False, "includeToolCallsInConversation": True}
        mock_context.messages = [
            {"role": "user", "content": "Run ls"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "bash", "arguments": '{"command": "ls -la"}'}}
            ]},
            {"role": "tool", "content": "file1.txt\nfile2.txt"},
            {"role": "user", "content": "Thanks"}
        ]
        manager = WorkflowVariableManager()
        variables = manager.generate_variables(mock_context)
        assert "Thanks" in variables.get("chat_user_prompt_last_one", "")
        last_four = variables.get("chat_user_prompt_last_four", "")
        assert "[Tool Call: bash] ls -la" in last_four

    def test_tool_calls_excluded_by_default(self, mock_context, mocker):
        """When includeToolCallsInConversation is not set, tool call messages remain empty."""
        self._apply_template_mocks(mocker)
        mock_context.config = {"jinja2": False}
        mock_context.messages = [
            {"role": "user", "content": "Run ls"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "bash", "arguments": '{"command": "ls -la"}'}}
            ]},
            {"role": "user", "content": "Thanks"}
        ]
        manager = WorkflowVariableManager()
        variables = manager.generate_variables(mock_context)
        last_three = variables.get("chat_user_prompt_last_three", "")
        assert "[Tool Call:" not in last_three

    def test_tool_calls_excluded_when_false(self, mock_context, mocker):
        """Explicitly setting includeToolCallsInConversation to false leaves tool calls out."""
        self._apply_template_mocks(mocker)
        mock_context.config = {"jinja2": False, "includeToolCallsInConversation": False}
        mock_context.messages = [
            {"role": "user", "content": "Run ls"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "bash", "arguments": '{"command": "ls -la"}'}}
            ]},
            {"role": "user", "content": "Thanks"}
        ]
        manager = WorkflowVariableManager()
        variables = manager.generate_variables(mock_context)
        last_three = variables.get("chat_user_prompt_last_three", "")
        assert "[Tool Call:" not in last_three

    def test_tool_calls_appended_to_existing_content(self, mock_context, mocker):
        """When an assistant message has both content and tool_calls, both are present."""
        self._apply_template_mocks(mocker)
        mock_context.config = {"jinja2": False, "includeToolCallsInConversation": True}
        mock_context.messages = [
            {"role": "user", "content": "Check something"},
            {"role": "assistant", "content": "Sure, checking now.", "tool_calls": [
                {"function": {"name": "bash", "arguments": '{"command": "git status"}'}}
            ]}
        ]
        manager = WorkflowVariableManager()
        variables = manager.generate_variables(mock_context)
        last_two = variables.get("chat_user_prompt_last_two", "")
        assert "Sure, checking now." in last_two
        assert "[Tool Call: bash] git status" in last_two

    def test_original_messages_not_mutated(self, mock_context, mocker):
        """Enabling tool call inclusion must not mutate context.messages."""
        self._apply_template_mocks(mocker)
        original_messages = [
            {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "bash", "arguments": '{"command": "pwd"}'}}
            ]},
            {"role": "user", "content": "Done"}
        ]
        mock_context.config = {"jinja2": False, "includeToolCallsInConversation": True}
        mock_context.messages = original_messages
        manager = WorkflowVariableManager()
        manager.generate_variables(mock_context)
        assert original_messages[0]["content"] == ""

    def test_configurable_variables_also_enriched(self, mock_context, mocker):
        """The min_n_max_tokens and other configurable variables also receive tool call enrichment."""
        self._apply_template_mocks(mocker)
        mock_context.config = {
            "jinja2": False,
            "includeToolCallsInConversation": True,
            "minMessagesInVariable": 2,
            "maxEstimatedTokensInVariable": 10000
        }
        mock_context.messages = [
            {"role": "user", "content": "Do it"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"function": {"name": "write", "arguments": '{"filePath": "/tmp/out.txt"}'}}
            ]},
            {"role": "user", "content": "OK"}
        ]
        manager = WorkflowVariableManager()
        variables = manager.generate_variables(mock_context, prompt="{chat_user_prompt_min_n_max_tokens}")
        combo_var = variables.get("chat_user_prompt_min_n_max_tokens", "")
        assert "[Tool Call: write] /tmp/out.txt" in combo_var


# ---------------------------------------------------------------------------
# Comprehensive bracket-escaping scenario tests
# ---------------------------------------------------------------------------
# These tests are written from the perspective of "how should the system
# behave" rather than "what does the code do".  They cover the full
# lifecycle: gateway escaping, variable generation, variable substitution,
# conversation variables with and without tool calls, agent outputs from
# file-save/load round trips, the Jinja2 path, and apply_early_variables.
# ---------------------------------------------------------------------------

class TestBracketEscaping_AgentOutputs:
    """Agent outputs may contain arbitrary text including JSON, code, and tool
    call data.  The variable system must substitute them into prompts without
    crashing and with the original braces intact in the final output."""

    @staticmethod
    def _make_variables(manager, mock_context, agent_outputs, agent_inputs=None):
        """Helper: call generate_variables with messages=None to isolate agent output escaping."""
        mock_context.agent_outputs = agent_outputs
        mock_context.agent_inputs = agent_inputs
        mock_context.messages = None
        return manager.generate_variables(mock_context)

    def test_simple_json_object(self, mocker, mock_context):
        """A plain JSON object in an agent output should not break formatting."""
        manager = WorkflowVariableManager()
        variables = self._make_variables(manager, mock_context, {
            "agent1Output": '{"status": "ok", "count": 42}'
        })
        mocker.patch.object(manager, 'generate_variables', return_value=variables)
        mock_context.config = {"jinja2": False}

        result = manager.apply_variables("Response: {agent1Output}", mock_context)
        assert result == 'Response: {"status": "ok", "count": 42}'

    def test_nested_json(self, mocker, mock_context):
        """Deeply nested JSON with arrays should survive substitution."""
        original = '{"data": {"items": [{"id": 1}, {"id": 2}], "meta": {"page": 1}}}'
        manager = WorkflowVariableManager()
        variables = self._make_variables(manager, mock_context, {"agent1Output": original})
        mocker.patch.object(manager, 'generate_variables', return_value=variables)
        mock_context.config = {"jinja2": False}

        result = manager.apply_variables("{agent1Output}", mock_context)
        assert result == original

    def test_tool_call_response_json(self, mocker, mock_context):
        """The exact JSON structure from a tool call response should survive."""
        tool_json = '{"function": {"name": "bash", "arguments": "{\\"command\\": \\"ls -la\\"}"}}'
        manager = WorkflowVariableManager()
        variables = self._make_variables(manager, mock_context, {"agent1Output": tool_json})
        mocker.patch.object(manager, 'generate_variables', return_value=variables)
        mock_context.config = {"jinja2": False}

        result = manager.apply_variables("Tool result: {agent1Output}", mock_context)
        assert tool_json in result

    def test_python_code_with_braces(self, mocker, mock_context):
        """Python code containing dict/set literals should not break formatting."""
        code = 'data = {"key": value}\nfor item in items:\n    result = {item: process(item)}'
        manager = WorkflowVariableManager()
        variables = self._make_variables(manager, mock_context, {"agent1Output": code})
        mocker.patch.object(manager, 'generate_variables', return_value=variables)
        mock_context.config = {"jinja2": False}

        result = manager.apply_variables("{agent1Output}", mock_context)
        assert result == code

    def test_empty_braces_in_output(self, mocker, mock_context):
        """Empty brace pairs (common in code) should survive."""
        manager = WorkflowVariableManager()
        variables = self._make_variables(manager, mock_context, {
            "agent1Output": "result = {}"
        })
        mocker.patch.object(manager, 'generate_variables', return_value=variables)
        mock_context.config = {"jinja2": False}

        result = manager.apply_variables("{agent1Output}", mock_context)
        assert result == "result = {}"

    def test_single_open_brace(self, mocker, mock_context):
        """An unmatched open brace should not cause a ValueError."""
        manager = WorkflowVariableManager()
        variables = self._make_variables(manager, mock_context, {
            "agent1Output": "incomplete { brace"
        })
        mocker.patch.object(manager, 'generate_variables', return_value=variables)
        mock_context.config = {"jinja2": False}

        result = manager.apply_variables("{agent1Output}", mock_context)
        assert result == "incomplete { brace"

    def test_single_close_brace(self, mocker, mock_context):
        """An unmatched close brace should not cause a ValueError."""
        manager = WorkflowVariableManager()
        variables = self._make_variables(manager, mock_context, {
            "agent1Output": "incomplete } brace"
        })
        mocker.patch.object(manager, 'generate_variables', return_value=variables)
        mock_context.config = {"jinja2": False}

        result = manager.apply_variables("{agent1Output}", mock_context)
        assert result == "incomplete } brace"

    def test_multiple_outputs_mixed(self, mocker, mock_context):
        """Multiple agent outputs, some with braces and some without, should all resolve."""
        manager = WorkflowVariableManager()
        variables = self._make_variables(manager, mock_context, {
            "agent1Output": '{"json": true}',
            "agent2Output": "plain text no braces",
            "agent3Output": 'code: if x { return y; }'
        })
        mocker.patch.object(manager, 'generate_variables', return_value=variables)
        mock_context.config = {"jinja2": False}

        result = manager.apply_variables(
            "A: {agent1Output} | B: {agent2Output} | C: {agent3Output}", mock_context
        )
        assert '{"json": true}' in result
        assert "plain text no braces" in result
        assert "code: if x { return y; }" in result

    def test_output_that_looks_like_variable_reference(self, mocker, mock_context):
        """An agent output containing text like '{agent2Output}' should be treated as
        literal text, not as a variable reference on the second format pass."""
        manager = WorkflowVariableManager()
        variables = self._make_variables(manager, mock_context, {
            "agent1Output": "See {agent2Output} for details",
            "agent2Output": "SHOULD NOT APPEAR"
        })
        mocker.patch.object(manager, 'generate_variables', return_value=variables)
        mock_context.config = {"jinja2": False}

        result = manager.apply_variables("{agent1Output}", mock_context)
        # The braces in the value are literal, not a reference to agent2Output
        assert result == "See {agent2Output} for details"
        assert "SHOULD NOT APPEAR" not in result

    def test_output_with_empty_string(self, mocker, mock_context):
        """An empty string output should resolve to empty, not crash."""
        manager = WorkflowVariableManager()
        variables = self._make_variables(manager, mock_context, {"agent1Output": ""})
        mocker.patch.object(manager, 'generate_variables', return_value=variables)
        mock_context.config = {"jinja2": False}

        result = manager.apply_variables("Before:{agent1Output}:After", mock_context)
        assert result == "Before::After"

    def test_output_with_only_braces(self, mocker, mock_context):
        """Output that is nothing but braces should survive."""
        manager = WorkflowVariableManager()
        variables = self._make_variables(manager, mock_context, {"agent1Output": "{{{}}}"})
        mocker.patch.object(manager, 'generate_variables', return_value=variables)
        mock_context.config = {"jinja2": False}

        result = manager.apply_variables("{agent1Output}", mock_context)
        assert result == "{{{}}}"

    def test_non_string_output_passes_through(self, mock_context):
        """Non-string outputs (e.g., int) should not be escaped, just passed through."""
        manager = WorkflowVariableManager()
        mock_context.agent_outputs = {"agent1Output": 42}
        mock_context.agent_inputs = None
        mock_context.messages = None
        variables = manager.generate_variables(mock_context)
        assert variables["agent1Output"] == 42


class TestBracketEscaping_AgentInputs:
    """Agent inputs from parent workflows may pass structured data. The same
    escaping guarantees apply."""

    def test_json_input_from_parent(self, mocker, mock_context):
        """JSON passed as a scoped input should survive substitution."""
        payload = '{"endpoint": "fast", "options": {"stream": true}}'
        manager = WorkflowVariableManager()
        mock_context.agent_outputs = {}
        mock_context.agent_inputs = {"agent1Input": payload}
        mock_context.messages = None
        variables = manager.generate_variables(mock_context)

        mocker.patch.object(manager, 'generate_variables', return_value=variables)
        mock_context.config = {"jinja2": False}
        result = manager.apply_variables("Config: {agent1Input}", mock_context)
        assert result == f"Config: {payload}"

    def test_plain_text_input_unchanged(self, mocker, mock_context):
        """Plain text inputs without braces are unaffected by escaping."""
        manager = WorkflowVariableManager()
        mock_context.agent_outputs = {}
        mock_context.agent_inputs = {"agent1Input": "MyEndpoint"}
        mock_context.messages = None
        variables = manager.generate_variables(mock_context)

        mocker.patch.object(manager, 'generate_variables', return_value=variables)
        mock_context.config = {"jinja2": False}
        result = manager.apply_variables("{agent1Input}", mock_context)
        assert result == "MyEndpoint"

    def test_input_and_output_both_have_braces(self, mocker, mock_context):
        """Both inputs and outputs containing braces should resolve independently."""
        manager = WorkflowVariableManager()
        mock_context.agent_outputs = {"agent1Output": '{"from": "output"}'}
        mock_context.agent_inputs = {"agent1Input": '{"from": "input"}'}
        mock_context.messages = None
        variables = manager.generate_variables(mock_context)

        mocker.patch.object(manager, 'generate_variables', return_value=variables)
        mock_context.config = {"jinja2": False}
        result = manager.apply_variables(
            "Output={agent1Output} Input={agent1Input}", mock_context
        )
        assert '{"from": "output"}' in result
        assert '{"from": "input"}' in result


class TestBracketEscaping_Jinja2Path:
    """The Jinja2 rendering path should handle sentinel tokens the same way
    as the str.format() path."""

    def test_json_in_agent_output_via_jinja2(self, mocker, mock_context):
        """JSON braces in an agent output should appear correctly after Jinja2 rendering."""
        json_val = '{"result": [1, 2, 3]}'
        escaped = json_val.replace("{", "__WILMER_L_CURLY__").replace("}", "__WILMER_R_CURLY__")
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_variables', return_value={
            "agent1Output": escaped
        })
        mock_context.config = {"jinja2": True}
        mock_context.messages = []

        result = manager.apply_variables("Data: {{ agent1Output }}", mock_context)
        assert result == f"Data: {json_val}"

    def test_jinja2_loop_with_escaped_content(self, mocker, mock_context):
        """A Jinja2 loop rendering messages whose content contains sentinel tokens
        should produce output with real braces."""
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_variables', return_value={})
        mock_context.config = {"jinja2": True}
        mock_context.messages = [
            {"role": "user", "content": "Show __WILMER_L_CURLY__data__WILMER_R_CURLY__"}
        ]

        prompt = "{% for m in messages %}{{ m.content }}{% endfor %}"
        result = manager.apply_variables(prompt, mock_context)
        assert result == "Show {data}"

    def test_jinja2_conditional_with_braces_in_value(self, mocker, mock_context):
        """Jinja2 conditionals should work even when variable values contain braces."""
        escaped = "__WILMER_L_CURLY__ok__WILMER_R_CURLY__"
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_variables', return_value={
            "status": escaped
        })
        mock_context.config = {"jinja2": True}
        mock_context.messages = []

        prompt = "{% if status %}Status: {{ status }}{% endif %}"
        result = manager.apply_variables(prompt, mock_context)
        assert result == "Status: {ok}"


class TestBracketEscaping_ConversationVariables:
    """Conversation variables are built from message content. The gateway escapes
    user message braces at ingestion. When tool calls are enriched, the injected
    text must also be safe for str.format()."""

    @staticmethod
    def _apply_template_mocks(mocker):
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_chat_template_name',
            return_value="chat"
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.format_system_prompts',
            return_value={}
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string',
            return_value="templated"
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_by_estimated_token_limit_as_string',
            return_value="templated"
        )
        mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_with_min_messages_and_token_limit_as_string',
            return_value="templated"
        )

    def test_gateway_escaped_message_flows_through(self, mocker, mock_context):
        """A user message whose braces were gateway-escaped should appear with real
        braces in the final prompt output."""
        self._apply_template_mocks(mocker)
        manager = WorkflowVariableManager()
        # Simulate what the gateway does: { → __WILMER_L_CURLY__
        mock_context.messages = [
            {"role": "user", "content": "Here is JSON: __WILMER_L_CURLY__\"a\": 1__WILMER_R_CURLY__"}
        ]
        mock_context.config = {"jinja2": False}

        variables = manager.generate_variables(mock_context)
        last_one = variables["chat_user_prompt_last_one"]

        # The variable value should still have sentinels (not yet restored)
        assert "__WILMER_L_CURLY__" in last_one

        # Full apply_variables should restore them
        mocker.patch.object(manager, 'generate_variables', return_value=variables)
        result = manager.apply_variables("{chat_user_prompt_last_one}", mock_context)
        assert '"a": 1' in result
        assert "{" in result  # Real braces restored

    def test_conversation_without_tool_calls_no_braces(self, mocker, mock_context):
        """A normal conversation without tool calls or JSON should pass through cleanly."""
        self._apply_template_mocks(mocker)
        manager = WorkflowVariableManager()
        mock_context.messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"}
        ]
        mock_context.config = {"jinja2": False}

        variables = manager.generate_variables(mock_context)
        mocker.patch.object(manager, 'generate_variables', return_value=variables)
        result = manager.apply_variables("Chat: {chat_user_prompt_last_three}", mock_context)
        assert "Hello" in result
        assert "Hi there!" in result
        assert "How are you?" in result

    def test_tool_call_with_json_args_in_conversation(self, mocker, mock_context):
        """When includeToolCallsInConversation is enabled and a tool call has JSON
        arguments that fall back to raw display, the braces should not break formatting."""
        self._apply_template_mocks(mocker)
        manager = WorkflowVariableManager()
        mock_context.config = {"jinja2": False, "includeToolCallsInConversation": True}
        # This tool call has no string-valued args, so _summarize_tool_arguments
        # falls back to the raw JSON string which contains braces.
        mock_context.messages = [
            {"role": "user", "content": "Process data"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "transform", "arguments": '{"nested": {"deep": true}}'}}
            ]},
            {"role": "user", "content": "Done"}
        ]

        variables = manager.generate_variables(mock_context)
        last_three = variables["chat_user_prompt_last_three"]
        # The tool call text should be present (sentinel-escaped internally)
        assert "[Tool Call: transform]" in last_three

        # Full apply_variables round-trip should not crash
        mocker.patch.object(manager, 'generate_variables', return_value=variables)
        result = manager.apply_variables("Conversation:\n{chat_user_prompt_last_three}", mock_context)
        assert "Conversation:" in result
        assert "[Tool Call: transform]" in result

    def test_tool_call_with_string_args_no_braces_in_summary(self, mocker, mock_context):
        """When tool call args have a string field, the summary uses that field and
        typically has no braces. This should work as before."""
        self._apply_template_mocks(mocker)
        manager = WorkflowVariableManager()
        mock_context.config = {"jinja2": False, "includeToolCallsInConversation": True}
        mock_context.messages = [
            {"role": "user", "content": "List files"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "bash", "arguments": '{"command": "ls -la"}'}}
            ]},
            {"role": "user", "content": "Thanks"}
        ]

        variables = manager.generate_variables(mock_context)
        mocker.patch.object(manager, 'generate_variables', return_value=variables)
        result = manager.apply_variables("{chat_user_prompt_last_three}", mock_context)
        assert "[Tool Call: bash] ls -la" in result

    def test_multiple_tool_calls_mixed_arg_types(self, mocker, mock_context):
        """Multiple tool calls in one message: some with string args (no braces in summary),
        some with only non-string args (raw JSON in summary with braces)."""
        self._apply_template_mocks(mocker)
        manager = WorkflowVariableManager()
        mock_context.config = {"jinja2": False, "includeToolCallsInConversation": True}
        mock_context.messages = [
            {"role": "user", "content": "Do both"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "bash", "arguments": '{"command": "pwd"}'}},
                {"function": {"name": "config", "arguments": '{"retries": 3, "timeout": 30}'}}
            ]},
            {"role": "user", "content": "OK"}
        ]

        variables = manager.generate_variables(mock_context)
        mocker.patch.object(manager, 'generate_variables', return_value=variables)
        result = manager.apply_variables("{chat_user_prompt_last_three}", mock_context)
        assert "[Tool Call: bash] pwd" in result
        assert "[Tool Call: config]" in result

    def test_tool_role_messages_dont_break_formatting(self, mocker, mock_context):
        """Tool-role messages (function results) may contain JSON. The gateway
        escapes their content, so they should be safe in conversation variables."""
        self._apply_template_mocks(mocker)
        manager = WorkflowVariableManager()
        mock_context.config = {"jinja2": False}
        mock_context.messages = [
            {"role": "user", "content": "Run it"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"function": {"name": "api", "arguments": '{"url": "/data"}'}}
            ]},
            {"role": "tool", "content": "__WILMER_L_CURLY__\"result\": \"success\"__WILMER_R_CURLY__"},
            {"role": "user", "content": "Great"}
        ]

        variables = manager.generate_variables(mock_context)
        mocker.patch.object(manager, 'generate_variables', return_value=variables)
        # Should not crash
        result = manager.apply_variables("{chat_user_prompt_last_four}", mock_context)
        assert "Great" in result


class TestBracketEscaping_FileRoundTrip:
    """Simulates the SaveCustomFile → GetCustomFile cycle. SaveCustomFile calls
    apply_variables (which restores braces) then writes to disk. GetCustomFile
    reads the file and returns the raw content (with real braces). That content
    becomes an agent output and must be re-escaped for the next node."""

    def test_save_then_load_cycle(self, mocker, mock_context):
        """Content with braces should survive a save→load→reuse cycle."""
        manager = WorkflowVariableManager()
        json_content = '{"saved": {"nested": true}}'

        # Step 1: Node 1 produces the JSON as agent1Output.
        # generate_variables escapes it.
        mock_context.agent_outputs = {"agent1Output": json_content}
        mock_context.agent_inputs = None
        mock_context.messages = None
        mock_context.config = {"jinja2": False}

        # apply_variables calls the real generate_variables (which escapes),
        # then restores braces in the final output.
        saved_content = manager.apply_variables("{agent1Output}", mock_context)
        assert saved_content == json_content  # Real braces, as written to file

        # Step 2: GetCustomFile reads the file (real braces). This becomes agent2Output.
        # The next node's generate_variables must re-escape it.
        mock_context.agent_outputs = {"agent2Output": saved_content}
        variables_step2 = manager.generate_variables(mock_context)
        assert "__WILMER_L_CURLY__" in variables_step2["agent2Output"]

        # Step 3: Next node uses agent2Output — should get the original JSON back.
        final_result = manager.apply_variables("Loaded: {agent2Output}", mock_context)
        assert final_result == f"Loaded: {json_content}"

    def test_concatenator_output_reused(self, mocker, mock_context):
        """StringConcatenator calls apply_variables (restoring braces) and its return
        value becomes an agent output. The next node must handle the real braces."""
        manager = WorkflowVariableManager()
        json_part = '{"key": "value"}'
        mock_context.agent_inputs = None
        mock_context.messages = None
        mock_context.config = {"jinja2": False}

        # Step 1: StringConcatenator resolves parts via apply_variables.
        mock_context.agent_outputs = {
            "agent1Output": json_part,
            "agent2Output": "plain text"
        }
        part1 = manager.apply_variables("{agent1Output}", mock_context)
        part2 = manager.apply_variables("{agent2Output}", mock_context)
        concatenated = part1 + " | " + part2
        assert concatenated == '{"key": "value"} | plain text'

        # Step 2: Concatenated result becomes agent3Output for the next node.
        mock_context.agent_outputs = {"agent3Output": concatenated}
        final = manager.apply_variables("Final: {agent3Output}", mock_context)
        assert final == f"Final: {concatenated}"


class TestBracketEscaping_ApplyEarlyVariables:
    """apply_early_variables is used for endpointName and preset fields. It
    should handle braces in agent inputs consistently."""

    def test_agent_input_with_braces_resolves(self):
        """An agent input containing braces should resolve and restore correctly."""
        manager = WorkflowVariableManager()
        result = manager.apply_early_variables(
            "{agent1Input}",
            agent_inputs={"agent1Input": '{"endpoint": "fast"}'}
        )
        assert result == '{"endpoint": "fast"}'

    def test_plain_agent_input_unchanged(self):
        """A plain string agent input works as before."""
        manager = WorkflowVariableManager()
        result = manager.apply_early_variables(
            "{agent1Input}",
            agent_inputs={"agent1Input": "MyEndpoint"}
        )
        assert result == "MyEndpoint"

    def test_workflow_config_nested_variable_still_resolves(self):
        """Workflow config values with nested variable references must NOT be escaped,
        because they need the second format pass to resolve {Discussion_Id} etc."""
        manager = WorkflowVariableManager()
        result = manager.apply_early_variables(
            "{my_endpoint}",
            workflow_config={"my_endpoint": "data-service", "nodes": []}
        )
        assert result == "data-service"

    def test_mixed_config_and_input_with_braces(self):
        """Workflow config and agent input both present; input has braces."""
        manager = WorkflowVariableManager()
        result = manager.apply_early_variables(
            "{base}/{agent1Input}",
            agent_inputs={"agent1Input": '{"v": 2}'},
            workflow_config={"base": "https://api.local"}
        )
        assert result == 'https://api.local/{"v": 2}'

    def test_no_sentinels_leak_into_result(self):
        """The final result should never contain sentinel tokens."""
        manager = WorkflowVariableManager()
        result = manager.apply_early_variables(
            "{agent1Input}",
            agent_inputs={"agent1Input": '{"a": {"b": {"c": 1}}}'}
        )
        assert "__WILMER_L_CURLY__" not in result
        assert "__WILMER_R_CURLY__" not in result
        assert '{"a": {"b": {"c": 1}}}' == result

    def test_partial_substitution_with_braces_in_input(self, mocker):
        """When one variable is missing, partial substitution should still escape
        the available variable's braces correctly."""
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.logger.warning')
        manager = WorkflowVariableManager()
        result = manager.apply_early_variables(
            "{agent1Input}/{missing}",
            agent_inputs={"agent1Input": '{"ok": true}'}
        )
        # The available input should be substituted with braces restored;
        # the missing variable should stay as a placeholder.
        assert '{"ok": true}' in result
        assert "{missing}" in result


class TestBracketEscaping_NoDoubleMangle:
    """Strings that have already been sentinel-escaped by the gateway should
    not be mangled when they flow through agent outputs or inputs."""

    def test_already_escaped_content_in_agent_output(self, mocker, mock_context):
        """If an agent output somehow already contains sentinel tokens (e.g., a node
        that returned raw gateway-escaped content), they should be restored exactly
        once, not double-processed."""
        manager = WorkflowVariableManager()
        # This value already has sentinels — perhaps from a node that read message
        # content without restoring it first.
        sentinel_content = "data: __WILMER_L_CURLY__x__WILMER_R_CURLY__"

        mock_context.agent_outputs = {"agent1Output": sentinel_content}
        mock_context.agent_inputs = None
        mock_context.messages = None
        variables = manager.generate_variables(mock_context)

        mocker.patch.object(manager, 'generate_variables', return_value=variables)
        mock_context.config = {"jinja2": False}
        result = manager.apply_variables("{agent1Output}", mock_context)

        # The sentinels should be restored to real braces
        assert result == "data: {x}"
        assert "__WILMER_L_CURLY__" not in result

    def test_real_braces_in_output_dont_become_sentinel_in_result(self, mocker, mock_context):
        """The final output of apply_variables should always have real braces,
        never sentinel tokens, regardless of how many escaping cycles occurred."""
        manager = WorkflowVariableManager()
        mock_context.agent_outputs = {"agent1Output": '{"a": 1}'}
        mock_context.agent_inputs = None
        mock_context.messages = None
        variables = manager.generate_variables(mock_context)

        mocker.patch.object(manager, 'generate_variables', return_value=variables)
        mock_context.config = {"jinja2": False}
        result = manager.apply_variables("{agent1Output}", mock_context)

        assert "__WILMER_L_CURLY__" not in result
        assert "__WILMER_R_CURLY__" not in result
        assert result == '{"a": 1}'


class TestBracketEscaping_EdgeCases:
    """Edge cases that could trip up the escaping mechanism."""

    def test_prompt_with_no_variables_and_agent_output_has_braces(self, mocker, mock_context):
        """If the prompt has no variable references, agent output braces are irrelevant
        and the prompt should be returned as-is with sentinels restored."""
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_variables', return_value={
            "agent1Output": '{"ignored": true}'
        })
        mock_context.config = {"jinja2": False}

        result = manager.apply_variables("Static prompt, no variables.", mock_context)
        assert result == "Static prompt, no variables."

    def test_prompt_template_itself_has_sentinels(self, mocker, mock_context):
        """If the prompt template (from gateway-escaped content) contains sentinels,
        they should be restored in the output."""
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_variables', return_value={
            "name": "Wilmer"
        })
        mock_context.config = {"jinja2": False}

        prompt = "Hello {name}, code: __WILMER_L_CURLY____WILMER_R_CURLY__"
        result = manager.apply_variables(prompt, mock_context)
        assert result == "Hello Wilmer, code: {}"

    def test_very_large_json_in_agent_output(self, mocker, mock_context):
        """A large JSON blob should not cause performance issues or crashes."""
        manager = WorkflowVariableManager()
        # Build a moderately large JSON-like string
        large_json = '{"items": [' + ', '.join(
            f'{{"id": {i}, "data": {{"nested": true}}}}'
            for i in range(100)
        ) + ']}'

        mock_context.agent_outputs = {"agent1Output": large_json}
        mock_context.agent_inputs = None
        mock_context.messages = None
        variables = manager.generate_variables(mock_context)

        mocker.patch.object(manager, 'generate_variables', return_value=variables)
        mock_context.config = {"jinja2": False}
        result = manager.apply_variables("{agent1Output}", mock_context)
        assert result == large_json

    def test_workflow_config_variable_with_nested_reference_still_resolves(self, mocker, mock_context):
        """Workflow config values intentionally support nested variable references.
        A config value like 'path/{Discussion_Id}/file' must have {Discussion_Id}
        resolved on the second format pass — it must NOT be sentinel-escaped."""
        manager = WorkflowVariableManager()
        mocker.patch.object(manager, 'generate_variables', return_value={
            "my_path": "data/{Discussion_Id}/output.txt",
            "Discussion_Id": "conv-123"
        })
        mock_context.config = {"jinja2": False}

        result = manager.apply_variables("{my_path}", mock_context)
        assert result == "data/conv-123/output.txt"

    def test_agent_output_containing_format_spec_syntax(self, mocker, mock_context):
        """Output containing Python format spec syntax (e.g., {:.2f}) must not crash."""
        manager = WorkflowVariableManager()
        mock_context.agent_outputs = {"agent1Output": "Value: {:.2f}"}
        mock_context.agent_inputs = None
        mock_context.messages = None
        variables = manager.generate_variables(mock_context)

        mocker.patch.object(manager, 'generate_variables', return_value=variables)
        mock_context.config = {"jinja2": False}
        result = manager.apply_variables("{agent1Output}", mock_context)
        assert result == "Value: {:.2f}"

    def test_agent_output_containing_numbered_format_placeholders(self, mocker, mock_context):
        """Output containing {0}, {1} style placeholders must not crash."""
        manager = WorkflowVariableManager()
        mock_context.agent_outputs = {"agent1Output": "args: {0} and {1}"}
        mock_context.agent_inputs = None
        mock_context.messages = None
        variables = manager.generate_variables(mock_context)

        mocker.patch.object(manager, 'generate_variables', return_value=variables)
        mock_context.config = {"jinja2": False}
        result = manager.apply_variables("{agent1Output}", mock_context)
        assert result == "args: {0} and {1}"


class TestEstimationLevelScalingOfVariables:
    """The endpoint estimation level scales the TOKEN budgets of the token-based
    conversation variables (estimatedTokensToIncludeInVariable,
    maxEstimatedTokensInVariable), but never the message COUNTS, and only when the
    clamp is on. Conservative / clamp-off => no change (handoff Q1 + 7.1)."""

    def _stub_selectors(self, mocker, manager):
        """Stub every conversation selector so the test can inspect the budget
        argument passed to the estimated-token-limit selector in isolation."""
        mocker.patch.object(manager, 'generate_conversation_turn_variables', return_value={})
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.format_system_prompts',
                     return_value={})
        for name in ('extract_last_n_turns_as_string', 'get_formatted_last_n_turns_as_string',
                     'get_formatted_last_turns_by_estimated_token_limit_as_string',
                     'extract_last_turns_with_min_messages_and_token_limit_as_string',
                     'get_formatted_last_turns_with_min_messages_and_token_limit_as_string'):
            mocker.patch(f'Middleware.workflows.managers.workflow_variable_manager.{name}',
                         return_value="")
        return mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_by_estimated_token_limit_as_string',
            return_value="")

    def _endpoint(self, level):
        return {"maxContextTokenSize": 32768, "wilmerContextEstimationLevel": level}

    def test_aggressive_level_scales_estimated_token_budget(self, mocker, mock_context):
        """Clamp on + aggressive (1.5): 4000 -> 6000 forwarded to the selector."""
        manager = WorkflowVariableManager()
        mock_context.config = {'jinja2': False, 'estimatedTokensToIncludeInVariable': 4000,
                               'clampPromptToContextWindow': True}
        mock_context.llm_handler.llm.endpoint_file = self._endpoint('aggressive')
        mock_extract = self._stub_selectors(mocker, manager)
        manager.generate_variables(mock_context)
        mock_extract.assert_called_with(mocker.ANY, 6000, True, None, add_role_tags=False, separator='\n')

    def test_clamp_off_leaves_token_budget_raw(self, mocker, mock_context):
        """Clamp off (no flag): a non-conservative endpoint level is inert; 4000 stays 4000."""
        manager = WorkflowVariableManager()
        mock_context.config = {'jinja2': False, 'estimatedTokensToIncludeInVariable': 4000}
        mock_context.llm_handler.llm.endpoint_file = self._endpoint('aggressive')
        mock_extract = self._stub_selectors(mocker, manager)
        manager.generate_variables(mock_context)
        mock_extract.assert_called_with(mocker.ANY, 4000, True, None, add_role_tags=False, separator='\n')

    def test_conservative_level_leaves_token_budget_raw(self, mocker, mock_context):
        """Clamp on + conservative (1.0): no change (the default is a true no-op)."""
        manager = WorkflowVariableManager()
        mock_context.config = {'jinja2': False, 'estimatedTokensToIncludeInVariable': 4000,
                               'clampPromptToContextWindow': True}
        mock_context.llm_handler.llm.endpoint_file = self._endpoint('conservative')
        mock_extract = self._stub_selectors(mocker, manager)
        manager.generate_variables(mock_context)
        mock_extract.assert_called_with(mocker.ANY, 4000, True, None, add_role_tags=False, separator='\n')

    def test_min_n_max_scales_tokens_not_count(self, mocker, mock_context):
        """xaggressive (1.85) scales maxEstimatedTokensInVariable (4000 -> 7400) but
        leaves minMessagesInVariable (a message count) untouched."""
        manager = WorkflowVariableManager()
        mock_context.config = {'jinja2': False, 'minMessagesInVariable': 6,
                               'maxEstimatedTokensInVariable': 4000,
                               'clampPromptToContextWindow': True}
        mock_context.llm_handler.llm.endpoint_file = self._endpoint('xaggressive')
        self._stub_selectors(mocker, manager)
        mock_combo = mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_with_min_messages_and_token_limit_as_string',
            return_value="")
        manager.generate_variables(mock_context)
        mock_combo.assert_called_with(mocker.ANY, 6, 7400, True, None, add_role_tags=False, separator='\n',
                                      budget_overrides_min=True)

    def test_n_messages_count_is_never_scaled(self, mocker, mock_context):
        """nMessagesToIncludeInVariable is a pure message count: the level must NOT
        touch it even with the clamp on and an aggressive level."""
        manager = WorkflowVariableManager()
        mock_context.config = {'jinja2': False, 'nMessagesToIncludeInVariable': 7,
                               'clampPromptToContextWindow': True}
        mock_context.llm_handler.llm.endpoint_file = self._endpoint('xaggressive')
        self._stub_selectors(mocker, manager)
        mock_n = mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_n_turns_as_string',
            return_value="")
        manager.generate_variables(mock_context)
        # Count 7 forwarded unscaled (4th positional arg is the count).
        assert mock_n.call_args[0][1] == 7


class TestFloorYieldsToBudgetWhenClamping:
    """budget_overrides_min: with the clamp ON, the minMessagesInVariable floor for
    the min_n_max conversation variable yields to the window budget, so an
    authored-prompt node (categorizer/planner) whose floor of whole messages would
    exceed the window cannot build an over-window prompt. With the clamp OFF the
    floor stays a hard minimum (the flag is False). Regression guard for the
    re-opened context-overflow crash on those nodes."""

    def _stub_other_selectors(self, mocker, manager):
        """Stub every other selector and return the two min_n_max mocks to inspect."""
        mocker.patch.object(manager, 'generate_conversation_turn_variables', return_value={})
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.format_system_prompts',
                     return_value={})
        for name in ('extract_last_n_turns_as_string', 'get_formatted_last_n_turns_as_string',
                     'extract_last_turns_by_estimated_token_limit_as_string',
                     'get_formatted_last_turns_by_estimated_token_limit_as_string'):
            mocker.patch(f'Middleware.workflows.managers.workflow_variable_manager.{name}', return_value="")
        mock_combo = mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_with_min_messages_and_token_limit_as_string',
            return_value="")
        mock_formatted = mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_turns_with_min_messages_and_token_limit_as_string',
            return_value="")
        return mock_combo, mock_formatted

    def test_clamp_on_forwards_budget_overrides_min_true(self, mocker, mock_context):
        """Clamp on => both min_n_max selectors receive budget_overrides_min=True."""
        manager = WorkflowVariableManager()
        mock_context.config = {'jinja2': False, 'minMessagesInVariable': 10,
                               'maxEstimatedTokensInVariable': 4000,
                               'clampPromptToContextWindow': True}
        mock_context.llm_handler.llm.endpoint_file = {"maxContextTokenSize": 32768}
        mock_context.llm_handler.llm.max_tokens = 1000
        mock_combo, mock_formatted = self._stub_other_selectors(mocker, manager)
        manager.generate_variables(mock_context)
        assert mock_combo.call_args.kwargs['budget_overrides_min'] is True
        assert mock_formatted.call_args.kwargs['budget_overrides_min'] is True

    def test_clamp_off_forwards_budget_overrides_min_false(self, mocker, mock_context):
        """Clamp off (no flag) => the floor stays hard; selectors receive False."""
        manager = WorkflowVariableManager()
        mock_context.config = {'jinja2': False, 'minMessagesInVariable': 10,
                               'maxEstimatedTokensInVariable': 4000}
        mock_context.llm_handler.llm.endpoint_file = {"maxContextTokenSize": 32768}
        mock_context.llm_handler.llm.max_tokens = 1000
        mock_combo, mock_formatted = self._stub_other_selectors(mocker, manager)
        manager.generate_variables(mock_context)
        assert mock_combo.call_args.kwargs['budget_overrides_min'] is False
        assert mock_formatted.call_args.kwargs['budget_overrides_min'] is False


class TestCountVariableTokenAwareness:
    """Invariant J: the COUNT variables (chat_user_prompt_last_*, *_n_messages) become
    token-aware when the clamp is on (drop oldest WHOLE messages to fit the endpoint
    window budget OR the count, whichever is hit first), and select exactly N when the
    clamp is off / conservative. The conversation is trimmed; the authored prompt never."""

    def _chat_handler(self):
        handler = MagicMock()
        handler.prompt_template_file_name = "test_template.json"
        handler.takes_message_collection = True
        return handler

    def test_turn_variables_bounded_by_token_limit(self, mocker):
        """With a budget, every last-N slice draws from the budget-bounded conversation,
        so last_twenty and last_five collapse to the few newest messages that fit."""
        handler = self._chat_handler()
        messages = [{"role": "user", "content": f"m{i}"} for i in range(20)]
        mocker.patch('Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
                     return_value=100)
        # Avoid the real template-file load for the templated_ variables.
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string',
                     return_value="")
        result = WorkflowVariableManager.generate_conversation_turn_variables(
            messages, handler, remove_all_system_override=None, token_limit=250)
        # 100/msg, budget 250 => newest 2 survive; last_twenty == last_five == those 2.
        assert result['chat_user_prompt_last_twenty'] == "m18\nm19"
        assert result['chat_user_prompt_last_five'] == "m18\nm19"
        assert result['chat_user_prompt_last_one'] == "m19"

    def test_turn_variables_none_limit_keeps_exactly_n(self, mocker):
        """No budget (clamp off / conservative) => exactly the last N, byte-for-byte."""
        handler = self._chat_handler()
        messages = [{"role": "user", "content": f"m{i}"} for i in range(20)]
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string',
                     return_value="")
        result = WorkflowVariableManager.generate_conversation_turn_variables(
            messages, handler, remove_all_system_override=None, token_limit=None)
        assert result['chat_user_prompt_last_five'] == "m15\nm16\nm17\nm18\nm19"
        assert result['chat_user_prompt_last_twenty'].count("\n") == 19  # all 20 present

    def test_end_to_end_clamp_bounds_embedded_count_variable(self, mocker, mock_context):
        """The categorizer/planner overflow case, done right: a {chat_user_prompt_last_twenty}
        embedded in an authored prompt is bounded to the endpoint window at build time,
        so the conversation (not the authored prompt) is what gives way."""
        manager = WorkflowVariableManager()
        mock_context.messages = [{"role": "user", "content": f"m{i}"} for i in range(20)]
        mock_context.config = {'jinja2': False, 'clampPromptToContextWindow': True}
        mock_context.llm_handler.llm.endpoint_file = {"maxContextTokenSize": 1000}
        mock_context.llm_handler.llm.max_tokens = 100
        mock_context.llm_handler.takes_message_collection = True
        mock_context.llm_handler.prompt_template_file_name = "test_template.json"
        mocker.patch('Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
                     return_value=100)
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string',
                     return_value="")
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.format_system_prompts',
                     return_value={})
        variables = manager.generate_variables(mock_context, prompt="{chat_user_prompt_last_twenty}")
        # budget = (1000-100)*1.0 - 512 = 388; 100/msg => newest 3 (m17,m18,m19) survive.
        assert variables['chat_user_prompt_last_twenty'] == "m17\nm18\nm19"

    def test_end_to_end_clamp_off_keeps_full_last_twenty(self, mocker, mock_context):
        """Same setup, clamp OFF: the count variable is the full last-20 (no bounding)."""
        manager = WorkflowVariableManager()
        mock_context.messages = [{"role": "user", "content": f"m{i}"} for i in range(20)]
        mock_context.config = {'jinja2': False}  # clamp absent => off
        mock_context.llm_handler.llm.endpoint_file = {"maxContextTokenSize": 1000}
        mock_context.llm_handler.llm.max_tokens = 100
        mock_context.llm_handler.takes_message_collection = True
        mock_context.llm_handler.prompt_template_file_name = "test_template.json"
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string',
                     return_value="")
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.format_system_prompts',
                     return_value={})
        variables = manager.generate_variables(mock_context, prompt="{chat_user_prompt_last_twenty}")
        assert variables['chat_user_prompt_last_twenty'].count("\n") == 19  # all 20

    def test_end_to_end_clamp_bounds_n_messages_variable(self, mocker, mock_context):
        """The configurable {chat_user_prompt_n_messages} is bounded the same way."""
        manager = WorkflowVariableManager()
        mock_context.messages = [{"role": "user", "content": f"m{i}"} for i in range(20)]
        mock_context.config = {'jinja2': False, 'nMessagesToIncludeInVariable': 15,
                               'clampPromptToContextWindow': True}
        mock_context.llm_handler.llm.endpoint_file = {"maxContextTokenSize": 1000}
        mock_context.llm_handler.llm.max_tokens = 100
        mock_context.llm_handler.takes_message_collection = True
        mock_context.llm_handler.prompt_template_file_name = "test_template.json"
        mocker.patch('Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
                     return_value=100)
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string',
                     return_value="")
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.format_system_prompts',
                     return_value={})
        variables = manager.generate_variables(mock_context, prompt="{chat_user_prompt_n_messages}")
        # N=15 requested, but budget 388 (3 msgs) bounds it: token limit hit before count.
        assert variables['chat_user_prompt_n_messages'] == "m17\nm18\nm19"


class TestTokenVariableWindowCap:
    """Adversarial tests: the token-budget variables (estimatedTokensToIncludeInVariable,
    maxEstimatedTokensInVariable) are capped at the node's window budget when the clamp
    is on -- scaled THEN capped, gated on the clamp, never touching counts, the window
    value, or the authored prompt. budget = (window - response)*level - headroom(512).
    These exist to catch a regression before a user does."""

    # window 65536, response 20000, conservative => (65536-20000) - 512 = 45024
    BUDGET = 45024

    def _run(self, mocker, mock_context, *, config, window=65536, n_predict=20000, level=None, clamp=True):
        """Stub every selector and return (estimated_token_selector, min_n_max_selector)
        so a test can read the exact token budget each was handed."""
        manager = WorkflowVariableManager()
        cfg = {'jinja2': False}
        cfg.update(config)
        if clamp:
            cfg['clampPromptToContextWindow'] = True
        mock_context.config = cfg
        ep = {"maxContextTokenSize": window}
        if level is not None:
            ep["wilmerContextEstimationLevel"] = level
        mock_context.llm_handler.llm.endpoint_file = ep
        mock_context.llm_handler.llm.max_tokens = n_predict
        mocker.patch.object(manager, 'generate_conversation_turn_variables', return_value={})
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.format_system_prompts',
                     return_value={})
        for name in ('extract_last_n_turns_as_string', 'get_formatted_last_n_turns_as_string',
                     'get_formatted_last_turns_by_estimated_token_limit_as_string',
                     'get_formatted_last_turns_with_min_messages_and_token_limit_as_string'):
            mocker.patch(f'Middleware.workflows.managers.workflow_variable_manager.{name}', return_value="")
        est = mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_by_estimated_token_limit_as_string',
            return_value="")
        combo = mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_with_min_messages_and_token_limit_as_string',
            return_value="")
        manager.generate_variables(mock_context)
        return est, combo

    # --- the headline case the user asked about ---
    def test_huge_estimated_ceiling_capped_to_window(self, mocker, mock_context):
        est, _ = self._run(mocker, mock_context, config={'estimatedTokensToIncludeInVariable': 100000})
        assert est.call_args[0][1] == self.BUDGET

    def test_huge_max_estimated_ceiling_capped_to_window(self, mocker, mock_context):
        _, combo = self._run(mocker, mock_context,
                             config={'maxEstimatedTokensInVariable': 100000, 'minMessagesInVariable': 5})
        assert combo.call_args[0][2] == self.BUDGET  # max_tokens capped
        assert combo.call_args[0][1] == 5            # min_messages untouched

    # --- boundary probing (off-by-one around the cap) ---
    def test_ceiling_below_window_is_not_inflated(self, mocker, mock_context):
        est, _ = self._run(mocker, mock_context, config={'estimatedTokensToIncludeInVariable': 5000})
        assert est.call_args[0][1] == 5000  # cap must never RAISE a smaller ceiling

    def test_ceiling_exactly_at_budget_unchanged(self, mocker, mock_context):
        est, _ = self._run(mocker, mock_context, config={'estimatedTokensToIncludeInVariable': self.BUDGET})
        assert est.call_args[0][1] == self.BUDGET

    def test_ceiling_one_over_budget_is_capped(self, mocker, mock_context):
        est, _ = self._run(mocker, mock_context, config={'estimatedTokensToIncludeInVariable': self.BUDGET + 1})
        assert est.call_args[0][1] == self.BUDGET

    def test_ceiling_one_under_budget_unchanged(self, mocker, mock_context):
        est, _ = self._run(mocker, mock_context, config={'estimatedTokensToIncludeInVariable': self.BUDGET - 1})
        assert est.call_args[0][1] == self.BUDGET - 1

    def test_zero_ceiling_stays_zero(self, mocker, mock_context):
        est, _ = self._run(mocker, mock_context, config={'estimatedTokensToIncludeInVariable': 0})
        assert est.call_args[0][1] == 0

    # --- scaled THEN capped: the order matters ---
    def test_conservative_clamp_on_still_caps(self, mocker, mock_context):
        # The exact behavior the user expected: conservative + clamp on STILL caps 100k -> 45024.
        est, _ = self._run(mocker, mock_context,
                          config={'estimatedTokensToIncludeInVariable': 100000}, level='conservative')
        assert est.call_args[0][1] == self.BUDGET

    def test_aggressive_raises_the_cap(self, mocker, mock_context):
        # budget = int((65536-20000)*1.5) - 512; ceiling 100000*1.5=150000 -> min = budget.
        est, _ = self._run(mocker, mock_context,
                          config={'estimatedTokensToIncludeInVariable': 100000}, level='aggressive')
        assert est.call_args[0][1] == int((65536 - 20000) * 1.5) - 512

    def test_xaggressive_raises_the_cap_further(self, mocker, mock_context):
        est, _ = self._run(mocker, mock_context,
                          config={'estimatedTokensToIncludeInVariable': 100000}, level='xaggressive')
        assert est.call_args[0][1] == int((65536 - 20000) * 1.85) - 512
        # ...and strictly more than aggressive lets through.
        assert int((65536 - 20000) * 1.85) - 512 > int((65536 - 20000) * 1.5) - 512

    # --- gating: clamp off => NO cap, level inert ---
    def test_clamp_off_uses_raw_ceiling_even_huge(self, mocker, mock_context):
        est, _ = self._run(mocker, mock_context, config={'estimatedTokensToIncludeInVariable': 100000},
                          level='aggressive', clamp=False)
        assert est.call_args[0][1] == 100000  # neither scaled nor capped

    def test_clamp_off_small_ceiling_unchanged(self, mocker, mock_context):
        est, _ = self._run(mocker, mock_context, config={'estimatedTokensToIncludeInVariable': 1234},
                          clamp=False)
        assert est.call_args[0][1] == 1234

    # --- the cap tracks the response budget (Q3 basis) ---
    def test_larger_response_budget_tightens_cap(self, mocker, mock_context):
        est, _ = self._run(mocker, mock_context, config={'estimatedTokensToIncludeInVariable': 100000},
                          window=65536, n_predict=40000)
        assert est.call_args[0][1] == (65536 - 40000) - 512  # 25024

    # --- counts are sacred (never scaled, never capped) ---
    def test_absurd_min_messages_passes_through_untouched(self, mocker, mock_context):
        _, combo = self._run(mocker, mock_context,
                             config={'maxEstimatedTokensInVariable': 100000, 'minMessagesInVariable': 9999})
        assert combo.call_args[0][1] == 9999       # count untouched
        assert combo.call_args[0][2] == self.BUDGET  # token budget capped

    # --- the window value itself is never mutated ---
    def test_window_value_not_mutated(self, mocker, mock_context):
        self._run(mocker, mock_context, config={'estimatedTokensToIncludeInVariable': 100000}, level='aggressive')
        assert mock_context.llm_handler.llm.endpoint_file['maxContextTokenSize'] == 65536

    # --- misconfig: response > window => negative budget, passed through (selector keeps 1, no crash) ---
    def test_negative_budget_passed_through(self, mocker, mock_context):
        est, _ = self._run(mocker, mock_context, config={'estimatedTokensToIncludeInVariable': 100000},
                          window=1000, n_predict=2000)
        assert est.call_args[0][1] == (1000 - 2000) - 512  # -1512

    # --- mocked endpoint (no real window) disables the cap entirely ---
    def test_no_window_no_cap(self, mocker, mock_context):
        # endpoint_file left as a Mock (not a dict) -> budget None -> raw ceiling.
        manager = WorkflowVariableManager()
        mock_context.config = {'jinja2': False, 'estimatedTokensToIncludeInVariable': 100000,
                               'clampPromptToContextWindow': True}
        mocker.patch.object(manager, 'generate_conversation_turn_variables', return_value={})
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.format_system_prompts',
                     return_value={})
        for name in ('extract_last_n_turns_as_string', 'get_formatted_last_n_turns_as_string',
                     'get_formatted_last_turns_by_estimated_token_limit_as_string',
                     'extract_last_turns_with_min_messages_and_token_limit_as_string',
                     'get_formatted_last_turns_with_min_messages_and_token_limit_as_string'):
            mocker.patch(f'Middleware.workflows.managers.workflow_variable_manager.{name}', return_value="")
        est = mocker.patch(
            'Middleware.workflows.managers.workflow_variable_manager.extract_last_turns_by_estimated_token_limit_as_string',
            return_value="")
        manager.generate_variables(mock_context)
        assert est.call_args[0][1] == 100000  # clamp on but window unknown -> no cap

    # --- end-to-end with the REAL selectors + real messages ---
    def _e2e(self, mocker, mock_context, *, config, prompt, window, n_predict,
             level=None, clamp=True, per_msg=100, n=30):
        manager = WorkflowVariableManager()
        cfg = {'jinja2': False}
        cfg.update(config)
        if clamp:
            cfg['clampPromptToContextWindow'] = True
        mock_context.config = cfg
        ep = {"maxContextTokenSize": window}
        if level is not None:
            ep["wilmerContextEstimationLevel"] = level
        mock_context.llm_handler.llm.endpoint_file = ep
        mock_context.llm_handler.llm.max_tokens = n_predict
        mock_context.llm_handler.takes_message_collection = True
        mock_context.llm_handler.prompt_template_file_name = "test_template.json"
        mock_context.messages = [{"role": "user", "content": f"m{i}"} for i in range(n)]
        mocker.patch('Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
                     return_value=per_msg)
        for name in ('get_formatted_last_n_turns_as_string',
                     'get_formatted_last_turns_by_estimated_token_limit_as_string',
                     'get_formatted_last_turns_with_min_messages_and_token_limit_as_string'):
            mocker.patch(f'Middleware.workflows.managers.workflow_variable_manager.{name}', return_value="")
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.format_system_prompts',
                     return_value={})
        return manager.generate_variables(mock_context, prompt=prompt)

    def test_e2e_min_n_max_capped_to_window(self, mocker, mock_context):
        # window 1000, response 100 -> budget 388; ceiling 100000 capped to 388; min 1.
        # 30 msgs @100: m29(100), m28(200), m27(300), m26 ->400>388 stop => newest 3 WHOLE.
        v = self._e2e(mocker, mock_context, prompt="{chat_user_prompt_min_n_max_tokens}",
                      config={'maxEstimatedTokensInVariable': 100000, 'minMessagesInVariable': 1},
                      window=1000, n_predict=100)
        assert v['chat_user_prompt_min_n_max_tokens'] == "m27\nm28\nm29"

    def test_e2e_estimated_token_limit_capped_to_window(self, mocker, mock_context):
        v = self._e2e(mocker, mock_context, prompt="{chat_user_prompt_estimated_token_limit}",
                      config={'estimatedTokensToIncludeInVariable': 100000},
                      window=1000, n_predict=100)
        assert v['chat_user_prompt_estimated_token_limit'] == "m27\nm28\nm29"

    def test_e2e_clamp_off_uses_full_ceiling(self, mocker, mock_context):
        # Clamp off: 100000 ceiling, 30 msgs @100 = 3000 tokens < 100000 -> ALL 30 survive.
        v = self._e2e(mocker, mock_context, prompt="{chat_user_prompt_min_n_max_tokens}",
                      config={'maxEstimatedTokensInVariable': 100000, 'minMessagesInVariable': 1},
                      window=1000, n_predict=100, clamp=False)
        assert v['chat_user_prompt_min_n_max_tokens'].count("\n") == 29  # all 30

    def test_e2e_min_messages_floor_yields_to_window_when_clamping(self, mocker, mock_context):
        # The fix: with the clamp ON, minMessagesInVariable=8 YIELDS to the window
        # budget instead of overflowing it. budget 388; 8*100=800 would overflow, so
        # only the newest messages that fit are kept (m27,m28,m29 = 300 <= 388). Whole
        # messages are dropped, conversation content is never truncated. (Pre-fix the
        # floor was honored whole and the authored prompt 400'd at the backend -- the
        # re-opened categorizer/planner context-overflow crash.)
        v = self._e2e(mocker, mock_context, prompt="{chat_user_prompt_min_n_max_tokens}",
                      config={'maxEstimatedTokensInVariable': 100000, 'minMessagesInVariable': 8},
                      window=1000, n_predict=100)
        assert v['chat_user_prompt_min_n_max_tokens'].split("\n") == [f"m{i}" for i in range(27, 30)]

    def test_e2e_min_messages_floor_hard_when_clamp_off(self, mocker, mock_context):
        # Clamp OFF: the floor is a HARD minimum (historical behavior preserved). The
        # 300 ceiling fits only 3 by tokens, but min 8 overrides it -> 8 kept whole.
        v = self._e2e(mocker, mock_context, prompt="{chat_user_prompt_min_n_max_tokens}",
                      config={'maxEstimatedTokensInVariable': 300, 'minMessagesInVariable': 8},
                      window=1000, n_predict=100, clamp=False)
        assert v['chat_user_prompt_min_n_max_tokens'].split("\n") == [f"m{i}" for i in range(22, 30)]

    def test_e2e_apply_variables_keeps_instructions_bounds_conversation(self, mocker, mock_context):
        # The whole point, under adversarial pressure: the authored instruction text is
        # byte-for-byte intact; only the embedded conversation variable shrinks to fit.
        manager = WorkflowVariableManager()
        mock_context.config = {'jinja2': False, 'maxEstimatedTokensInVariable': 100000,
                               'minMessagesInVariable': 1, 'clampPromptToContextWindow': True}
        mock_context.llm_handler.llm.endpoint_file = {"maxContextTokenSize": 1000}
        mock_context.llm_handler.llm.max_tokens = 100
        mock_context.llm_handler.takes_message_collection = True
        mock_context.llm_handler.prompt_template_file_name = "test_template.json"
        mock_context.messages = [{"role": "user", "content": f"m{i}"} for i in range(30)]
        mocker.patch('Middleware.utilities.prompt_extraction_utils.rough_estimate_token_length',
                     return_value=100)
        for name in ('get_formatted_last_n_turns_as_string',
                     'get_formatted_last_turns_by_estimated_token_limit_as_string',
                     'get_formatted_last_turns_with_min_messages_and_token_limit_as_string'):
            mocker.patch(f'Middleware.workflows.managers.workflow_variable_manager.{name}', return_value="")
        mocker.patch('Middleware.workflows.managers.workflow_variable_manager.format_system_prompts',
                     return_value={})
        template = "SAFETY RULES STAY. <c>{chat_user_prompt_min_n_max_tokens}</c> END."
        rendered = manager.apply_variables(template, mock_context)
        assert rendered.startswith("SAFETY RULES STAY. <c>")
        assert rendered.endswith("</c> END.")
        assert "m27" in rendered and "m29" in rendered   # bounded conversation present
        assert "m26" not in rendered                      # older messages dropped to fit

