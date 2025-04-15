import unittest
from unittest.mock import patch, MagicMock
import json
import sys
import os
import time # Import time for mocking strftime
import logging # Import logging

# Configure logging for this test file
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Add project root to sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../../WilmerAI'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from Middleware.llmapis.openai_api_handler import OpenAiApiHandler
# Import the function we need to mock in api_utils
from Middleware.utilities import api_utils

# Mock config loading and other dependencies
@patch('Middleware.utilities.config_utils.load_config')
@patch('Middleware.utilities.api_utils.get_current_username') # Mock username used in model name
@patch('time.strftime') # Mock time for created_at
class TestOpenAiApiHandlerOllamaSSE(unittest.TestCase):

    @patch('requests.Session') # Also mock the session object creation
    def test_handle_streaming_ollama_sse_format(self, mock_session_cls, mock_time_strftime, mock_get_username, mock_load_config):
        """
        Test that handle_streaming yields chunks in the correct Ollama SSE format
        when configured for 'ollamaapichat'. This test is expected to fail initially
        due to the implementation not yielding intermediate chunks correctly.
        """
        # 1. Mock dependencies
        mock_get_username.return_value = "mock-model" # Consistent model name
        mock_time_strftime.return_value = "2024-01-01T12:00:00Z" # Consistent timestamp

        # Mock configuration loading (remains the same)
        mock_endpoint_config = {
            "endpoint": "http://mock-ollama.com/v1",
            "modelNameToSendToAPI": "mock-model",
            "apiTypeConfigFileName": "ollamaapichat_config",
            "presetConfigFileName": "mock_preset",
            "addGenerationPrompt": False,
            "stripStartStopLineBreaks": True,
            "maxContextTokenSize": 4096,
            "max_tokens": 1024
        }
        mock_api_type_config = {
            "apiType": "ollamaapichat",
            "apiKey": "fake-key",
            "apiBaseUrl": "http://mock-ollama.com",
            "defaultHeaders": {"Authorization": "Bearer {apiKey}", "Content-Type": "application/json"},
            "streamPropertyName": "stream",
            "maxNewTokensPropertyName": "max_tokens"
        }
        mock_preset_config = {
            "temperature": 0.7,
            "top_p": 0.9
        }
        # The handler's init uses these raw configs

        # 2. Prepare mock LLM response chunks (remains the same)
        raw_llm_chunks = ["Hello", " ", "World", "!"]
        mock_response = MagicMock()
        mock_response.iter_content = MagicMock(return_value=(
            f"data: {json.dumps({'choices': [{'delta': {'content': chunk}}], 'model': 'mock-model'})}\n\n".encode('utf-8')
            for chunk in raw_llm_chunks
        ))
        mock_response.raise_for_status = MagicMock()
        mock_response.status_code = 200

        # 3. Mock the HTTP session (remains the same)
        mock_session_instance = MagicMock()
        mock_session_instance.post.return_value.__enter__.return_value = mock_response
        mock_session_cls.return_value = mock_session_instance

        # 4. Instantiate the handler (remains the same)
        handler = OpenAiApiHandler(
            base_url=mock_api_type_config["apiBaseUrl"],
            api_key=mock_api_type_config["apiKey"],
            gen_input={"temperature": mock_preset_config["temperature"], "top_p": mock_preset_config["top_p"]},
            model_name=mock_endpoint_config["modelNameToSendToAPI"],
            headers={"Authorization": f"Bearer {mock_api_type_config['apiKey']}", "Content-Type": "application/json"},
            strip_start_stop_line_breaks=mock_endpoint_config["stripStartStopLineBreaks"],
            stream=True,
            api_type_config=mock_api_type_config,
            endpoint_config=mock_endpoint_config,
            max_tokens=mock_endpoint_config["max_tokens"]
        )
        handler.session = mock_session_instance

        # Use the correct callback for OpenAI streams
        callback_to_use = api_utils.extract_openai_chat_content

        # Patch instance_utils.API_TYPE and call handle_streaming
        with patch('Middleware.utilities.instance_utils.API_TYPE', 'ollamaapichat'):
            messages = [{"role": "user", "content": "Hello"}]
            # Pass the specific callback expected by the handler
            stream_generator = handler.handle_streaming(conversation=messages)

            # 6. Collect output
            output_chunks = list(stream_generator)

        # Define the CORRECT expected Ollama /api/chat SSE format
        expected_output = []
        expected_created_at = "2024-01-01T12:00:00Z"
        expected_model = "mock-model"

        for token in raw_llm_chunks:
            # Build the expected JSON payload for Ollama /api/chat
            payload = {
                "model": expected_model,
                "created_at": expected_created_at,
                "message": {"role": "assistant", "content": token},
                "done": False
            }
            # Expect raw JSON followed by a single newline
            expected_output.append(f"{json.dumps(payload)}\n")

        # Add the final done chunk (raw JSON + newline)
        final_payload = {
            "model": expected_model,
            "created_at": expected_created_at,
            "message": {"role": "assistant", "content": ""}, # Empty content for final
            "done": True,
            # Add the expected timing fields for the final Ollama chunk
            "total_duration": 5000000000,
            "load_duration": 3000000,
            "prompt_eval_count": 10,
            "prompt_eval_duration": 300000000,
            "eval_count": 5,
            "eval_duration": 200000000
        }
        expected_output.append(f"{json.dumps(final_payload)}\n")

        # DO NOT add the final [DONE] signal for Ollama

        # This assertion should now PASS after the code fixes
        self.assertEqual(output_chunks, expected_output, "Output stream does not match expected Ollama SSE format (structure or chunking).")


if __name__ == '__main__':
    unittest.main() 