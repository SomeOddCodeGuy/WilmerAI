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

    @patch('requests.Session')
    def test_handle_streaming_openai_sse_format(self, mock_session_cls, mock_time_strftime, mock_get_username, mock_load_config):
        """
        Test that handle_streaming yields chunks in the correct OpenAI SSE format
        when configured for 'openaichatcompletion'.
        """
        # 1. Mock dependencies
        mock_get_username.return_value = "mock-openai-model"
        mock_time_strftime.return_value = "2024-01-02T13:00:00Z" # Use different time for clarity

        # Mock configuration loading (Use OpenAI apiType)
        mock_endpoint_config = {
            "endpoint": "http://mock-openai-backend.com/v1",
            "modelNameToSendToAPI": "mock-openai-model",
            "apiTypeConfigFileName": "openaichatcompletion_config", # Use OpenAI config name
            "presetConfigFileName": "mock_preset",
            "addGenerationPrompt": False,
            "stripStartStopLineBreaks": True,
            "maxContextTokenSize": 4096,
            "max_tokens": 1024
        }
        mock_api_type_config = {
            "apiType": "openaichatcompletion", # Critical: Set API type to OpenAI
            "apiKey": "fake-openai-key",
            "apiBaseUrl": "http://mock-openai-backend.com",
            "defaultHeaders": {"Authorization": "Bearer {apiKey}", "Content-Type": "application/json"},
            "streamPropertyName": "stream",
            "maxNewTokensPropertyName": "max_tokens",
            # Backend properties (assuming OpenAI backend)
            "backendApiType": "openaichatcompletion",
            "backendApiPath": "/v1/chat/completions",
            "backendResponseTokenExtractor": "extract_openai_chat_content",
            "backendResponseFinishReasonExtractor": "extract_openai_finish_reason"
        }
        mock_preset_config = {
            "temperature": 0.5,
            "top_p": 1.0
        }

        # 2. Prepare mock LLM response chunks (Simulating OpenAI backend response)
        raw_llm_chunks = ["Test", " ", "OpenAI", "!"]
        mock_response = MagicMock()
        # Backend sends OpenAI format
        mock_response.iter_content = MagicMock(return_value=(
            f"data: {json.dumps({'choices': [{'delta': {'content': chunk}}], 'model': 'mock-backend'})}\n\n".encode('utf-8')
            for chunk in raw_llm_chunks + [''] # Add empty chunk to allow finish reason processing
        ))
        # Add finish reason chunk
        final_backend_chunk = f"data: {json.dumps({'choices': [{'finish_reason': 'stop', 'delta':{}}], 'model': 'mock-backend'})}\n\n".encode('utf-8')
        mock_response.iter_content.return_value = list(mock_response.iter_content()) + [final_backend_chunk]
        # Add DONE marker
        done_marker = b"data: [DONE]\n\n"
        mock_response.iter_content.return_value = list(mock_response.iter_content()) + [done_marker]

        mock_response.raise_for_status = MagicMock()
        mock_response.status_code = 200

        # 3. Mock the HTTP session
        mock_session_instance = MagicMock()
        mock_session_instance.post.return_value.__enter__.return_value = mock_response
        mock_session_cls.return_value = mock_session_instance

        # 4. Instantiate the handler
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

        # 5. Patch instance_utils.API_TYPE and call handle_streaming
        # Patch the specific API type for this test run
        with patch('Middleware.utilities.instance_utils.API_TYPE', 'openaichatcompletion'):
            messages = [{"role": "user", "content": "Test"}]
            stream_generator = handler.handle_streaming(conversation=messages)

            # 6. Collect output
            output_chunks = list(stream_generator)

        # 7. Define the CORRECT expected OpenAI /v1/chat/completions SSE format structure
        #    We will compare parsed JSON objects, not raw strings.
        expected_events = []
        expected_model = "mock-openai-model"

        for token in raw_llm_chunks:
            if not token: continue # Skip empty processing tokens
            expected_event_payload = {
                # id: Ignored during comparison
                "object": "chat.completion.chunk",
                # created: Ignored during comparison
                "model": expected_model,
                "system_fingerprint": "fp_44709d6fcb", # Assuming this is constant
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": token},
                        "logprobs": None,
                        "finish_reason": None
                    }
                ]
            }
            expected_events.append(expected_event_payload)

        # Add the final chunk payload with finish_reason
        final_event_payload = {
            "object": "chat.completion.chunk",
            "model": expected_model,
            "system_fingerprint": "fp_44709d6fcb",
            "choices": [
                {
                    "index": 0,
                    "delta": {}, # Delta might be empty if only finish_reason is sent
                    "logprobs": None,
                    "finish_reason": "stop"
                }
            ]
            # NOTE: Sometimes OpenAI sends delta: {"content": ""} and finish_reason: "stop" in the same chunk
            # Adjust if the implementation's final chunk payload differs slightly.
        }
        expected_events.append(final_event_payload)

        # Parse the actual output chunks
        actual_events = []
        done_signal_received = False
        for chunk_str in output_chunks:
            if chunk_str.startswith("data: "):
                json_str = chunk_str[len("data: "):].strip()
                if json_str == "[DONE]":
                    done_signal_received = True
                    continue
                try:
                    parsed = json.loads(json_str)
                    # Remove volatile fields before comparison
                    parsed.pop('id', None)
                    parsed.pop('created', None)
                    actual_events.append(parsed)
                except json.JSONDecodeError:
                    self.fail(f"Failed to parse actual output chunk as JSON: {json_str}")

        # 8. Assert the list of parsed event payloads match
        self.assertEqual(len(actual_events), len(expected_events),
                         f"Number of actual events ({len(actual_events)}) does not match expected ({len(expected_events)})")

        for i in range(len(expected_events)):
            # Special handling for the last event which might have delta: {} vs delta: {"content": ""}
            if i == len(expected_events) - 1:
                # Tolerate empty content in delta for the final chunk
                if actual_events[i]['choices'][0]['delta'] == {'content': ''} and expected_events[i]['choices'][0]['delta'] == {}:
                     actual_events[i]['choices'][0]['delta'] = {}

            self.assertDictEqual(actual_events[i], expected_events[i],
                                 f"Actual event {i} does not match expected event {i}.")

        # Assert the [DONE] signal was received
        self.assertTrue(done_signal_received, "Final data: [DONE] signal was not received.")


if __name__ == '__main__':
    unittest.main() 