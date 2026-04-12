import json
from unittest.mock import MagicMock, patch

import pytest

from Middleware.services.prompt_categorization_service import PromptCategorizationService


@pytest.fixture
def mock_routing_config():
    """Provides a standard, valid routing configuration dictionary."""
    return {
        "CODING": {
            "description": "Writing or editing code.",
            "workflow": "CodingWorkflow"
        },
        "TECHNICAL": {
            "description": "IT-related discussion, not code.",
            "workflow": "TechnicalWorkflow"
        }
    }


@pytest.fixture
def underscore_routing_config():
    """Provides a routing configuration with underscore-containing category keys."""
    return {
        "NEW_INSTRUCTION": {
            "description": "The human user has sent a new instruction.",
            "workflow": "NewInstructionWorkflow"
        },
        "TOOL_CONTINUATION": {
            "description": "The LLM needs to continue executing tools.",
            "workflow": "ToolContinuationWorkflow"
        }
    }


@pytest.fixture
def mixed_routing_config():
    """Provides a routing configuration mixing single-word and underscore keys."""
    return {
        "CODING": {
            "description": "Writing or editing code.",
            "workflow": "CodingWorkflow"
        },
        "NEW_INSTRUCTION": {
            "description": "A new instruction from the user.",
            "workflow": "NewInstructionWorkflow"
        },
        "TOOL_CONTINUATION": {
            "description": "Continue executing tools.",
            "workflow": "ToolContinuationWorkflow"
        },
        "GENERAL_CHAT": {
            "description": "General conversation.",
            "workflow": "GeneralChatWorkflow"
        }
    }


@pytest.fixture
def multi_underscore_routing_config():
    """Provides a routing configuration with multi-underscore category keys."""
    return {
        "DEEP_CODE_REVIEW": {
            "description": "In-depth code review.",
            "workflow": "DeepCodeReviewWorkflow"
        },
        "QUICK_BUG_FIX": {
            "description": "A quick bug fix.",
            "workflow": "QuickBugFixWorkflow"
        },
        "A_B_C_D": {
            "description": "Many underscores.",
            "workflow": "ABCDWorkflow"
        }
    }


@pytest.fixture
def underscore_service(mocker, underscore_routing_config) -> PromptCategorizationService:
    """Service initialized with underscore-containing category keys."""
    mocker.patch('Middleware.services.prompt_categorization_service.get_categories_config',
                 return_value=underscore_routing_config)
    mocker.patch('Middleware.services.prompt_categorization_service.get_max_categorization_attempts',
                 return_value=1)
    return PromptCategorizationService()


@pytest.fixture
def mixed_service(mocker, mixed_routing_config) -> PromptCategorizationService:
    """Service initialized with a mix of single-word and underscore category keys."""
    mocker.patch('Middleware.services.prompt_categorization_service.get_categories_config',
                 return_value=mixed_routing_config)
    mocker.patch('Middleware.services.prompt_categorization_service.get_max_categorization_attempts',
                 return_value=1)
    return PromptCategorizationService()


@pytest.fixture
def multi_underscore_service(mocker, multi_underscore_routing_config) -> PromptCategorizationService:
    """Service initialized with multi-underscore category keys."""
    mocker.patch('Middleware.services.prompt_categorization_service.get_categories_config',
                 return_value=multi_underscore_routing_config)
    mocker.patch('Middleware.services.prompt_categorization_service.get_max_categorization_attempts',
                 return_value=1)
    return PromptCategorizationService()


@pytest.fixture
def service(mocker, mock_routing_config) -> PromptCategorizationService:
    """
    Provides an initialized PromptCategorizationService instance with
    config dependencies already mocked out. Defaults max attempts to 1.
    """
    mocker.patch('Middleware.services.prompt_categorization_service.get_categories_config',
                 return_value=mock_routing_config)
    mocker.patch('Middleware.services.prompt_categorization_service.get_max_categorization_attempts',
                 return_value=1)
    return PromptCategorizationService()


