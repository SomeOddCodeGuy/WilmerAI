import unittest
from unittest.mock import patch, MagicMock
import json
import sys
import os
import time
import logging
import uuid
import requests

# Configure logging for this test file
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Add project root to sys.path to allow importing WilmerAI modules
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')) # Adjust path as needed
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from Middleware.llmapis.ollama_chat_api_handler import OllamaChatHandler
from Middleware.utilities import api_utils

# Mock LlmHandlerService if needed for init (though not directly used here)
class MockLlmHandlerService: # Basic mock if needed
    pass 

class TestOllamaChatApiHandlerSSE(unittest.TestCase):

    def test_handle_streaming_ollama_chat_sse_format(self):
        """Test that OllamaChatHandler.handle_streaming yields chunks in the correct
        Ollama Chat SSE format (plain JSON lines without 'data:' prefix).
        """
        # --- GIVEN ---
        fixed_uuid = uuid.UUID('11111111-1111-1111-1111-111111111111') # Fixed UUID
        fixed_time = 1678886400 # Fixed timestamp

        # Define realistic mock configs instead of MagicMock
        mock_endpoint_config = {
            "maxContextTokenSize": 2048, # Example value needed by set_gen_input
            # Add other keys if handler init uses them
        }
        mock_api_type_config = {
            "type": "ollamaapichat",
            "truncatePropertyName": "num_ctx", # Example key needed by set_gen_input
            "streamPropertyName": "stream", # Example key needed by set_gen_input
            "maxNewTokensPropertyName": "num_predict", # Example key needed by set_gen_input
            "apiKey": "",
            "apiBaseUrl": "http://mock-ollama",
            "defaultHeaders": {"Content-Type": "application/json"},
            # Add other keys if handler init uses them
        }

        # Simulate response from Ollama Chat API (stream=True)
        mock_response = MagicMock(spec=requests.Response)
        # Content chunks as bytes, mimicking iter_content
        chunk1_data = {"model":"test_model","created_at":"2023-08-04T08:52:19.325406415Z","message":{"role":"assistant","content":"Hello "},"done":False}
        chunk2_data = {"model":"test_model","created_at":"2023-08-04T08:52:19.555406415Z","message":{"role":"assistant","content":"world"},"done":False}
        chunk3_data = {"model":"test_model","created_at":"2023-08-04T08:52:19.999406415Z","message":{"role":"assistant","content":"!"},"done":True}
        # Ollama streaming yields JSON lines
        mock_response.iter_content.return_value = [
            (json.dumps(chunk1_data) + '\n').encode('utf-8'),
            (json.dumps(chunk2_data) + '\n').encode('utf-8'),
            (json.dumps(chunk3_data) + '\n').encode('utf-8'),
        ]
        mock_response.raise_for_status = MagicMock()
        mock_response.status_code = 200 # Explicitly mock status code
        # Explicitly make iter_content a callable mock that returns the list
        mock_response.iter_content = MagicMock(return_value=mock_response.iter_content.return_value)
        
        handler = OllamaChatHandler(
            endpoint_config=mock_endpoint_config, # Use mock dict
            api_type_config=mock_api_type_config, # Use mock dict
            gen_input={},     # Start with empty dict
            max_tokens=100,
            stream=True,
            base_url=mock_api_type_config['apiBaseUrl'], 
            model_name="test_model", 
            headers=mock_api_type_config['defaultHeaders'], 
            strip_start_stop_line_breaks=False,
            api_key="" 
        )
        
        # Manually Patch the session instance on the handler
        mock_session_instance = MagicMock(spec=requests.Session)
        mock_post_context = MagicMock()
        mock_post_context.__enter__.return_value = mock_response
        mock_post_context.__exit__ = MagicMock(return_value=None)
        mock_session_instance.post.return_value = mock_post_context
        handler.session = mock_session_instance # Replace the real session with the mock

        # --- WHEN ---
        # Use nested patch context managers
        with patch('uuid.uuid4', return_value=fixed_uuid) as mock_uuid_patch, \
             patch('time.time', return_value=fixed_time) as mock_time_patch:
            result_generator = handler.handle_streaming([])
            results = list(result_generator)

        # --- THEN ---
        self.assertEqual(len(results), 4) # 3 content chunks + 1 final chunk

        # Build expected JSON dictionaries for comparison
        test_username = "test_user_ollama_chat"
        expected_json1 = api_utils.build_response_json("Hello ", 'ollamaapichat', current_username=test_username)
        expected_json2 = api_utils.build_response_json("world", 'ollamaapichat', current_username=test_username)
        expected_json3 = api_utils.build_response_json("!", 'ollamaapichat', current_username=test_username)
        expected_final_json = api_utils.build_response_json("", 'ollamaapichat', current_username=test_username, finish_reason="stop")

        # Check that the yielded strings match the Ollama format (json + \n)
        self.assertEqual(results[0], json.dumps(expected_json1) + '\n')
        self.assertEqual(results[1], json.dumps(expected_json2) + '\n')
        self.assertEqual(results[2], json.dumps(expected_json3) + '\n')
        self.assertEqual(results[3], json.dumps(expected_final_json) + '\n') # Check final chunk

        # Verify no SSE prefix/suffix were added
        self.assertFalse(any(r.startswith('data:') for r in results))
        self.assertFalse(any(r.endswith('\n\n') for r in results))

if __name__ == '__main__':
    unittest.main()
