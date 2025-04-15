#!/usr/bin/env python

"""
Unit tests for the WorkflowManager focusing on intermediate streaming steps.
"""

import unittest
import sys
import os
import uuid
import json
import logging
from unittest.mock import patch, MagicMock, call, ANY

# === Configure Logging ===
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# =========================

# Adjust import paths
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from WilmerAI.Middleware.workflows.managers.workflow_manager import WorkflowManager
from WilmerAI.Middleware.utilities import api_utils

class TestWorkflowManagerIntermediateStreaming(unittest.TestCase):
    """
    Tests the WorkflowManager's ability to handle scenarios where an intermediate
    step in a workflow returns a generator (e.g., a streaming LLM response),
    but the final output of the workflow might be non-streaming or a different stream.

    Rationale:
    Workflow steps can call various processors, including LLMs that might stream
    their responses. If an intermediate step (e.g., Step 1) streams its output,
    but a subsequent step (e.g., Step 2) needs the *complete* text output of Step 1
    to use in its own prompt (e.g., "Analyze the following text: {agent1Output}"),
    the WorkflowManager must fully consume/aggregate the generator from Step 1
    before proceeding to Step 2.

    These tests ensure that:
    1. Intermediate stream generators are correctly identified.
    2. Their output is aggregated into a single text string.
    3. This aggregated text string (not the generator object itself) is stored
       in the `agent_outputs` dictionary for use by subsequent steps.
    4. The final output of the workflow is handled correctly (either streamed if
       the *final* step is streaming, or returned as a single value otherwise).
    """

    def setUp(self):
        # Restore class patch for WorkflowVariableManager (needed for __init__)
        self.patcher_replace_var_manager = patch(
            'WilmerAI.Middleware.workflows.managers.workflow_manager.WorkflowVariableManager',
            new_callable=MagicMock
        )
        self.mock_variable_manager_class = self.patcher_replace_var_manager.start()

        # Keep patches for other dependencies possibly used in __init__
        self.patcher_sqlite = patch('WilmerAI.Middleware.workflows.managers.workflow_manager.SqlLiteUtils')
        self.mock_sqlite = self.patcher_sqlite.start()

        self.patcher_llm_service = patch('WilmerAI.Middleware.workflows.managers.workflow_manager.LlmHandlerService')
        self.mock_llm_service_factory = self.patcher_llm_service.start()
        mock_service_instance = MagicMock()
        mock_handler = MagicMock()
        mock_handler.takes_message_collection = True
        mock_handler.prompt_template_file_name = "mock_template"
        mock_service_instance.load_model_from_config.return_value = mock_handler
        self.mock_llm_service_factory.return_value = mock_service_instance

        # Keep general config patch
        self.patcher_run_get_user_config = patch('WilmerAI.Middleware.utilities.config_utils.get_user_config')
        self.mock_run_get_user_config = self.patcher_run_get_user_config.start()
        self.mock_run_get_user_config.return_value = {
            'stream': True, 'discussionDirectory': '/tmp',
            'sqlLiteDirectory': '/tmp', 'chatPromptTemplateName': 'mock_template'
        }

    def tearDown(self):
        patch.stopall()

    # Decorators for external/other functions
    @patch('WilmerAI.Middleware.workflows.managers.workflow_manager.get_workflow_path')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch('WilmerAI.Middleware.workflows.managers.workflow_manager.api_utils.extract_text_from_chunk')
    def test_intermediate_streaming_output_is_captured_as_text(self,
                                                            mock_extract_text,
                                                            mock_file_open,
                                                            mock_get_workflow_path):
        """
        Verify that the output of an intermediate streaming node is aggregated
        into a single text string and stored correctly in `agent_outputs`.

        Scenario Tested:
        - Workflow has two steps: "Streaming Responder" and "Consumer".
        - Step 1 ("Streaming Responder") is mocked to return a simple generator
          yielding text chunks ("Hello", " ", "World"). This simulates an LLM call.
        - Step 2 ("Consumer") is configured to use the output of Step 1
          (implicitly via `{agent1Output}` in its prompt, although prompt processing
          is mocked here). It's marked as `returnToUser=True`.
        - The overall `run_workflow` call uses `stream=True`, meaning the *final*
          output *could* be streamed if the final step generated chunks.

        Assertions:
        - Checks that `_process_section` is called for both steps.
        - **Crucially**, asserts that `agent_outputs['agent1Output']` (the variable
          available to Step 2) contains the *aggregated string* "Hello World",
          proving the intermediate generator was fully consumed.
        - Asserts that the *final* output yielded by `run_workflow` is the
          result from Step 2 ("Processed response from consumer"), correctly
          formatted as an SSE chunk because `stream=True` was requested for the
          overall workflow and the *final* step didn't return a generator itself
          in this mock setup.
        """
        # Instantiate Manager INSIDE test
        manager = WorkflowManager(workflow_config_name="TestWorkflow")

        # Patch _process_section using 'with' on the specific instance
        with patch.object(manager, '_process_section') as mock_process_section:
            # Patch track_message_timestamps locally (needed if final step uses it)
            with patch('WilmerAI.Middleware.workflows.managers.workflow_manager.track_message_timestamps') as mock_track_timestamps:

                # GIVEN: Mock workflow config
                mock_workflow_config_steps_list = [
                    { "title": "Streaming Responder", "agentName": "Streamer", "endpointName": "TestEndpoint",
                      "preset": "TestPreset", "maxResponseSizeInTokens": 100, "type": "Standard" },
                    { "title": "Consumer", "agentName": "Consumer", "systemPrompt": "System prompt",
                      "prompt": "User prompt using {agent1Output}", "endpointName": "TestEndpoint",
                      "preset": "TestPreset", "maxResponseSizeInTokens": 100, "type": "Standard", "returnToUser": True }
                ]
                mock_workflow_config_dict = {"workflow": mock_workflow_config_steps_list}

                # Configure file loading mocks
                workflow_name = "TestWorkflow"
                mock_get_workflow_path.return_value = f"/fake/path/to/{workflow_name}.json"
                mock_file_open.return_value.read.return_value = json.dumps(mock_workflow_config_dict)

                # GIVEN: Test Data & Mocks
                initial_messages = [{"role": "user", "content": "Initial prompt"}]
                discussion_id = None
                captured_agent_outputs = {}

                # Mock generator for step 1
                def simple_generator():
                    yield '{"choices": [{"delta": {"content": "Hello"}}]}'
                    yield '{"choices": [{"delta": {"content": " "}}]}'
                    yield '{"choices": [{"delta": {"content": "World"}}]}'
                    yield '{"choices": [{}], "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}}'

                # Mock _process_section side effect
                def mock_process_section_side_effect(*args, **kwargs):
                    config = args[0]
                    step_agent_outputs = args[5] if len(args) > 5 else kwargs.get('agent_outputs', {})
                    # logging.debug(...) # Keep logs minimal for PR
                    if config.get("title") == "Streaming Responder":
                        return simple_generator()
                    elif config.get("title") == "Consumer":
                        captured_agent_outputs.update(step_agent_outputs)
                        return "Processed response from consumer"
                    return None
                mock_process_section.side_effect = mock_process_section_side_effect

                # Mock api_utils.extract_text_from_chunk
                def safe_extract(chunk):
                    try:
                        data = json.loads(chunk)
                        return data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    except Exception: return ""
                mock_extract_text.side_effect = safe_extract

                # --- WHEN: Execute Workflow ---
                workflow_gen = manager.run_workflow(
                    initial_messages, "test_req_id", discussion_id, stream=True
                )

                # --- Consume the generator ---
                final_output_list = []
                last_chunk = None
                try:
                    final_output_list = list(workflow_gen)
                    if final_output_list: last_chunk = final_output_list[-1]
                except Exception as e:
                    logging.error(f"Error consuming generator: {e}", exc_info=True)

                # === Assertions ===
                # Check mocks
                mock_get_workflow_path.assert_called_with(workflow_name)
                mock_file_open.assert_called_with(f"/fake/path/to/{workflow_name}.json")
                self.assertEqual(mock_process_section.call_count, 2)

                # Check captured output for intermediate step
                self.assertIn('agent1Output', captured_agent_outputs)
                self.assertIsInstance(captured_agent_outputs['agent1Output'], str)
                self.assertEqual(captured_agent_outputs['agent1Output'], "Hello World")

                # Check final yielded output (should be SSE chunk)
                self.assertGreaterEqual(len(final_output_list), 1)
                try:
                    self.assertTrue(isinstance(last_chunk, str) and last_chunk.startswith("data: "), f"Expected SSE chunk, got: '{last_chunk}'")
                    sse_data = json.loads(last_chunk[len("data: "):].strip())
                    self.assertEqual(sse_data.get('response'), "Processed response from consumer")
                except Exception as e:
                     self.fail(f"Final SSE output check failed. Last chunk: '{last_chunk}'. Error: {e}")

if __name__ == '__main__':
    unittest.main() 