class TestInitialization:
    """Tests the __init__ and initialize methods."""

    def test_initialize_success(self, mocker, mock_routing_config):
        """
        Verifies that the service loads and processes a valid routing config correctly.
        """
        mock_get_config = mocker.patch('Middleware.services.prompt_categorization_service.get_categories_config',
                                       return_value=mock_routing_config)

        service = PromptCategorizationService()

        mock_get_config.assert_called_once()
        assert len(service.categories) == 2
        assert service.categories["CODING"]["workflow"] == "CodingWorkflow"
        assert service.categories["TECHNICAL"]["description"] == "IT-related discussion, not code."

    def test_initialize_raises_file_not_found(self, mocker):
        """
        Ensures that a FileNotFoundError from the config utility is re-raised.
        """
        mocker.patch('Middleware.services.prompt_categorization_service.get_categories_config',
                     side_effect=FileNotFoundError)

        with pytest.raises(FileNotFoundError):
            PromptCategorizationService()

    def test_initialize_raises_json_decode_error(self, mocker):
        """
        Ensures that a JSONDecodeError from the config utility is re-raised.
        """
        mocker.patch('Middleware.services.prompt_categorization_service.get_categories_config',
                     side_effect=json.JSONDecodeError("mock error", "", 0))

        with pytest.raises(json.JSONDecodeError):
            PromptCategorizationService()


class TestStaticMethods:
    """Tests the static methods of the service."""

    @patch('Middleware.services.prompt_categorization_service.WorkflowManager.run_custom_workflow')
    def test_conversational_method(self, mock_run_workflow):
        """
        Verifies that the conversational_method correctly calls the WorkflowManager
        with the hardcoded '_DefaultWorkflow' and passes all arguments through.
        """
        messages = [{"role": "user", "content": "Hello"}]
        request_id = "req-123"
        discussion_id = "disc-456"

        PromptCategorizationService.conversational_method(messages, request_id, discussion_id, stream=True)

        mock_run_workflow.assert_called_once_with(
            workflow_name='_DefaultWorkflow',
            request_id=request_id,
            discussion_id=discussion_id,
            messages=messages,
            is_streaming=True,
            api_key=None,
            tools=None,
            tool_choice=None,
        )

    @patch('Middleware.services.prompt_categorization_service.WorkflowManager')
    @patch('Middleware.services.prompt_categorization_service.get_active_categorization_workflow_name')
    def test_configure_workflow_manager(self, mock_get_workflow_name, MockWorkflowManager):
        """
        Verifies that the helper method correctly instantiates WorkflowManager
        with the categorization workflow name and injected category data.
        """
        mock_get_workflow_name.return_value = "TestCategorizationWF"
        category_data = {"categoriesSeparatedByOr": "A or B"}

        PromptCategorizationService._configure_workflow_manager(category_data)

        mock_get_workflow_name.assert_called_once()
        MockWorkflowManager.assert_called_once_with(
            workflow_config_name="TestCategorizationWF",
            **category_data
        )


