import unittest
from unittest.mock import patch, MagicMock
import json
import sys
import os
import time
import logging

# Configure logging for this test file
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Add project root to sys.path to allow importing WilmerAI modules
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')) # Adjust path as needed
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from Middleware.llmapis.ollama_chat_api_handler import OllamaChatHandler
from Middleware.utilities import api_utils

@patch('Middleware.utilities.config_utils.load_config')
@patch('Middleware.utilities.api_utils.get_current_username')
@patch('time.strftime')
class TestOllamaChatApiHandlerSSE(unittest.TestCase):

    @patch('requests.Session')
    def test_handle_streaming_ollama_chat_sse_format(self, mock_session_cls, mock_time_strftime, mock_get_username, mock_load_config):
        """
        Test that OllamaChatHandler.handle_streaming yields chunks in the correct
        Ollama /api/chat SSE format (raw JSON + \n).
        """
        # 1. Mock dependencies
        mock_get_username.return_value = "mock-ollama-chat-model"
        mock_time_strftime.return_value = "2024-01-03T10:00:00Z"

        # Mock configuration (specific to Ollama Chat)
        mock_endpoint_config = {
            "endpoint": "http://mock-ollama-backend.com/api/chat",
            "modelNameToSendToAPI": "mock-ollama-chat-model",
            "apiTypeConfigFileName": "ollamachat_config", # Simulate Ollama Chat config
            "presetConfigFileName": "mock_preset",
            "addGenerationPrompt": False,
            "stripStartStopLineBreaks": True,
            "maxContextTokenSize": 4096,
            "max_tokens": 1024
        }
        mock_api_type_config = {
            "apiType": "ollamaapichat", # Critical: Set API type to Ollama Chat
            "apiKey": None, # Ollama typically doesn't use API keys
            "apiBaseUrl": "http://mock-ollama-backend.com",
            "defaultHeaders": {"Content-Type": "application/json"},
            "streamPropertyName": "stream", # Property name in the request payload
            "maxNewTokensPropertyName": "num_predict", # Example, adjust if needed
            # Backend properties (assuming backend uses Ollama Chat API itself)
            "backendApiType": "ollamaapichat",
            "backendApiPath": "/api/chat",
            "backendResponseTokenExtractor": "extract_ollama_chat_content", # Custom extractor needed
            "backendResponseFinishReasonExtractor": "extract_ollama_finish_reason" # Custom extractor needed
        }
        mock_preset_config = {
            "temperature": 0.8,
            "top_p": 0.9
        }

        # 2. Prepare mock LLM response chunks (Simulating OLLAMA backend response)
        #    Even though the backend is Ollama, WilmerAI's handler might still internally
        #    parse based on a generic SSE structure or its specific extractor logic.
        #    For robustness, simulate the actual Ollama backend format here.
        raw_backend_tokens = ["This ", "is ", "Ollama ", "Chat!"]
        mock_response = MagicMock()
        backend_chunks = []
        for token in raw_backend_tokens:
            chunk = {
                "model": mock_endpoint_config["modelNameToSendToAPI"],
                "created_at": mock_time_strftime.return_value,
                "message": {"role": "assistant", "content": token},
                "done": False
            }
            backend_chunks.append(f"{json.dumps(chunk)}\n".encode('utf-8'))

        # Add final done chunk from backend
        final_backend_chunk = {
            "model": mock_endpoint_config["modelNameToSendToAPI"],
            "created_at": mock_time_strftime.return_value,
            "message": {"role": "assistant", "content": ""},
            "done": True,
            "total_duration": 123, "load_duration": 456, # Example backend timings
            "prompt_eval_count": 7, "prompt_eval_duration": 890,
            "eval_count": 10, "eval_duration": 1112
        }
        backend_chunks.append(f"{json.dumps(final_backend_chunk)}\n".encode('utf-8'))

        # Mock iter_content to yield byte chunks
        mock_response.iter_content = MagicMock(return_value=backend_chunks)
        mock_response.raise_for_status = MagicMock()
        mock_response.status_code = 200

        # 3. Mock the HTTP session
        mock_session_instance = MagicMock()
        mock_session_instance.post.return_value.__enter__.return_value = mock_response
        mock_session_cls.return_value = mock_session_instance

        # 4. Instantiate the CORRECT handler
        handler = OllamaChatHandler(
            base_url=mock_api_type_config["apiBaseUrl"],
            api_key=mock_api_type_config["apiKey"],
            gen_input={"temperature": mock_preset_config["temperature"], "top_p": mock_preset_config["top_p"]},
            model_name=mock_endpoint_config["modelNameToSendToAPI"],
            headers=mock_api_type_config["defaultHeaders"],
            strip_start_stop_line_breaks=mock_endpoint_config["stripStartStopLineBreaks"],
            stream=True,
            api_type_config=mock_api_type_config,
            endpoint_config=mock_endpoint_config,
            max_tokens=mock_endpoint_config["max_tokens"]
        )
        handler.session = mock_session_instance

        # 5. Patch instance_utils.API_TYPE (simulating incoming request type) and call handle_streaming
        with patch('Middleware.utilities.instance_utils.API_TYPE', 'ollamaapichat'):
            messages = [{"role": "user", "content": "Test Ollama Chat"}]
            stream_generator = handler.handle_streaming(conversation=messages)

            # 6. Collect output
            output_chunks = list(stream_generator)

        # 7. Define the CORRECT expected Ollama /api/chat SSE output format (raw JSON + \n)
        expected_output = []
        expected_model = mock_get_username.return_value # WilmerAI uses username as model
        expected_created_at = mock_time_strftime.return_value

        for token in raw_backend_tokens:
            # Build the expected JSON payload using api_utils helper for consistency
            payload_str = api_utils.build_response_json(
                token=token,
                finish_reason=None,
                current_username=expected_model,
                api_type='ollamaapichat'
            )
            # Expect raw JSON followed by a single newline
            expected_output.append(f"{payload_str}\n")

        # Add the final done chunk payload (raw JSON + newline)
        # Note: build_response_json adds timing fields for the final ollamaapichat chunk
        final_payload_str = api_utils.build_response_json(
            token="", # Empty content for final
            finish_reason="stop",
            current_username=expected_model,
            api_type='ollamaapichat'
        )
        expected_output.append(f"{final_payload_str}\n")

        # DO NOT add the final [DONE] signal for Ollama

        # 8. Assert the output matches the expected Ollama /api/chat SSE format
        self.assertEqual(output_chunks, expected_output,
                         "Output stream does not match expected Ollama /api/chat SSE format.")

if __name__ == '__main__':
    unittest.main()
