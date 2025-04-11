#!/usr/bin/env python

"""
Unit tests for the ApiChatAPI class, focusing on message handling,
transformation, and ordering issues.
"""

import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import json
from flask import Flask

# Adjust import paths to access Middleware modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../WilmerAI")))

# Import the class under test
from Middleware.core.open_ai_api import ApiChatAPI, WilmerApi
from Middleware.utilities.config_utils import get_is_chat_complete_add_user_assistant, \
    get_is_chat_complete_add_missing_assistant

# Create dummy app for testing
app = Flask(__name__)
app.add_url_rule("/api/chat", view_func=ApiChatAPI.as_view('test_api_chat'))


class TestApiChatMessageHandling(unittest.TestCase):

    def setUp(self):
        """Set up common test dependencies."""
        self.client = app.test_client()
        # Ensure all patches are applied to appropriate paths
        patch_prefix = 'Middleware.core.open_ai_api.'
        self.patcher_add_user = patch(f'{patch_prefix}get_is_chat_complete_add_user_assistant')
        self.patcher_add_missing = patch(f'{patch_prefix}get_is_chat_complete_add_missing_assistant')
        self.patcher_handle = patch(f'{patch_prefix}WilmerApi.handle_user_prompt')

        # Start the patches
        self.mock_add_user = self.patcher_add_user.start()
        self.mock_add_missing = self.patcher_add_missing.start()
        self.mock_handle_prompt = self.patcher_handle.start()

        # Set default return values
        self.mock_add_user.return_value = False
        self.mock_add_missing.return_value = False
        self.mock_handle_prompt.return_value = "Test response"

    def tearDown(self):
        """Clean up after tests."""
        # Stop all the patches
        self.patcher_add_user.stop()
        self.patcher_add_missing.stop()
        self.patcher_handle.stop()

    def test_api_chat_message_ordering_without_reversal(self):
        """GIVEN a request to ApiChatAPI with messages in temporal order (oldest-first),
        WHEN the endpoint is called, 
        THEN it should NOT reverse the messages before passing to handle_user_prompt."""
        # ==================
        # GIVEN (Setup)
        # ==================
        # Messages in chronological order (oldest first) - typical of OpenAI's API
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "First user message"},
            {"role": "assistant", "content": "First assistant response"},
            {"role": "user", "content": "Second user message"},
            {"role": "assistant", "content": "Second assistant response"},
            {"role": "user", "content": "Last user message"}
        ]
        request_data = {
            "model": "test-model",
            "messages": messages,
            "stream": False
        }

        # ==================
        # WHEN (Action)
        # ==================
        response = self.client.post("/api/chat", json=request_data)

        # ==================
        # THEN (Assertions)
        # ==================
        self.mock_handle_prompt.assert_called_once()
        actual_args, actual_kwargs = self.mock_handle_prompt.call_args
        passed_messages = actual_args[0]
        
        # Verify order is preserved (not reversed)
        first_message = passed_messages[0]
        last_message = passed_messages[-1]
        self.assertEqual(first_message["content"], "You are a helpful assistant.", 
                         "First message was not preserved correctly")
        self.assertEqual(last_message["content"], "Last user message", 
                         "Last message was not preserved correctly")
        
    def test_api_chat_message_prefixing(self):
        """GIVEN a request to ApiChatAPI with add_user_assistant=True,
        WHEN the endpoint is called, 
        THEN it should correctly prefix user and assistant messages."""
        # ==================
        # GIVEN (Setup)
        # ==================
        self.mock_add_user.return_value = True
        
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Test user message"},
            {"role": "assistant", "content": "Test assistant response"}
        ]
        request_data = {
            "model": "test-model",
            "messages": messages,
            "stream": False
        }
        
        expected_user_prefix = "User: Test user message"
        expected_assistant_prefix = "Assistant: Test assistant response"

        # ==================
        # WHEN (Action)
        # ==================
        response = self.client.post("/api/chat", json=request_data)

        # ==================
        # THEN (Assertions)
        # ==================
        self.mock_handle_prompt.assert_called_once()
        actual_args, actual_kwargs = self.mock_handle_prompt.call_args
        passed_messages = actual_args[0]
        
        # Find the user and assistant messages
        user_message = next((m for m in passed_messages if m["role"] == "user"), None)
        assistant_message = next((m for m in passed_messages if m["role"] == "assistant"), None)
        
        self.assertIsNotNone(user_message, "User message not found in passed messages")
        self.assertIsNotNone(assistant_message, "Assistant message not found in passed messages")
        self.assertEqual(user_message["content"], expected_user_prefix, 
                         "User message prefix not applied correctly")
        self.assertEqual(assistant_message["content"], expected_assistant_prefix, 
                         "Assistant message prefix not applied correctly")

    def test_api_chat_image_handling(self):
        """GIVEN a request to ApiChatAPI with image content,
        WHEN the endpoint is called, 
        THEN it should correctly extract and process image messages."""
        # ==================
        # GIVEN (Setup)
        # ==================
        messages = [
            {"role": "user", "content": "Analyze this image", "images": ["base64_image_data_1"]}
        ]
        request_data = {
            "model": "test-model",
            "messages": messages,
            "stream": False
        }

        # ==================
        # WHEN (Action)
        # ==================
        response = self.client.post("/api/chat", json=request_data)

        # ==================
        # THEN (Assertions)
        # ==================
        self.mock_handle_prompt.assert_called_once()
        actual_args, actual_kwargs = self.mock_handle_prompt.call_args
        passed_messages = actual_args[0]
        
        # Verify both the user message and image message are present
        user_message = next((m for m in passed_messages if m["role"] == "user"), None)
        image_message = next((m for m in passed_messages if m["role"] == "images"), None)
        
        self.assertIsNotNone(user_message, "User message not found in passed messages")
        self.assertIsNotNone(image_message, "Image message not found in passed messages")
        self.assertEqual(user_message["content"], "Analyze this image", 
                         "User message content incorrect")
        self.assertEqual(image_message["content"], "base64_image_data_1", 
                         "Image message content incorrect")

    def test_api_chat_placeholder_assistant_handling(self):
        """GIVEN a request to ApiChatAPI with add_missing_assistant=True,
        WHEN the endpoint is called with messages ending with a user message, 
        THEN it should add an empty assistant message at the end."""
        # ==================
        # GIVEN (Setup)
        # ==================
        self.mock_add_missing.return_value = True
        
        messages = [
            {"role": "user", "content": "First message"},
            {"role": "assistant", "content": "First response"},
            {"role": "user", "content": "Second message"}  # Ends with user
        ]
        request_data = {
            "model": "test-model",
            "messages": messages,
            "stream": False
        }

        # ==================
        # WHEN (Action)
        # ==================
        response = self.client.post("/api/chat", json=request_data)

        # ==================
        # THEN (Assertions)
        # ==================
        self.mock_handle_prompt.assert_called_once()
        actual_args, actual_kwargs = self.mock_handle_prompt.call_args
        passed_messages = actual_args[0]
        
        # Verify an empty assistant message was added at the end
        self.assertEqual(len(passed_messages), 4, "Expected 4 messages including the added assistant")
        last_message = passed_messages[-1]
        self.assertEqual(last_message["role"], "assistant", "Last message should be assistant role")
        self.assertEqual(last_message["content"], "", "Assistant placeholder should be empty")


if __name__ == '__main__':
    unittest.main() 