class TestCategorizationAndRouting:
    """Tests the main categorization and routing logic."""

    @patch('Middleware.services.prompt_categorization_service.WorkflowManager')
    def test_get_prompt_category_success(self, MockWorkflowManager, service, mocker):
        """
        Tests the successful path where a category is identified and the
        corresponding workflow is executed.
        """
        mock_categorize = mocker.patch.object(service, '_categorize_request', return_value="CODING")
        mock_workflow_instance = MagicMock()
        MockWorkflowManager.return_value = mock_workflow_instance
        messages = [{"role": "user", "content": "Write a python script."}]
        request_id = "req-123"
        discussion_id = "disc-456"

        service.get_prompt_category(messages, request_id, discussion_id, stream=True)

        mock_categorize.assert_called_once_with(messages, request_id)
        # Verify the correct workflow was instantiated and run
        MockWorkflowManager.assert_called_once_with(workflow_config_name="CodingWorkflow")
        mock_workflow_instance.run_workflow.assert_called_once_with(
            messages=messages,
            request_id=request_id,
            discussionId=discussion_id,
            stream=True,
            api_key=None,
            tools=None,
            tool_choice=None,
        )

    @patch('Middleware.services.prompt_categorization_service.PromptCategorizationService.conversational_method')
    def test_get_prompt_category_fallback_to_default(self, mock_conversational_method, service, mocker):
        """
        Tests the fallback path where an unknown category results in calling
        the default conversational method.
        """
        mock_categorize = mocker.patch.object(service, '_categorize_request', return_value="UNKNOWN")
        messages = [{"role": "user", "content": "Just chatting."}]
        request_id = "req-123"
        discussion_id = "disc-456"

        service.get_prompt_category(messages, request_id, discussion_id, stream=False)

        mock_categorize.assert_called_once_with(messages, request_id)
        mock_conversational_method.assert_called_once_with(messages, request_id, discussion_id, False, api_key=None,
                                                              tools=None, tool_choice=None)

    def test_initialize_categories(self, service):
        """
        Verifies that category data is correctly formatted into various strings
        for prompt injection.
        """
        result = service._initialize_categories()

        assert result['categoriesSeparatedByOr'] == 'CODING or TECHNICAL'
        assert result[
                   'category_colon_descriptions'] == 'CODING: Writing or editing code.; TECHNICAL: IT-related discussion, not code.'
        assert result['categoryNameBulletpoints'] == '\n- CODING\n- TECHNICAL'
        assert result['category_list'] == ['CODING', 'TECHNICAL']

    @pytest.mark.parametrize("processed_input, expected_match", [
        ("The category is CODING.", "CODING"),
        ("technical", "TECHNICAL"),
        ("I think it is coding", "CODING"),
        ("This is unrelated.", None),
        ("CODING and TECHNICAL", "CODING"),  # First match wins
    ])
    def test_match_category(self, service, processed_input, expected_match):
        """
        Tests the logic for matching LLM string output to a category key.
        """
        assert service._match_category(processed_input) == expected_match

    def test_categorize_request_success_first_try(self, service, mocker):
        """
        Verifies a successful categorization on the first attempt.
        """
        mock_workflow_manager_instance = MagicMock()
        mock_workflow_manager_instance.run_workflow.return_value = "The final category is CODING."
        mocker.patch.object(service, '_configure_workflow_manager', return_value=mock_workflow_manager_instance)

        result = service._categorize_request([{"role": "user", "content": "test"}], "req-123")

        assert result == "CODING"
        mock_workflow_manager_instance.run_workflow.assert_called_once()

    def test_categorize_request_fails_with_default_one_attempt(self, service, mocker):
        """
        Verifies that with the default of 1 attempt, a failed match returns 'UNKNOWN' immediately.
        """
        mock_workflow_manager_instance = MagicMock()
        mock_workflow_manager_instance.run_workflow.return_value = "This does not match anything."
        mocker.patch.object(service, '_configure_workflow_manager', return_value=mock_workflow_manager_instance)

        result = service._categorize_request([{"role": "user", "content": "test"}], "req-123")

        assert result == "UNKNOWN"
        assert mock_workflow_manager_instance.run_workflow.call_count == 1

    def test_categorize_request_fails_after_configured_retries(self, service, mocker):
        """
        Verifies that with maxCategorizationAttempts set to 3, the workflow
        is called 3 times before returning 'UNKNOWN'.
        """
        mocker.patch('Middleware.services.prompt_categorization_service.get_max_categorization_attempts',
                     return_value=3)
        mock_workflow_manager_instance = MagicMock()
        mock_workflow_manager_instance.run_workflow.return_value = "This does not match anything."
        mocker.patch.object(service, '_configure_workflow_manager', return_value=mock_workflow_manager_instance)

        result = service._categorize_request([{"role": "user", "content": "test"}], "req-123")

        assert result == "UNKNOWN"
        assert mock_workflow_manager_instance.run_workflow.call_count == 3

    def test_categorize_request_succeeds_on_retry(self, service, mocker):
        """
        Verifies that if the workflow fails once but succeeds on a retry,
        the correct category is returned.
        """
        mocker.patch('Middleware.services.prompt_categorization_service.get_max_categorization_attempts',
                     return_value=3)
        mock_workflow_manager_instance = MagicMock()
        mock_workflow_manager_instance.run_workflow.side_effect = [
            "Invalid response",
            "The category is TECHNICAL"
        ]
        mocker.patch.object(service, '_configure_workflow_manager', return_value=mock_workflow_manager_instance)

        result = service._categorize_request([{"role": "user", "content": "test"}], "req-123")

        assert result == "TECHNICAL"
        assert mock_workflow_manager_instance.run_workflow.call_count == 2


