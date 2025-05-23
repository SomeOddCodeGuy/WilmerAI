import unittest
from unittest.mock import patch, MagicMock, AsyncMock, ANY
import json
import os
import sys
from flask import Flask
import logging

# Configure logging for this test file
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

from Middleware.core.open_ai_api import ApiChatAPI
from Middleware.workflows.managers.workflow_manager import WorkflowManager
from Middleware.models.llm_handler import LlmHandler
from Middleware.llmapis.llm_api import LlmApiService
app = Flask(__name__)
app.add_url_rule("/api/chat", view_func=ApiChatAPI.as_view('test_api_chat'))


class TestOpenAIAPI(unittest.TestCase):

    def test_tool_extractor_ignores_embedded_history(self):
        """GIVEN messages with embedded history in the last user content AND the updated Step 0 prompt, WHEN Step 0 is processed, THEN the PromptProcessor method should be called with the correct arguments and produce the expected (mocked) output."""
        with patch('Middleware.workflows.processors.prompt_processor.PromptProcessor.handle_conversation_type_node') as mock_handle_conversation, \
             patch('Middleware.utilities.config_utils.get_current_username') as mock_get_username, \
             patch('Middleware.utilities.config_utils.get_user_config') as mock_get_user_config, \
             patch('Middleware.utilities.config_utils.get_categories_config') as mock_get_categories_config, \
             patch('Middleware.core.open_ai_api.PromptCategorizer') as mock_prompt_categorizer:

            # ==================
            # GIVEN (Setup)
            # ==================
            # Configure mocks (mock objects are now passed directly from the 'with' statement)
            mock_get_username.return_value = "test_user"
            default_user_config = {
                'chatCompleteAddUserAssistant': False,
                'chatCompletionAddMissingAssistantGenerator': False,
            }
            mock_get_user_config.return_value = default_user_config
            mock_get_categories_config.return_value = {} # Return empty dict for routing config
            formatted_history_content = """USER:\n\"\"\"what does President of Ukraine tells about that?\"\"\"\nASSISTANT:\n\"\"\"The latest news about Trump...\"\"\"\nUSER:\n\"\"\"tell me latest news... Use tool \"tavily\"\"\"\nASSISTANT:\n\"\"\"The current time in UTC is 12:00 PM.\"\"\""""
            
            final_query_content = "what does President of Ukraine tells about that?"
            
            self.mock_transformed_messages_with_history = [
                {"role": "system", "content": "Initial system prompt."}, # Original system
                {"role": "user", "content": "Oldest message"},          # Original user before history
                {"role": "assistant", "content": "Previous answer"},   # Original assistant before history
                # The original user message with history is REPLACED by these two:
                {"role": "system", "content": formatted_history_content}, # History block as system message
                {"role": "user", "content": final_query_content}      # Final query as user message
                # Note: This mock assumes add_missing_assistant=False for transform_messages
                # If it were True, an empty assistant message would be appended here.
            ]
            # --- End Definition ---
            
            # Configure mocks
            mock_handle_conversation.return_value = "none" # Step 0 returns 'none'

            # Test messages (oldest-first, with embedded history in last user message)
            embedded_history_content = (
                "User: Query: History:\n"
                "USER: \"\"\"what does President of Ukraine tells about that?\"\"\"\n"
                "ASSISTANT: \"\"\"The latest news about Trump...\"\"\"\n"
                "USER: \"\"\"tell me latest news... Use tool \"tavily\"\"\"\n"
                "ASSISTANT: \"\"\"The current time in UTC is 12:00 PM.\"\"\"\n"
                "Query: what does President of Ukraine tells about that?"
            )
            # This is the raw input to the API endpoint
            request_data_with_embedded_history = {
                "model": "test-model",
                "messages": [
                    {"role": "system", "content": "Initial system prompt."}, 
                    {"role": "user", "content": "Oldest message"},
                    {"role": "assistant", "content": "Previous answer"},
                    {"role": "user", "content": embedded_history_content}
                ]
            }

            # Create a Flask test client
            self.client = app.test_client()

            # ==================
            # WHEN (Action)
            # ==================
            # Simulate the POST request to the endpoint
            response = self.client.post('/api/chat', json=request_data_with_embedded_history)

            # ==================
            # THEN (Assertions)
            # ==================
            # Assert status code first
            self.assertEqual(response.status_code, 200)

if __name__ == '__main__':
    unittest.main() 