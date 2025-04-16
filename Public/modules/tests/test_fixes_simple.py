#!/usr/bin/env python

"""
Simple verification script to test the implementation of our fixes.
This directly imports and tests the key components that were modified.
"""

import sys
import os
from unittest.mock import patch, MagicMock
import json

# Ensure we can import from WilmerAI
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../WilmerAI")))

try:
    # 1. Test the message_transformation_utils
    from Middleware.utilities.message_transformation_utils import transform_messages
    
    print("Testing message_transformation_utils.transform_messages...")
    
    # Test basic prefixing
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"}
    ]
    
    transformed = transform_messages(messages, add_user_assistant=True, add_missing_assistant=False)
    
    assert transformed[0]["content"] == "User: Hello", f"Expected 'User: Hello', got '{transformed[0]['content']}'"
    assert transformed[1]["content"] == "Assistant: Hi there", f"Expected 'Assistant: Hi there', got '{transformed[1]['content']}'"
    
    print("  ✓ Prefixing works correctly")
    
    # Test adding missing assistant
    messages = [
        {"role": "user", "content": "First question"},
        {"role": "assistant", "content": "First answer"},
        {"role": "user", "content": "Second question"}
    ]
    
    transformed = transform_messages(messages, add_user_assistant=False, add_missing_assistant=True)
    
    assert len(transformed) == 4, f"Expected 4 messages, got {len(transformed)}"
    assert transformed[-1]["role"] == "assistant", f"Expected last message role to be 'assistant', got '{transformed[-1]['role']}'"
    assert transformed[-1]["content"] == "", f"Expected empty content, got '{transformed[-1]['content']}'"
    
    print("  ✓ Adding missing assistant works correctly")
    
    # Test handling images
    messages = [
        {"role": "user", "content": "Check this image", "images": ["image_data_1", "image_data_2"]}
    ]
    
    transformed = transform_messages(messages, add_user_assistant=False, add_missing_assistant=False)
    
    assert len(transformed) == 3, f"Expected 3 messages (1 user + 2 images), got {len(transformed)}"
    assert transformed[0]["role"] == "user", f"Expected first message role to be 'user', got '{transformed[0]['role']}'"
    assert transformed[0]["content"] == "Check this image", f"Expected user content, got '{transformed[0]['content']}'"
    assert transformed[1]["role"] == "images", f"Expected second message role to be 'images', got '{transformed[1]['role']}'"
    assert transformed[1]["content"] == "image_data_1", f"Expected first image content, got '{transformed[1]['content']}'"
    assert transformed[2]["role"] == "images", f"Expected third message role to be 'images', got '{transformed[2]['role']}'"
    assert transformed[2]["content"] == "image_data_2", f"Expected second image content, got '{transformed[2]['content']}'"
    
    print("  ✓ Image extraction works correctly")
    
    # 2. Test the WorkflowVariableManager's last user message extraction
    from Middleware.workflows.managers.workflow_variable_manager import WorkflowVariableManager
    
    print("\nTesting WorkflowVariableManager.generate_conversation_turn_variables...")
    
    # Mock the handler and utility functions to isolate our test
    mock_llm_handler = MagicMock()
    mock_llm_handler.takes_message_collection = True
    mock_llm_handler.prompt_template_file_name = "test_template" # Base name without .json
    
    # Mock the template loading to prevent FileNotFoundError
    mock_template = {
        "promptTemplateUserPrefix": "U:",
        "promptTemplateUserSuffix": "",
        "promptTemplateAssistantPrefix": "A:",
        "promptTemplateAssistantSuffix": "",
        "promptTemplateSystemPrefix": "S:",
        "promptTemplateSystemSuffix": "",
        "promptTemplateEndToken": "<|end|>"
    }
    
    # Patch the functions where they are *used* within the call stack
    # Patch the name within the WorkflowVariableManager module
    with patch('Middleware.utilities.prompt_extraction_utils.extract_last_n_turns_as_string') as mock_extract, \
         patch('Middleware.workflows.managers.workflow_variable_manager.get_formatted_last_n_turns_as_string') as mock_formatted, \
         patch('Middleware.utilities.prompt_template_utils.load_template_from_json') as mock_load_template:
        
        # Set return values on the mock variables
        mock_extract.return_value="mocked_extract"
        mock_formatted.return_value="mocked_formatted"
        mock_load_template.return_value=mock_template
        
        # Test with normal order (oldest first)
        messages = [
            {"role": "system", "content": "You are an assistant"},
            {"role": "user", "content": "First message"},
            {"role": "assistant", "content": "First response"},
            {"role": "user", "content": "Last message"}
        ]
        
        variables = WorkflowVariableManager.generate_conversation_turn_variables(
            messages, mock_llm_handler, None)
        
        assert variables["chat_user_prompt_last_one"] == "Last message", \
            f"Expected 'Last message', got '{variables['chat_user_prompt_last_one']}'"
        assert variables["templated_user_prompt_last_one"] == "mocked_formatted", \
            f"Expected 'mocked_formatted', got '{variables['templated_user_prompt_last_one']}'"
        
        print("  ✓ Extracts last user message correctly with oldest-first order")
        
        # Test with assistant placeholder at the end
        messages = [
            {"role": "user", "content": "User message"},
            {"role": "assistant", "content": ""}  # Empty placeholder
        ]
        
        variables = WorkflowVariableManager.generate_conversation_turn_variables(
            messages, mock_llm_handler, None)
        
        assert variables["chat_user_prompt_last_one"] == "User message", \
            f"Expected 'User message', got '{variables['chat_user_prompt_last_one']}'"
        
        print("  ✓ Handles empty assistant placeholder correctly")
    
    # 3. Test that ApiChatAPI uses transform_messages and doesn't reverse
    print("\nVerifying ApiChatAPI implementation...")
    
    # Correct the path to open_ai_api.py based on the script's location
    # __file__ is WilmerData/Public/modules/tests/test_fixes_simple.py
    # We need to go up 4 levels to get to the project root, then into WilmerAI
    script_dir = os.path.dirname(__file__)
    project_root = os.path.abspath(os.path.join(script_dir, "../../../..")) # Corrected: Go up four levels
    api_file_path = os.path.join(project_root, "WilmerAI", "Middleware", "core", "open_ai_api.py")
    
    # Ensure the path exists before trying to open
    assert os.path.exists(api_file_path), f"API file path does not exist: {api_file_path}"
    
    with open(api_file_path, 'r') as f:
        api_code = f.read()
    
    # Check for reversal pattern (this should no longer exist)
    reversal_pattern = "messages_for_handler = transformed_messages[::-1]"
    reversal_found = reversal_pattern in api_code
    
    assert not reversal_found, "Message reversal code still present in ApiChatAPI!"
    print("  ✓ Message reversal code removed from ApiChatAPI")
    
    # Check for transform_messages usage
    transform_pattern = "transform_messages("
    transform_found = transform_pattern in api_code
    
    assert transform_found, "transform_messages() function not used in ApiChatAPI!"
    print("  ✓ transform_messages() function used in ApiChatAPI")

    print("\nAll tests passed successfully!")
    
except Exception as e:
    import traceback
    print(f"Error during testing: {e}")
    traceback.print_exc()
    sys.exit(1) 