class TestMatchCategoryUnderscoreKeys:
    """
    Tests _match_category with underscore-containing category keys.

    The categorization pipeline strips all punctuation (including underscores)
    from LLM output before passing it to _match_category. These tests verify
    that matching still works when underscores have been removed from the input
    but remain in the category keys.
    """

    # --- Exact output, underscores intact ---

    def test_exact_match_with_underscore(self, underscore_service):
        """Underscore key matched when input still contains the underscore."""
        assert underscore_service._match_category("NEW_INSTRUCTION") == "NEW_INSTRUCTION"

    def test_exact_match_tool_continuation(self, underscore_service):
        assert underscore_service._match_category("TOOL_CONTINUATION") == "TOOL_CONTINUATION"

    # --- Underscores stripped (simulates punctuation removal) ---

    def test_match_after_underscore_removal(self, underscore_service):
        """Key point of the bug: underscores removed from input must still match."""
        assert underscore_service._match_category("NEWINSTRUCTION") == "NEW_INSTRUCTION"

    def test_match_tool_continuation_stripped(self, underscore_service):
        assert underscore_service._match_category("TOOLCONTINUATION") == "TOOL_CONTINUATION"

    # --- Case variations ---

    def test_lowercase_stripped(self, underscore_service):
        assert underscore_service._match_category("newinstruction") == "NEW_INSTRUCTION"

    def test_mixed_case_stripped(self, underscore_service):
        assert underscore_service._match_category("NewInstruction") == "NEW_INSTRUCTION"

    def test_lowercase_with_underscore(self, underscore_service):
        assert underscore_service._match_category("new_instruction") == "NEW_INSTRUCTION"

    def test_mixed_case_with_underscore(self, underscore_service):
        assert underscore_service._match_category("Tool_Continuation") == "TOOL_CONTINUATION"

    # --- Embedded in sentences ---

    def test_stripped_in_sentence(self, underscore_service):
        assert underscore_service._match_category("I think this is NEWINSTRUCTION") == "NEW_INSTRUCTION"

    def test_underscore_in_sentence(self, underscore_service):
        assert underscore_service._match_category("The category is NEW_INSTRUCTION") == "NEW_INSTRUCTION"

    def test_stripped_at_end_of_sentence(self, underscore_service):
        assert underscore_service._match_category("This should be TOOLCONTINUATION") == "TOOL_CONTINUATION"

    def test_stripped_lowercase_in_sentence(self, underscore_service):
        assert underscore_service._match_category("clearly toolcontinuation here") == "TOOL_CONTINUATION"

    # --- No match ---

    def test_no_match_unrelated_text(self, underscore_service):
        assert underscore_service._match_category("something completely unrelated") is None

    def test_no_match_partial_key(self, underscore_service):
        """A partial key fragment should not match."""
        assert underscore_service._match_category("INSTRUCTION") is None

    def test_no_match_empty_string(self, underscore_service):
        assert underscore_service._match_category("") is None

    # --- First match wins when both could match ---

    def test_first_match_wins_both_present(self, underscore_service):
        """When both category names appear, the first word-match wins."""
        result = underscore_service._match_category("NEWINSTRUCTION then TOOLCONTINUATION")
        assert result == "NEW_INSTRUCTION"

    def test_first_match_wins_reversed_order(self, underscore_service):
        result = underscore_service._match_category("TOOLCONTINUATION then NEWINSTRUCTION")
        assert result == "TOOL_CONTINUATION"


