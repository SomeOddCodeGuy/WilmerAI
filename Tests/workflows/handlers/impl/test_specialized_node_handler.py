# tests/workflows/handlers/impl/test_specialized_node_handler.py

from unittest.mock import MagicMock, patch

import pytest

# Dependencies to mock
from Middleware.common import instance_global_variables
# Base classes and exceptions
from Middleware.exceptions.early_termination_exception import EarlyTerminationException
from Middleware.services.locking_service import LockingService
# The refactored utility function to test
from Middleware.utilities.streaming_utils import stream_static_content
# The class to test
from Middleware.workflows.handlers.impl.specialized_node_handler import SpecializedNodeHandler
from Middleware.workflows.models.execution_context import ExecutionContext


@pytest.fixture
def mock_locking_service(mocker):
    """Mocks the LockingService class to prevent DB interactions."""
    mock_service_instance = MagicMock(spec=LockingService)
    mocker.patch(
        'Middleware.workflows.handlers.impl.specialized_node_handler.LockingService',
        return_value=mock_service_instance
    )
    return mock_service_instance


@pytest.fixture
def mock_variable_service():
    """Provides a mock for the WorkflowVariableManager."""
    mock_service = MagicMock()
    # Simplified mock for apply_variables that handles basic f-string like substitution
    mock_service.apply_variables.side_effect = lambda prompt, context: prompt.format(
        **(context.agent_inputs or {}), **(context.agent_outputs or {})
    )
    return mock_service


@pytest.fixture
def specialized_handler(mock_locking_service, mock_variable_service):
    """Provides an instance of SpecializedNodeHandler with mocked dependencies."""
    handler = SpecializedNodeHandler(
        workflow_manager=MagicMock(),
        workflow_variable_service=mock_variable_service
    )
    return handler


@pytest.fixture
def base_context(mock_variable_service):
    """Provides a basic, reusable ExecutionContext object."""
    return ExecutionContext(
        request_id="req-123",
        workflow_id="wf-abc",
        discussion_id="disc-xyz",
        config={},
        messages=[],
        stream=False,
        agent_outputs={},
        agent_inputs={},
        llm_handler=MagicMock(),
        workflow_variable_service=mock_variable_service
    )


class TestHandleRouter:
    """Tests the main 'handle' method to ensure it routes to the correct internal function."""

    @pytest.mark.parametrize("node_type, method_to_mock", [
        ("WorkflowLock", "handle_workflow_lock"),
        ("GetCustomFile", "handle_get_custom_file"),
        ("SaveCustomFile", "handle_save_custom_file"),
        ("ImageProcessor", "handle_image_processor_node"),
        ("StaticResponse", "handle_static_response"),
        ("ArithmeticProcessor", "handle_arithmetic_processor"),
        ("Conditional", "handle_conditional"),
        ("StringConcatenator", "handle_string_concatenator"),
    ])
    def test_handle_routes_to_correct_method(self, mocker, specialized_handler, base_context, node_type,
                                             method_to_mock):
        """Verifies that handle() calls the appropriate internal method based on node type."""
        mock_method = mocker.patch.object(specialized_handler, method_to_mock, return_value="mocked_return")
        base_context.config = {"type": node_type}

        result = specialized_handler.handle(base_context)

        mock_method.assert_called_once_with(base_context)
        assert result == "mocked_return"

    def test_handle_raises_for_unknown_type(self, specialized_handler, base_context):
        """Ensures a ValueError is raised for an unrecognized node type."""
        base_context.config = {"type": "UnknownType"}
        with pytest.raises(ValueError, match="Unknown specialized node type: UnknownType"):
            specialized_handler.handle(base_context)


