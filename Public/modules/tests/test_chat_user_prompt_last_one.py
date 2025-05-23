#!/usr/bin/env python

# Unit test for the WorkflowVariableManager's handling of 'chat_user_prompt_last_one'.
# This variable is crucial for workflows that need to isolate the user's most recent
# input (e.g., for RAG, specific tool commands, or focused analysis).
# This test ensures that given a conversation history, the manager correctly
# extracts and provides the content of the last user message.
# For example, if the history is:
#   User: "Hello"
#   Assistant: "Hi"
#   User: "What's the weather?"
# The 'chat_user_prompt_last_one' should be "What's the weather?".
# The test also verifies behavior with empty or no user messages.

# Example how to run the test from folder that contains the WilmerAI folder:
# export PYTHONPATH=/path/to/WilmerAI:${PYTHONPATH} && /path/to/WilmerAI/venv/bin/python3 -m unittest WilmerAI/Public/modules/tests/test_chat_user_prompt_last_one.py

"""
Simple verification script for the chat_user_prompt_last_one variable fix.
This script bypasses the need for mocking complex dependencies.
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

class TestChatUserPromptLastOne(unittest.TestCase):

    @staticmethod
    def mock_extract_last_n_turns_as_string(messages, n, include_sysmes=True, remove_all_systems_override=False):
        # This mock should only return non-system, non-image messages' content
        filtered_messages = []
        for msg in messages:
            if msg.get("role") not in ["system", "images"]:
                filtered_messages.append(msg)
        
        if not filtered_messages:
            return ""
            
        # Ensure we don't go out of bounds with -n
        actual_n = min(n, len(filtered_messages))
        if actual_n == 0:
            return ""

        return "\\n".join(msg["content"] for msg in filtered_messages[-actual_n:])

    @staticmethod
    def mock_get_formatted_last_n_turns_as_string(messages, n, template_file_name, isChatCompletion):
        # This mock is for a different utility, keeping its simple filter for now
        filtered_messages = [msg for msg in messages if msg["role"] != "system" and msg["role"] != "images"]
        return "\\n".join(msg["content"] for msg in filtered_messages[-n:])

    @patch('Middleware.utilities.prompt_template_utils.load_template_from_json')
    @patch('Middleware.workflows.managers.workflow_variable_manager.extract_last_n_turns_as_string')
    def test_fix_directly(self, mock_wvm_extract_last_n_as_string, mock_load_template_from_json):
        """Test the fix for chat_user_prompt_last_one directly."""
        # Configure the mock for load_template_from_json
        mock_load_template_from_json.return_value = {
            "promptTemplateUserPrefix": "U:", "promptTemplateUserSuffix": "",
            "promptTemplateAssistantPrefix": "A:", "promptTemplateAssistantSuffix": "",
            "promptTemplateSystemPrefix": "S:", "promptTemplateSystemSuffix": "",
            "promptTemplateEndToken": "<|end|>",
            "template_type": "chat", 
            "roles": {"user": "User", "assistant": "Assistant", "system": "System"}
        }
        
        # Assign the class's static mock method to the patched object
        mock_wvm_extract_last_n_as_string.side_effect = TestChatUserPromptLastOne.mock_extract_last_n_turns_as_string

        # Mock for get_formatted_last_n_turns_as_string if it's imported in workflow_variable_manager
        # This was previously done via sys.modules, now using a more direct patch if necessary,
        # but the primary one for chat_user_prompt_last_one is extract_last_n_turns_as_string
        # For now, let's assume the previous sys.modules mock for this one might still be active or test specific.
        # If other 'templated_user_prompt_last_x' variables cause issues, this might need revisiting.
        # Original test had:
        # sys.modules['Middleware.utilities.prompt_template_utils'].get_formatted_last_n_turns_as_string = TestChatUserPromptLastOne.mock_get_formatted_last_n_turns_as_string
        # We'll rely on the load_template_from_json mock to prevent file access from the original get_formatted_last_n_turns_as_string
        
        from Middleware.workflows.managers.workflow_variable_manager import WorkflowVariableManager
        
        class TestableManager(WorkflowVariableManager):
            def __init__(self):
                self.category_list = None
                self.categoriesSeparatedByOr = None
                self.category_colon_descriptions = None
                self.category_colon_descriptions_newline_bulletpoint = None
                self.categoryNameBulletpoints = None
                self.category_descriptions = None
                self.categories = None
                self.chat_template_name = "default" # Use chat_template_name as in parent
        
        class MockLLMHandler:
            def __init__(self):
                self.takes_message_collection = True # This sets include_sysmes=True for the mock
                self.prompt_template_file_name = "default_template.json"
        
        manager = TestableManager()
        mock_llm_handler = MockLLMHandler()
        
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello, how are you?"},
            {"role": "assistant", "content": "I'm doing well, thanks for asking!"},
            {"role": "user", "content": "Tell me about the weather"},
            {"role": "assistant", "content": "I don't have access to current weather information."},
            {"role": "user", "content": "What time is it in Berlin?"}
        ]
        
        variables = manager.generate_conversation_turn_variables(messages, mock_llm_handler, None)
        
        errors = []
        
        if "chat_user_prompt_last_one" not in variables:
            errors.append("Variable 'chat_user_prompt_last_one' was not found in the output")
        elif variables["chat_user_prompt_last_one"] != "What time is it in Berlin?":
            errors.append(f"Expected 'What time is it in Berlin?' but got '{variables['chat_user_prompt_last_one']}'")
        
        no_user_messages = [
            {"role": "system", "content": "You are a helpful assistant."}
        ]
        # When `generate_conversation_turn_variables` calls the mocked `extract_last_n_turns_as_string`
        # with no_user_messages, `takes_message_collection` is True (so include_sysmes=True for the mock)
        # The mock `TestChatUserPromptLastOne.mock_extract_last_n_turns_as_string` filters out system roles.
        variables_no_user = manager.generate_conversation_turn_variables(no_user_messages, mock_llm_handler, None)
        
        if "chat_user_prompt_last_one" not in variables_no_user:
            errors.append("Variable 'chat_user_prompt_last_one' was not found in the output for empty user test")
        elif variables_no_user["chat_user_prompt_last_one"] != "":
            # This assertion relies on mock_extract_last_n_turns_as_string correctly returning ""
            # when only system messages are present and it filters them out.
            errors.append(f"Expected empty string for no user messages but got '{variables_no_user['chat_user_prompt_last_one']}'")
        
        self.assertEqual(len(errors), 0, "\\n".join(errors))

if __name__ == "__main__":
    unittest.main() 