class TestMatchCategoryMixedKeys:
    """
    Tests _match_category with a config that mixes single-word keys and
    underscore-containing keys.
    """

    def test_single_word_key_exact(self, mixed_service):
        assert mixed_service._match_category("CODING") == "CODING"

    def test_underscore_key_exact(self, mixed_service):
        assert mixed_service._match_category("NEW_INSTRUCTION") == "NEW_INSTRUCTION"

    def test_single_word_key_in_sentence(self, mixed_service):
        assert mixed_service._match_category("This is clearly CODING") == "CODING"

    def test_underscore_key_stripped_in_sentence(self, mixed_service):
        assert mixed_service._match_category("This is NEWINSTRUCTION") == "NEW_INSTRUCTION"

    def test_general_chat_stripped(self, mixed_service):
        assert mixed_service._match_category("GENERALCHAT") == "GENERAL_CHAT"

    def test_general_chat_with_underscore(self, mixed_service):
        assert mixed_service._match_category("GENERAL_CHAT") == "GENERAL_CHAT"

    def test_general_chat_lowercase(self, mixed_service):
        assert mixed_service._match_category("generalchat") == "GENERAL_CHAT"

    def test_tool_continuation_mixed_case(self, mixed_service):
        assert mixed_service._match_category("toolContinuation") == "TOOL_CONTINUATION"

    def test_no_match_in_mixed(self, mixed_service):
        assert mixed_service._match_category("unrelated gibberish") is None


class TestMatchCategoryMultiUnderscoreKeys:
    """
    Tests _match_category with keys that have multiple underscores, ensuring
    the normalization handles them correctly.
    """

    def test_deep_code_review_exact(self, multi_underscore_service):
        assert multi_underscore_service._match_category("DEEP_CODE_REVIEW") == "DEEP_CODE_REVIEW"

    def test_deep_code_review_stripped(self, multi_underscore_service):
        assert multi_underscore_service._match_category("DEEPCODEREVIEW") == "DEEP_CODE_REVIEW"

    def test_deep_code_review_lowercase_stripped(self, multi_underscore_service):
        assert multi_underscore_service._match_category("deepcodereview") == "DEEP_CODE_REVIEW"

    def test_quick_bug_fix_stripped(self, multi_underscore_service):
        assert multi_underscore_service._match_category("QUICKBUGFIX") == "QUICK_BUG_FIX"

    def test_quick_bug_fix_mixed_case(self, multi_underscore_service):
        assert multi_underscore_service._match_category("QuickBugFix") == "QUICK_BUG_FIX"

    def test_abcd_stripped(self, multi_underscore_service):
        assert multi_underscore_service._match_category("ABCD") == "A_B_C_D"

    def test_abcd_with_underscores(self, multi_underscore_service):
        assert multi_underscore_service._match_category("A_B_C_D") == "A_B_C_D"

    def test_abcd_lowercase(self, multi_underscore_service):
        assert multi_underscore_service._match_category("abcd") == "A_B_C_D"

    def test_deep_code_review_in_sentence(self, multi_underscore_service):
        assert multi_underscore_service._match_category("I think DEEPCODEREVIEW applies") == "DEEP_CODE_REVIEW"


