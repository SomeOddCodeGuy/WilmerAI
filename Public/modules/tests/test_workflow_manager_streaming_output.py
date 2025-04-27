import unittest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock, call, ANY, mock_open
import json
import os
import sys
import logging
import uuid
from typing import List, Dict, Any, Generator, AsyncGenerator

# Adjust the path to import Middleware modules
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../../WilmerAI'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Modules to test
from Middleware.workflows.managers.workflow_manager import WorkflowManager
from Middleware.workflows.processors.prompt_processor import PromptProcessor
from Middleware.utilities import config_utils
from mocks import MockLlmHandlerServiceForInit
from Middleware.llmapis.llm_api import LlmApiService
from Middleware.utilities.sql_lite_utils import SqlLiteUtils
from Middleware.utilities.config_utils import WorkflowPathResolver
from Middleware.utilities import api_utils
# Disable logging for cleaner test output
logging.disable(logging.CRITICAL)

# Helper to create a generator
def create_generator(*args):
    for item in args:
        yield item

# Helper function to consume sync generator
def consume_sync_gen(gen: Generator) -> List[Any]:
    items = []
    for item in gen:
        items.append(item)
    return items

# Mock LLM Service
class MockLlmServiceClass:
    pass # Minimal mock needed for patching

class TestWorkflowManagerStreamingOutput(unittest.TestCase):
    """Tests focused on the format of streamed output from WorkflowManager."""

    def setUp(self):
        """Set up common test data."""
        self.workflow_name = "streaming_output_test"
        self.initial_messages = [{"role": "user", "content": "Test streaming output"}]
        self.request_id = "stream-out-req-1"
        self.discussion_id = "stream-out-disc-1"
        self.frontend_api_type_openai = "openaichatcompletion"
        self.fake_workflow_path = f'/fake/workflows/{self.workflow_name}.json'
        # Define a simple workflow config for tests
        self.mock_workflow_config = [{'title': 'Final Streaming Step', 'type': 'Standard', 'endpointName': 'ep_stream', 'returnToUser': True}]

        # Mock _process_section directly on the instance
        mock_process_section_instance = MagicMock()
        expected_sse_chunks = [
            'data: {"id": "1", "content": "Hello "}\n\n',
            'data: {"id": "2", "content": "world!"}\n\n',
            'data: {"id": "3", "finish_reason": "stop"}\n\n',
            'data: [DONE]\n\n' # Include DONE signal
        ]
        def mock_generator():
            for chunk in expected_sse_chunks:
                yield chunk
        mock_process_section_instance.return_value = mock_generator()

        # Instantiate manager for this test
        manager = WorkflowManager(
            workflow_config_name=self.workflow_name # Reverted __init__ only takes name
        )
        # Assign mock process section to the created instance
        manager._process_section = mock_process_section_instance

        # --- WHEN ---
        actual_yielded_chunks = []
        # Use nested context managers for file/json loading and get_workflow_path
        with patch('Middleware.workflows.managers.workflow_manager.LlmHandlerService') as MockLlmService, \
             patch('Middleware.workflows.managers.workflow_manager.get_workflow_path', return_value=self.fake_workflow_path) as mock_get_path, \
             patch('builtins.open', mock_open(read_data=json.dumps(self.mock_workflow_config))) as mock_open_patch, \
             patch('Middleware.workflows.managers.workflow_manager.json.load', return_value=self.mock_workflow_config) as mock_json_load_patch:
            
            result_generator = manager.run_workflow(
                messages=self.initial_messages, request_id=self.request_id, discussionId=self.discussion_id,
                stream=True
            )
            actual_yielded_chunks = consume_sync_gen(result_generator)

        # --- THEN ---
        # Verify the yielded chunks are exactly what the mock _process_section provided
        self.assertEqual(actual_yielded_chunks, expected_sse_chunks)
        mock_process_section_instance.assert_called_once() # Check the instance mock
        # Verify mocks were used
        mock_get_path.assert_called_once_with(self.workflow_name)
        mock_open_patch.assert_called_once_with(self.fake_workflow_path)
        mock_json_load_patch.assert_called_once()
        # self.mock_db_utils.delete_node_locks.assert_called_once() # Cannot check without mock

    # Add more tests for other frontend_api_types (ollama) if needed

if __name__ == '__main__':
    unittest.main()

# Enable logging again if it was disabled
logging.disable(logging.NOTSET) 