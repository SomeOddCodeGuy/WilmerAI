#!/usr/bin/env python

"""
Unit tests for the prompt extraction utility functions.
"""

import unittest
import sys
import os

# Adjust import paths to access Middleware modules
# Assumes the test is run from the project root or the WilmerAI directory structure is accessible
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../WilmerAI")))

# Import the functions under test
from Middleware.utilities.prompt_extraction_utils import extract_last_n_turns, extract_last_n_turns_as_string

class TestPromptExtractionUtils(unittest.TestCase):

    def test_extract_last_n_turns_basic(self):
        """GIVEN a list of messages, WHEN extract_last_n_turns is called, THEN it should return the correct last N messages."""
        messages = [
            {"role": "system", "content": "Initial system prompt"},
            {"role": "user", "content": "User message 1"},
            {"role": "assistant", "content": "Assistant response 1"},
            {"role": "user", "content": "User message 2"},
            {"role": "assistant", "content": "Assistant response 2"}
        ]

        # Test getting last 3 (excluding initial system)
        result = extract_last_n_turns(messages, 3, include_sysmes=True)
        expected = [
            {"role": "assistant", "content": "Assistant response 1"},
            {"role": "user", "content": "User message 2"},
            {"role": "assistant", "content": "Assistant response 2"}
        ]
        self.assertEqual(result, expected, "Should extract last 3 non-initial-system messages")

        # Test getting last 2
        result_2 = extract_last_n_turns(messages, 2, include_sysmes=True)
        expected_2 = [
            {"role": "user", "content": "User message 2"},
            {"role": "assistant", "content": "Assistant response 2"}
        ]
        self.assertEqual(result_2, expected_2, "Should extract last 2 messages")

        # Test getting last 3 excluding ALL system messages
        messages_with_mid_system = [
            {"role": "system", "content": "Initial system prompt"},
            {"role": "user", "content": "User message 1"},
            {"role": "system", "content": "Mid-conversation system prompt"}, # Added mid-convo system
            {"role": "assistant", "content": "Assistant response 1"},
            {"role": "user", "content": "User message 2"},
            {"role": "assistant", "content": "Assistant response 2"}
        ]
        result_no_sys = extract_last_n_turns(messages_with_mid_system, 3, remove_all_systems_override=True)
        expected_no_sys = [
             {"role": "assistant", "content": "Assistant response 1"},
             {"role": "user", "content": "User message 2"},
             {"role": "assistant", "content": "Assistant response 2"}
        ]
        self.assertEqual(result_no_sys, expected_no_sys, "Should extract last 3 non-system messages with override")


    def test_extract_last_n_turns_as_string_correct_formatting(self):
        """
        GIVEN a list of messages (simulating output after message_transformation_utils),
        WHEN extract_last_n_turns_as_string is called,
        THEN it should return a correctly formatted string with 'Role: Content' for the last N turns.
        """
        # This input simulates the state *after* transform_messages has run,
        # including the OpenWebUI fix which adds history + final query.
        # Note: Content might have prefixes from _apply_role_prefixes if it ran,
        # but the new implementation should handle this gracefully by just using the content as-is.
        processed_messages = [
            {"role": "system", "content": "Initial system prompt (should be excluded by default)"},
            {"role": "user", "content": "User message 1"}, # Part of extracted history
            {"role": "assistant", "content": "Assistant response 1"}, # Part of extracted history
            {"role": "user", "content": "User message 2 (final query)"} # Final extracted query
        ]

        n = 3 # Get last 3 turns (user1, assistant1, user2)

        # ==================
        # WHEN (Action)
        # ==================
        result_string = extract_last_n_turns_as_string(processed_messages, n, include_sysmes=True)

        # ==================
        # THEN (Assertions)
        # ==================
        expected_string = (
            "User: User message 1\n"
            "Assistant: Assistant response 1\n"
            "User: User message 2 (final query)"
        )

        self.assertEqual(result_string, expected_string,
                         "Output string formatting or message selection is incorrect.")

    def test_extract_last_n_turns_as_string_empty_input(self):
        """GIVEN an empty message list, WHEN extract_last_n_turns_as_string is called, THEN it should return an empty string."""
        result = extract_last_n_turns_as_string([], 3)
        self.assertEqual(result, "", "Should return empty string for empty input")

    def test_extract_last_n_turns_as_string_n_greater_than_messages(self):
        """GIVEN n > message count, WHEN extract_last_n_turns_as_string is called, THEN it should return all non-initial-system messages formatted."""
        messages = [
            {"role": "system", "content": "Sys"},
            {"role": "user", "content": "U1"},
            {"role": "assistant", "content": "A1"}
        ]
        result = extract_last_n_turns_as_string(messages, 5, include_sysmes=True)
        expected = ("User: U1\n"
                    "Assistant: A1")
        self.assertEqual(result, expected, "Should return all available formatted messages")

if __name__ == '__main__':
    unittest.main()
