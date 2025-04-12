#!/usr/bin/env python

"""
Unit tests for the WorkflowManager focusing on state propagation.
"""

import unittest
import sys
import os
import uuid
import json
from unittest.mock import patch, MagicMock, ANY

# Adjust import paths 
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../WilmerAI")))

# Import the class under test
from Middleware.workflows.managers.workflow_manager import WorkflowManager
from Middleware.utilities.config_utils import get_workflow_path # Use this to mock file loading
from Middleware.workflows.processors.prompt_processor import PromptProcessor # Add this import

# Mock LlmHandlerService and its methods if needed by __init__ or _process_section mocks
class MockLlmHandler:
    def __init__(self):
        self.takes_message_collection = True
        self.prompt_template_file_name = "mock_template"

class MockLlmHandlerService:
    def load_model_from_config(self, *args, **kwargs):
        return MockLlmHandler()

class TestWorkflowManagerStatePropagation(unittest.TestCase):

    @patch('Middleware.workflows.managers.workflow_manager.get_workflow_path')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch.object(WorkflowManager, '_process_section') # Mock the processing logic
    @patch('Middleware.workflows.managers.workflow_manager.LlmHandlerService', MockLlmHandlerService) # Mock service used in __init__
    @patch('Middleware.workflows.managers.workflow_manager.SqlLiteUtils') # Mock DB calls
    @patch('Middleware.utilities.config_utils.get_user_config', return_value={'chatPromptTemplateName': 'mock_template'}) # Mock the user config directly
    def test_python_module_message_modification_propagation(self, 
                                                           mock_get_user_config, # Use this mock
                                                           mock_sqlite,
                                                           mock_process_section, 
                                                           mock_file_open, 
                                                           mock_get_workflow_path):
        """
        Tests the propagation of message modifications made by a PythonModule step.

        Scenario:
        Consider a workflow sequence: Step 1 (PythonModule) -> Step 2 (Standard).
        Step 1 is designed to modify the list of messages (e.g., add a system prompt,
        rephrase the user's query).

        Expected Behavior:
        The modifications made by Step 1 should be reflected in the 'messages' list
        that is passed to Step 2 for processing. Step 2 should operate on the updated
        message list, not the original one provided to the workflow.

        Test Setup:
        - A mock workflow configuration with a 'Python Modifier' step (PythonModule)
          followed by a 'Standard Consumer' step (Standard) is created.
        - The core processing logic (`_process_section`) is mocked.
        - The mock for the 'Python Modifier' step is configured to return a
          predefined list of *modified* messages.
        - The mock for the 'Standard Consumer' step is configured to capture the
          'messages' list it receives as input.

        Verification:
        The test asserts that the 'messages' list captured by the mock for the
        'Standard Consumer' step is identical to the *modified* message list
        returned by the mock for the 'Python Modifier' step. This confirms that
        the state change (message modification) persisted between the steps.
        """
        # ==================
        # GIVEN (Setup)
        # ==================
        workflow_name = "test_state_workflow"
        request_id = str(uuid.uuid4())
        discussion_id = "test_discussion"
        
        initial_messages = [
            {"role": "user", "content": "Initial User Message"}
        ]

        # Define the mock workflow structure
        mock_workflow_config = [
            {
                "title": "Python Modifier",
                "type": "PythonModule",
                # Actual module path/args/kwargs don't matter much as we mock _process_section
                "module_path": "dummy_modifier.py", 
                "args": [],
                "kwargs": {}
            },
            {
                "title": "Standard Consumer",
                "type": "Standard",
                "endpointName": "TestEndpoint", # Need this to trigger LLM handler loading mock
                "prompt": "Use this: {{ chat_user_prompt_last_one }}",
                "returnToUser": True # Make it the final step
            }
        ]
        
        # Configure mocks
        mock_get_workflow_path.return_value = f"/fake/path/to/{workflow_name}.json"
        mock_file_open.return_value.read.return_value = json.dumps(mock_workflow_config)

        # --- Mock _process_section behavior ---
        modified_messages_from_python = [
            {"role": "system", "content": "System prompt added by Python"},
            {"role": "user", "content": "MODIFIED User Message"}
        ]
        
        # Side effect: First call (PythonModule) returns dict with modified messages
        # Second call (Standard) captures args and returns dummy output
        standard_step_call_args = {} # To store args passed to the standard step processing

        def process_section_side_effect(*args, **kwargs):
            config = args[0] # self, config, ...
            messages_received = args[4] # self, config, req_id, wf_id, disc_id, messages, ...
            
            if config["title"] == "Python Modifier":
                # Simulate Python module returning modified messages
                return {"messages": modified_messages_from_python} 
            elif config["title"] == "Standard Consumer":
                # Capture the messages list passed to the standard node processing
                # Specifically interested in the list used for variable generation
                # Note: _process_section calls prompt_processor which calls variable_manager
                # We mock _process_section directly, so we capture the list it receives.
                standard_step_call_args['messages'] = messages_received 
                return "Final LLM Response" # Dummy final output
            else:
                return "Unexpected step"

        mock_process_section.side_effect = process_section_side_effect

        # Instantiate the manager
        manager = WorkflowManager(workflow_config_name=workflow_name)

        # ==================
        # WHEN (Action)
        # ==================
        # run_workflow returns a generator, exhaust it for non-streaming
        result = manager.run_workflow(initial_messages, request_id, discussion_id, stream=False)

        # ==================
        # THEN (Assertions)
        # ==================
        self.assertEqual(result, "Final LLM Response") # Check final output is as expected
        
        # Verify _process_section was called twice (once for each step)
        self.assertEqual(mock_process_section.call_count, 2, "Should process two steps")

        # *** THE KEY ASSERTION ***
        # Check that the messages list passed to the *second* call 
        # (the Standard step processing) reflects the modifications 
        # made and returned by the *first* call (the Python step).
        # We captured the 'messages' argument passed to the second call's side_effect.
        self.assertIn('messages', standard_step_call_args, "Messages arg not captured for standard step")
        self.assertEqual(standard_step_call_args['messages'], modified_messages_from_python,
                         "Standard step did not receive the modified messages from the Python step.")

if __name__ == '__main__':
    unittest.main()