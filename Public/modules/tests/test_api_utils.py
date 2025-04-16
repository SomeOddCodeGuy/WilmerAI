import unittest
import json
import sys
import os

# Add the project root to the Python path to allow importing Middleware modules
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../WilmerAI'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import the public function and the private helper for direct testing
from Middleware.utilities.api_utils import extract_text_from_chunk, _extract_content_from_parsed_json

class TestApiUtils(unittest.TestCase):

    # === Direct Tests for Helper Function ===
    def test_helper_extract_content_openai(self):
        parsed = {"choices": [{"delta": {"content": "OpenAI Text"}}]}
        self.assertEqual(_extract_content_from_parsed_json(parsed), "OpenAI Text")

    def test_helper_extract_content_ollama(self):
        parsed = {"response": "Ollama Text"}
        self.assertEqual(_extract_content_from_parsed_json(parsed), "Ollama Text")

    def test_helper_extract_content_message(self):
        parsed = {"message": {"content": "Message Text"}}
        self.assertEqual(_extract_content_from_parsed_json(parsed), "Message Text")

    def test_helper_extract_content_priority_openai(self):
        parsed = {"choices": [{"delta": {"content": "OpenAI Wins"}}], "response": "Ollama Loses", "message": {"content": "Msg Loses"}}
        self.assertEqual(_extract_content_from_parsed_json(parsed), "OpenAI Wins")
        
    def test_helper_extract_content_priority_ollama(self):
        parsed = {"choices": [{"delta": {"content": ""}}], "response": "Ollama Wins", "message": {"content": "Msg Loses"}}
        self.assertEqual(_extract_content_from_parsed_json(parsed), "Ollama Wins")
        
        parsed_no_choices = {"response": "Ollama Wins", "message": {"content": "Msg Loses"}}
        self.assertEqual(_extract_content_from_parsed_json(parsed_no_choices), "Ollama Wins")
        
    def test_helper_extract_content_priority_message(self):
        parsed = {"choices": [{"delta": {"content": ""}}], "response": "", "message": {"content": "Msg Wins"}}
        self.assertEqual(_extract_content_from_parsed_json(parsed), "Msg Wins")
        
        parsed_no_choices_no_resp = {"message": {"content": "Msg Wins"}}
        self.assertEqual(_extract_content_from_parsed_json(parsed_no_choices_no_resp), "Msg Wins")

    def test_helper_extract_content_empty_invalid(self):
        self.assertEqual(_extract_content_from_parsed_json({}), "")
        self.assertEqual(_extract_content_from_parsed_json({"choices": []}), "")
        self.assertEqual(_extract_content_from_parsed_json({"choices": [{}]}), "")
        self.assertEqual(_extract_content_from_parsed_json({"choices": [{"delta": {}}]}), "")
        self.assertEqual(_extract_content_from_parsed_json({"choices": [{"delta": {"content": ""}}]}), "")
        self.assertEqual(_extract_content_from_parsed_json({"response": ""}), "")
        self.assertEqual(_extract_content_from_parsed_json({"message": {}}), "")
        self.assertEqual(_extract_content_from_parsed_json({"message": {"content": ""}}), "")
        self.assertEqual(_extract_content_from_parsed_json("not a dict"), "") # Test non-dict input
        self.assertEqual(_extract_content_from_parsed_json(None), "")

    # === Tests for the Public Function (extract_text_from_chunk) ===
    # Keep existing tests, they should still pass as they test the overall behavior
    # with different input chunk types (SSE string, plain JSON string, dict, etc.)

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

    def test_extract_text_from_chunk_non_json_string(self):
        self.assertEqual(extract_text_from_chunk("Just a plain string"), "")

    def test_extract_text_from_chunk_number(self):
        self.assertEqual(extract_text_from_chunk(123), "")

    def test_extract_text_from_chunk_dict_ollama(self):
        """Test extracting text from a dictionary chunk in Ollama format."""
        chunk = {
            "model": "test-model",
            "created_at": "2023-01-01T12:00:00Z",
            "response": "This is Ollama text.",
            "done": False
        }
        self.assertEqual(extract_text_from_chunk(chunk), "This is Ollama text.")

    def test_extract_text_from_chunk_dict_openai_chat(self):
        """Test extracting text from a dictionary chunk in OpenAI Chat format (message.content)."""
        chunk = {
            "model": "test-model",
            "message": {
                "role": "assistant",
                "content": "This is OpenAI Chat text."
            },
            "done": True
        }
        self.assertEqual(extract_text_from_chunk(chunk), "This is OpenAI Chat text.")
    
    def test_extract_text_from_chunk_dict_mixed_prefers_response(self):
        """Test that 'response' is checked if 'message.content' is empty/missing in dict."""
        chunk = {
            "model": "test-model",
            "message": {"role": "assistant", "content": ""}, # Empty content
            "response": "This is the response text.",
            "done": False
        }
        self.assertEqual(extract_text_from_chunk(chunk), "This is the response text.")
        
        chunk_no_content = {
            "model": "test-model",
            "message": {"role": "assistant"}, # No content key
            "response": "This is the response text.",
            "done": False
        }
        self.assertEqual(extract_text_from_chunk(chunk_no_content), "This is the response text.")
        
        chunk_no_message = {
            "model": "test-model",
            "response": "This is the response text.",
            "done": False
        }
        self.assertEqual(extract_text_from_chunk(chunk_no_message), "This is the response text.")

    def test_extract_text_from_chunk_sse_ollama(self):
        """Test extracting text from an SSE string chunk in Ollama format."""
        chunk_str = 'data: { "model": "test", "response": "Ollama SSE text", "done": false }'
        self.assertEqual(extract_text_from_chunk(chunk_str), "Ollama SSE text")

    def test_extract_text_from_chunk_sse_openai(self):
        """Test extracting text from an SSE string chunk in OpenAI format."""
        chunk_str = 'data: { "choices": [{ "delta": { "content": "OpenAI SSE text" } }] }'
        self.assertEqual(extract_text_from_chunk(chunk_str), "OpenAI SSE text")

    def test_extract_text_from_chunk_sse_done(self):
        """Test extracting text from an SSE [DONE] signal."""
        chunk_str = 'data: [DONE]'
        self.assertEqual(extract_text_from_chunk(chunk_str), "")

if __name__ == '__main__':
    unittest.main() 