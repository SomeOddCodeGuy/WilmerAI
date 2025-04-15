import unittest
from unittest.mock import patch, MagicMock
import json
import sys
import os
import time
import logging

# Configure logging for this test file
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Add project root to sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from Middleware.llmapis.ollama_generate_api_handler import OllamaGenerateHandler
from Middleware.utilities import api_utils

@patch('Middleware.utilities.config_utils.load_config')
@patch('Middleware.utilities.api_utils.get_current_username')
@patch('time.strftime')
class TestOllamaGenerateApiHandlerSSE(unittest.TestCase):

    @patch('requests.Session')
    def test_handle_streaming_ollama_generate_sse_format(self, mock_session_cls, mock_time_strftime, mock_get_username, mock_load_config):
        """
        Test that OllamaGenerateHandler.handle_streaming yields chunks in the correct
        Ollama /api/generate SSE format (raw JSON + \n).
        """
        # 1. Mock dependencies
        mock_get_username.return_value = "mock-ollama-gen-model"
        mock_time_strftime.return_value = "2024-01-04T11:00:00Z"

        # Mock configuration (specific to Ollama Generate)
        mock_endpoint_config = {
            "endpoint": "http://mock-ollama-backend.com/api/generate",
            "modelNameToSendToAPI": "mock-ollama-gen-model",
            "apiTypeConfigFileName": "ollamagenerate_config",
            "presetConfigFileName": "mock_preset",
            "addGenerationPrompt": False,
            "stripStartStopLineBreaks": True,
            "maxContextTokenSize": 4096,
            "max_tokens": 512
        }
        mock_api_type_config = {
            "apiType": "ollamagenerate", # Critical: Set API type to Ollama Generate
            "apiKey": None,
            "apiBaseUrl": "http://mock-ollama-backend.com",
            "defaultHeaders": {"Content-Type": "application/json"},
            "streamPropertyName": "stream",
            "maxNewTokensPropertyName": "num_predict",
            # Backend properties (assuming backend uses Ollama Generate API itself)
            "backendApiType": "ollamagenerate",
            "backendApiPath": "/api/generate",
            "backendResponseTokenExtractor": "extract_ollama_generate_content",
            "backendResponseFinishReasonExtractor": "extract_ollama_finish_reason"
        }
        mock_preset_config = {
            "temperature": 0.9,
            "top_p": 0.8
        }

        # 2. Prepare mock LLM response chunks (Simulating OLLAMA /api/generate backend response)
        raw_backend_tokens = ["Ollama ", "Generate ", "Response!"]
        mock_response = MagicMock()
        backend_chunks = []
        for token in raw_backend_tokens:
            chunk = {
                "model": mock_endpoint_config["modelNameToSendToAPI"],
                "created_at": mock_time_strftime.return_value,
                "response": token, # Key difference: 'response' instead of 'message'
                "done": False
            }
            backend_chunks.append(f"{json.dumps(chunk)}\n".encode('utf-8'))

        # Add final done chunk from backend
        final_backend_chunk = {
            "model": mock_endpoint_config["modelNameToSendToAPI"],
            "created_at": mock_time_strftime.return_value,
            "response": "",
            "done": True,
            "total_duration": 1234, "load_duration": 5678,
            "prompt_eval_count": 9, "prompt_eval_duration": 1011,
            "eval_count": 12, "eval_duration": 1314
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
        handler = OllamaGenerateHandler(
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

        # 5. Patch instance_utils.API_TYPE and call handle_streaming
        with patch('Middleware.utilities.instance_utils.API_TYPE', 'ollamagenerate'):
            # Generate handler takes prompt/system_prompt, not conversation
            stream_generator = handler.handle_streaming(prompt="Test Ollama Generate", system_prompt="System:")

            # 6. Collect output
            output_chunks = list(stream_generator)

        # 7. Define the CORRECT expected Ollama /api/generate SSE output format (raw JSON + \n)
        expected_output = []
        expected_model = mock_get_username.return_value
        expected_created_at = mock_time_strftime.return_value

        for token in raw_backend_tokens:
            payload_str = api_utils.build_response_json(
                token=token,
                finish_reason=None,
                current_username=expected_model,
                api_type='ollamagenerate' # Use correct type
            )
            expected_output.append(f"{payload_str}\n")

        # Add the final done chunk payload
        # build_response_json does NOT add timing info for /api/generate final chunk yet
        final_payload_str = api_utils.build_response_json(
            token="",
            finish_reason="stop",
            current_username=expected_model,
            api_type='ollamagenerate'
        )
        expected_output.append(f"{final_payload_str}\n")

        # DO NOT add the final [DONE] signal for Ollama

        # 8. Assert the output matches the expected Ollama /api/generate SSE format
        self.assertEqual(output_chunks, expected_output,
                         "Output stream does not match expected Ollama /api/generate SSE format.")

if __name__ == '__main__':
    unittest.main()
