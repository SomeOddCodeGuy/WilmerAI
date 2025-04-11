#!/usr/bin/env python

"""
Unit tests for the WorkflowVariableManager class, focusing on message order handling 
and extraction of user messages, especially chat_user_prompt_last_one.
"""

import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Adjust import paths to access Middleware modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../WilmerAI")))

# Import the class under test
from Middleware.workflows.managers.workflow_variable_manager import WorkflowVariableManager
from Middleware.utilities.prompt_extraction_utils import extract_last_n_turns_as_string


class TestWorkflowVariableManager(unittest.TestCase):

    def setUp(self):
        """Set up common test dependencies."""
        # Create a mock LLM handler for testing
        self.mock_llm_handler = MagicMock()
        self.mock_llm_handler.takes_message_collection = True
        self.mock_llm_handler.prompt_template_file_name = "test_template"

        # Mock the template data (used as return value for patched loader)
        self.mock_template = {
            "promptTemplateUserPrefix": "U:",
            "promptTemplateUserSuffix": "",
            "promptTemplateAssistantPrefix": "A:",
            "promptTemplateAssistantSuffix": "",
            "promptTemplateSystemPrefix": "S:",
            "promptTemplateSystemSuffix": "",
            "promptTemplateEndToken": "<|end|>"
        }

    def test_generate_conversation_turn_variables_extracts_last_user_message(self):
        """GIVEN a sequence of messages, WHEN generate_conversation_turn_variables is called,
        THEN it should correctly extract the last user message for chat_user_prompt_last_one."""
        # ==================
        # GIVEN (Setup)
        # ==================
        # Messages in chronological order (oldest first)
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "First user message"},
            {"role": "assistant", "content": "First assistant response"},
            {"role": "user", "content": "Second user message"},
            {"role": "assistant", "content": "Second assistant response"},
            {"role": "user", "content": "Last user message"}
        ]
        expected_last_user_message = "Last user message"

        # ==================
        # WHEN (Action)
        # ==================
        # Use standard patch context managers
        with patch('Middleware.utilities.prompt_extraction_utils.extract_last_n_turns_as_string') as mock_extract, \
             patch('Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string') as mock_formatted, \
             patch('Middleware.utilities.prompt_template_utils.load_template_from_json') as mock_load_template:
            
            # Set return values
            mock_extract.return_value = "mocked_extract"
            mock_formatted.return_value = "mocked_formatted"
            mock_load_template.return_value = self.mock_template
            
            variables = WorkflowVariableManager.generate_conversation_turn_variables(
                messages, self.mock_llm_handler, None)

        # ==================
        # THEN (Assertions)
        # ==================
        self.assertEqual(variables["chat_user_prompt_last_one"], expected_last_user_message,
                        "Failed to extract the correct last user message")
        self.assertEqual(variables["templated_user_prompt_last_one"], "mocked_formatted",
                        "Templated prompt mock not applied correctly")

    def test_generate_conversation_turn_variables_handles_empty_messages(self):
        """GIVEN an empty messages list, WHEN generate_conversation_turn_variables is called,
        THEN it should return empty string for chat_user_prompt_last_one."""
        # ==================
        # GIVEN (Setup)
        # ==================
        messages = []

        # ==================
        # WHEN (Action)
        # ==================
        with patch('Middleware.utilities.prompt_extraction_utils.extract_last_n_turns_as_string') as mock_extract, \
             patch('Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string') as mock_formatted, \
             patch('Middleware.utilities.prompt_template_utils.load_template_from_json') as mock_load_template:
            
            mock_extract.return_value = "mocked_extract"
            mock_formatted.return_value = "mocked_formatted"
            mock_load_template.return_value = self.mock_template
            
            variables = WorkflowVariableManager.generate_conversation_turn_variables(
                messages, self.mock_llm_handler, None)

        # ==================
        # THEN (Assertions)
        # ==================
        self.assertEqual(variables["chat_user_prompt_last_one"], "",
                        "Failed to handle empty messages list correctly")

    def test_generate_conversation_turn_variables_with_assistant_placeholder(self):
        """GIVEN messages with an empty assistant placeholder at the end, WHEN generate_conversation_turn_variables is called,
        THEN it should still extract the correct last user message."""
        # ==================
        # GIVEN (Setup)
        # ==================
        # Messages with empty assistant placeholder at the end (added by add_missing_assistant)
        messages = [
            {"role": "user", "content": "First user message"},
            {"role": "assistant", "content": "First assistant response"},
            {"role": "user", "content": "Last user message"},
            {"role": "assistant", "content": ""}  # Empty placeholder
        ]
        expected_last_user_message = "Last user message"

        # ==================
        # WHEN (Action)
        # ==================
        with patch('Middleware.utilities.prompt_extraction_utils.extract_last_n_turns_as_string') as mock_extract, \
             patch('Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string') as mock_formatted, \
             patch('Middleware.utilities.prompt_template_utils.load_template_from_json') as mock_load_template:
            
            mock_extract.return_value = "mocked_extract"
            mock_formatted.return_value = "mocked_formatted"
            mock_load_template.return_value = self.mock_template
            
            variables = WorkflowVariableManager.generate_conversation_turn_variables(
                messages, self.mock_llm_handler, None)

        # ==================
        # THEN (Assertions)
        # ==================
        self.assertEqual(variables["chat_user_prompt_last_one"], expected_last_user_message,
                        "Failed to extract the correct last user message when an empty assistant placeholder exists")

    def test_apply_variables_simple_format_key_error(self):
        """GIVEN a simple prompt string without specific placeholders,
           WHEN apply_variables is called (simulating standard .format() path),
           THEN it should raise KeyError: 'messages' due to inclusion of unused variables.
           (This test verifies the bug reported in the traceback)
        """
        # GIVEN
        # Use with patch inside the test, similar to other tests
        with patch('Middleware.utilities.prompt_template_utils.load_template_from_json', return_value={"system_prefix": "SYS:", "user_prefix": "USR:", "assistant_prefix": "AST:", "generation_prompt": ""}) as mock_load_template, \
             patch('Middleware.utilities.config_utils.get_user_config', return_value={'chatPromptTemplateName': 'mock_template'}) as mock_get_config:
            
            # Instantiation should now work with get_user_config patched
            manager = WorkflowVariableManager()
            prompt_string = "Prompt with messages: {messages}" # Include the placeholder
            mock_llm_handler = MagicMock()
            mock_llm_handler.prompt_template_file_name = None # Assume no template for basic format
            messages = [{"role": "user", "content": "hello"}]
            agent_outputs = {}
            config = {"jinja2": False} # Force standard .format()

            # WHEN/THEN - Expect NO KeyError
            # with self.assertRaisesRegex(KeyError, "'messages'"):
            # The call should now succeed without raising KeyError
            formatted_prompt = manager.apply_variables(
                prompt=prompt_string,
                llm_handler=mock_llm_handler,
                messages=messages,
                agent_outputs=agent_outputs,
                config=config
            )
            # Optionally, assert the output is as expected (it should be unchanged for this simple string)
            # self.assertEqual(formatted_prompt, prompt_string, "Formatting changed the simple string unexpectedly.")
            # Assert that the messages list was correctly formatted into the string
            expected_output = f"Prompt with messages: {messages}"
            self.assertEqual(formatted_prompt, expected_output, "Messages variable was not correctly substituted.")


if __name__ == '__main__':
    unittest.main() 