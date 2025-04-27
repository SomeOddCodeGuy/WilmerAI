import unittest
import sys
import os
import base64
from unittest.mock import patch, MagicMock, call, ANY, mock_open
import json
from copy import deepcopy

# Add the project root to the Python path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Ensure Middleware can be found
middleware_path = os.path.join(project_root, 'WilmerAI')
if middleware_path not in sys.path:
     sys.path.insert(0, middleware_path)

# Imports after path adjustments
from WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler import (
    OpenAIApiChatImageSpecificHandler,
    prep_corrected_conversation,
    convert_to_data_uri,
    is_valid_http_url,
    is_base64_image,
    is_file_url
)
from WilmerAI.Middleware.utilities import api_utils # For mocking
import requests # For mocking exceptions

# Mock instance_utils and config_utils as they are used globally or in helpers
sys.modules['Middleware.utilities.instance_utils'] = MagicMock()
# sys.modules['Middleware.utilities.config_utils'] = MagicMock() # Keep config_utils for mocking specific functions
# Set a specific return value for API_TYPE
sys.modules['Middleware.utilities.instance_utils'].API_TYPE = 'openai' # Keep this for potential other uses

# Mock config_utils functions used in handler init and tests
# @patch('Middleware.utilities.config_utils.get_current_username', return_value="testuser") # Apply via decorator if needed per test
# @patch('Middleware.utilities.config_utils.get_api_type_config') # Apply via decorator

from Middleware.utilities import config_utils
config_utils.get_current_username.return_value = "testuser"
config_utils.get_is_chat_complete_add_user_assistant.return_value = False
config_utils.get_is_chat_complete_add_missing_assistant.return_value = False

# --- Tests for Helper Functions ---

class TestPrepCorrectedConversationHelpers(unittest.TestCase):

    def test_is_valid_http_url(self):
        self.assertTrue(is_valid_http_url("http://example.com"))
        self.assertTrue(is_valid_http_url("https://example.com/path?query=1"))
        self.assertFalse(is_valid_http_url("ftp://example.com"))
        self.assertFalse(is_valid_http_url("example.com"))
        self.assertFalse(is_valid_http_url("/local/path"))
        self.assertFalse(is_valid_http_url("http:/example")) # Invalid format

    def test_is_base64_image(self):
        self.assertTrue(is_base64_image("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAUA"))
        self.assertTrue(is_base64_image("iVBORw0KGgoAAAANSUhEUgAAAAUA")) # Raw base64
        self.assertFalse(is_base64_image("http://example.com/image.png"))
        self.assertFalse(is_base64_image("just plain text"))
        self.assertFalse(is_base64_image("data:text/plain;base64,YWFh")) # Not image

    def test_is_file_url(self):
        self.assertTrue(is_file_url("file:///path/to/image.jpg"))
        self.assertTrue(is_file_url("file://localhost/path/to/image.jpg"))
        self.assertFalse(is_file_url("http://example.com"))
        self.assertFalse(is_file_url("/path/to/image.jpg"))

    def test_convert_to_data_uri(self):
        with patch('os.path.exists') as mock_exists, \
             patch('builtins.open', new_callable=mock_open) as mock_open_ctx:

            mock_exists.return_value = True
            # Mock reading binary data and base64 encoding
            mock_file = MagicMock()
            mock_file.read.return_value = b'\x89PNG\r\n\x1a\n' # Sample PNG header
            mock_open_ctx.return_value.__enter__.return_value = mock_file

            expected_base64 = base64.b64encode(b'\x89PNG\r\n\x1a\n').decode('utf-8')

            # Test with explicit mime type
            uri = convert_to_data_uri("/fake/path/image.png", mime_type="image/png")
            self.assertEqual(uri, f"data:image/png;base64,{expected_base64}")

            # Test with guessed mime type
            uri_guessed = convert_to_data_uri("/fake/path/image.jpeg")
            self.assertEqual(uri_guessed, f"data:image/jpeg;base64,{expected_base64}")

            # Test with unknown extension
            uri_unknown = convert_to_data_uri("/fake/path/image.xyz")
            self.assertEqual(uri_unknown, f"data:application/octet-stream;base64,{expected_base64}")

            # Test file not found
            mock_exists.return_value = False
            with self.assertRaises(FileNotFoundError):
                convert_to_data_uri("/not/real/path.png")

