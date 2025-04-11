#!/usr/bin/env python

"""
Unit tests for the message transformation utility, which centralizes
message handling logic across different API endpoints.
"""

import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import copy

# Adjust import paths to access Middleware modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../WilmerAI")))

# Import the utility under test (we'll create this after writing the tests)
from Middleware.utilities.message_transformation_utils import transform_messages
# ---> ADD IMPORT FOR PRIVATE FUNCTION TEST <---
# from Middleware.utilities.message_transformation_utils import _extract_final_query # REMOVED as it was renamed and the test using it was removed
# from Middleware.utilities.message_transformation_utils import _apply_openwebui_workaround # ADDED for direct testing
# ---> END IMPORT <---


class TestMessageTransformationUtil(unittest.TestCase):

    def test_transform_messages_with_prefixing(self):
        """GIVEN messages and add_user_assistant=True, 
        WHEN transform_messages is called, 
        THEN it should add proper prefixes to user and assistant messages."""
        # ==================
        # GIVEN (Setup)
        # ==================
        original_messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"}
        ]
        add_user_assistant = True
        add_missing_assistant = False
        
        # ==================
        # WHEN (Action)
        # ==================
        transformed_messages = transform_messages(
            original_messages, add_user_assistant, add_missing_assistant)
        
        # ==================
        # THEN (Assertions)
        # ==================
        # Verify the original messages weren't modified
        self.assertEqual(original_messages[1]["content"], "Hello", 
                         "Original messages should not be modified")
        
        # Verify prefixes were added correctly
        self.assertEqual(transformed_messages[0]["content"], "You are a helpful assistant.", 
                         "System message should not be prefixed")
        self.assertEqual(transformed_messages[1]["content"], "User: Hello", 
                         "User message should be prefixed with 'User: '")
        self.assertEqual(transformed_messages[2]["content"], "Assistant: Hi there", 
                         "Assistant message should be prefixed with 'Assistant: '")

    def test_transform_messages_with_missing_assistant(self):
        """GIVEN messages ending with user and add_missing_assistant=True, 
        WHEN transform_messages is called, 
        THEN it should add an empty assistant message at the end."""
        # ==================
        # GIVEN (Setup)
        # ==================
        original_messages = [
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "First answer"},
            {"role": "user", "content": "Follow-up question"}
        ]
        add_user_assistant = False
        add_missing_assistant = True
        
        # ==================
        # WHEN (Action)
        # ==================
        transformed_messages = transform_messages(
            original_messages, add_user_assistant, add_missing_assistant)
        
        # ==================
        # THEN (Assertions)
        # ==================
        # Verify length and last message
        self.assertEqual(len(transformed_messages), 4, 
                         "Should add one message for the missing assistant")
        self.assertEqual(transformed_messages[-1]["role"], "assistant", 
                         "Last message should be an assistant role")
        self.assertEqual(transformed_messages[-1]["content"], "", 
                         "Last message should have empty content")

    def test_transform_messages_with_both_flags(self):
        """GIVEN messages ending with user and both flags=True, 
        WHEN transform_messages is called, 
        THEN it should add both prefixes and the empty assistant message."""
        # ==================
        # GIVEN (Setup)
        # ==================
        original_messages = [
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "First answer"},
            {"role": "user", "content": "Follow-up question"}
        ]
        add_user_assistant = True
        add_missing_assistant = True
        
        # ==================
        # WHEN (Action)
        # ==================
        transformed_messages = transform_messages(
            original_messages, add_user_assistant, add_missing_assistant)
        
        # ==================
        # THEN (Assertions)
        # ==================
        # Verify prefixes and additional message
        self.assertEqual(transformed_messages[0]["content"], "User: First question", 
                         "First user message should be prefixed")
        self.assertEqual(transformed_messages[1]["content"], "Assistant: First answer", 
                         "First assistant message should be prefixed")
        self.assertEqual(transformed_messages[2]["content"], "User: Follow-up question", 
                         "Second user message should be prefixed")
        self.assertEqual(len(transformed_messages), 4, 
                         "Should add one message for the missing assistant")
        self.assertEqual(transformed_messages[-1]["role"], "assistant", 
                         "Last message should be an assistant role")
        self.assertEqual(transformed_messages[-1]["content"], "Assistant: ", 
                         "Last message should have just the prefix")

    def test_transform_messages_with_images(self):
        """GIVEN messages with images, 
        WHEN transform_messages is called, 
        THEN it should correctly handle image extraction."""
        # ==================
        # GIVEN (Setup)
        # ==================
        original_messages = [
            {"role": "user", "content": "Look at this image", "images": ["base64_data_1", "base64_data_2"]}
        ]
        add_user_assistant = False
        add_missing_assistant = False
        
        # ==================
        # WHEN (Action)
        # ==================
        transformed_messages = transform_messages(
            original_messages, add_user_assistant, add_missing_assistant)
        
        # ==================
        # THEN (Assertions)
        # ==================
        # Verify we have 3 messages now (1 user + 2 image messages)
        self.assertEqual(len(transformed_messages), 3, 
                         "Should have 3 messages: 1 user + 2 images")
        
        # Verify user message
        self.assertEqual(transformed_messages[0]["role"], "user", 
                         "First message should be user role")
        self.assertEqual(transformed_messages[0]["content"], "Look at this image", 
                         "User message content incorrect")
        
        # Verify image messages
        self.assertEqual(transformed_messages[1]["role"], "images", 
                         "Second message should be images role")
        self.assertEqual(transformed_messages[1]["content"], "base64_data_1", 
                         "First image content incorrect")
        self.assertEqual(transformed_messages[2]["role"], "images", 
                         "Third message should be images role")
        self.assertEqual(transformed_messages[2]["content"], "base64_data_2", 
                         "Second image content incorrect")

    def test_transform_messages_preserves_order(self):
        """GIVEN a sequence of messages, 
        WHEN transform_messages is called, 
        THEN it should preserve the original message order."""
        # ==================
        # GIVEN (Setup)
        # ==================
        original_messages = [
            {"role": "system", "content": "System instruction"},
            {"role": "user", "content": "First user message"},
            {"role": "assistant", "content": "First assistant message"},
            {"role": "user", "content": "Second user message"}
        ]
        add_user_assistant = False
        add_missing_assistant = False
        
        # ==================
        # WHEN (Action)
        # ==================
        transformed_messages = transform_messages(
            original_messages, add_user_assistant, add_missing_assistant)
        
        # ==================
        # THEN (Assertions)
        # ==================
        # Verify order is preserved
        roles = [msg["role"] for msg in transformed_messages]
        expected_roles = ["system", "user", "assistant", "user"]
        self.assertEqual(roles, expected_roles, 
                         "Message order should be preserved")

    def test_transform_messages_preserves_history_when_no_history_markers(self):
        """GIVEN a message without the specific History/Query format markers,
        WHEN transform_messages is called,
        THEN it should not attempt to extract or modify the message content."""
        # ==================
        # GIVEN (Setup)
        # ==================
        regular_content = "This is a regular query with no history markers, but it mentions Query: and History: as terms."
        original_messages = [
            {"role": "system", "content": "System info"},
            {"role": "user", "content": regular_content}
        ]
        
        add_user_assistant = False
        add_missing_assistant = False
        
        # ==================
        # WHEN (Action)
        # ==================
        transformed_messages = transform_messages(
            original_messages, add_user_assistant, add_missing_assistant)
            
        # ==================
        # THEN (Assertions)
        # ==================
        self.assertEqual(len(transformed_messages), 2, "Number of messages should remain the same")
        self.assertEqual(transformed_messages[1]["content"], regular_content, 
                         "Content should not be modified when no proper history format is detected")


if __name__ == '__main__':
    unittest.main() 