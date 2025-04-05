#!/usr/bin/env python

"""
Simple verification script for the chat_user_prompt_last_one variable fix.
This script bypasses the need for mocking complex dependencies.
"""

import sys
import os
from unittest.mock import patch, MagicMock

def test_fix_directly():
    """Test the fix for chat_user_prompt_last_one directly."""
    # Add mocks before importing to prevent file loading
    sys.modules['Middleware.utilities.prompt_template_utils'] = MagicMock()
    sys.modules['Middleware.utilities.prompt_extraction_utils'] = MagicMock()
    
    # Define extract_last_n_turns_as_string mock that just returns the content
    def mock_extract_last_n_turns_as_string(messages, n, include_sysmes=True, remove_all_systems_override=False):
        filtered_messages = [msg for msg in messages if msg["role"] != "system" and msg["role"] != "images"]
        return "\n".join(msg["content"] for msg in filtered_messages[-n:])
    
    # Define get_formatted_last_n_turns_as_string mock that just returns the content
    def mock_get_formatted_last_n_turns_as_string(messages, n, template_file_name, isChatCompletion):
        filtered_messages = [msg for msg in messages if msg["role"] != "system" and msg["role"] != "images"]
        return "\n".join(msg["content"] for msg in filtered_messages[-n:])
    
    # Set up the mocks
    sys.modules['Middleware.utilities.prompt_extraction_utils'].extract_last_n_turns_as_string = mock_extract_last_n_turns_as_string
    sys.modules['Middleware.utilities.prompt_template_utils'].get_formatted_last_n_turns_as_string = mock_get_formatted_last_n_turns_as_string
    
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
    success = True
    errors = []
    
    # Check for chat_user_prompt_last_one variable
    if "chat_user_prompt_last_one" not in variables:
        success = False
        errors.append("Variable 'chat_user_prompt_last_one' was not found in the output")
    
    # Check for correct content
    elif variables["chat_user_prompt_last_one"] != "What time is it in Berlin?":
        success = False
        errors.append(f"Expected 'What time is it in Berlin?' but got '{variables['chat_user_prompt_last_one']}'")
    
    # Test with no user messages
    no_user_messages = [
        {"role": "system", "content": "You are a helpful assistant."}
    ]
    variables_no_user = manager.generate_conversation_turn_variables(no_user_messages, mock_llm_handler, None)
    
    # Check that the variable exists
    if "chat_user_prompt_last_one" not in variables_no_user:
        success = False
        errors.append("Variable 'chat_user_prompt_last_one' was not found in the output for empty user test")
    
    # Check that it's an empty string
    elif variables_no_user["chat_user_prompt_last_one"] != "":
        success = False
        errors.append(f"Expected empty string for no user messages but got '{variables_no_user['chat_user_prompt_last_one']}'")
    
    # Print results
    if success:
        print("SUCCESS: All tests passed! The fix is working correctly.")
        print(f"- chat_user_prompt_last_one = '{variables['chat_user_prompt_last_one']}'")
        print(f"- Empty case = '{variables_no_user['chat_user_prompt_last_one']}'")
    else:
        print("FAILURE: The fix is not working correctly.")
        for error in errors:
            print(f"- ERROR: {error}")
    
    return success

if __name__ == "__main__":
    test_fix_directly() 