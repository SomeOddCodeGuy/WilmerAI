import unittest
import json
import sys
import os
from unittest.mock import patch, MagicMock, call

# Add the project root to the Python path to allow importing Middleware modules
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../WilmerAI'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Import the public function and the private helper for direct testing
from Middleware.utilities.api_utils import extract_text_from_chunk, _extract_content_from_parsed_json

# Import public functions from api_utils
from Middleware.utilities.api_utils import (
    build_response_json,
    sse_format,
    remove_assistant_prefix,
    get_model_name # Assuming this might be needed or tested
)
# Import instance_utils to potentially set API_TYPE if needed
from Middleware.utilities import instance_utils

class TestExtractTextFromChunk(unittest.TestCase):
    "Tests for the public extract_text_from_chunk function."

    def test_extract_openai_chat_content(self):
        chunk_str = 'data: {"id": "chatcmpl-1", "object": "chat.completion.chunk", "choices": [{"delta": {"content": "Hello"}}]}\n\n'
        self.assertEqual(extract_text_from_chunk(chunk_str), "Hello")

    def test_extract_openai_completion_content(self):
        chunk_str = 'data: {"id": "cmpl-1", "object": "text_completion", "choices": [{"text": " World"}]}\\n\\n'
        self.assertEqual(extract_text_from_chunk(chunk_str), " World")

    def test_extract_ollama_generate_content(self):
        # Ollama Generate stream is typically just JSON lines
        chunk_str = '{"response": " Ollama"}'
        self.assertEqual(extract_text_from_chunk(chunk_str), " Ollama")

    def test_extract_ollama_chat_content(self):
        chunk_str = '{"message": {"content": " Chat!"}}'
        self.assertEqual(extract_text_from_chunk(chunk_str), " Chat!")

    def test_extract_from_dict(self):
        chunk_dict = {"choices": [{"delta": {"content": "From Dict"}}]}
        self.assertEqual(extract_text_from_chunk(chunk_dict), "From Dict")

    def test_extract_from_done_chunk(self):
        chunk_str = 'data: [DONE]\\n\\n'
        self.assertEqual(extract_text_from_chunk(chunk_str), "")

    def test_extract_from_empty_data_chunk(self):
        chunk_str = 'data: \\n\\n' # Empty data
        self.assertEqual(extract_text_from_chunk(chunk_str), "")
        chunk_str_2 = 'data: {}\\n\\n' # Empty JSON
        self.assertEqual(extract_text_from_chunk(chunk_str_2), "")

    def test_extract_from_malformed_json(self):
        chunk_str = 'data: {"content": \"unclosed}\\n\\n'
        # Should log a warning and return empty string
        with self.assertLogs(level='WARNING') as cm:
            self.assertEqual(extract_text_from_chunk(chunk_str), "")
        self.assertTrue(any("Failed to parse SSE JSON content" in log for log in cm.output))

    def test_extract_from_non_sse_string(self):
        # Should treat as plain JSON string if possible
        chunk_str = '{"response": "Plain JSON"}'
        self.assertEqual(extract_text_from_chunk(chunk_str), "Plain JSON")
        chunk_str_malformed = 'not json'
        self.assertEqual(extract_text_from_chunk(chunk_str_malformed), "")

    def test_extract_from_none(self):
        self.assertEqual(extract_text_from_chunk(None), "")

    def test_extract_from_other_type(self):
        self.assertEqual(extract_text_from_chunk(123), "")
        self.assertEqual(extract_text_from_chunk([1, 2]), "")

# ... (Keep other test classes like TestBuildResponseJson, TestSseFormat, etc.) ...

# Remove the old test class for the internal function
# class TestExtractContentFromParsedJson(unittest.TestCase):
#    ...

if __name__ == '__main__':
    unittest.main() 