class TestPrepCorrectedConversation(unittest.TestCase):

    def test_no_images_simple_prompt(self):
        conversation = [{"role": "user", "content": "Hello"}]
        result = prep_corrected_conversation(conversation, None, None)
        expected = [{"role": "user", "content": "Hello"}]
        self.assertEqual(result, expected)

    def test_system_and_user_prompt(self):
        result = prep_corrected_conversation(None, "Be helpful", "How are you?")
        expected = [
            {"role": "system", "content": "Be helpful"},
            {"role": "user", "content": "How are you?"}
        ]
        self.assertEqual(result, expected)

    def test_systemMes_role_conversion(self):
        conversation = [{"role": "systemMes", "content": "System instructions"}]
        result = prep_corrected_conversation(conversation, None, None)
        expected = [{"role": "system", "content": "System instructions"}]
        self.assertEqual(result, expected)

    def test_empty_final_assistant_message_removed(self):
        conversation = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": ""}
        ]
        result = prep_corrected_conversation(conversation, None, None)
        expected = [{"role": "user", "content": "Hi"}]
        self.assertEqual(result, expected)

        conversation_none = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": None}
        ]
        result_none = prep_corrected_conversation(conversation_none, None, None)
        self.assertEqual(result_none, expected)

    def test_image_url_added_to_last_user_message(self):
        conversation = [
            {"role": "user", "content": "First message"},
            {"role": "assistant", "content": "Okay"},
            {"role": "user", "content": "Look at this"},
            {"role": "images", "content": "http://example.com/image.jpg"}
        ]
        result = prep_corrected_conversation(conversation, None, None)
        expected = [
            {"role": "user", "content": "First message"},
            {"role": "assistant", "content": "Okay"},
            {"role": "user", "content": [
                {"type": "text", "text": "Look at this"},
                {"type": "image_url", "image_url": {"url": "http://example.com/image.jpg"}}
            ]}
        ]
        self.assertEqual(result, expected)

    def test_multiple_image_urls(self):
        conversation = [
            {"role": "user", "content": "Describe these"},
            {"role": "images", "content": "http://image1.png https://image2.jpeg //image3.gif"}
        ]
        result = prep_corrected_conversation(conversation, None, None)
        expected = [
            {"role": "user", "content": [
                {"type": "text", "text": "Describe these"},
                {"type": "image_url", "image_url": {"url": "http://image1.png"}},
                {"type": "image_url", "image_url": {"url": "https://image2.jpeg"}},
                {"type": "image_url", "image_url": {"url": "https://image3.gif"}} # // gets https:
            ]}
        ]
        self.assertEqual(result, expected)

    def test_base64_data_uri(self):
        b64_string = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAUA"
        conversation = [
            {"role": "user", "content": "What is this?"},
            {"role": "images", "content": b64_string}
        ]
        result = prep_corrected_conversation(conversation, None, None)
        expected = [
            {"role": "user", "content": [
                {"type": "text", "text": "What is this?"},
                {"type": "image_url", "image_url": {"url": b64_string}}
            ]}
        ]
        self.assertEqual(result, expected)

    def test_raw_base64_data(self):
        raw_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAUA"
        expected_uri = f"data:image/jpeg;base64,{raw_b64}" # Assumes jpeg if not specified
        conversation = [
            {"role": "user", "content": "Raw base64"},
            {"role": "images", "content": raw_b64}
        ]
        result = prep_corrected_conversation(conversation, None, None)
        expected = [
            {"role": "user", "content": [
                {"type": "text", "text": "Raw base64"},
                {"type": "image_url", "image_url": {"url": expected_uri}}
            ]}
        ]
        self.assertEqual(result, expected)

    def test_base64_with_semicolon_no_data_prefix(self):
        b64_chunk = "iVBORw0KGgoAAAANSUhEUgAAAAUA"
        b64_string = f"image/png;base64,{b64_chunk}"
        expected_uri = f"data:image/jpeg;base64,{b64_chunk}"
        conversation = [
            {"role": "user", "content": "Semi base64"},
            {"role": "images", "content": b64_string}
        ]
        result = prep_corrected_conversation(conversation, None, None)
        expected = [
            {"role": "user", "content": [
                {"type": "text", "text": "Semi base64"},
                {"type": "image_url", "image_url": {"url": expected_uri}}
            ]}
        ]
        self.assertEqual(result, expected)

    def test_file_url(self):
        with patch('WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler.convert_to_data_uri') as mock_convert:
            file_url = "file:///images/my_image.png"
            expected_data_uri = "data:image/png;base64,FAKEDATA"
            mock_convert.return_value = expected_data_uri

            conversation = [
                {"role": "user", "content": "Check this file"},
                {"role": "images", "content": file_url}
            ]
            result = prep_corrected_conversation(conversation, None, None)
            expected = [
                {"role": "user", "content": [
                    {"type": "text", "text": "Check this file"},
                    {"type": "image_url", "image_url": {"url": expected_data_uri}}
                ]}
            ]
            mock_convert.assert_called_once_with("/images/my_image.png")
            self.assertEqual(result, expected)

    def test_file_url_conversion_error(self):
        with patch('WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler.convert_to_data_uri') as mock_convert:
            # Simulate an error during file conversion (e.g., file not found)
            file_url = "file:///images/missing.png"
            mock_convert.side_effect = FileNotFoundError("File gone")

            conversation = [
                {"role": "user", "content": "Check this file"},
                {"role": "images", "content": file_url}
            ]
            # Expect it to skip the image if conversion fails
            result = prep_corrected_conversation(conversation, None, None)
            expected = [
                {"role": "user", "content": "Check this file"} # Image part omitted
            ]
            mock_convert.assert_called_once_with("/images/missing.png")
            self.assertEqual(result, expected)

    def test_invalid_image_url_skipped(self):
        conversation = [
            {"role": "user", "content": "Look at this"},
            {"role": "images", "content": "invalid-url"}
        ]
        result = prep_corrected_conversation(conversation, None, None)
        expected = [
            {"role": "user", "content": "Look at this"} # Image part omitted
        ]
        self.assertEqual(result, expected)

    def test_images_added_to_new_user_message_if_none_exists(self):
        conversation = [
            {"role": "system", "content": "System prompt"},
            {"role": "images", "content": "http://example.com/image.jpg"}
        ]
        result = prep_corrected_conversation(conversation, None, None)
        expected = [
            {'role': 'system', 'content': 'System prompt'},
            {'role': 'user', 'content': [
                {'type': 'text', 'text': 'Please describe this image.'},
                {'type': 'image_url', 'image_url': {'url': 'http://example.com/image.jpg'}}
            ]}
        ]
        self.assertEqual(result, expected)

    def test_integration_mixed_content(self):
        with patch('WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler.convert_to_data_uri') as mock_convert:
            b64_string = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAUA"
            raw_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAYAAAAGCAYAAADgzO9rAAAAAXNSR0IArs4c6QAAADNJREFUGFdjePv27X8ZGAwYGEDAwMzPz/+AaUcUxAZEGUDmQAJGBiYGAQZDIBhBXgqDNAAAAP//AwDL0AVaPEGrAAAAAElFTkSuQmCC"
            expected_raw_uri = f"data:image/jpeg;base64,{raw_b64}"
            file_url = "file:///tmp/test.gif"
            http_url = "http://place.com/img.webp"
            https_url = "https://secure.com/pic.jpeg"
            invalid_url = "bad stuff"

            mock_data_uri = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7" # Mocked file conversion

            def mock_side_effect(path):
                if path == "/tmp/test.gif":
                    raise FileNotFoundError("Mocked file not found")
                return None

            def run_test():
                # Configure the mock to raise an error for the specific file path
                mock_convert.side_effect = mock_side_effect

                conversation = [
                    {"role": "user", "content": "Message 1"},
                    {"role": "assistant", "content": "Response 1"},
                    {"role": "user", "content": "Look at all these"},
                    {"role": "images", "content": f"{b64_string} {raw_b64} {file_url} {http_url}"},
                    {"role": "images", "content": f"{https_url} {invalid_url}"} # Separate images message
                ]
                result = prep_corrected_conversation(conversation, "System prompt", None)

                # Dynamically build the expected content list based on valid inputs
                expected_image_urls = [
                    b64_string,       # Valid data URI
                    expected_raw_uri, # Valid converted raw base64
                    # file_url is skipped due to mocked FileNotFoundError
                    http_url,         # Valid HTTP URL
                    https_url         # Valid HTTPS URL
                    # invalid_url is skipped
                ]
                expected_final_user_content_structure = [
                    {"type": "text", "text": "Look at all these"}
                ] + [
                    {"type": "image_url", "image_url": {"url": url}}
                    for url in expected_image_urls
                ]

                self.assertEqual(len(result), 4) # user, assistant, user, system
                self.assertEqual(result[0], {"role": "user", "content": "Message 1"})
                self.assertEqual(result[1], {"role": "assistant", "content": "Response 1"})
                self.assertEqual(result[2]["role"], "user")
                # Use assertCountEqual for list comparison where order might not strictly matter
                # (though in this case, text should be first)
                self.assertIsInstance(result[2]["content"], list)
                self.assertCountEqual(result[2]["content"], expected_final_user_content_structure)
                # Optional: Verify text is first element if order is guaranteed
                self.assertEqual(result[2]["content"][0], {"type": "text", "text": "Look at all these"})

                self.assertEqual(result[3], {"role": "system", "content": "System prompt"})

                mock_convert.assert_called_once_with("/tmp/test.gif")

            run_test()