class TestCategorizeRequestWithUnderscoreKeys:
    """
    End-to-end tests through _categorize_request, which strips punctuation
    (including underscores) from LLM output before matching. These tests
    exercise the full pipeline that caused the original bug.
    """

    def test_llm_returns_exact_underscore_key(self, underscore_service, mocker):
        """LLM returns 'NEW_INSTRUCTION' — the underscore is stripped, must still match."""
        mock_wm = MagicMock()
        mock_wm.run_workflow.return_value = "NEW_INSTRUCTION"
        mocker.patch.object(underscore_service, '_configure_workflow_manager', return_value=mock_wm)

        result = underscore_service._categorize_request([{"role": "user", "content": "hi"}], "req-1")
        assert result == "NEW_INSTRUCTION"

    def test_llm_returns_tool_continuation(self, underscore_service, mocker):
        mock_wm = MagicMock()
        mock_wm.run_workflow.return_value = "TOOL_CONTINUATION"
        mocker.patch.object(underscore_service, '_configure_workflow_manager', return_value=mock_wm)

        result = underscore_service._categorize_request([{"role": "user", "content": "hi"}], "req-1")
        assert result == "TOOL_CONTINUATION"

    def test_llm_returns_key_in_sentence(self, underscore_service, mocker):
        """LLM wraps the category in a sentence — punctuation stripped, then matched."""
        mock_wm = MagicMock()
        mock_wm.run_workflow.return_value = "The category is NEW_INSTRUCTION."
        mocker.patch.object(underscore_service, '_configure_workflow_manager', return_value=mock_wm)

        result = underscore_service._categorize_request([{"role": "user", "content": "hi"}], "req-1")
        assert result == "NEW_INSTRUCTION"

    def test_llm_returns_key_with_quotes(self, underscore_service, mocker):
        """LLM wraps answer in quotes — quotes are stripped as punctuation."""
        mock_wm = MagicMock()
        mock_wm.run_workflow.return_value = '"NEW_INSTRUCTION"'
        mocker.patch.object(underscore_service, '_configure_workflow_manager', return_value=mock_wm)

        result = underscore_service._categorize_request([{"role": "user", "content": "hi"}], "req-1")
        assert result == "NEW_INSTRUCTION"

    def test_llm_returns_key_with_trailing_period(self, underscore_service, mocker):
        mock_wm = MagicMock()
        mock_wm.run_workflow.return_value = "TOOL_CONTINUATION."
        mocker.patch.object(underscore_service, '_configure_workflow_manager', return_value=mock_wm)

        result = underscore_service._categorize_request([{"role": "user", "content": "hi"}], "req-1")
        assert result == "TOOL_CONTINUATION"

    def test_llm_returns_key_with_asterisks(self, underscore_service, mocker):
        """LLM uses markdown bold — asterisks are stripped."""
        mock_wm = MagicMock()
        mock_wm.run_workflow.return_value = "**NEW_INSTRUCTION**"
        mocker.patch.object(underscore_service, '_configure_workflow_manager', return_value=mock_wm)

        result = underscore_service._categorize_request([{"role": "user", "content": "hi"}], "req-1")
        assert result == "NEW_INSTRUCTION"

    def test_llm_returns_key_with_colon_prefix(self, underscore_service, mocker):
        """LLM says 'Category: NEW_INSTRUCTION' — colon stripped."""
        mock_wm = MagicMock()
        mock_wm.run_workflow.return_value = "Category: NEW_INSTRUCTION"
        mocker.patch.object(underscore_service, '_configure_workflow_manager', return_value=mock_wm)

        result = underscore_service._categorize_request([{"role": "user", "content": "hi"}], "req-1")
        assert result == "NEW_INSTRUCTION"

    def test_llm_returns_lowercase_underscore_key(self, underscore_service, mocker):
        mock_wm = MagicMock()
        mock_wm.run_workflow.return_value = "new_instruction"
        mocker.patch.object(underscore_service, '_configure_workflow_manager', return_value=mock_wm)

        result = underscore_service._categorize_request([{"role": "user", "content": "hi"}], "req-1")
        assert result == "NEW_INSTRUCTION"

    def test_llm_returns_mixed_case_underscore_key(self, underscore_service, mocker):
        mock_wm = MagicMock()
        mock_wm.run_workflow.return_value = "New_Instruction"
        mocker.patch.object(underscore_service, '_configure_workflow_manager', return_value=mock_wm)

        result = underscore_service._categorize_request([{"role": "user", "content": "hi"}], "req-1")
        assert result == "NEW_INSTRUCTION"

    def test_llm_returns_no_match_goes_unknown(self, underscore_service, mocker):
        mock_wm = MagicMock()
        mock_wm.run_workflow.return_value = "I have no idea"
        mocker.patch.object(underscore_service, '_configure_workflow_manager', return_value=mock_wm)

        result = underscore_service._categorize_request([{"role": "user", "content": "hi"}], "req-1")
        assert result == "UNKNOWN"

    def test_llm_returns_none(self, underscore_service, mocker):
        mock_wm = MagicMock()
        mock_wm.run_workflow.return_value = None
        mocker.patch.object(underscore_service, '_configure_workflow_manager', return_value=mock_wm)

        result = underscore_service._categorize_request([{"role": "user", "content": "hi"}], "req-1")
        assert result == "UNKNOWN"

    def test_llm_returns_whitespace_padded_key(self, underscore_service, mocker):
        mock_wm = MagicMock()
        mock_wm.run_workflow.return_value = "  NEW_INSTRUCTION  "
        mocker.patch.object(underscore_service, '_configure_workflow_manager', return_value=mock_wm)

        result = underscore_service._categorize_request([{"role": "user", "content": "hi"}], "req-1")
        assert result == "NEW_INSTRUCTION"

    def test_llm_returns_newline_before_key(self, underscore_service, mocker):
        mock_wm = MagicMock()
        mock_wm.run_workflow.return_value = "\nNEW_INSTRUCTION\n"
        mocker.patch.object(underscore_service, '_configure_workflow_manager', return_value=mock_wm)

        result = underscore_service._categorize_request([{"role": "user", "content": "hi"}], "req-1")
        assert result == "NEW_INSTRUCTION"