class TestHandleWorkflowLock:
    """Tests the 'WorkflowLock' node logic."""

    def test_acquires_lock_when_not_locked(self, specialized_handler, base_context, mock_locking_service):
        """Should acquire a lock if one is not already active."""
        mock_locking_service.get_lock.return_value = False
        base_context.config = {"workflowLockId": "test-lock"}

        specialized_handler.handle_workflow_lock(base_context)

        mock_locking_service.get_lock.assert_called_once_with("test-lock")
        mock_locking_service.create_node_lock.assert_called_once_with(
            instance_global_variables.INSTANCE_ID, base_context.workflow_id, "test-lock"
        )

    def test_terminates_when_locked(self, specialized_handler, base_context, mock_locking_service):
        """Should raise EarlyTerminationException if a lock is already active."""
        mock_locking_service.get_lock.return_value = True
        base_context.config = {"workflowLockId": "test-lock"}

        with pytest.raises(EarlyTerminationException, match="Workflow is locked by test-lock"):
            specialized_handler.handle_workflow_lock(base_context)

        mock_locking_service.create_node_lock.assert_not_called()

    def test_raises_error_if_lock_id_missing(self, specialized_handler, base_context):
        """Should raise ValueError if 'workflowLockId' is missing from the config."""
        base_context.config = {}
        with pytest.raises(ValueError, match="A WorkflowLock node must have a 'workflowLockId'"):
            specialized_handler.handle_workflow_lock(base_context)


class TestHandleGetCustomFile:
    """Tests the 'GetCustomFile' node logic."""

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.load_custom_file', return_value="file content")
    def test_calls_load_custom_file_with_correct_args(self, mock_load_file, specialized_handler, base_context):
        """Should call the file utility with arguments from the node config."""
        base_context.config = {
            "filepath": "/path/to/file.txt",
            "delimiter": ";",
            "customReturnDelimiter": "\n"
        }

        result = specialized_handler.handle_get_custom_file(base_context)

        assert result == "file content"
        mock_load_file.assert_called_once_with(
            filepath="/path/to/file.txt",
            delimiter=";",
            custom_delimiter="\n"
        )

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.load_custom_file')
    def test_defaults_delimiters(self, mock_load_file, specialized_handler, base_context):
        """Should use default delimiters when they are not specified in the config."""
        base_context.config = {"filepath": "/path/to/file.txt"}

        specialized_handler.handle_get_custom_file(base_context)

        mock_load_file.assert_called_once_with(
            filepath="/path/to/file.txt",
            delimiter="\n",
            custom_delimiter="\n"
        )

    def test_returns_error_if_filepath_missing(self, specialized_handler, base_context):
        """Should return an error message if 'filepath' is missing."""
        base_context.config = {}
        result = specialized_handler.handle_get_custom_file(base_context)
        assert result == "No filepath specified"


class TestHandleSaveCustomFile:
    """Tests the 'SaveCustomFile' node logic."""

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.save_custom_file')
    def test_saves_file_successfully(self, mock_save_file, specialized_handler, base_context, mock_variable_service):
        """Should resolve variables and call the save utility."""
        base_context.config = {"filepath": "/path/save.txt", "content": "Hello {agent1Output}"}
        base_context.agent_outputs = {"agent1Output": "World"}

        # Manually resolve variables for assertion since the mock is simple
        resolved_content = base_context.config["content"].format(agent1Output="World")

        result = specialized_handler.handle_save_custom_file(base_context)

        mock_variable_service.apply_variables.assert_called_once_with(
            "Hello {agent1Output}", base_context
        )
        mock_save_file.assert_called_once_with(filepath="/path/save.txt", content=resolved_content)
        assert result == "File successfully saved to /path/save.txt"

    def test_handles_missing_filepath(self, specialized_handler, base_context):
        """Should return an error message if 'filepath' is missing."""
        base_context.config = {"content": "some content"}
        assert specialized_handler.handle_save_custom_file(base_context) == "No filepath specified"

    def test_handles_missing_content(self, specialized_handler, base_context):
        """Should return an error message if 'content' is missing."""
        base_context.config = {"filepath": "/path/save.txt"}
        assert specialized_handler.handle_save_custom_file(base_context) == "No content specified"

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.save_custom_file',
           side_effect=IOError("Disk full"))
    def test_handles_save_exception(self, mock_save_file, specialized_handler, base_context):
        """Should return a formatted error message if the save operation fails."""
        base_context.config = {"filepath": "/path/save.txt", "content": "some content"}

        result = specialized_handler.handle_save_custom_file(base_context)

        assert "Error saving file: Disk full" in result