# --- Tests for Handler Methods (will be added later) ---

class TestOpenAIApiChatImageSpecificHandlerMethods(unittest.TestCase):

    def setUp(self):
        """Set up a handler instance for testing."""
        with patch('Middleware.utilities.config_utils.get_api_type_config') as mock_get_api_type_config:
            # Define a mock config dict to be returned by get_api_type_config('openai')
            self.mock_api_config = {
                "apiType": "openai",
                "truncateLengthPropertyName": "max_tokens",
                "streamPropertyName": "stream",
                "maxTokenPropertyName": "max_tokens"
                # Add other keys if LlmApiHandler.__init__ needs them
            }
            mock_get_api_type_config.return_value = self.mock_api_config

            self.mock_endpoint_config = {
                "baseURL": "http://mock-openai.com",
                "apiKey": "fake-key",
                "modelName": "gpt-4-vision-preview",
                "maxContextTokenSize": 8000,
                "maxToken": 1000,
                "truncatePropertyName": "max_tokens", # Example property name
                "streamPropertyName": "stream", # Example property name
                "maxTokenPropertyName": "max_tokens" # Example property name
            }
            # Handler instantiation now happens inside the patch context
            self.handler = OpenAIApiChatImageSpecificHandler(
                endpoint_config=self.mock_endpoint_config,
                headers={"Authorization": "Bearer fake-key", "Content-Type": "application/json"},
                stream=True, # Default to stream=True for setup
                strip_start_stop_line_breaks=True,
                base_url=self.mock_endpoint_config["baseURL"],
                api_key=self.mock_endpoint_config["apiKey"],
                gen_input={}, # Initialize as empty dict
                model_name=self.mock_endpoint_config["modelName"],
                # Pass the mocked config dictionary here
                api_type_config=self.mock_api_config,
                max_tokens=self.mock_endpoint_config["maxToken"]
            )
        # Mock the requests session used by the handler (outside the patch context)
        self.handler.session = MagicMock(spec=requests.Session)
        self.mock_post = self.handler.session.post

        # Define sample conversation for tests that need it
        self.sample_conversation = [
            {"role": "user", "content": "Hello, describe the image please."},
            {"role": "images", "content": "http://example.com/image.jpg"} # Example image
        ]

    @patch('requests.post')
    def test_handle_streaming_success(self, mock_post):
        """Test successful streaming using the utility function."""
        mock_response = MagicMock()
        # Simulate SSE chunks
        sse_chunks = [
            b'data: {"id": "chatcmpl-1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4", "choices": [{"index": 0, "delta": {"content": "Hello"}, "finish_reason": null}]}\n\n',
            b'data: {"id": "chatcmpl-1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4", "choices": [{"index": 0, "delta": {"content": " World"}, "finish_reason": null}]}\n\n',
            b'data: {"id": "chatcmpl-1", "object": "chat.completion.chunk", "created": 1, "model": "gpt-4", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}\n\n',
            b'data: [DONE]\n\n'
        ]
        mock_response.iter_lines.return_value = sse_chunks
        mock_response.raise_for_status = MagicMock() # Mock this method
        self.mock_post.return_value = mock_response

        # Restore the patch for the utility function
        with patch('WilmerAI.Middleware.utilities.api_utils.handle_sse_and_json_stream') as mock_handle_stream_util:
            # Simulate the utility yielding formatted strings
            mock_handle_stream_util.return_value = iter([
                'data: {"id": "chatcmpl-test1", ..., "delta": {"content": "Hello"}, ...}\n\n',
                'data: {"id": "chatcmpl-test1", ..., "delta": {"content": " World"}, ...}\n\n',
                'data: {"id": "chatcmpl-test1", ..., "delta": {}, "finish_reason": "stop"}\n\n',
                'data: [DONE]\n\n'
            ])

            # Call the method
            result_generator = self.handler.handle_streaming(
                conversation=self.sample_conversation,
                current_username="test_user"
            )
            results = list(result_generator)

            # Check that the utility was called correctly
            mock_handle_stream_util.assert_called_once_with(
                response=mock_response,
                extract_content_callback=ANY, # Check if a callable is passed
                frontend_api_type='openaichatcompletion', # This handler *should* know its target type
                current_username='test_user',
                strip_start_stop_line_breaks=True,
                add_user_assistant=False, # Assuming default config
                add_missing_assistant=True # Assuming default config
            )

            # Check that the final output matches what the mocked utility returned
            self.assertEqual(len(results), 4)
            self.assertTrue('Hello' in results[0])
            self.assertTrue('World' in results[1])
            self.assertTrue('finish_reason": "stop"' in results[2])
            self.assertEqual(results[3], 'data: [DONE]\n\n')

    def test_handle_streaming_request_exception(self):
        """Test streaming handling of requests.RequestException."""
        with patch('WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler.prep_corrected_conversation') as mock_prep_convo, \
             patch('WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler.api_utils.build_response_json', return_value='{"error": "mocked"}') as mock_build_json, \
             patch('WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler.api_utils.sse_format', side_effect=lambda d, f: f"sse: {d} format: {f}") as mock_sse_format, \
             patch('WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler.get_current_username', return_value='testuser-mocked') as mock_get_username:

            mock_prep_convo.return_value = [{"role": "user", "content": "Prepared"}]
            # Simulate POST raising an exception
            request_error = requests.exceptions.RequestException("Connection failed")
            self.mock_post.side_effect = request_error

            # Call handle_streaming without frontend_api_type
            result_generator = self.handler.handle_streaming(
                conversation=self.sample_conversation,
                current_username="test_user"
            )
            results = list(result_generator)

            # Assertions
            self.mock_post.assert_called_once()
            # Update assertion to expect api_type
            mock_build_json.assert_called_once_with(
                 token=f"Error communicating with OpenAI API: {request_error}",
                 api_type='openaichatcompletion', # Expect the correct type
                 finish_reason="stop",
                 current_username="testuser-mocked"
            )
            # Check that sse_format was called twice (once for error, once for DONE)
            self.assertEqual(mock_sse_format.call_count, 2)
            # Update assertion to expect the correct type
            expected_calls = [
                 call('{"error": "mocked"}', 'openaichatcompletion'),
                 call("[DONE]", 'openaichatcompletion')
            ]
            mock_sse_format.assert_has_calls(expected_calls)

            # Check the final yielded results (sse_format mock uses the type)
            self.assertEqual(results, [
                 'sse: {"error": "mocked"} format: openaichatcompletion',
                 'sse: [DONE] format: openaichatcompletion'
            ])

    @patch('requests.post')
    def test_handle_streaming_unexpected_exception(self, mock_post):
        """Test streaming handling of unexpected exceptions AFTER request starts."""
        mock_response = MagicMock()
        mock_response.iter_lines.return_value = iter([b'data: {"delta": {"content": "A"}}', b'invalid data']) # Simulate good then bad data
        mock_response.raise_for_status = MagicMock()
        self.mock_post.return_value = mock_response

        unexpected_error = ValueError("Simulated processing error")

        # Restore the patch for the utility function
        with patch('WilmerAI.Middleware.utilities.api_utils.handle_sse_and_json_stream') as mock_handle_stream_util, \
             patch('WilmerAI.Middleware.utilities.api_utils.logger') as mock_logger: # Patch logger too

            # Simulate the utility raising an error after yielding some data
            def side_effect(*args, **kwargs):
                yield 'data: {"id": "chatcmpl-test1", ..., "delta": {"content": "A"}, ...}\n\n'
                raise unexpected_error
            mock_handle_stream_util.side_effect = side_effect

            # Call handle_streaming
            result_generator = self.handler.handle_streaming(
                conversation=self.sample_conversation,
                current_username="test_user"
            )

            # Expect the first part, then the error message in the stream
            results = []
            try:
                for item in result_generator:
                    results.append(item)
            except ValueError as e:
                 self.fail(f"handle_streaming should yield error messages, not raise: {e}")


            # Check that the utility was called
            mock_handle_stream_util.assert_called_once_with(
                 response=mock_response,
                 extract_content_callback=ANY,
                 frontend_api_type='openaichatcompletion',
                 current_username='test_user',
                 strip_start_stop_line_breaks=True,
                 add_user_assistant=False,
                 add_missing_assistant=True
             )

            # Check results: should contain the first chunk and then the error message
            self.assertEqual(len(results), 2) # Should yield the good chunk and the error
            self.assertTrue('"content": "A"' in results[0])
            self.assertIn("Error during streaming", results[1]) # Check for generic error message
            self.assertIn("Simulated processing error", results[1]) # Check for specific error details

            # Verify error logging
            mock_logger.error.assert_called_once()
            self.assertIn("Error during streaming processing", mock_logger.error.call_args[0][0])

    def test_handle_non_streaming_retry_then_success(self): # Removed mock_sleep, mock_prep_convo args
        """Test non-streaming retry logic."""
        self.handler.stream = False
        mock_prep_convo_return = [{"role": "user", "content": "Prepared"}]

        # Simulate first failure, then success
        mock_fail_response = MagicMock(spec=requests.Response)
        mock_fail_response.status_code = 500
        mock_fail_response.raise_for_status.side_effect = requests.exceptions.HTTPError("Server Error")

        mock_success_response = MagicMock(spec=requests.Response)
        mock_success_response.status_code = 200
        mock_success_response.json.return_value = {
            "choices": [{"message": {"content": "Success!"}}]
        }
        mock_success_response.raise_for_status = MagicMock() # Ensure raise_for_status is mock

        # Make post return failure then success
        self.mock_post.side_effect = [
            mock_fail_response,
            mock_success_response
        ]

        result = None
        # Use internal with patch
        with patch('WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler.prep_corrected_conversation', return_value=mock_prep_convo_return) as mock_prep_convo_patch:
                 
            result = self.handler.handle_non_streaming(prompt="Test prompt")

            # Assertions (inside the with block)
            mock_prep_convo_patch.assert_called_once()
            self.assertEqual(self.mock_post.call_count, 2) # Called twice (1 fail, 1 success)
            # Ensure raise_for_status was called on both responses
            mock_fail_response.raise_for_status.assert_called_once()
            mock_success_response.raise_for_status.assert_called_once()
            self.assertEqual(result, "Success!")

    def test_handle_non_streaming_retry_limit_reached(self):
        """Test non-streaming raises exception after hitting retry limit."""
        with patch('WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler.prep_corrected_conversation') as mock_prep_convo, \
             patch('urllib3.util.retry.Retry.sleep', return_value=None) as mock_sleep:

            self.handler.stream = False
            mock_prep_convo.return_value = [{"role": "user", "content": "Prepared"}]

            # Simulate persistent failure
            mock_fail_response = MagicMock(spec=requests.Response)
            mock_fail_response.status_code = 500
            http_error = requests.exceptions.HTTPError("Server Error")
            mock_fail_response.raise_for_status.side_effect = http_error

            self.mock_post.return_value = mock_fail_response

            # Expect the original HTTPError to be raised after retries
            with self.assertRaises(requests.exceptions.HTTPError) as cm:
                self.handler.handle_non_streaming(prompt="Test prompt")

            # Assertions (outside inner with, using mocks from outer with)
            mock_prep_convo.assert_called_once()
            self.assertEqual(self.mock_post.call_count, 3) # Default retries = 3
            self.assertEqual(cm.exception, http_error) # Check if the correct exception is raised

    def test_init_raises_value_error_on_missing_config(self):
        """Test __init__ raises ValueError if api_type_config is missing or empty."""
        # --- GIVEN ---
        # Simulate get_api_type_config returning None or empty dict
        mock_endpoint_config = {'apiTypeConfigFileName': 'missing_config'}
        mock_gen_input = {}

        # Test case 1: api_type_config is None
        with self.assertRaises(ValueError) as cm1:
            # Patch get_current_username which might be called for error logging
            with patch('Middleware.utilities.config_utils.get_current_username', return_value="testuser"):
                 OpenAIApiChatImageSpecificHandler(
                     endpoint_config=mock_endpoint_config,
                     api_type_config=None, # Explicitly None
                     gen_input=mock_gen_input,
                     # Other required args...
                     stream=False, max_tokens=10, base_url='', model_name='', headers={}, strip_start_stop_line_breaks=False, api_key=''
                 )
        self.assertIn("API type configuration is missing or invalid.", str(cm1.exception))

        # Test case 2: api_type_config is empty dict
        with self.assertRaises(ValueError) as cm2:
            # Patch get_current_username which might be called for error logging
            with patch('Middleware.utilities.config_utils.get_current_username', return_value="testuser"):
                 OpenAIApiChatImageSpecificHandler(
                     endpoint_config=mock_endpoint_config,
                     api_type_config={}, # Explicitly empty
                     gen_input=mock_gen_input,
                     # Other required args...
                     stream=False, max_tokens=10, base_url='', model_name='', headers={}, strip_start_stop_line_breaks=False, api_key=''
                 )
        self.assertIn("API type configuration is missing or invalid.", str(cm2.exception))

    # === Tests for handle_non_streaming ===
    def test_handle_non_streaming_success(self): # Removed mock args
        """Test handle_non_streaming success path."""
        # --- GIVEN ---
        self.handler.stream = False # Ensure non-streaming mode
        mock_prepared_convo = [{"role": "user", "content": "Prepared non-streaming prompt"}]
        mock_response_content = "Assistant: Final Response Text"
        expected_final_text = "Final Response Text" # After prefix removal
        mock_response_json = {"choices": [{"message": {"content": mock_response_content}}]}
        
        # Mock the HTTP response
        mock_http_response = MagicMock(spec=requests.Response)
        mock_http_response.status_code = 200
        mock_http_response.json.return_value = mock_response_json
        mock_http_response.raise_for_status = MagicMock() # Mock raise_for_status
        self.mock_post.return_value = mock_http_response # Configure session mock

        # --- WHEN ---
        result = None
        with patch('WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler.prep_corrected_conversation', return_value=mock_prepared_convo) as mock_prep_convo_patch, \
             patch('WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler.api_utils.remove_assistant_prefix', return_value=expected_final_text) as mock_remove_prefix_patch:
                 
            result = self.handler.handle_non_streaming(prompt="Test non-streaming prompt")

        # --- THEN ---
        mock_prep_convo_patch.assert_called_once()
        self.mock_post.assert_called_once()
        call_args, call_kwargs = self.mock_post.call_args
        # Correctly get payload from 'json' kwarg, not 'data'
        posted_data = call_kwargs.get('json', {}) 
        self.assertEqual(posted_data.get('messages'), mock_prepared_convo)
        self.assertFalse(posted_data.get('stream')) # Stream should be false
        
        mock_http_response.raise_for_status.assert_called_once()
        mock_http_response.json.assert_called_once()
        mock_remove_prefix_patch.assert_called_once_with(mock_response_content)
        self.assertEqual(result, expected_final_text)


if __name__ == '__main__':
    unittest.main() 