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
        filtered_messages = [msg for msg in messages if msg["role"] != "system" and msg["role"] != "images"]
        return "\n".join(msg["content"] for msg in filtered_messages[-n:])

    @staticmethod
    def mock_get_formatted_last_n_turns_as_string(messages, n, template_file_name, isChatCompletion):
        filtered_messages = [msg for msg in messages if msg["role"] != "system" and msg["role"] != "images"]
        return "\n".join(msg["content"] for msg in filtered_messages[-n:])

    def test_fix_directly(self):
        """Test the fix for chat_user_prompt_last_one directly."""
        # Add mocks before importing to prevent file loading
        sys.modules['Middleware.utilities.prompt_template_utils'] = MagicMock()
        sys.modules['Middleware.utilities.prompt_extraction_utils'] = MagicMock()
        
        # Set up the mocks
        sys.modules['Middleware.utilities.prompt_extraction_utils'].extract_last_n_turns_as_string = TestChatUserPromptLastOne.mock_extract_last_n_turns_as_string
        sys.modules['Middleware.utilities.prompt_template_utils'].get_formatted_last_n_turns_as_string = TestChatUserPromptLastOne.mock_get_formatted_last_n_turns_as_string
        
        from Middleware.workflows.managers.workflow_variable_manager import WorkflowVariableManager
        
        # Create a simple class that inherits from WorkflowVariableManager but skips the __init__
        class TestableManager(WorkflowVariableManager):
            def __init__(self):
                # Skip the parent __init__ to avoid dependencies
                self.category_list = None
                self.categoriesSeparatedByOr = None
                self.category_colon_descriptions = None
                self.category_colon_descriptions_newline_bulletpoint = None
                self.categoryNameBulletpoints = None
                self.category_descriptions = None
                self.categories = None
                self.chatPromptTemplate = "default"
        
        # Create a mock LLM handler with the required attributes
        class MockLLMHandler:
            def __init__(self):
                self.takes_message_collection = True
                self.prompt_template_file_name = "default_template.json"
        
        # Create a simple instance
        manager = TestableManager()
        mock_llm_handler = MockLLMHandler()
        
        # Test data
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello, how are you?"},
            {"role": "assistant", "content": "I'm doing well, thanks for asking!"},
            {"role": "user", "content": "Tell me about the weather"},
            {"role": "assistant", "content": "I don't have access to current weather information."},
            {"role": "user", "content": "What time is it in Berlin?"}
        ]
        
        # Call the method we're testing
        variables = manager.generate_conversation_turn_variables(messages, mock_llm_handler, None)
        
        # Check results
        errors = []
        
        # Check for chat_user_prompt_last_one variable
        if "chat_user_prompt_last_one" not in variables:
            errors.append("Variable 'chat_user_prompt_last_one' was not found in the output")
        
        # Check for correct content
        elif variables["chat_user_prompt_last_one"] != "What time is it in Berlin?":
            errors.append(f"Expected 'What time is it in Berlin?' but got '{variables['chat_user_prompt_last_one']}'")
        
        # Test with no user messages
        no_user_messages = [
            {"role": "system", "content": "You are a helpful assistant."}
        ]
        variables_no_user = manager.generate_conversation_turn_variables(no_user_messages, mock_llm_handler, None)
        
        # Check that the variable exists
        if "chat_user_prompt_last_one" not in variables_no_user:
            errors.append("Variable 'chat_user_prompt_last_one' was not found in the output for empty user test")
        
        # Check that it's an empty string
        elif variables_no_user["chat_user_prompt_last_one"] != "":
            errors.append(f"Expected empty string for no user messages but got '{variables_no_user['chat_user_prompt_last_one']}'")
        
        # Assert results
        self.assertEqual(len(errors), 0, "\n".join(errors))

if __name__ == "__main__":
    unittest.main() 