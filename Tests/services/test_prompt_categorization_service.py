# Tests/services/test_prompt_categorization_service.py

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
def service(mocker, mock_routing_config) -> PromptCategorizationService:
    """
    Provides an initialized PromptCategorizationService instance with
    config dependencies already mocked out.
    """
    mocker.patch('Middleware.services.prompt_categorization_service.get_categories_config',
                 return_value=mock_routing_config)
    return PromptCategorizationService()


class TestInitialization:
    """Tests the __init__ and initialize methods."""

    def test_initialize_success(self, mocker, mock_routing_config):
        """
        Verifies that the service loads and processes a valid routing config correctly.
        """
        # Arrange
        mock_get_config = mocker.patch('Middleware.services.prompt_categorization_service.get_categories_config',
                                       return_value=mock_routing_config)

        # Act
        service = PromptCategorizationService()

        # Assert
        mock_get_config.assert_called_once()
        assert len(service.categories) == 2
        assert service.categories["CODING"]["workflow"] == "CodingWorkflow"
        assert service.categories["TECHNICAL"]["description"] == "IT-related discussion, not code."

    def test_initialize_raises_file_not_found(self, mocker):
        """
        Ensures that a FileNotFoundError from the config utility is re-raised.
        """
        # Arrange
        mocker.patch('Middleware.services.prompt_categorization_service.get_categories_config',
                     side_effect=FileNotFoundError)

        # Act & Assert
        with pytest.raises(FileNotFoundError):
            PromptCategorizationService()

    def test_initialize_raises_json_decode_error(self, mocker):
        """
        Ensures that a JSONDecodeError from the config utility is re-raised.
        """
        # Arrange
        mocker.patch('Middleware.services.prompt_categorization_service.get_categories_config',
                     side_effect=json.JSONDecodeError("mock error", "", 0))

        # Act & Assert
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
        # Arrange
        messages = [{"role": "user", "content": "Hello"}]
        request_id = "req-123"
        discussion_id = "disc-456"

        # Act
        PromptCategorizationService.conversational_method(messages, request_id, discussion_id, stream=True)

        # Assert
        mock_run_workflow.assert_called_once_with(
            workflow_name='_DefaultWorkflow',
            request_id=request_id,
            discussion_id=discussion_id,
            messages=messages,
            is_streaming=True
        )

    @patch('Middleware.services.prompt_categorization_service.WorkflowManager')
    @patch('Middleware.services.prompt_categorization_service.get_active_categorization_workflow_name')
    def test_configure_workflow_manager(self, mock_get_workflow_name, MockWorkflowManager):
        """
        Verifies that the helper method correctly instantiates WorkflowManager
        with the categorization workflow name and injected category data.
        """
        # Arrange
        mock_get_workflow_name.return_value = "TestCategorizationWF"
        category_data = {"categoriesSeparatedByOr": "A or B"}

        # Act
        PromptCategorizationService._configure_workflow_manager(category_data)

        # Assert
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
        # Arrange
        mock_categorize = mocker.patch.object(service, '_categorize_request', return_value="CODING")
        mock_workflow_instance = MagicMock()
        MockWorkflowManager.return_value = mock_workflow_instance
        messages = [{"role": "user", "content": "Write a python script."}]
        request_id = "req-123"
        discussion_id = "disc-456"

        # Act
        service.get_prompt_category(messages, request_id, discussion_id, stream=True)

        # Assert
        mock_categorize.assert_called_once_with(messages, request_id)
        # Verify the correct workflow was instantiated and run
        MockWorkflowManager.assert_called_once_with(workflow_config_name="CodingWorkflow")
        mock_workflow_instance.run_workflow.assert_called_once_with(
            messages=messages,
            request_id=request_id,
            discussionId=discussion_id,
            stream=True
        )

    @patch('Middleware.services.prompt_categorization_service.PromptCategorizationService.conversational_method')
    def test_get_prompt_category_fallback_to_default(self, mock_conversational_method, service, mocker):
        """
        Tests the fallback path where an unknown category results in calling
        the default conversational method.
        """
        # Arrange
        mock_categorize = mocker.patch.object(service, '_categorize_request', return_value="UNKNOWN")
        messages = [{"role": "user", "content": "Just chatting."}]
        request_id = "req-123"
        discussion_id = "disc-456"

        # Act
        service.get_prompt_category(messages, request_id, discussion_id, stream=False)

        # Assert
        mock_categorize.assert_called_once_with(messages, request_id)
        mock_conversational_method.assert_called_once_with(messages, request_id, discussion_id, False)

    def test_initialize_categories(self, service):
        """
        Verifies that category data is correctly formatted into various strings
        for prompt injection.
        """
        # Act
        result = service._initialize_categories()

        # Assert
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
        # Arrange
        mock_workflow_manager_instance = MagicMock()
        mock_workflow_manager_instance.run_workflow.return_value = "The final category is CODING."
        mocker.patch.object(service, '_configure_workflow_manager', return_value=mock_workflow_manager_instance)

        # Act
        result = service._categorize_request([{"role": "user", "content": "test"}], "req-123")

        # Assert
        assert result == "CODING"
        mock_workflow_manager_instance.run_workflow.assert_called_once()

    def test_categorize_request_fails_after_retries(self, service, mocker):
        """
        Verifies that after multiple failures, the category is 'UNKNOWN'.
        """
        # Arrange
        mock_workflow_manager_instance = MagicMock()
        mock_workflow_manager_instance.run_workflow.return_value = "This does not match anything."
        mocker.patch.object(service, '_configure_workflow_manager', return_value=mock_workflow_manager_instance)

        # Act
        result = service._categorize_request([{"role": "user", "content": "test"}], "req-123")

        # Assert
        assert result == "UNKNOWN"
        assert mock_workflow_manager_instance.run_workflow.call_count == 4

    def test_categorize_request_succeeds_on_retry(self, service, mocker):
        """
        Verifies that if the workflow fails once but succeeds on a retry,
        the correct category is returned.
        """
        # Arrange
        mock_workflow_manager_instance = MagicMock()
        mock_workflow_manager_instance.run_workflow.side_effect = [
            "Invalid response",
            "The category is TECHNICAL"
        ]
        mocker.patch.object(service, '_configure_workflow_manager', return_value=mock_workflow_manager_instance)

        # Act
        result = service._categorize_request([{"role": "user", "content": "test"}], "req-123")

        # Assert
        assert result == "TECHNICAL"
        assert mock_workflow_manager_instance.run_workflow.call_count == 2