class TestHandleImageProcessorNode:
    """Tests the 'ImageProcessor' node logic."""

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.LLMDispatchService.dispatch')
    def test_no_images_in_context(self, mock_dispatch, specialized_handler, base_context):
        """Should return a specific message and not call the LLM if no images are present."""
        base_context.messages = [{"role": "user", "content": "A message with no images."}]

        result = specialized_handler.handle_image_processor_node(base_context)

        assert result == "There were no images attached to the message"
        mock_dispatch.assert_not_called()

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.LLMDispatchService.dispatch',
           return_value="description of image 1")
    def test_processes_single_image(self, mock_dispatch, specialized_handler, base_context):
        """Should correctly process a single image message."""
        image_msg = {"role": "images", "content": "img1_data"}
        user_msg = {"role": "user", "content": "describe this"}
        base_context.messages = [user_msg, image_msg]

        result = specialized_handler.handle_image_processor_node(base_context)

        assert result == "description of image 1"
        mock_dispatch.assert_called_once()

        # Check the context passed to the dispatch service
        call_context = mock_dispatch.call_args.kwargs['context']
        assert call_context.messages == [user_msg, image_msg]
        assert mock_dispatch.call_args.kwargs['image_message'] == image_msg

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.LLMDispatchService.dispatch',
           side_effect=["desc1", "desc2"])
    def test_processes_multiple_images(self, mock_dispatch, specialized_handler, base_context):
        """Should process multiple image messages and join their descriptions."""
        image_msg1 = {"role": "images", "content": "img1_data"}
        image_msg2 = {"role": "images", "content": "img2_data"}
        user_msg = {"role": "user", "content": "describe these"}
        base_context.messages = [user_msg, image_msg1, image_msg2]

        result = specialized_handler.handle_image_processor_node(base_context)

        assert result == "desc1\n-------------\ndesc2"
        assert mock_dispatch.call_count == 2

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.LLMDispatchService.dispatch',
           return_value="desc")
    def test_add_as_user_message_true(self, mock_dispatch, specialized_handler, base_context, mock_variable_service):
        """Should insert a new user message with the description into the conversation history."""
        image_msg = {"role": "images", "content": "img_data"}
        user_msg = {"role": "user", "content": "describe this"}
        base_context.config = {"addAsUserMessage": True}
        base_context.messages = [image_msg, user_msg]

        # Mock apply_variables to just return the template for simplicity in assertion
        mock_variable_service.apply_variables.side_effect = lambda t, c: t.replace('[IMAGE_BLOCK]', 'desc')

        specialized_handler.handle_image_processor_node(base_context)

        assert len(base_context.messages) == 3
        new_message = base_context.messages[1]  # Inserted before the last message
        assert new_message["role"] == "user"
        assert "[IMAGE_BLOCK]" not in new_message["content"]
        assert "desc" in new_message["content"]


class TestHandleStaticResponse:
    """Tests the 'StaticResponse' node logic."""

    def test_non_streaming_returns_resolved_string(self, specialized_handler, base_context, mock_variable_service):
        """Should return a fully resolved string when not streaming."""
        base_context.config = {"content": "Output is {agent1Output}"}
        base_context.agent_outputs = {"agent1Output": "resolved"}
        base_context.stream = False

        result = specialized_handler.handle_static_response(base_context)

        assert isinstance(result, str)
        assert result == "Output is resolved"
        mock_variable_service.apply_variables.assert_called_once()

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.stream_static_content')
    def test_streaming_returns_generator(self, mock_streamer, specialized_handler, base_context):
        """Should return a generator from the streamer utility when streaming."""
        base_context.config = {"content": "stream this"}
        base_context.stream = True

        # Resolve content manually for assertion
        resolved_content = "stream this"

        result = specialized_handler.handle_static_response(base_context)

        assert result == mock_streamer.return_value
        mock_streamer.assert_called_once_with(resolved_content)


