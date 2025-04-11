import unittest
import json
import sys
import os

# Add the project root to the Python path to allow importing Middleware modules
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../WilmerAI'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from Middleware.utilities.api_utils import extract_text_from_chunk

class TestApiUtils(unittest.TestCase):

    def test_extract_text_from_openai_sse_chunk(self):
        """Test extraction from a standard OpenAI SSE chunk."""
        chunk_data = {
            "id": "chatcmpl-test",
            "object": "chat.completion.chunk",
            "created": 1234567890,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": "Hello"},
                    "finish_reason": None
                }
            ]
        }
        sse_chunk = f"data: {json.dumps(chunk_data)}\n\n"
        expected_text = "Hello"
        self.assertEqual(extract_text_from_chunk(sse_chunk), expected_text)

    def test_extract_text_from_sse_done_signal(self):
        """Test extraction from an SSE [DONE] signal."""
        sse_chunk = "data: [DONE]\n\n"
        expected_text = ""
        self.assertEqual(extract_text_from_chunk(sse_chunk), expected_text)

    def test_extract_text_from_ollama_sse_chunk_fallback(self):
        """Test extraction from an SSE chunk using the message.content fallback."""
        # This simulates a format where the primary extraction might fail
        # but the fallback should catch it.
        chunk_data = {
            "model": "ollama-test",
            "created_at": "2023-10-26T...",
            "message": {
                "role": "assistant",
                "content": "Ollama says hi"
            },
            "done": False
        }
        sse_chunk = f"data: {json.dumps(chunk_data)}\n\n"
        expected_text = "Ollama says hi"
        # Note: The current logic prioritizes choices[0].delta.content.
        # If that's missing, *then* it checks message.content.
        # So, we create a dict *without* 'choices' to test the fallback.
        self.assertEqual(extract_text_from_chunk(sse_chunk), expected_text)
        
    def test_extract_text_from_sse_chunk_without_content(self):
        """Test SSE chunk where delta or message has no content."""
        chunk_data = {
            "id": "chatcmpl-test",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]
        }
        sse_chunk = f"data: {json.dumps(chunk_data)}\n\n"
        self.assertEqual(extract_text_from_chunk(sse_chunk), "")

        chunk_data_msg = {"message": {"role": "assistant"}}
        sse_chunk_msg = f"data: {json.dumps(chunk_data_msg)}\n\n"
        self.assertEqual(extract_text_from_chunk(sse_chunk_msg), "")


    def test_extract_text_from_invalid_sse_json(self):
        """Test extraction from an SSE chunk with invalid JSON."""
        sse_chunk = "data: {invalid json'\n\n"
        expected_text = ""
        # Should log a warning but return empty string
        self.assertEqual(extract_text_from_chunk(sse_chunk), expected_text)

    def test_extract_text_from_non_sse_json_string(self):
        """Test extraction from a regular JSON string (not SSE formatted)."""
        chunk_data = {
            "message": {
                "content": "Plain JSON string"
            }
        }
        json_string = json.dumps(chunk_data)
        expected_text = "Plain JSON string"
        # This tests the `else` block after `if chunk.startswith('data:')`
        self.assertEqual(extract_text_from_chunk(json_string), expected_text)

    def test_extract_text_from_invalid_non_sse_json_string(self):
        """Test extraction from an invalid regular JSON string."""
        json_string = "{invalid json'"
        expected_text = ""
        # Should log a warning but return empty string
        self.assertEqual(extract_text_from_chunk(json_string), expected_text)

    def test_extract_text_from_dict(self):
        """Test extraction directly from a Python dictionary."""
        chunk_dict = {
            "message": {
                "content": "From dict"
            }
        }
        expected_text = "From dict"
        self.assertEqual(extract_text_from_chunk(chunk_dict), expected_text)
        
    def test_extract_text_from_dict_missing_keys(self):
        """Test extraction from dicts missing expected keys."""
        chunk_dict_no_content = {"message": {"role": "assistant"}}
        self.assertEqual(extract_text_from_chunk(chunk_dict_no_content), "")

        chunk_dict_no_message = {"other_key": "value"}
        self.assertEqual(extract_text_from_chunk(chunk_dict_no_message), "")

        chunk_dict_message_not_dict = {"message": "not a dict"}
        self.assertEqual(extract_text_from_chunk(chunk_dict_message_not_dict), "")


    def test_extract_text_from_none(self):
        """Test extraction when input is None."""
        self.assertEqual(extract_text_from_chunk(None), "")

    def test_extract_text_from_int(self):
        """Test extraction when input is an integer."""
        self.assertEqual(extract_text_from_chunk(123), "")

    def test_extract_text_from_empty_string(self):
        """Test extraction when input is an empty string."""
        self.assertEqual(extract_text_from_chunk(""), "")

if __name__ == '__main__':
    unittest.main() 