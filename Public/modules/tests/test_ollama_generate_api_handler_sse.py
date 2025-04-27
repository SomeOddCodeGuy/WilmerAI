import unittest
from unittest.mock import patch, MagicMock, AsyncMock, ANY, call
import json
import sys
import os
import time
import logging
import asyncio
from typing import List, Dict, Any, AsyncGenerator
import requests
# Configure logging for this test file
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Add project root to sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from Middleware.llmapis.ollama_generate_api_handler import OllamaGenerateHandler
from Middleware.utilities import api_utils

# Helper async function to consume async generators
async def consume_async_gen(agen: AsyncGenerator) -> List[Any]:
    items = []
    async for item in agen:
        items.append(item)
    return items

# Mock LlmHandlerService for initialization
class MockLlmHandlerService:
    def get_llm_handler(self, *args, **kwargs):
        # Return a mock handler if needed by the tested class methods
        return AsyncMock()

# Remove class-level patches
# @patch('Middleware.utilities.config_utils.load_config')
# @patch('Middleware.utilities.api_utils.get_current_username')
# @patch('time.strftime')
class TestOllamaGenerateApiHandlerSSE(unittest.TestCase):

    def setUp(self):
        """Set up test fixtures, if any."""
        # Set up mocks for config loading or other dependencies if needed
        # Example: Mock load_config if OllamaGenerateHandler uses it in __init__
        pass # No shared setup needed for this specific test

    def test_handle_streaming_ollama_generate_sse_format(self):
        """Test that OllamaGenerateHandler.handle_streaming yields chunks in the correct
        Ollama /api/generate SSE format (raw JSON + \n).
        """
        # 1. Define Mock Values and Configs
        fixed_strftime = "2024-01-03T10:00:00Z"
        fixed_time = 1704276000
        mock_endpoint_config = {
            "endpoint": "http://mock-ollama-backend.com/api/generate",
            "modelNameToSendToAPI": "mock-ollama-generate-model",
            "apiTypeConfigFileName": "ollamagenerate_config", # Keep for load_config mapping
            "presetConfigFileName": "mock_preset",           # Keep for load_config mapping
            "addGenerationPrompt": False,
            "stripStartStopLineBreaks": True,
            "maxContextTokenSize": 4096,
            "max_tokens": 1024
        }
        mock_api_type_config = {
            "apiType": "ollamagenerate", "apiKey": None,
            "apiBaseUrl": "http://mock-ollama-backend.com",
            "defaultHeaders": {"Content-Type": "application/json"},
            "streamPropertyName": "stream", "maxNewTokensPropertyName": "num_predict",
            "backendApiType": "ollamagenerate", "backendApiPath": "/api/generate",
            "backendResponseTokenExtractor": "extract_ollama_generate_content",
            "backendResponseFinishReasonExtractor": "extract_ollama_finish_reason"
        }
        mock_preset_config = {"temperature": 0.7, "top_k": 40}

        # 2. Prepare mock LLM response chunks
        raw_backend_tokens = ["This ", "is ", "Ollama ", "Generate!"]
        mock_response = MagicMock(spec=requests.Response)
        backend_chunks = []
        for token in raw_backend_tokens:
            chunk = {
                "model": mock_endpoint_config["modelNameToSendToAPI"],
                "created_at": fixed_strftime, # Use fixed strftime
                "response": token,
                "done": False
            }
            backend_chunks.append(f"{json.dumps(chunk)}\n".encode('utf-8'))
        final_backend_chunk = {
            "model": mock_endpoint_config["modelNameToSendToAPI"],
            "created_at": fixed_strftime, # Use fixed strftime
            "response": "",
            "done": True, "total_duration": 123, "load_duration": 456,
            "prompt_eval_count": 7, "prompt_eval_duration": 890,
            "eval_count": 10, "eval_duration": 1112
        }
        backend_chunks.append(f"{json.dumps(final_backend_chunk)}\n".encode('utf-8'))
        mock_response.iter_content = MagicMock(return_value=backend_chunks)
        mock_response.raise_for_status = MagicMock()
        mock_response.status_code = 200

        # Use nested context managers for patching
        with patch('Middleware.utilities.config_utils.load_config') as mock_load_config_patch, \
             patch('Middleware.utilities.api_utils.time.time', return_value=fixed_time) as mock_time_patch, \
             patch('Middleware.utilities.api_utils.time.strftime', return_value=fixed_strftime) as mock_strftime_patch, \
             patch('Middleware.llmapis.ollama_generate_api_handler.requests.Session') as mock_session_patch:
            
            # Configure load_config mock side effect
            def load_config_side_effect(config_name, *args, **kwargs):
                if config_name == mock_endpoint_config['apiTypeConfigFileName']:
                    return mock_api_type_config
                elif config_name == mock_endpoint_config['presetConfigFileName']:
                    return mock_preset_config
                # Add more conditions or a default return if load_config is called elsewhere
                return {} # Default empty dict
            mock_load_config_patch.side_effect = load_config_side_effect

            # Configure the Session mock
            mock_session_instance = mock_session_patch.return_value
            mock_post_context = MagicMock()
            mock_post_context.__enter__.return_value = mock_response
            mock_post_context.__exit__ = MagicMock(return_value=None)
            mock_session_instance.post.return_value = mock_post_context

            # 4. Instantiate the handler *inside* the context managers
            handler = OllamaGenerateHandler(
                endpoint_config=mock_endpoint_config,
                api_type_config=mock_api_type_config,
                gen_input=mock_preset_config,
                max_tokens=mock_endpoint_config['max_tokens'],
                stream=True,
                base_url=mock_api_type_config['apiBaseUrl'],
                model_name=mock_endpoint_config['modelNameToSendToAPI'],
                headers=mock_api_type_config['defaultHeaders'],
                strip_start_stop_line_breaks=mock_endpoint_config['stripStartStopLineBreaks'],
                api_key=""
            )
            # Note: handler.session will be the mock_session_instance from the patch

            # 5. Run the streaming method
            messages = [{"role": "user", "content": "Test Ollama Generate"}]
            stream_generator = handler.handle_streaming(
                conversation=messages
            )
            output_chunks = list(stream_generator)

        # 6. Define expected output (outside the context managers)
        expected_output = []
        expected_model = "mock_user_gen"
        expected_created_at = fixed_strftime # Use the fixed value
        for token in raw_backend_tokens:
            payload_dict = {
                "model": expected_model,
                "created_at": expected_created_at,
                "response": token,
                "done": False
            }
            expected_output.append(f"{json.dumps(payload_dict)}\n")

        final_payload_dict = {
            "model": expected_model,
            "created_at": expected_created_at,
            "response": "",
            "done": True
        }
        expected_output.append(f"{json.dumps(final_payload_dict)}\n")

        # 7. Assert
        self.assertEqual(len(output_chunks), len(expected_output), f"Expected {len(expected_output)} chunks, got {len(output_chunks)}")
        for i, expected_chunk in enumerate(expected_output):
            self.assertEqual(output_chunks[i], expected_chunk,
                             f"Chunk {i} mismatch.\nExpected: {repr(expected_chunk)}\nActual:   {repr(output_chunks[i])}")
        self.assertFalse(any(r.startswith('data:') for r in output_chunks))
        self.assertFalse(any(r.endswith('\n\n') for r in output_chunks))
        
        # Verify mocks were called if needed (e.g., session.post)
        mock_session_instance.post.assert_called_once()
        # Verify load_config calls
        # mock_load_config_patch.assert_any_call(mock_endpoint_config['apiTypeConfigFileName'], ...) # Add details if needed
        # mock_load_config_patch.assert_any_call(mock_endpoint_config['presetConfigFileName'], ...)

if __name__ == '__main__':
    unittest.main()