class TestCategorizeRequestWithMultiUnderscoreKeys:
    """
    End-to-end tests through _categorize_request with multi-underscore keys.
    """

    def test_deep_code_review_exact(self, multi_underscore_service, mocker):
        mock_wm = MagicMock()
        mock_wm.run_workflow.return_value = "DEEP_CODE_REVIEW"
        mocker.patch.object(multi_underscore_service, '_configure_workflow_manager', return_value=mock_wm)

        result = multi_underscore_service._categorize_request([{"role": "user", "content": "hi"}], "req-1")
        assert result == "DEEP_CODE_REVIEW"

    def test_quick_bug_fix_in_sentence(self, multi_underscore_service, mocker):
        mock_wm = MagicMock()
        mock_wm.run_workflow.return_value = "This is a QUICK_BUG_FIX situation."
        mocker.patch.object(multi_underscore_service, '_configure_workflow_manager', return_value=mock_wm)

        result = multi_underscore_service._categorize_request([{"role": "user", "content": "hi"}], "req-1")
        assert result == "QUICK_BUG_FIX"

    def test_abcd_exact(self, multi_underscore_service, mocker):
        mock_wm = MagicMock()
        mock_wm.run_workflow.return_value = "A_B_C_D"
        mocker.patch.object(multi_underscore_service, '_configure_workflow_manager', return_value=mock_wm)

        result = multi_underscore_service._categorize_request([{"role": "user", "content": "hi"}], "req-1")
        assert result == "A_B_C_D"


