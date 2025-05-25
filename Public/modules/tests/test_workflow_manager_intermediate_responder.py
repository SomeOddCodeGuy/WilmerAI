import unittest
import json
import sys
import os
from unittest.mock import patch, MagicMock, ANY, mock_open, AsyncMock
import logging
import asyncio

log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)

# Get the root logger and add the handler
root_logger = logging.getLogger()
# Clear existing handlers to avoid duplicate messages if the test runner also configures logging
if root_logger.hasHandlers():
    root_logger.handlers.clear()
root_logger.addHandler(console_handler)
root_logger.setLevel(logging.DEBUG) 
logger = logging.getLogger(__name__)

# Import necessary classes
from Middleware.workflows.managers.workflow_manager import WorkflowManager, EarlyTerminationException
from Middleware.llmapis.llm_api import LlmApiService
from Middleware.utilities.sql_lite_utils import SqlLiteUtils
from Middleware.utilities import config_utils, api_utils

# Helper function to consume the generator returned by run_workflow(stream=True)
def consume_sync_gen(gen):
    items = []
    for item in gen:
        items.append(item)
    return items

class TestWorkflowManagerIntermediateResponder(unittest.TestCase):
    """Tests the WorkflowManager's handling of intermediate responder steps."""

    def setUp(self):
        # Common test data
        self.workflow_name = "IntermediateResponderTest"
        self.initial_messages = [{"role": "user", "content": "Trigger intermediate"}]
        self.request_id = "inter-req-1"
        self.discussion_id = "inter-disc-1"
        self.frontend_api_type = "openaichatcompletion"
        self.mock_user_config = {'currentUser': 'test_inter_resp_user', 'chatPromptTemplateName': 'default'} # Define mock_user_config

        # Define workflow config structure used in tests
        self.step1_config = {"title": "Step 1 (Non-Responder)", "type": "Standard", "returnToUser": False}
        self.step2_config = {"title": "Step 2 (Responder)", "type": "Standard", "endpointName":"responder_ep", "returnToUser": True}
        self.step3_config = {"title": "Step 3 (After Responder)", "type": "Standard", "returnToUser": False}
        self.mock_workflow_config = [self.step1_config, self.step2_config, self.step3_config]
        self.fake_workflow_path = f'/fake/workflows/{self.workflow_name}.json'

    def test_intermediate_responder_streams_and_continues(self):
        """
        Test streaming from an intermediate responder node.
        
        Verifies that:
        1. The raw stream chunks from the intermediate step (`returnToUser: True`) 
           are correctly yielded by `run_workflow`.
        2. Subsequent steps *are still executed* after the intermediate streaming 
           step completes (reflecting current WorkflowManager behavior).
        3. The aggregated output from the streaming step is correctly passed 
           in `agent_outputs` to the subsequent step.
        """
        # --- GIVEN ---
        # Workflow defined in setUp: Step 1 (Non-Responder) -> Step 2 (Responder) -> Step 3 (After Responder)
        step1_output = "Output from Step 1"
        step2_stream_chunks = ["Chunk 1", " Chunk 2", " End"] # Chunks from the intermediate responder
        step2_aggregated_output = "".join(step2_stream_chunks)
        step3_output = "Output from Step 3"

        # Define a SYNC generator for the responder step's mock return value
        def step2_responder_generator():
            for chunk_text in step2_stream_chunks:
                # Simulate OpenAI chat completion chunk format
                yield {
                    "choices": [
                        {
                            "delta": {"content": chunk_text}
                        }
                    ]
                }

        # Define a SYNC side effect for the mock _process_section
        mock_process_section_instance = MagicMock() # Create mock instance
        def process_section_side_effect(*args, **kwargs):
            config = args[0] # First positional arg is config
            agent_outputs = args[5] # Sixth positional arg is agent_outputs
            stream_flag = kwargs.get('stream', args[6] if len(args) > 6 else False) # Check stream kwarg or 7th positional
            
            logger.debug(f"Mock _process_section called with config: {config.get('title')}, stream: {stream_flag}, agent_outputs: {agent_outputs}")

            # Match the steps defined in self.mock_workflow_config
            if config['title'] == "Step 1 (Non-Responder)":
                # Workflow stream=True, but this step is non-responder, so manager calls it with stream=False internally
                self.assertFalse(stream_flag, "Stream flag should be False for Step 1 (Non-Responder)")
                self.assertEqual(agent_outputs, {}, "agent_outputs should be empty for Step 1")
                logger.debug("Mock _process_section returning simple string for Step 1")
                return step1_output
            elif config['title'] == "Step 2 (Responder)":
                # This is the intermediate responder, manager calls it with stream=True
                self.assertTrue(stream_flag, "Stream flag should be True for Step 2 (Responder)")
                # Assert that the necessary prior output exists and is correct
                self.assertIn('agent1Output', agent_outputs, "'agent1Output' should be in agent_outputs for Step 2")
                self.assertEqual(agent_outputs['agent1Output'], step1_output, "agent_outputs['agent1Output'] should match Step 1 output for Step 2")
                
                logger.debug("Mock _process_section returning generator for Step 2 (Responder)")
                return step2_responder_generator()
            elif config['title'] == "Step 3 (After Responder)":
                 # Workflow stream=True, but this step is non-responder, so manager calls it with stream=False internally
                 self.assertFalse(stream_flag, "Stream flag should be False for Step 3 (After Responder)")
                 # IMPORTANT: The manager should have aggregated the generator from Step 2
                 self.assertEqual(agent_outputs, {'agent1Output': step1_output, 'agent2Output': step2_aggregated_output}, "agent_outputs mismatch during Step 3 call")
                 logger.debug("Mock _process_section returning simple string for Step 3")
                 return step3_output # Return the final output for this step
            else:
                 logger.error(f"Mock _process_section received unexpected config title: {config.get('title')}")
                 return "Unexpected Step" # Should not happen in this test
        mock_process_section_instance.side_effect = process_section_side_effect

        # Create a mock path finder function
        mock_get_path = MagicMock(return_value=self.fake_workflow_path)

        # Configure patches (REMOVE patch for default_get_workflow_path)
        with patch('Middleware.utilities.config_utils.get_user_config', return_value=self.mock_user_config) as mock_get_config, \
             patch('Middleware.workflows.managers.workflow_manager.LlmHandlerService') as MockLlmService, \
             patch('Middleware.workflows.managers.workflow_manager.SqlLiteUtils') as MockSqlUtils, \
             patch('builtins.open', mock_open(read_data=json.dumps(self.mock_workflow_config))) as mock_open_patch, \
             patch('Middleware.workflows.managers.workflow_manager.json.load', return_value=self.mock_workflow_config) as mock_json_load_patch, \
             patch.object(WorkflowManager, '_process_section', side_effect=process_section_side_effect) as mock_process_section: # Keep this patch target

            # Instantiate Manager *inside* the patch block, injecting the mock path finder
            manager = WorkflowManager(
                workflow_config_name=self.workflow_name,
                path_finder_func=mock_get_path # Inject mock here
            )
            # --- Assign instance mock AFTER creation ---
            manager._process_section = mock_process_section_instance

            # Call run_workflow
            result_generator = manager.run_workflow(
                messages=self.initial_messages,
                request_id=self.request_id,
                discussionId=self.discussion_id,
                stream=True # Manager is called with stream=True
            )
            # Consume the generator
            results = consume_sync_gen(result_generator)

        # --- Assertions ---
        # Verify _process_section calls on the instance mock
        self.assertEqual(mock_process_section_instance.call_count, 3,
                         f"Expected _process_section to be called 3 times. Calls: {mock_process_section_instance.call_args_list}")

        # Assert that the first step (Non-Responder) was called correctly
        step1_call_args, step1_call_kwargs = mock_process_section_instance.call_args_list[0]
        self.assertEqual(step1_call_args[0]['title'], "Step 1 (Non-Responder)")
        self.assertFalse(step1_call_kwargs.get('stream'), "Step 1 should be called with stream=False internally")

        # Assert that the second step (Responder) was called correctly
        step2_call_args, step2_call_kwargs = mock_process_section_instance.call_args_list[1]
        self.assertEqual(step2_call_args[0]['title'], "Step 2 (Responder)")
        self.assertTrue(step2_call_kwargs.get('stream'), "Step 2 should be called with stream=True")

        # Assert that the third step (After Responder) was called correctly
        step3_call_args, step3_call_kwargs = mock_process_section_instance.call_args_list[2]
        self.assertEqual(step3_call_args[0]['title'], "Step 3 (After Responder)")
        self.assertFalse(step3_call_kwargs.get('stream'), "Step 3 should be called with stream=False internally")

        # Construct the expected list of dictionary chunks yielded by the INTERMEDIATE responder (Step 2)
        expected_yielded_chunks = [
            {"choices": [{"delta": {"content": chunk_text}}]} for chunk_text in step2_stream_chunks
        ]
        # Assert the final result list contains ONLY the chunks yielded by the intermediate responder
        self.assertEqual(results, expected_yielded_chunks, "Final results should match the yielded dictionary chunks from the intermediate responder (Step 2)")

        # Verify other mocks (including the injected one)
        mock_get_path.assert_called_once_with(self.workflow_name)
        mock_get_config.assert_called_once()
        mock_open_patch.assert_called_once_with(self.fake_workflow_path) # Check file opened
        mock_json_load_patch.assert_called_once()
        MockLlmService.assert_called_once()
        MockSqlUtils.delete_node_locks.assert_called_once_with(ANY, ANY) # Use MockSqlUtils instance here

    # Add other tests here...

if __name__ == '__main__':
    unittest.main()