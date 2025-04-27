import unittest
from unittest.mock import patch, MagicMock, AsyncMock, ANY, call
import json
import sys
import os
import time # Import time for mocking strftime
import logging # Import logging
import asyncio
import uuid # Ensure uuid is imported
from typing import List, Dict, Any, AsyncGenerator
import requests

# Configure logging for this test file
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Add project root to sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../../WilmerAI'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from Middleware.llmapis.openai_api_handler import OpenAiApiHandler
# Import the function we need to mock in api_utils
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

class TestOpenAiApiHandlerOllamaSSE(unittest.TestCase):

    def setUp(self):
        self.mock_config = {
            'endpointName': 'TestOpenAIEndpoint',
            'endpoint': 'http://mock-openai-api.com/v1/chat/completions',
            'apiTypeConfigFileName': 'OpenAIChatCompletion_Config',
            'presetConfigFileName': 'mock_preset',
            'addGenerationPrompt': False,
            'stripStartStopLineBreaks': True,
            'max_tokens': 512,
            'maxContextTokenSize': 4096
        }
        self.mock_api_type_config = {
            'type': 'openaichatcompletion',
            'presetType': 'OpenAI',
            'apiBaseUrl': 'http://mock-openai-api.com',
            'apiKey': 'TEST_API_KEY',
            'defaultHeaders': {'Authorization': 'Bearer TEST_API_KEY'},
            'backendApiPath': '/v1/chat/completions'
        }
        self.mock_preset = {'temperature': 0.5}

        # Use context manager patches within setUp for dependencies
        # needed ONLY for instantiation
        with patch('Middleware.utilities.config_utils.get_endpoint_config', return_value=self.mock_config), \
             patch('Middleware.utilities.config_utils.get_api_type_config', return_value=self.mock_api_type_config), \
             patch('Middleware.utilities.config_utils.get_current_username', return_value="testuser"):
             # Removed patch for load_preset_config
             # patch('Middleware.utilities.config_utils.load_preset_config', return_value=self.mock_preset): 
            
            # Pass the preset directly if the handler expects it, 
            # or ensure endpoint_config contains enough info
            self.handler = OpenAiApiHandler(
                endpoint_config=self.mock_config,
                api_type_config=self.mock_api_type_config,
                gen_input=self.mock_preset,
                stream=True,
                max_tokens=self.mock_config['max_tokens'],
                base_url=self.mock_api_type_config['apiBaseUrl'],
                model_name=self.mock_config.get('modelNameToSendToAPI', ''),
                headers=self.mock_api_type_config['defaultHeaders'],
                strip_start_stop_line_breaks=self.mock_config['stripStartStopLineBreaks'],
                api_key=self.mock_api_type_config.get('apiKey', '')
            )

    def test_handle_streaming_openai_sse_format(self):
        """Test that handle_streaming yields chunks in the correct OpenAI SSE format
           (data: {json}\n\n) when the frontend expects OpenAI.
        """
        # --- GIVEN ---
        fixed_uuid = uuid.UUID('12345678-1234-5678-1234-567812345678') # Fixed UUID
        fixed_time = 1678886400 # Fixed timestamp

        # GIVEN: Simulate response from an OpenAI-compatible API (stream=True)
        mock_response = MagicMock(spec=requests.Response)

        # Raw chunks from backend (OpenAI format)
        chunk1_backend = {"id":"chatcmpl-mock1","object":"chat.completion.chunk","created":1678886401,"model":"gpt-mock","choices":[{"index":0,"delta":{"content":"Hello "},"finish_reason":None}]}
        chunk2_backend = {"id":"chatcmpl-mock1","object":"chat.completion.chunk","created":1678886402,"model":"gpt-mock","choices":[{"index":0,"delta":{"content":"World"},"finish_reason":None}]}
        chunk3_backend = {"id":"chatcmpl-mock1","object":"chat.completion.chunk","created":1678886403,"model":"gpt-mock","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]} # Finish reason chunk
        done_chunk_backend = 'data: [DONE]\n\n' # Keep as string

        # Backend yields standard SSE formatted chunks as STRINGS
        mock_response.iter_content.return_value = [
            f"data: {json.dumps(chunk1_backend)}\n\n",
            f"data: {json.dumps(chunk2_backend)}\n\n",
            f"data: {json.dumps(chunk3_backend)}\n\n",
            done_chunk_backend
        ]
        mock_response.raise_for_status = MagicMock()
        mock_response.status_code = 200

        # GIVEN: Mock the HTTP session instance directly
        mock_session_instance = MagicMock(spec=requests.Session) # Create mock instance
        mock_post_context = MagicMock()
        mock_post_context.__enter__.return_value = mock_response
        mock_post_context.__exit__ = MagicMock(return_value=None)
        mock_session_instance.post.return_value = mock_post_context
        self.handler.session = mock_session_instance # Assign mocked session

        # --- WHEN ---
        # Frontend is expecting OpenAI format
        messages = [{"role": "user", "content": "Test OpenAI SSE"}]
        test_username = "mock_openai_user"

        # --- Define expected payloads BEFORE patching --- 
        # Build expected JSON PAYLOADS that build_response_json should return
        expected_payload1 = {"id": "chatcmpl-fixed1","object":"chat.completion.chunk","created":1,"model":"fixed_model","choices":[{"index":0,"delta":{"content":"Hello "},"finish_reason":None}]}
        expected_payload2 = {"id": "chatcmpl-fixed2","object":"chat.completion.chunk","created":2,"model":"fixed_model","choices":[{"index":0,"delta":{"content":"World"},"finish_reason":None}]}
        expected_payload3 = {"id": "chatcmpl-fixed3","object":"chat.completion.chunk","created":3,"model":"fixed_model","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}

        # Define side effect for the build_response_json mock
        def build_json_side_effect(token, current_username, finish_reason=None, **kwargs):
            self.assertEqual(current_username, test_username)
            if finish_reason == "stop":
                return expected_payload3 # Final payload
            elif token == "Hello ":
                return expected_payload1
            elif token == "World":
                return expected_payload2
            else:
                # Fallback or raise error if unexpected token received
                raise ValueError(f"Unexpected token in build_json_side_effect: {token}")

        # Use patch context manager for build_response_json
        with patch('Middleware.utilities.api_utils.build_response_json', side_effect=build_json_side_effect) as mock_build_json:
            stream_generator = self.handler.handle_streaming(
                conversation=messages
            )
            output_chunks = list(stream_generator)

        # --- THEN ---
        # Expected: SSE(payload1), SSE(payload2), SSE(payload3), SSE([DONE])
        self.assertEqual(len(output_chunks), 4, f"Expected 4 chunks, got {len(output_chunks)}: {output_chunks}")

        # Check the formatted SSE strings using the pre-defined payloads
        self.assertEqual(output_chunks[0], f"data: {json.dumps(expected_payload1)}\n\n")
        self.assertEqual(output_chunks[1], f"data: {json.dumps(expected_payload2)}\n\n")
        # Verify the final data chunk (index 2) contains payload 3
        self.assertEqual(output_chunks[2], f"data: {json.dumps(expected_payload3)}\n\n",
                         "Final data chunk payload mismatch")

        # Verify the final [DONE] chunk (index 3)
        self.assertEqual(output_chunks[3], 'data: [DONE]\n\n',
                         f"Expected final chunk (index 3) to be 'data: [DONE]\n\n', got: {repr(output_chunks[3])}")

        # Verify build_response_json was called correctly (3 times for content, 1 for final)
        self.assertEqual(mock_build_json.call_count, 3, "build_response_json call count mismatch")
        mock_build_json.assert_has_calls([
            call(token='Hello ', current_username=test_username, finish_reason=None, additional_fields=None),
            call(token='World', current_username=test_username, finish_reason=None, additional_fields=None),
            call(token='', current_username=test_username, finish_reason='stop', additional_fields=None)
        ], any_order=False) # Order matters here


if __name__ == '__main__':
    unittest.main() 