class TestStreamStaticContentUtil:
    """Tests the 'stream_static_content' utility function."""

    @patch('time.sleep')
    def test_streams_tokens_correctly(self, mock_sleep):
        """Should yield dictionaries for each token (word and whitespace)."""
        content = "word1 word2"
        generator = stream_static_content(content)
        results = list(generator)

        # Expects ['word1', ' ', 'word2'] + stop token
        assert len(results) == 4
        assert results[0] == {'token': 'word1', 'finish_reason': None}
        assert results[1] == {'token': ' ', 'finish_reason': None}
        assert results[2] == {'token': 'word2', 'finish_reason': None}
        assert results[3] == {'token': '', 'finish_reason': 'stop'}
        assert mock_sleep.call_count == 2  # Only for non-whitespace

    @patch('time.sleep')
    def test_streams_preserves_whitespace_and_newlines(self, mock_sleep):
        """(CORRECTED) Should correctly preserve all whitespace including spaces, tabs, and newlines."""
        content = "Line 1\n\nLine 2 \tDone."
        generator = stream_static_content(content)
        results = list(generator)

        # Expected tokens from re.split: ['Line', ' ', '1', '\n\n', 'Line', ' ', '2', ' \t', 'Done.']
        # Total tokens = 9 from split + 1 for stop token = 10
        assert len(results) == 10

        # Reconstruct the string from the generator's output to ensure it matches the original
        reconstructed_content = "".join([r['token'] for r in results if r['finish_reason'] is None])
        assert reconstructed_content == content

        # Check key tokens at their correct indices
        assert results[3] == {'token': '\n\n', 'finish_reason': None}  # Preserved newline
        assert results[6] == {'token': '2', 'finish_reason': None}
        assert results[7] == {'token': ' \t', 'finish_reason': None}  # Preserved space and tab
        assert results[9] == {'token': '', 'finish_reason': 'stop'}

        # 'Line', '1', 'Line', '2', 'Done.' -> 5 non-whitespace tokens
        assert mock_sleep.call_count == 5

    @patch('time.sleep')
    def test_streams_empty_string(self, mock_sleep):
        """Should yield a single 'stop' token for empty content."""
        content = ""
        generator = stream_static_content(content)
        results = list(generator)

        assert len(results) == 1
        assert results[0] == {'token': '', 'finish_reason': 'stop'}
        mock_sleep.assert_not_called()


class TestHandleArithmeticProcessor:
    """Tests the 'ArithmeticProcessor' node logic."""

    @pytest.mark.parametrize("expression, agent_outputs, expected", [
        ("10 + 5", {}, "15"),
        ("10.5 - 5.5", {}, "5"),  # Test float result becomes int string
        ("10 * 2.5", {}, "25"),  # Test float result becomes int string
        ("10 / 4", {}, "2.5"),
        ("-5 * 10", {}, "-50"),
        ("{val} + 2", {"val": "8"}, "10"),
        (" 20  /  -4 ", {}, "-5"),  # Test extra whitespace
    ])
    def test_valid_expressions(self, specialized_handler, base_context, mock_variable_service, expression,
                               agent_outputs, expected):
        """Should correctly evaluate valid arithmetic expressions."""
        base_context.config = {"expression": expression}
        base_context.agent_outputs = agent_outputs

        # Simulate variable replacement for this test
        mock_variable_service.apply_variables.side_effect = lambda t, c: t.format(val=c.agent_outputs.get('val'))

        result = specialized_handler.handle_arithmetic_processor(base_context)
        assert result == expected

    @pytest.mark.parametrize("expression, agent_outputs, warning_msg", [
        ("10 / 0", {}, "Division by zero"),
        ("10 ++ 5", {}, "Invalid arithmetic expression format"),
        ("ten + 5", {}, "Invalid arithmetic expression format"),
        ("{val} + 5", {"val": "text"}, "Invalid arithmetic expression format"),
    ])
    def test_invalid_expressions_return_minus_one(self, specialized_handler, base_context, mock_variable_service,
                                                  expression, agent_outputs, warning_msg):
        """Should return '-1' for invalid or erroneous expressions."""
        base_context.config = {"expression": expression}
        base_context.agent_outputs = agent_outputs

        # Simulate variable replacement for this test
        mock_variable_service.apply_variables.side_effect = lambda t, c: t.format(val=c.agent_outputs.get('val', ''))

        with patch('Middleware.workflows.handlers.impl.specialized_node_handler.logger.warning') as mock_log:
            result = specialized_handler.handle_arithmetic_processor(base_context)
            assert result == "-1"
            mock_log.assert_called_once()
            assert warning_msg in mock_log.call_args[0][0]

    def test_missing_expression_returns_minus_one(self, specialized_handler, base_context):
        """Should return '-1' if the 'expression' property is missing."""
        base_context.config = {}
        with patch('Middleware.workflows.handlers.impl.specialized_node_handler.logger.warning') as mock_log:
            result = specialized_handler.handle_arithmetic_processor(base_context)
            assert result == "-1"
            mock_log.assert_called_once_with("ArithmeticProcessor node is missing 'expression'.")


