import unittest
from unittest.mock import patch, MagicMock, mock_open
import json
import os
import sys
import logging

# Adjust the path to import Middleware modules
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../../WilmerAI'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Modules to test
from Middleware.workflows.managers.workflow_manager import WorkflowManager
from Middleware.workflows.processors.prompt_processor import PromptProcessor
from Middleware.utilities import config_utils

# Disable logging for cleaner test output
logging.disable(logging.CRITICAL)

# Helper to create a generator
def create_generator(*args):
    for item in args:
        yield item

class TestWorkflowManagerStreamingOutput(unittest.TestCase):

    def test_openai_sse_stream_passthrough(self):
        """
        Verify run_workflow yields pre-formatted OpenAI SSE chunks directly.

        Checks the case where stream=True.
        """
        # 1. Define Mock Data and Expected Output
        workflow_name = "TestOpenAIStreamWorkflow"
        request_id = "test-req-openai-sse"
        discussion_id = "test-disc-openai-sse"
        initial_messages = [{'role': 'user', 'content': 'Hello OpenAI'}]
        
        # Correctly formatted OpenAI SSE chunks (as strings)
        expected_sse_chunks = [
            'data: {"id": "chatcmpl-1", "object": "chat.completion.chunk", "choices": [{"delta": {"content": "Hello"}}]}\n\n',
            'data: {"id": "chatcmpl-2", "object": "chat.completion.chunk", "choices": [{"delta": {"content": " World"}}]}\n\n',
            # Example stop chunk
            'data: {"id": "chatcmpl-3", "object": "chat.completion.chunk", "choices": [{"delta": {}, "finish_reason": "stop"}}]}\n\n', 
            'data: [DONE]\n\n' 
        ]

        # Mock workflow config (as JSON string for mock_open)
        mock_workflow_config_list = [
            {
                "title": "Standard OpenAI Step",
                "type": "Standard",
                "endpointName": "MockEndpoint",
                "preset": "MockPreset",
                "maxResponseSizeInTokens": 100
            }
        ]
        mock_config_content = json.dumps(mock_workflow_config_list)
        mock_config_path = f"/mock/path/workflows/{workflow_name}.json" # Path expected by get_workflow_path

        # 2. Setup Mocks
        # **** UPDATED: Patch target for get_workflow_path ****
        patch_get_workflow_path = patch('Middleware.workflows.managers.workflow_manager.get_workflow_path', return_value=mock_config_path)
        # Mock builtins.open to simulate reading the config file
        patch_open = mock_open(read_data=mock_config_content)

        # Mock PromptProcessor where it's instantiated/used in WorkflowManager
        mock_prompt_processor_instance = MagicMock(spec=PromptProcessor)
        mock_prompt_processor_instance.handle_conversation_type_node.return_value = create_generator(*expected_sse_chunks)
        patch_prompt_processor = patch('Middleware.workflows.managers.workflow_manager.PromptProcessor', return_value=mock_prompt_processor_instance)
        
        # Mock LlmHandlerService.load_model_from_config to prevent TypeError
        patch_load_model = patch('Middleware.services.llm_service.LlmHandlerService.load_model_from_config', return_value=MagicMock())

        # Mock SqlLiteUtils.delete_node_locks to prevent DB interactions during cleanup
        patch_delete_locks = patch('Middleware.utilities.sql_lite_utils.SqlLiteUtils.delete_node_locks')
        # Mock get_user_config needed for WorkflowVariableManager init inside WorkflowManager
        patch_get_user_config = patch('Middleware.utilities.config_utils.get_user_config', return_value={'chatPromptTemplateName': 'mock_template'})

        # 3. Execute and Assert within patched context
        with patch_get_workflow_path as mock_get_workflow_path, \
             patch('builtins.open', patch_open) as mocked_open, \
             patch_prompt_processor as mock_prompt_processor, \
             patch_load_model, \
             patch_delete_locks, \
             patch_get_user_config:

            # Instantiate the manager
            manager = WorkflowManager(workflow_config_name=workflow_name, instance_id="test-instance-id")

            # Call run_workflow with stream=True
            result_generator = manager.run_workflow(
                messages=initial_messages,
                request_id=request_id,
                discussionId=discussion_id,
                stream=True
            )

            # Consume the generator and collect results
            actual_yielded_chunks = list(result_generator)

            # Assert that the yielded chunks match the expected SSE strings exactly
            self.assertEqual(actual_yielded_chunks, expected_sse_chunks)

            # Verify mocks were called as expected
            mock_get_workflow_path.assert_called_once_with(workflow_name)
            mocked_open.assert_called_once_with(mock_config_path) # Assert on mocked_open
            # Assert on the instance returned by the PromptProcessor mock
            mock_prompt_processor.return_value.handle_conversation_type_node.assert_called_once()


if __name__ == '__main__':
    unittest.main()

# Enable logging again if it was disabled
logging.disable(logging.NOTSET) 