class TestCategorizeRequestWithMixedKeys:
    """
    End-to-end tests with a config containing both single-word and underscore keys.
    """

    def test_single_word_key_still_works(self, mixed_service, mocker):
        mock_wm = MagicMock()
        mock_wm.run_workflow.return_value = "CODING"
        mocker.patch.object(mixed_service, '_configure_workflow_manager', return_value=mock_wm)

        result = mixed_service._categorize_request([{"role": "user", "content": "hi"}], "req-1")
        assert result == "CODING"

    def test_underscore_key_alongside_single_word(self, mixed_service, mocker):
        mock_wm = MagicMock()
        mock_wm.run_workflow.return_value = "NEW_INSTRUCTION"
        mocker.patch.object(mixed_service, '_configure_workflow_manager', return_value=mock_wm)

        result = mixed_service._categorize_request([{"role": "user", "content": "hi"}], "req-1")
        assert result == "NEW_INSTRUCTION"

    def test_general_chat_underscore_key(self, mixed_service, mocker):
        mock_wm = MagicMock()
        mock_wm.run_workflow.return_value = "GENERAL_CHAT"
        mocker.patch.object(mixed_service, '_configure_workflow_manager', return_value=mock_wm)

        result = mixed_service._categorize_request([{"role": "user", "content": "hi"}], "req-1")
        assert result == "GENERAL_CHAT"

    def test_tool_continuation_with_extra_punctuation(self, mixed_service, mocker):
        mock_wm = MagicMock()
        mock_wm.run_workflow.return_value = "**TOOL_CONTINUATION!**"
        mocker.patch.object(mixed_service, '_configure_workflow_manager', return_value=mock_wm)

        result = mixed_service._categorize_request([{"role": "user", "content": "hi"}], "req-1")
        assert result == "TOOL_CONTINUATION"


class TestGetPromptCategoryRoutingWithUnderscoreKeys:
    """
    Tests the full get_prompt_category path with underscore keys, verifying
    that the correct workflow is instantiated and run.
    """

    @patch('Middleware.services.prompt_categorization_service.WorkflowManager')
    def test_routes_to_correct_underscore_workflow(self, MockWorkflowManager, underscore_service, mocker):
        mocker.patch.object(underscore_service, '_categorize_request', return_value="NEW_INSTRUCTION")
        mock_workflow_instance = MagicMock()
        MockWorkflowManager.return_value = mock_workflow_instance
        messages = [{"role": "user", "content": "Do something new."}]

        underscore_service.get_prompt_category(messages, "req-1", "disc-1", stream=False)

        MockWorkflowManager.assert_called_once_with(workflow_config_name="NewInstructionWorkflow")
        mock_workflow_instance.run_workflow.assert_called_once()

    @patch('Middleware.services.prompt_categorization_service.WorkflowManager')
    def test_routes_tool_continuation_workflow(self, MockWorkflowManager, underscore_service, mocker):
        mocker.patch.object(underscore_service, '_categorize_request', return_value="TOOL_CONTINUATION")
        mock_workflow_instance = MagicMock()
        MockWorkflowManager.return_value = mock_workflow_instance
        messages = [{"role": "assistant", "content": "tool call"}, {"role": "tool", "content": "result"}]

        underscore_service.get_prompt_category(messages, "req-1", "disc-1", stream=True)

        MockWorkflowManager.assert_called_once_with(workflow_config_name="ToolContinuationWorkflow")
        mock_workflow_instance.run_workflow.assert_called_once()

    @patch('Middleware.services.prompt_categorization_service.PromptCategorizationService.conversational_method')
    def test_unknown_falls_back_to_default(self, mock_conv, underscore_service, mocker):
        mocker.patch.object(underscore_service, '_categorize_request', return_value="UNKNOWN")
        messages = [{"role": "user", "content": "???"}]

        underscore_service.get_prompt_category(messages, "req-1", "disc-1", stream=False)

        mock_conv.assert_called_once()
