import unittest
import json
from unittest.mock import patch, mock_open, MagicMock, call

# Assuming WorkflowManager and get_workflow_path are accessible
# Adjust imports based on actual project structure if needed
from Middleware.workflows.managers.workflow_manager import WorkflowManager
# Need to mock get_user_config which is called during WorkflowManager init via config_utils
from Middleware.utilities.config_utils import get_workflow_path, get_user_config
# Need LlmHandlerService for mocking
from Middleware.services.llm_service import LlmHandlerService


class TestWorkflowManagerConfigLoading(unittest.TestCase):

    # Use patch decorator for get_user_config to mock it for the entire test method
    @patch('Middleware.utilities.config_utils.get_user_config')
    # Also patch the LlmHandlerService instantiation within WorkflowManager
    @patch('Middleware.workflows.managers.workflow_manager.LlmHandlerService')
    # Patch builtins.open carefully
    @patch('builtins.open')
    def test_run_workflow_with_list_config_succeeds(self, mock_open_func, MockLlmHandlerService, mock_get_user_config):
        """
        Test that run_workflow succeeds when the config file contains a list.
        """
        # Mock get_user_config 
        mock_get_user_config.return_value = {'currentUser': 'testUser', 'chatPromptTemplateName': 'default'}
        
        # Mock the LlmHandlerService
        mock_llm_service_instance = MockLlmHandlerService.return_value
        # Mock the loaded LLM handler to prevent further file reads for templates etc.
        mock_llm_handler = MagicMock()
        mock_llm_handler.prompt_template_file_name = 'mock_template' # Avoid None issues if accessed
        mock_llm_service_instance.load_model_from_config.return_value = mock_llm_handler

        workflow_name = "test-list-config-workflow"
        mock_config_path = f"/root/projects/Wilmer/WilmerAI/Public/Configs/Workflows/{workflow_name}.json"
        mock_user_config_path = "/root/projects/Wilmer/WilmerAI/Public/Configs/Users/_current-user.json"
        
        # Valid JSON list content
        valid_list_json_content = json.dumps([
            {"title": "Step 1", "type": "Standard", "endpointName": "test-endpoint"} 
        ])
        
        # --- Refined Mocking for open --- 
        # Create mock file handles
        mock_workflow_file_handle = mock_open(read_data=valid_list_json_content).return_value
        mock_user_config_content = json.dumps({'currentUser': 'testUser', 'chatPromptTemplateName': 'default'}) # Ensure currentUser is here
        mock_user_config_handle = mock_open(read_data=mock_user_config_content).return_value

        def open_side_effect(file_path, *args, **kwargs):
            print(f"Mock open checking path: {file_path}") # Debug print
            if file_path == mock_config_path:
                print(f"Mock open returning workflow handle for: {file_path}")
                return mock_workflow_file_handle
            elif file_path == mock_user_config_path:
                print(f"Mock open returning user config handle for: {file_path}")
                return mock_user_config_handle
            else:
                # For any other file path, return a default mock_open handle 
                # to avoid errors, but we won't assert calls on these.
                print(f"Mock open returning default handle for: {file_path}")
                return mock_open().return_value
        
        # Apply the side effect to our patched open function
        mock_open_func.side_effect = open_side_effect
        # --- End Refined Mocking --- 

        dummy_messages = [{"role": "user", "content": "Hello"}]
        dummy_request_id = "test-req-123"
        dummy_discussion_id = "test-disc-456"

        with patch('Middleware.workflows.managers.workflow_manager.get_workflow_path', return_value=mock_config_path) as mock_get_path:
            # Note: 'builtins.open' is already patched via decorator
            workflow_manager_instance = WorkflowManager(workflow_config_name=workflow_name)
            
            try:
                _ = workflow_manager_instance.run_workflow(
                    messages=dummy_messages,
                    request_id=dummy_request_id,
                    discussionId=dummy_discussion_id,
                    stream=False 
                )
                pass 
            except Exception as e:
                self.fail(f"run_workflow raised an unexpected exception: {e}")
            
            # Verify mocks
            mock_get_path.assert_called_once_with(workflow_name)
            # Assert that our main patched open function was called with the specific workflow path
            mock_open_func.assert_any_call(mock_config_path)
            # Assert that open was also called for the user config path
            mock_open_func.assert_any_call(mock_user_config_path)
            # Check if the specific handle for our file was used (e.g., read was called on it)
            mock_workflow_file_handle.read.assert_called_once() 
            mock_user_config_handle.read.assert_called_once()
            mock_get_user_config.assert_called()
            mock_llm_service_instance.load_model_from_config.assert_called()

if __name__ == '__main__':
    unittest.main() 