class TestHandleConditionalSimple:
    """Tests the 'Conditional' node logic for simple, single comparisons."""

    @pytest.mark.parametrize("condition_template, agent_outputs, expected", [
        # Numeric comparisons
        ("10 > 5", {}, "TRUE"),
        ("5 > 10", {}, "FALSE"),
        ("10 >= 10", {}, "TRUE"),
        ("5.5 <= 5.4", {}, "FALSE"),
        ("5 == 5.0", {}, "TRUE"),
        # String comparisons
        ("'hello' == 'hello'", {}, "TRUE"),
        ('"world" != "World"', {}, "TRUE"),
        # Variable resolution simulation
        ("{val} > 5", {"val": "10"}, "TRUE"),
        ("'{status}' == 'done'", {"status": "done"}, "TRUE"),
        ("'{status}' == 'pending'", {"status": "done"}, "FALSE"),
        # Type mismatch comparisons
        ("10 == '10'", {}, "FALSE"),
        ("5 > 'hello'", {}, "FALSE"),  # Should be handled gracefully
    ])
    def test_valid_conditions(self, specialized_handler, base_context, mock_variable_service,
                              condition_template, agent_outputs, expected):
        """Should correctly evaluate various valid conditions to TRUE or FALSE."""
        base_context.config = {"condition": condition_template}
        base_context.agent_outputs = agent_outputs
        mock_variable_service.apply_variables.side_effect = lambda t, c: t.format(
            val=c.agent_outputs.get('val'), status=c.agent_outputs.get('status'))

        result = specialized_handler.handle_conditional(base_context)
        assert result == expected

    def test_missing_condition_returns_false(self, specialized_handler, base_context):
        """Should return 'FALSE' if the 'condition' property is missing."""
        base_context.config = {}
        with patch('Middleware.workflows.handlers.impl.specialized_node_handler.logger.warning') as mock_log:
            result = specialized_handler.handle_conditional(base_context)
            assert result == "FALSE"
            mock_log.assert_called_once_with("Conditional node is missing 'condition'.")


class TestHandleConditionalComplex:
    """Tests the 'Conditional' node with complex logic (AND, OR, parentheses)."""

    @pytest.mark.parametrize("condition_template, agent_outputs, expected", [
        # Basic AND
        ("5 > 3 AND 'a' == 'a'", {}, "TRUE"),
        ("5 > 3 AND 'a' == 'b'", {}, "FALSE"),
        # Basic OR
        ("a == a OR b == a", {}, "TRUE"),
        ("a == b OR b == a", {}, "FALSE"),
        ("5 < 3 OR 'a' == 'a'", {}, "TRUE"),
        ("5 < 3 OR 'a' == 'b'", {}, "FALSE"),
        # Basic Parentheses
        ("(5 < 3) OR ('a' == 'a')", {}, "TRUE"),
        ("(2 < 3) OR ('a' == 'b')", {}, "TRUE"),
        # Case-insensitivity of operators and boolean words
        ("true AND 5 > 3", {}, "TRUE"),
        ("5 < 3 or TRUE", {}, "TRUE"),
        # Precedence (AND before OR)
        ("FALSE OR TRUE AND TRUE", {}, "TRUE"),
        ("TRUE AND FALSE OR TRUE", {}, "TRUE"),
        ("FALSE AND TRUE OR FALSE", {}, "FALSE"),
        # Parentheses to override precedence
        ("(FALSE OR TRUE) AND FALSE", {}, "FALSE"),
        ("5 > 3 AND (5 < 3 OR 1 == 1)", {}, "TRUE"),
        # Nested Parentheses
        ("((5 > 3 AND 1 == 1) OR 2 < 1) AND 'x' == 'x'", {}, "TRUE"),
        ("((5 > 3 AND 1 == 0) OR 2 < 1) AND 'x' == 'x'", {}, "FALSE"),
        # With Variables
        ("{val} > 5 AND '{status}' == 'complete'", {"val": 10, "status": "complete"}, "TRUE"),
        ("{val} > 5 AND '{status}' == 'complete'", {"val": 3, "status": "complete"}, "FALSE"),
        ("({val} > 5 OR '{status}' == 'pending') AND {is_admin}", {"val": 3, "status": "pending", "is_admin": "TRUE"},
         "TRUE"),
        # Truthiness of resolved variables
        ("{output} AND {val} > 10", {"output": "some_string", "val": 20}, "TRUE"),
        ("{output} AND {val} > 10", {"output": "", "val": 20}, "FALSE"),  # Empty string is falsy
        ("{output} OR {val} > 10", {"output": 0, "val": 5}, "FALSE"),  # 0 is falsy
    ])
    def test_complex_expressions(self, specialized_handler, base_context, mock_variable_service,
                                 condition_template, agent_outputs, expected):
        """Should correctly evaluate complex logical expressions."""
        base_context.config = {"condition": condition_template}
        base_context.agent_outputs = agent_outputs

        # Set up a more realistic mock that replaces variables
        def apply_vars_side_effect(template, context):
            return template.format(**context.agent_outputs)

        mock_variable_service.apply_variables.side_effect = apply_vars_side_effect

        result = specialized_handler.handle_conditional(base_context)
        assert result == expected

    @pytest.mark.parametrize("condition, warning_msg", [
        ("5 > 3 AND", "Syntax error: Not enough operands for 'AND'"),
        ("(5 > 3", "Mismatched parentheses: missing ')'"),
        ("5 > < 3", "Syntax error: Operator '<' must follow a single value."),
        ("5 OR AND 3", "Syntax error: Not enough operands for 'OR'"),
    ])
    def test_malformed_expressions(self, specialized_handler, base_context, mock_variable_service,
                                   condition, warning_msg):
        """Should return FALSE and log a warning for malformed expressions."""
        base_context.config = {"condition": condition}
        mock_variable_service.apply_variables.return_value = condition

        with patch('Middleware.workflows.handlers.impl.specialized_node_handler.logger.warning') as mock_log:
            result = specialized_handler.handle_conditional(base_context)
            assert result == "FALSE"
            mock_log.assert_called_once()
            assert warning_msg in mock_log.call_args[0][0]


