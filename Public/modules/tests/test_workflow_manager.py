#!/usr/bin/env python

"""
Unit tests for the WorkflowManager focusing on state propagation.
"""

import unittest
import sys
import os
import uuid
import json
from unittest.mock import patch, MagicMock, ANY, call
import logging
from copy import deepcopy
from Middleware.exceptions.early_termination_exception import EarlyTerminationException

# === START Logging Configuration ===
log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)

# Get the root logger and add the handler
# You might want to target a specific logger if your application uses them (e.g., logging.getLogger('WilmerAI'))
root_logger = logging.getLogger()
# Clear existing handlers to avoid duplicate messages if the test runner also configures logging
if root_logger.hasHandlers():
    root_logger.handlers.clear()
root_logger.addHandler(console_handler)
root_logger.setLevel(logging.DEBUG) 
logger = logging.getLogger(__name__) # Optional: Get a logger specific to this test file
# === END Logging Configuration ===

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
    @patch('Middleware.utilities.config_utils.get_user_config', return_value={'chatPromptTemplateName': 'mock_template', 'currentUser': 'testuser'}) # Mock the user config directly
    def test_python_module_message_modification_propagation(self, 
                                                           mock_get_user_config, # Reverted mock name
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
        mock_workflow_config = {"workflow": [
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
        ]}
        
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

        # Corrected signature: Matches positional args passed by run_workflow loop
        # Added **kwargs to capture stream_override
        def process_section_side_effect(config, req_id, wf_id, disc_id, messages, 
                                        agent_outputs_arg, # Match the 6 positional args from run_workflow's call
                                        **kwargs): # Capture stream, addGenerationPrompt, etc.
            
            messages_received = messages # Direct access 

            if config["title"] == "Python Modifier":
                # Simulate Python module execution result (which includes modified messages)
                return {"messages": modified_messages_from_python} 
            elif config["title"] == "Standard Consumer":
                # Capture the messages list passed 
                standard_step_call_args['messages'] = messages_received 
                # Simulate LLM Response
                return "Final LLM Response" # Dummy final output
            else:
                return "Unexpected step"

        # Assign the corrected side effect function to the mock
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

    @patch('Middleware.workflows.managers.workflow_manager.get_workflow_path')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch.object(WorkflowManager, '_process_section') # Mock the core processing logic
    @patch('Middleware.workflows.managers.workflow_manager.LlmHandlerService') # Mock service used in __init__
    @patch('Middleware.workflows.managers.workflow_manager.SqlLiteUtils') # Mock DB calls
    @patch('Middleware.utilities.config_utils.get_user_config', return_value={'chatPromptTemplateName': 'mock_template', 'currentUser': 'testuser'}) # Mock user config
    def test_mcp_tool_result_propagation_to_final_node(self,
                                                     mock_get_user_config, # Reverted mock name
                                                     mock_sqlite,
                                                     mock_llm_service_factory, # Renamed for clarity
                                                     mock_process_section,
                                                     mock_file_open,
                                                     mock_get_workflow_path):
        """
        Tests the end-to-end flow for MCP:
        1. Extract tool names (LLM)
        2. Enhance prompt (Python Module - simulate returning map)
        3. Request tool call (LLM)
        4. Execute tool (Python Module - simulate returning formatted result)
        5. Generate final response (LLM - VERIFY IT RECEIVES TOOL RESULT)
        """
        # ==================
        # GIVEN (Arrange)
        # ==================
        workflow_name = "TestMCPWorkflow"
        request_id = "test_req_mcp"
        discussion_id = "test_disc_mcp"

        # --- Mock Workflow Definition ---
        # Simplified workflow reflecting the MCP steps
        mock_workflow_data = {
            "workflow": [
                {
                    "title": "Tool Service Extractor", # Step 0
                    "node_type": "Standard",
                    "model": "Worker-Endpoint",
                    "output_variables": {"extracted_services": "{response_text}"} # Assume LLM raw text output mapped
                },
                {
                    "title": "System Prompt Enhancer", # Step 1
                    "node_type": "PythonModule",
                    "module_path": "/path/to/ensure_system_prompt.py", # Path doesn't matter due to mock
                    "input_variables": {"services_to_discover": "{Tool Service Extractor.extracted_services}"},
                     # Simulate returning messages AND the map needed later
                    "output_variables": {"messages": "{messages}", "tool_execution_map": "{tool_map}"}
                },
                {
                    "title": "Tool Requester", # Step 2
                    "node_type": "Standard",
                    "model": "Worker-Endpoint",
                     # Input vars not strictly needed for mock, but good practice
                    "input_variables": {"messages": "{System Prompt Enhancer.messages}"},
                    "output_variables": {"llm_tool_request": "{response_text}"}
                },
                { # Step 3 - Sanitizer (Optional, can skip in mock if simple pass-through)
                  "title": "Sanitizer",
                  "node_type": "PythonModule",
                  "module_path": "/path/to/sanitizer.py",
                  "input_variables": {"raw_response": "{Tool Requester.llm_tool_request}"},
                  "output_variables": {"sanitized_llm_tool_request": "{result}"}
                },
                {
                    "title": "Tool Executor", # Step 4
                    "node_type": "PythonModule",
                    "module_path": "/path/to/mcp_workflow_integration.py",
                    "input_variables": {
                        "messages": "{System Prompt Enhancer.messages}", # Use messages from enhancer step
                        "original_response": "{Sanitizer.sanitized_llm_tool_request}", # Use sanitized request
                        "tool_execution_map": "{System Prompt Enhancer.tool_execution_map}" # Use map from enhancer step
                    },
                    "output_variables": {"tool_execution_output": "{result}"} # Map the python script's return
                },
                {
                    "title": "Final Response Generator", # Step 5
                    "node_type": "Standard",
                    "model": "Worker-Endpoint",
                     # CRITICAL: Ensure tool results are mapped as input
                    "input_variables": {
                        "messages": "{System Prompt Enhancer.messages}", # Use enhanced messages
                        "tool_results_for_prompt": "{Tool Executor.tool_execution_output}" # Map executor output
                        # Assume prompt template uses 'tool_results_for_prompt'
                    },
                    "stream": True # Match typical final step
                    # Output is implicitly the stream
                }
            ]
        }
        mock_file_open.return_value.read.return_value = json.dumps(mock_workflow_data)
        mock_get_workflow_path.return_value = f"/path/to/{workflow_name}.json" # Doesn't matter

        # --- Initial State ---
        initial_messages = [
            {"role": "system", "content": "Initial System Prompt"},
            {"role": "user", "content": "what is the latest python version? search for it"}
        ]
        # Add placeholder assistant message if needed by the starting logic
        initial_messages_with_placeholder = initial_messages + [{"role": "assistant", "content": ""}]


        # --- Define Expected Data Flow ---
        extracted_services_output = "tavily"
        enhanced_messages = [ # Simulate messages list *after* step 1 modifies system prompt
             {"role": "system", "content": "Initial System Prompt\nAvailable Tools: [...]"}, # Simplified
             {"role": "user", "content": "what is the latest python version? search for it"},
             {"role": "assistant", "content": ""}
        ]
        tool_map = {"tool_endpoint_tavily_search_post": {"service": "tavily", "path": "/s", "method": "post"}} # Simplified map
        tool_request_json = """{
          "tool_calls": [
            {"name": "tool_endpoint_tavily_search_post", "parameters": {"query": "latest python version"}}
          ]
        }"""
        # CRITICAL: This is the expected *output string* from the Tool Executor step (Step 4)
        formatted_tool_result_string = """Tool Results:

Tool:
Name: tool_endpoint_tavily_search_post
Parameters: {
  "query": "latest python version"
}

Result: [
  "Python 3.13.0 is the latest."
]"""
        final_llm_response = "According to the search, the latest version is Python 3.13.0."

        # --- Mock _process_section Side Effect ---
        # Capture arguments passed to the final step
        final_step_call_args = {}

        # Corrected signature: Matches positional args passed by run_workflow loop
        # Added **kwargs to capture stream_override
        def process_section_side_effect(config, request_id, workflow_id, discussion_id, messages, 
                                        agent_outputs, # Match the 6 positional args from run_workflow's call
                                        **kwargs): # Capture stream, addGenerationPrompt, etc.
            step_title = config.get("title")
            print(f"\n--- Mock _process_section called for: {step_title} ---")

            if step_title == "Tool Service Extractor": # Step 0
                # Simulate LLM outputting service names (direct string result)
                return extracted_services_output 
            elif step_title == "System Prompt Enhancer": # Step 1
                # Simulate Python module that returns a tool map and internally modifies messages
                # Return the direct output (tool map) + the message modification structure
                return {"messages": enhanced_messages, "tool_map": tool_map}
            elif step_title == "Tool Requester": # Step 2
                # Simulate LLM outputting tool request JSON (direct string result)
                return tool_request_json
            elif step_title == "Sanitizer": # Step 3
                # Simulate Python module returning sanitized result (direct string result)
                # Get input from the *actual* agent_outputs dict maintained by the main loop
                # Access the output of the previous step (Tool Requester, which was idx=2, output key agent3Output)
                return agent_outputs.get("agent3Output") 
            elif step_title == "Tool Executor": # Step 4
                # Simulate Python module executing tool and returning formatted string (direct string result)
                return formatted_tool_result_string
            elif step_title == "Final Response Generator": # Step 5
                # **** CAPTURE ARGUMENTS for the final step ****
                # We need to capture the 'agent_outputs' dict passed to this call
                # This dict should contain the results from previous steps
                final_step_call_args['config'] = deepcopy(config)
                final_step_call_args['messages'] = deepcopy(messages)
                final_step_call_args['agent_outputs'] = deepcopy(agent_outputs) # Capture the crucial outputs dict
                final_step_call_args['kwargs'] = deepcopy(kwargs) # Capture stream etc. if needed later
                print(f"DEBUG: [MCP Test] Side effect captured args for Final Response Generator.")
                # Simulate final LLM response (direct string result)
                return final_llm_response
            else:
                raise ValueError(f"Unexpected step title in mock: {step_title}")

        # Assign the corrected side effect function to the mock
        mock_process_section.side_effect = process_section_side_effect

        # Mock the LLM service factory to return a mock handler
        mock_llm_handler = MagicMock()
        # Set attributes expected by WorkflowManager if needed (e.g., takes_message_collection)
        mock_llm_handler.takes_message_collection = True
        mock_llm_service_factory.return_value.get_llm_handler.return_value = mock_llm_handler


        # Instantiate the manager
        # Pass a mock LLM service factory if WorkflowManager uses it in __init__
        manager = WorkflowManager(workflow_config_name=workflow_name, llm_service_factory=mock_llm_service_factory.return_value)

        # ==================
        # WHEN (Action)
        # ==================
        # run_workflow returns a generator, exhaust it for non-streaming test assertion
        # Use stream=False to get the final result string directly
        result = manager.run_workflow(initial_messages, request_id, discussion_id, stream=False)

        # ==================
        # THEN (Assertions)
        # ==================
        print(f"DEBUG: [MCP Test] Result received from run_workflow: {result}") # Added Debug Log
        print(f"\nFinal result from run_workflow: {result}")
        print(f"Arguments captured for final step call: {json.dumps(final_step_call_args, default=str, indent=2)}") # Use default=str for non-serializable

        # 1. Check final output
        self.assertEqual(result, final_llm_response)

        # 2. Check that _process_section was called for each step
        self.assertEqual(mock_process_section.call_count, 6, "Should process all 6 defined steps")

        # 3. Verify agent_outputs passed to the final step processing
        self.assertIn('agent_outputs', final_step_call_args,
                      "Arguments for final step processing were not captured correctly (missing 'agent_outputs')")
        final_step_received_agent_outputs = final_step_call_args['agent_outputs']

        # Check that the agent_outputs received by the final step's processing contains
        # the output from the previous step (Tool Executor). The key should be 'agent5Output'
        # because Tool Executor is the 5th step (index 4).
        self.assertIn('agent5Output', final_step_received_agent_outputs,
                      "Output from Tool Executor (agent5Output) not found in agent_outputs passed to final step")
        self.assertEqual(final_step_received_agent_outputs['agent5Output'], formatted_tool_result_string,
                         "Incorrect tool execution result passed to final step via agent_outputs")

    # ===== New Test Method for Prompt Overrides =====
    @patch('Middleware.workflows.managers.workflow_manager.get_workflow_path')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch.object(WorkflowManager, '_process_section')
    @patch('Middleware.workflows.managers.workflow_manager.LlmHandlerService', MockLlmHandlerService) # Use defined mock
    @patch('Middleware.workflows.managers.workflow_manager.SqlLiteUtils')
    @patch('Middleware.utilities.config_utils.get_user_config', return_value={'chatPromptTemplateName': 'mock_template', 'currentUser': 'testuser'})
    def test_first_node_prompt_override_applied_correctly(self,
                                                         mock_get_user_config, # Reverted mock name
                                                         mock_sqlite,
                                                         mock_process_section,
                                                         mock_file_open,
                                                         mock_get_workflow_path):
        """
        Tests that first_node_system_prompt_override and first_node_prompt_override
        are applied only to the *first* node in the workflow that has prompts defined.
        """
        # ==================
        # GIVEN (Setup)
        # ==================
        workflow_name = "test_override_workflow"
        request_id = str(uuid.uuid4())
        discussion_id = "test_discussion_override"
        initial_messages = [{"role": "user", "content": "User Query"}]
        
        override_system_prompt = "OVERRIDDEN System Prompt"
        override_user_prompt = "OVERRIDDEN User Prompt: {{ chat_user_prompt_last_one }}"

        original_step1_config = {
            "title": "Step 1 - No Prompts",
            "type": "Standard",
            "endpointName": "DummyEndpoint1" # Needs endpoint for mock handler
        }
        original_step2_config = {
            "title": "Step 2 - First Prompts",
            "type": "Standard",
            "endpointName": "DummyEndpoint2",
            "systemPrompt": "Original System 2",
            "prompt": "Original User 2: {{ chat_user_prompt_last_one }}"
        }
        original_step3_config = {
            "title": "Step 3 - Second Prompts",
            "type": "Standard",
            "endpointName": "DummyEndpoint3",
            "systemPrompt": "Original System 3",
            "prompt": "Original User 3: {{ chat_user_prompt_last_one }}",
            "returnToUser": True
        }
        
        mock_workflow_config = {
            "workflow": [
                original_step1_config,
                original_step2_config,
                original_step3_config
            ]
        }
        
        # Configure mocks
        mock_get_workflow_path.return_value = f"/fake/path/to/{workflow_name}.json"
        mock_file_open.return_value.read.return_value = json.dumps(mock_workflow_config)

        # --- Mock _process_section behavior ---
        captured_configs = {}
        
        # Capture the config passed to each step
        def process_section_capture_config(config, req_id, wf_id, disc_id, messages, 
                                        agent_outputs_arg, **kwargs): # Match signature used internally
            step_title = config.get('title', 'Unknown')
            # Make a deep copy to avoid issues with the manager potentially modifying the dict later
            captured_configs[step_title] = deepcopy(config)
            return f"Output from {step_title}" # Dummy return value

        mock_process_section.side_effect = process_section_capture_config

        # Instantiate the manager
        manager = WorkflowManager(workflow_config_name=workflow_name)

        # ==================
        # WHEN (Action)
        # ==================
        # run_workflow returns a generator, exhaust it for non-streaming
        result = manager.run_workflow(
            initial_messages, 
            request_id, 
            discussion_id, 
            stream=False,
            first_node_system_prompt_override=override_system_prompt,
            first_node_prompt_override=override_user_prompt
        )

        # ==================
        # THEN (Assertions)
        # ==================
        self.assertEqual(result, "Output from Step 3 - Second Prompts", "Ensure final step output is returned")
        self.assertEqual(mock_process_section.call_count, 3, "Should process three steps")

        # Verify Step 1 config (no prompts originally) was untouched
        self.assertIn(original_step1_config['title'], captured_configs)
        self.assertNotIn('systemPrompt', captured_configs[original_step1_config['title']])
        self.assertNotIn('prompt', captured_configs[original_step1_config['title']])
        
        # Verify Step 2 config (first with prompts) received the overrides
        self.assertIn(original_step2_config['title'], captured_configs)
        step2_captured_config = captured_configs[original_step2_config['title']]
        self.assertEqual(step2_captured_config.get('systemPrompt'), override_system_prompt)
        self.assertEqual(step2_captured_config.get('prompt'), override_user_prompt)

        # Verify Step 3 config (second with prompts) kept its *original* prompts
        self.assertIn(original_step3_config['title'], captured_configs)
        step3_captured_config = captured_configs[original_step3_config['title']]
        self.assertEqual(step3_captured_config.get('systemPrompt'), original_step3_config['systemPrompt'])
        self.assertEqual(step3_captured_config.get('prompt'), original_step3_config['prompt'])

    # ===== New Test Method for Non-Streaming Final Generator Aggregation =====
    @patch('Middleware.workflows.managers.workflow_manager.get_workflow_path')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch.object(WorkflowManager, '_process_section')
    @patch('Middleware.workflows.managers.workflow_manager.LlmHandlerService', MockLlmHandlerService) # Use defined mock
    @patch('Middleware.workflows.managers.workflow_manager.SqlLiteUtils')
    @patch('Middleware.utilities.config_utils.get_user_config', return_value={'chatPromptTemplateName': 'mock_template', 'currentUser': 'testuser'})
    @patch('Middleware.workflows.managers.workflow_manager.api_utils.extract_text_from_chunk') # Need to mock extraction used by aggregation
    def test_non_streaming_final_step_generator_aggregation(self,
                                                            mock_extract_text,
                                                            mock_get_user_config, # Reverted mock name
                                                            mock_sqlite,
                                                            mock_process_section,
                                                            mock_file_open,
                                                            mock_get_workflow_path):
        """
        Tests that if stream=False, but the final step returns a generator,
        the generator is aggregated and the final text result is returned.
        """
        # ==================
        # GIVEN (Setup)
        # ==================
        workflow_name = "test_final_gen_agg_workflow"
        request_id = str(uuid.uuid4())
        discussion_id = "test_discussion_final_gen_agg"
        initial_messages = [{"role": "user", "content": "User Query"}]

        final_step_config = {
            "title": "Final Step Generator",
            "type": "Standard",
            "endpointName": "DummyEndpointFinal",
            "returnToUser": True
        }
        
        mock_workflow_config = {
            "workflow": [ final_step_config ]
        }
        
        # Configure mocks
        mock_get_workflow_path.return_value = f"/fake/path/to/{workflow_name}.json"
        mock_file_open.return_value.read.return_value = json.dumps(mock_workflow_config)

        # --- Mock _process_section behavior ---
        # Define the simple generator to be returned by the final step
        def simple_final_generator():
            yield '{"chunk": "Chunk 1"}' # Simulate JSON chunks
            yield '{"chunk": " Chunk 2"}'
            yield '{"ignored_key": "value"}' # Chunk without extractable text

        mock_process_section.return_value = simple_final_generator() # Return the generator instance

        # Mock the text extraction utility used by _aggregate_text_from_stream_generator
        def mock_extractor(chunk_str):
            try:
                data = json.loads(chunk_str)
                return data.get("chunk", "") # Extract content from 'chunk' key
            except: 
                return "" 
        mock_extract_text.side_effect = mock_extractor

        # Instantiate the manager
        manager = WorkflowManager(workflow_config_name=workflow_name)

        # ==================
        # WHEN (Action)
        # ==================
        # Call run_workflow with stream=False
        result = manager.run_workflow(
            initial_messages, 
            request_id, 
            discussion_id, 
            stream=False # Key setting for this test
        )

        # ==================
        # THEN (Assertions)
        # ==================
        self.assertEqual(mock_process_section.call_count, 1, "Should process one step")
        mock_extract_text.assert_called() # Ensure aggregation helper was called

        # Verify the final result is the aggregated string
        self.assertEqual(result, "Chunk 1 Chunk 2", 
                         "Final non-streaming result should be the aggregated text from the generator")
        self.assertIsInstance(result, str) # Ensure it's not the generator object

    # ===== Test Method for Early Termination (Refactored to use 'with patch') =====
    def test_early_termination_exception_propagates_and_cleans_up(self):
        """
        Tests that if _process_section raises EarlyTerminationException, the
        exception propagates out of run_workflow, and SqlLiteUtils.delete_node_locks
        is called by the finally block.
        (Uses 'with patch' instead of decorators).
        """
        # Define mocks using context managers
        with patch('Middleware.workflows.managers.workflow_manager.get_workflow_path') as mock_get_workflow_path, \
             patch('builtins.open', new_callable=unittest.mock.mock_open) as mock_file_open, \
             patch.object(WorkflowManager, '_process_section') as mock_process_section, \
             patch('Middleware.workflows.managers.workflow_manager.LlmHandlerService') as mock_llm_service, \
             patch('Middleware.workflows.managers.workflow_manager.SqlLiteUtils') as mock_sqlite, \
             patch('Middleware.utilities.config_utils.get_user_config', return_value={'chatPromptTemplateName': 'mock_template', 'currentUser': 'testuser'}) as mock_get_user_config, \
             patch('Middleware.workflows.managers.workflow_manager.instance_utils.INSTANCE_ID', 'test-instance-id') as mock_instance_id, \
             patch('Middleware.workflows.managers.workflow_manager.uuid.uuid4') as mock_uuid4:

            # ==================
            # GIVEN
            # ==================
            workflow_name = "test_termination_workflow"
            request_id = "test_req_terminate" # Use a fixed request_id for clarity
            discussion_id = "test_discussion_terminate"
            initial_messages = [{"role": "user", "content": "Query"}]

            step_config = {"title": "Terminator Step", "type": "WorkflowLock"}
            mock_workflow_config = {"workflow": [step_config]}

            mock_get_workflow_path.return_value = f"/fake/path/to/{workflow_name}.json"
            mock_file_open.return_value.read.return_value = json.dumps(mock_workflow_config)

            # Mock _process_section to raise the exception
            termination_message = "Workflow locked!"
            mock_process_section.side_effect = EarlyTerminationException(termination_message)
            
            # Get a reference to the class method we want to assert on
            # Note: We patch SqlLiteUtils the *class*, so the mock is the class itself.
            # We need to access the class method on the *mock class*.
            mock_delete_locks = mock_sqlite.delete_node_locks 
            
            # Set the workflow_id that will be generated
            test_workflow_id = "fixed-workflow-id-for-test"
            mock_uuid4.return_value = test_workflow_id

            # Instantiate the manager *inside* the patch context
            # This ensures it uses the mocked dependencies (like LlmHandlerService)
            manager = WorkflowManager(workflow_config_name=workflow_name)

            # ==================
            # WHEN & THEN (Exception Assertion)
            # ==================
            with self.assertRaises(EarlyTerminationException) as cm:
                # Consume the generator for non-streaming case 
                the_generator = manager.run_workflow(initial_messages, request_id, discussion_id, stream=False)
                list(the_generator) # This should trigger the exception
                    
            # Assert the exception message is correct
            self.assertEqual(str(cm.exception), termination_message)

            # Assert that cleanup was called *after* the exception was handled
            # mock_instance_id is the patched *value* 'test-instance-id'
            mock_delete_locks.assert_called_once_with('test-instance-id', test_workflow_id)

    # ===== New Test Method for Timestamp Logic (Negative Cases) =====
    @patch('Middleware.workflows.managers.workflow_manager.get_workflow_path')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch.object(WorkflowManager, '_process_section')
    @patch('Middleware.workflows.managers.workflow_manager.LlmHandlerService', MockLlmHandlerService)
    @patch('Middleware.workflows.managers.workflow_manager.SqlLiteUtils')
    @patch('Middleware.utilities.config_utils.get_user_config', return_value={'chatPromptTemplateName': 'mock_template', 'currentUser': 'testuser'})
    @patch('Middleware.workflows.managers.workflow_manager.track_message_timestamps')
    def test_timestamp_not_added_when_conditions_not_met(self,
                                                         mock_track_timestamps,
                                                         mock_get_user_config, # Reverted mock name
                                                         mock_sqlite,
                                                         mock_process_section,
                                                         mock_file_open,
                                                         mock_get_workflow_path):
        """
        Tests that track_message_timestamps is NOT called when conditions are not met:
        - nonResponder=True
        - discussion_id=None
        - addDiscussionIdTimestampsForLLM=False
        """
        # --- Common Setup ---
        workflow_name = "test_no_timestamp_workflow"
        request_id = str(uuid.uuid4())
        initial_messages = [{"role": "user", "content": "Query"}]
        final_step_config_base = {
            "title": "Final Step No Timestamps", "type": "Standard",
            "endpointName": "DummyNoTS", "returnToUser": True
        }
        mock_get_workflow_path.return_value = f"/fake/path/to/{workflow_name}.json"

        captured_process_section_messages = None
        def process_section_capture(config, req_id, wf_id, disc_id, messages, outputs, **kwargs):
            nonlocal captured_process_section_messages
            captured_process_section_messages = messages
            return "Final Output"
        mock_process_section.side_effect = process_section_capture
        manager = WorkflowManager(workflow_config_name=workflow_name)
        
        # --- Test Case 1: addDiscussionIdTimestampsForLLM = False ---
        mock_track_timestamps.reset_mock()
        mock_process_section.reset_mock()
        captured_process_section_messages = None
        config_flag_off = {**final_step_config_base, "addDiscussionIdTimestampsForLLM": False}
        mock_workflow_config_1 = {"workflow": [config_flag_off]}
        mock_file_open.return_value.read.return_value = json.dumps(mock_workflow_config_1)
        manager.run_workflow(initial_messages, request_id, "disc-id-present", stream=False)
        mock_track_timestamps.assert_not_called()
        self.assertEqual(captured_process_section_messages, initial_messages, "Case 1 Failed: Original messages expected")

        # --- Test Case 2: nonResponder = True ---
        mock_track_timestamps.reset_mock()
        mock_process_section.reset_mock()
        captured_process_section_messages = None
        config_flag_on = {**final_step_config_base, "addDiscussionIdTimestampsForLLM": True}
        mock_workflow_config_2 = {"workflow": [config_flag_on]}
        mock_file_open.return_value.read.return_value = json.dumps(mock_workflow_config_2)
        manager.run_workflow(initial_messages, request_id, "disc-id-present", stream=False, nonResponder=True)
        mock_track_timestamps.assert_not_called()
        self.assertEqual(captured_process_section_messages, initial_messages, "Case 2 Failed: Original messages expected")
        
        # --- Test Case 3: discussion_id = None ---
        mock_track_timestamps.reset_mock()
        mock_process_section.reset_mock()
        captured_process_section_messages = None
        # Config flag is True, nonResponder is None (default)
        mock_workflow_config_3 = {"workflow": [config_flag_on]}
        mock_file_open.return_value.read.return_value = json.dumps(mock_workflow_config_3)
        manager.run_workflow(initial_messages, request_id, None, stream=False) # Pass None for discussionId
        mock_track_timestamps.assert_not_called()
        self.assertEqual(captured_process_section_messages, initial_messages, "Case 3 Failed: Original messages expected")

    # ===== New Test Method for Empty Workflow =====
    @patch('Middleware.workflows.managers.workflow_manager.get_workflow_path')
    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch.object(WorkflowManager, '_process_section') # Still need to patch this
    @patch('Middleware.workflows.managers.workflow_manager.LlmHandlerService', MockLlmHandlerService)
    @patch('Middleware.workflows.managers.workflow_manager.SqlLiteUtils')
    @patch('Middleware.utilities.config_utils.get_user_config', return_value={'chatPromptTemplateName': 'mock_template', 'currentUser': 'testuser'})
    def test_empty_workflow_returns_correctly(self,
                                            mock_get_user_config, # Reverted mock name
                                            mock_sqlite,
                                            mock_process_section, # Mock needed but won't be called
                                            mock_file_open,
                                            mock_get_workflow_path):
        """
        Tests that run_workflow handles an empty workflow configuration gracefully.
        - Non-streaming should return None.
        - Streaming should return an empty generator.
        """
        # ==================
        # GIVEN
        # ==================
        workflow_name = "test_empty_workflow"
        request_id = str(uuid.uuid4())
        initial_messages = [{"role": "user", "content": "Query"}]
        
        # Empty workflow list
        mock_workflow_config = {"workflow": []}

        mock_get_workflow_path.return_value = f"/fake/path/to/{workflow_name}.json"
        mock_file_open.return_value.read.return_value = json.dumps(mock_workflow_config)
        
        # Mock cleanup function to ensure finally block is reached
        mock_delete_locks = mock_sqlite.delete_node_locks 
        
        manager = WorkflowManager(workflow_config_name=workflow_name)

        # ==================
        # WHEN & THEN (Non-Streaming)
        # ==================
        mock_delete_locks.reset_mock()
        result_non_stream = manager.run_workflow(initial_messages, request_id, "disc-empty", stream=False)
        self.assertIsNone(result_non_stream, "Non-streaming empty workflow should return None")
        mock_process_section.assert_not_called() # Ensure no steps were processed
        mock_delete_locks.assert_called_once() # Ensure cleanup still happens

        # ==================
        # WHEN & THEN (Streaming)
        # ==================
        mock_process_section.reset_mock()
        mock_delete_locks.reset_mock()
        result_stream_gen = manager.run_workflow(initial_messages, request_id, "disc-empty", stream=True)
        
        # Consume the generator
        consumed_results = list(result_stream_gen)
        
        self.assertEqual(consumed_results, [], "Streaming empty workflow should yield an empty list")
        mock_process_section.assert_not_called() # Ensure no steps were processed
        mock_delete_locks.assert_called_once() # Ensure cleanup still happens

class TestWorkflowManagerFinalStreamingFormat(unittest.TestCase):
    """Tests specifically the formatting of the final yielded output."""

    def setUp(self):
        # Common mocks needed for WorkflowManager initialization and execution
        self.patcher_sqlite = patch('Middleware.workflows.managers.workflow_manager.SqlLiteUtils')
        self.mock_sqlite = self.patcher_sqlite.start()
        self.patcher_var_manager = patch('Middleware.workflows.managers.workflow_manager.WorkflowVariableManager')
        self.mock_var_manager = self.patcher_var_manager.start()
        self.patcher_llm_service = patch('Middleware.workflows.managers.workflow_manager.LlmHandlerService')
        self.mock_llm_service = self.patcher_llm_service.start()
        self.patcher_get_path = patch('Middleware.workflows.managers.workflow_manager.get_workflow_path')
        self.mock_get_path = self.patcher_get_path.start()
        self.patcher_track_ts = patch('Middleware.workflows.managers.workflow_manager.track_message_timestamps')
        self.mock_track_ts = self.patcher_track_ts.start()
        # Mock the chunk extraction utility
        self.patcher_extract_chunk = patch('Middleware.workflows.managers.workflow_manager.api_utils.extract_text_from_chunk')
        self.mock_extract_chunk = self.patcher_extract_chunk.start()

    def tearDown(self):
        patch.stopall()

    # Removed patch for extract_text_from_chunk
    def test_final_yield_preserves_plain_json_format(self):
        """
        Test that _yield_final_output yields plain JSON lines if the input chunk lacks 'data:'.
        Simulates the scenario with ollamagenerate API type.
        """
        # --- GIVEN ---
        workflow_name = "test-plain-json-yield"
        self.mock_get_path.return_value = f"/fake/{workflow_name}.json"

        # Mock workflow config with one final step
        workflow_config = {
            "workflow": [
                {"title": "Final Step", "type": "Standard", "endpointName": "fake", "returnToUser": True}
            ]
        }
        with patch('builtins.open', new_callable=unittest.mock.mock_open) as mock_open_func:
            mock_open_func.return_value.read.return_value = json.dumps(workflow_config)

            # Mock generator simulating ollamagenerate output (plain JSON lines)
            plain_json_chunk1 = '{"response": "Hello"}\n'
            plain_json_chunk2 = '{"response": " World"}\n'
            plain_json_chunk_done = '{"response": "", "done": true}\n'
            expected_chunks = [plain_json_chunk1, plain_json_chunk2, plain_json_chunk_done]

            def mock_handler_generator():
                # Yield the raw chunks directly
                yield plain_json_chunk1
                yield plain_json_chunk2
                yield plain_json_chunk_done

            # Mock _process_section to return the plain JSON generator for the final step
            mock_process_result = mock_handler_generator()
            manager = WorkflowManager(workflow_config_name=workflow_name)
            manager._process_section = MagicMock(return_value=mock_process_result)

            initial_messages = [{"role": "user", "content": "Hi"}]

            # --- WHEN ---
            # Call run_workflow in streaming mode
            result_generator = manager.run_workflow(initial_messages, "req-1", "disc-1", stream=True)

            # Consume the generator returned by run_workflow
            yielded_chunks = list(result_generator)

            # --- THEN ---
            # Verify _process_section was called for the final step
            manager._process_section.assert_called_once()

            # Assert that the final yielded chunks match the source chunks exactly
            self.assertEqual(len(yielded_chunks), 3)
            self.assertEqual(yielded_chunks, expected_chunks)

# ============================================================
# NEW Test Class for _yield_final_output Formatting
# ============================================================
class TestWorkflowManagerFinalYieldFormat(unittest.TestCase):
    """Tests focused specifically on the _yield_final_output helper method."""

    def setUp(self):
        # Basic setup needed if WorkflowManager instance is created, 
        # otherwise we can test _yield_final_output more directly if possible.
        # For simplicity, let's mock dependencies needed for basic init.
        self.mock_user_config = patch('Middleware.utilities.config_utils.get_user_config', return_value={'chatPromptTemplateName': 'mock_template'})
        self.mock_instance_user = patch('Middleware.utilities.instance_utils.USER', 'test_user')
        self.mock_makedirs = patch('os.makedirs')
        self.mock_sqlite = patch('Middleware.utilities.sql_lite_utils.SqlLiteUtils') # Patch the whole class

        # Start mocks
        self.mock_user_config.start()
        self.mock_instance_user.start()
        self.mock_makedirs.start()
        self.mock_sqlite.start()
        
        # Instantiate the manager (needed to call the protected method)
        # Requires a workflow name, even if we don't load it.
        self.manager = WorkflowManager(workflow_config_name="DummyWorkflowForInit")

    def tearDown(self):
        # Stop mocks
        self.mock_user_config.stop()
        self.mock_instance_user.stop()
        self.mock_makedirs.stop()
        self.mock_sqlite.stop()

    # Removed patch for extract_text_from_chunk
    def test_yield_final_output_standard_sse_format(self):
        """Verify standard SSE format is yielded when input chunk starts with 'data:'."""
        # GIVEN: Mock source generator yielding SSE strings
        sse_chunk_1 = 'data: { "choices": [{ "delta": { "content": "Hello" } }] }\n\n'
        sse_chunk_2 = 'data: { "choices": [{ "delta": { "content": " World" } }] }\n\n'
        sse_chunk_done = 'data: [DONE]\n\n'
        expected_chunks = [sse_chunk_1, sse_chunk_2, sse_chunk_done]
        
        def mock_source_generator():
            yield sse_chunk_1
            yield sse_chunk_2
            yield sse_chunk_done
        
        # WHEN: Call _yield_final_output with the mock generator
        result_generator = self.manager._yield_final_output(
            result=mock_source_generator(), 
            output_value_stored=None, # Not relevant for streaming case
            stream=True, 
            idx=1, 
            step_title="Final Step"
        )
        
        # THEN: Consume the generator and check output format
        output_list = list(result_generator)
        
        # Assert that the yielded chunks match the source chunks exactly
        self.assertEqual(output_list, expected_chunks)
        self.assertEqual(len(output_list), 3) # Check length matches source

    # Removed patch for extract_text_from_chunk
    def test_yield_final_output_plain_json_format(self):
        """Verify plain JSON format is yielded when input chunk does NOT start with 'data:'."""
        # GIVEN: Mock source generator yielding plain JSON strings (like Ollama)
        json_chunk_1 = '{"response": "Ollama says"}\n'
        json_chunk_2 = '{"response": " hi"}\n'
        json_chunk_done = '{"response": "", "done": true}\n' # Done signal
        expected_chunks = [json_chunk_1, json_chunk_2, json_chunk_done]

        def mock_source_generator():
            yield json_chunk_1
            yield json_chunk_2
            yield json_chunk_done
        
        # WHEN: Call _yield_final_output
        result_generator = self.manager._yield_final_output(
            result=mock_source_generator(), 
            output_value_stored=None, 
            stream=True, 
            idx=1, 
            step_title="Final Step"
        )
        
        # THEN: Consume and check output format
        output_list = list(result_generator)
        
        # Assert that the yielded chunks match the source chunks exactly
        self.assertEqual(output_list, expected_chunks)
        self.assertEqual(len(output_list), 3) # Check length matches source

if __name__ == '__main__':
    unittest.main()