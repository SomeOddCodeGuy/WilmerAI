# Tests/models/test_llm_handler.py
"""
Tests for the LlmHandler class.

These tests serve as a contract validation to ensure:
1. LlmHandler has all expected public attributes after initialization
2. The takes_message_collection flag is set correctly based on llm_type
3. Any changes to LlmHandler's interface are caught by tests

This helps prevent issues where code references attributes that have been
removed from the class (e.g., the takes_image_collection removal bug).
"""

import pytest
from unittest.mock import Mock

from Middleware.models.llm_handler import LlmHandler


class TestLlmHandlerContract:
    """
    Contract tests that verify LlmHandler's public interface.
    These tests ensure that all expected attributes exist and are set correctly.
    """

    # Define the expected public attributes that must exist on every LlmHandler instance
    EXPECTED_ATTRIBUTES = [
        'llm',
        'prompt_template_file_name',
        'add_generation_prompt',
        'api_key',
        'takes_message_collection',
    ]

    # Attributes that should NOT exist (removed in refactoring)
    REMOVED_ATTRIBUTES = [
        'takes_image_collection',  # Removed in image handler consolidation refactor
    ]

    @pytest.fixture
    def mock_llm(self):
        """Provides a mock LLM object for testing."""
        return Mock()

    def test_handler_has_all_expected_attributes(self, mock_llm):
        """
        Verify that LlmHandler instances have all expected public attributes.
        This test catches cases where attributes are removed but still referenced.
        """
        handler = LlmHandler(
            llm=mock_llm,
            prompt_template_filepath="test_template.json",
            add_generation_prompt=True,
            llm_type="openAiApiChat",
            api_key="test_key"
        )

        for attr in self.EXPECTED_ATTRIBUTES:
            assert hasattr(handler, attr), \
                f"LlmHandler is missing expected attribute '{attr}'. " \
                f"If this was intentionally removed, update all code that references it."

    def test_removed_attributes_do_not_exist(self, mock_llm):
        """
        Verify that removed attributes are not present.
        This documents intentional removals and helps prevent re-adding them.
        """
        handler = LlmHandler(
            llm=mock_llm,
            prompt_template_filepath="test_template.json",
            add_generation_prompt=True,
            llm_type="openAiApiChat",
            api_key="test_key"
        )

        for attr in self.REMOVED_ATTRIBUTES:
            assert not hasattr(handler, attr), \
                f"LlmHandler has attribute '{attr}' which was previously removed. " \
                f"If re-adding intentionally, remove from REMOVED_ATTRIBUTES list."


class TestLlmHandlerTakesMessageCollection:
    """
    Tests for the takes_message_collection flag logic.
    """

    @pytest.fixture
    def mock_llm(self):
        """Provides a mock LLM object for testing."""
        return Mock()

    @pytest.mark.parametrize("llm_type,expected_takes_messages", [
        # Completions-style APIs (takes_message_collection = False)
        ("openAIV1Completion", False),
        ("koboldCppGenerate", False),
        ("ollamaApiGenerate", False),
        # Chat-style APIs (takes_message_collection = True)
        ("openAiApiChat", True),
        ("ollamaApiChat", True),
        ("claudeApiChat", True),
        ("genericOpenAiCompatibleChat", True),
        # Unknown types default to True (chat-style)
        ("unknownApiType", True),
    ])
    def test_takes_message_collection_based_on_llm_type(
            self, mock_llm, llm_type, expected_takes_messages
    ):
        """
        Verify that takes_message_collection is set correctly based on llm_type.

        Completions-style APIs (False): Send prompts as single strings
        Chat-style APIs (True): Send messages as a list of role/content dicts
        """
        handler = LlmHandler(
            llm=mock_llm,
            prompt_template_filepath="test_template.json",
            add_generation_prompt=True,
            llm_type=llm_type,
            api_key=""
        )

        assert handler.takes_message_collection == expected_takes_messages, \
            f"llm_type '{llm_type}' should have takes_message_collection={expected_takes_messages}"


class TestLlmHandlerInitialization:
    """
    Tests for LlmHandler initialization and attribute assignment.
    """

    @pytest.fixture
    def mock_llm(self):
        """Provides a mock LLM object for testing."""
        return Mock()

    def test_attributes_are_assigned_correctly(self, mock_llm):
        """Verify all constructor arguments are stored as attributes."""
        handler = LlmHandler(
            llm=mock_llm,
            prompt_template_filepath="my_template.json",
            add_generation_prompt=True,
            llm_type="openAiApiChat",
            api_key="secret_key_123"
        )

        assert handler.llm is mock_llm
        assert handler.prompt_template_file_name == "my_template.json"
        assert handler.add_generation_prompt is True
        assert handler.api_key == "secret_key_123"

    def test_api_key_defaults_to_empty_string(self, mock_llm):
        """Verify api_key parameter default value."""
        handler = LlmHandler(
            llm=mock_llm,
            prompt_template_filepath="test.json",
            add_generation_prompt=False,
            llm_type="openAiApiChat"
            # api_key not provided - should default to ""
        )

        assert handler.api_key == ""