class TestHandleStringConcatenator:
    """Tests the 'StringConcatenator' node logic."""

    @pytest.mark.parametrize("strings_template, agent_outputs, delimiter, expected", [
        # Basic cases
        (["Hello", " ", "World"], {}, "", "Hello World"),
        (["Part1", "Part2"], {}, "-", "Part1-Part2"),
        # With variables
        (["Name: {name}", "Age: {age}"], {"name": "Test", "age": 30}, "\n", "Name: Test\nAge: 30"),
        # Mixed types from JSON config
        (["Count:", 100], {}, " ", "Count: 100"),
        # Edge cases
        ([], {}, ",", ""),
        (["Single"], {}, ",", "Single"),
        # No delimiter specified (should default to empty string)
        (["A", "B", "C"], {}, None, "ABC"),
    ])
    def test_non_streaming(self, specialized_handler, base_context, mock_variable_service,
                           strings_template, agent_outputs, delimiter, expected):
        """Should correctly concatenate strings and resolve variables when not streaming."""
        config = {"strings": strings_template}
        if delimiter is not None:
            config["delimiter"] = delimiter
        base_context.config = config
        base_context.agent_outputs = agent_outputs
        base_context.stream = False

        # Set up a more realistic mock that replaces variables
        def apply_vars_side_effect(template, context):
            if isinstance(template, str):
                return template.format(**context.agent_outputs)
            return str(template)

        mock_variable_service.apply_variables.side_effect = apply_vars_side_effect

        result = specialized_handler.handle_string_concatenator(base_context)

        assert isinstance(result, str)
        assert result == expected

    @patch('Middleware.workflows.handlers.impl.specialized_node_handler.stream_static_content')
    def test_streaming(self, mock_streamer, specialized_handler, base_context, mock_variable_service):
        """Should call the streamer utility with the concatenated string when streaming."""
        base_context.config = {"strings": ["Streaming", " ", "test"], "delimiter": ""}
        base_context.stream = True

        # Mock doesn't need to be complex; just return the input
        mock_variable_service.apply_variables.side_effect = lambda t, c: t

        result = specialized_handler.handle_string_concatenator(base_context)

        # The result should be the mocked return value of the streamer
        assert result == mock_streamer.return_value
        # And the streamer should have been called with the final string
        mock_streamer.assert_called_once_with("Streaming test")

    def test_handles_non_list_strings_property(self, specialized_handler, base_context):
        """Should return an empty string if 'strings' is not a list."""
        base_context.config = {"strings": "this-is-not-a-list"}

        with patch('Middleware.workflows.handlers.impl.specialized_node_handler.logger.warning') as mock_log:
            result = specialized_handler.handle_string_concatenator(base_context)
            assert result == ""
            mock_log.assert_called_once_with("StringConcatenator 'strings' property must be a list.")
