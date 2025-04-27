import unittest
import json
import sys
import os
from unittest.mock import patch, MagicMock
import requests
import uuid

# Add the project root to the Python path to allow importing Middleware modules
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../WilmerAI'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import the target functions and other necessary utils
from Middleware.utilities.api_utils import (
    handle_sse_and_json_stream,
    extract_openai_chat_content, # Using this as a representative callback
    sse_format,
    build_response_json # Need to mock this or its dependencies
)


class TestApiUtilsMisuseScenario(unittest.TestCase):

    def test_api_type_mismatch_produces_incorrect_stream_format(self):
        """
        Test that handle_sse_and_json_stream produces the CORRECT stream format
        when a handler provides the CORRECT frontend's expected API type.

        This test simulates:
        - Frontend expecting OpenAI SSE format ("openaichatcompletion").
        - Backend is Ollama (sending Ollama-style JSON lines).
        - Corrected Handler passes "openaichatcompletion" as intended_api_type.

        Expected Behavior: The test should PASS because the output format
        will match the expected OpenAI SSE format.
        """
        # =====================================================================
        # GIVEN: Setup reflecting the API type mismatch scenario
        # =====================================================================

        # GIVEN: A fixed UUID for deterministic ID generation during the test
        fixed_uuid = uuid.UUID('12345678-1234-5678-1234-567812345678')

        # GIVEN: The frontend expects standard OpenAI SSE format
        frontend_expected_api_type = "openaichatcompletion"
        expected_sse_prefix = "data: "
        expected_sse_suffix = "\n\n"

        # GIVEN: The backend sends data in its native format (Ollama-style JSON lines)
        backend_native_chunk_content = {"response": "Test token from backend"}
        backend_response_bytes = (json.dumps(backend_native_chunk_content) + "\n").encode('utf-8')

        # GIVEN: Mocked network response and helper callback
        mock_response = MagicMock(spec=requests.Response)
        mock_response.iter_content.return_value = [backend_response_bytes]
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        def mock_extract_callback(parsed_json): # Extracts content from the backend's native format
            return parsed_json.get("response", ""), None

        # =====================================================================
        # WHEN: The stream handler processes the response using the CORRECT API type
        # =====================================================================
        output_chunks = []
        
        # --- Define expected payloads BEFORE patching --- 
        expected_payload_content = {
            "id": "chatcmpl-fixed-content", "object": "chat.completion.chunk", "created": 1, 
            "model": "fixed_model", "system_fingerprint": "fp_fixed",
            "choices": [{"index": 0, "delta": {"content": "Test token from backend"}, "logprobs": None, "finish_reason": None}]
        }
        expected_payload_final = {
            "id": "chatcmpl-fixed-final", "object": "chat.completion.chunk", "created": 2, 
            "model": "fixed_model", "system_fingerprint": "fp_fixed",
            "choices": [{"index": 0, "delta": {}, "logprobs": None, "finish_reason": "stop"}]
        }

        # Define side effect for the build_response_json mock
        def build_json_side_effect(token, api_type, current_username, finish_reason=None, **kwargs):
            self.assertEqual(api_type, frontend_expected_api_type)
            self.assertEqual(current_username, "test_user_misuse")
            if finish_reason == "stop":
                return expected_payload_final
            elif token == "Test token from backend":
                return expected_payload_content
            else:
                raise ValueError(f"Unexpected token in build_json_side_effect: {token}")

        # Patch build_response_json directly
        with patch('Middleware.utilities.api_utils.build_response_json', side_effect=build_json_side_effect) as mock_build_json:
            stream_generator = handle_sse_and_json_stream(
                response=mock_response,
                extract_content_callback=mock_extract_callback,
                frontend_api_type=frontend_expected_api_type,
                current_username="test_user_misuse",
                strip_start_stop_line_breaks=False,
                add_user_assistant=False,
                add_missing_assistant=False
            )
            output_chunks = list(stream_generator) # Consume the generator to get output

        # =====================================================================
        # THEN: The output stream should match the frontend's expected format
        # =====================================================================

        self.assertTrue(len(output_chunks) >= 2,
                        "THEN: Generator should yield at least one content chunk and one final chunk.")
        
        # Get the first actual content chunk yielded by the stream handler
        actual_output_chunk = output_chunks[0]

        # Define the expected formatted chunk using the predefined payload
        expected_correct_chunk_format = sse_format(json.dumps(expected_payload_content), frontend_expected_api_type)

        # --- Primary Assertion: Check if the actual output matches the REQUIRED format ---
        self.assertEqual(actual_output_chunk, expected_correct_chunk_format,
                         f"The actual output chunk format should match the required frontend format ({frontend_expected_api_type}).\n"
                         f"Expected: {repr(expected_correct_chunk_format)}\n"
                         f"Actual:   {repr(actual_output_chunk)}")

        # --- THEN: Assert the full stream structure ---
        # Expected structure: Content chunk, Final chunk, [DONE] chunk
        self.assertEqual(len(output_chunks), 3,
                         f"Expected 3 chunks for OpenAI format (content+final+DONE), got {len(output_chunks)}: {repr(output_chunks)}")

        # Verify the final chunk structure (index 1 contains the final payload)
        final_actual_chunk_str = output_chunks[1] # Second chunk is the final data chunk
        expected_final_chunk_format = sse_format(json.dumps(expected_payload_final), frontend_expected_api_type)
        self.assertEqual(final_actual_chunk_str, expected_final_chunk_format,
                         "Final data chunk format mismatch.")

        # Verify the [DONE] chunk (should be index 2)
        done_chunk = output_chunks[2]
        expected_done_repr = repr("data: [DONE]\n\n")
        self.assertEqual(repr(done_chunk), expected_done_repr, 
                         f"Final chunk repr should match {expected_done_repr}. Got: {repr(done_chunk)}")
        
        # Verify build_response_json was called
        self.assertGreaterEqual(mock_build_json.call_count, 2, "build_response_json should be called at least twice")
        mock_build_json.assert_any_call(token='Test token from backend', api_type=frontend_expected_api_type, current_username='test_user_misuse', finish_reason=None, additional_fields=None)
        mock_build_json.assert_any_call(token='', api_type=frontend_expected_api_type, current_username='test_user_misuse', finish_reason='stop', additional_fields=None)


if __name__ == '__main__':
    unittest.main() 