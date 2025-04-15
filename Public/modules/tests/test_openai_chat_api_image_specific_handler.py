import unittest
import sys
import os
import base64
from unittest.mock import patch, MagicMock, call, ANY

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

    @patch('os.path.exists')
    @patch('builtins.open')
    def test_convert_to_data_uri(self, mock_open, mock_exists):
        mock_exists.return_value = True
        # Mock reading binary data and base64 encoding
        mock_file = MagicMock()
        mock_file.read.return_value = b'\x89PNG\r\n\x1a\n' # Sample PNG header
        mock_open.return_value.__enter__.return_value = mock_file

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

    @patch('WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler.convert_to_data_uri')
    def test_file_url(self, mock_convert):
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

    @patch('WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler.convert_to_data_uri')
    def test_file_url_conversion_error(self, mock_convert):
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
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": [
                {"type": "text", "text": "Please describe the image(s)."},
                {"type": "image_url", "image_url": {"url": "http://example.com/image.jpg"}}
            ]}
        ]
        self.assertEqual(result, expected)

    @patch('WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler.convert_to_data_uri')
    def test_integration_mixed_content(self, mock_convert):
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
            # You might need to return a valid data URI for other paths if the test needs it
            # but for this specific test case, returning None might be sufficient if only the error path is hit.
            return None 

        def run_test(mock_convert_inner):
            # Configure the mock to raise an error for the specific file path
            mock_convert_inner.side_effect = mock_side_effect # Use the function that raises
            
            conversation = [
                {"role": "user", "content": "Message 1"},
                {"role": "assistant", "content": "Response 1"},
                {"role": "user", "content": "Look at all these"},
                {"role": "images", "content": f"{b64_string} {raw_b64} {file_url} {http_url}"},
                {"role": "images", "content": f"{https_url} {invalid_url}"} # Separate images message
            ]
            result = prep_corrected_conversation(conversation, "System prompt", None)

            # Recalculate expected content based on verified rules
            expected_final_user_content_refined = [
                {"type": "text", "text": "Look at all these"},
                {"type": "image_url", "image_url": {"url": b64_string}},
                {"type": "image_url", "image_url": {"url": expected_raw_uri}},
                # File URL conversion error -> SKIPPED
                {"type": "image_url", "image_url": {"url": http_url}}, # http stays http
                {"type": "image_url", "image_url": {"url": https_url}}
                # Invalid URL -> SKIPPED
            ]

            expected_conversation = [
                {"role": "user", "content": "Message 1"},
                {"role": "assistant", "content": "Response 1"},
                {"role": "user", "content": expected_final_user_content_refined},
                {"role": "system", "content": "System prompt"}
            ]

            # Need to sort by role for comparison as system prompt might be added differently
            # Let's check the content directly instead of full list comparison due to insertion order
            self.assertEqual(len(result), 4) # user, assistant, user_with_images, system
            self.assertEqual(result[0], {"role": "user", "content": "Message 1"})
            self.assertEqual(result[1], {"role": "assistant", "content": "Response 1"})
            self.assertEqual(result[2]["role"], "user")
            # Compare content list items individually
            self.assertCountEqual(result[2]["content"], expected_final_user_content_refined)
            self.assertEqual(result[3], {"role": "system", "content": "System prompt"})

            # Ensure convert_to_data_uri was called for the file URL before it failed
            mock_convert_inner.assert_called_once_with("/tmp/test.gif")

        run_test(mock_convert)


# --- Tests for Handler Methods (will be added later) ---

class TestOpenAIApiChatImageSpecificHandlerMethods(unittest.TestCase):

    # Mock config functions at the class level
    @patch('Middleware.utilities.config_utils.get_api_type_config')
    @patch('Middleware.utilities.config_utils.get_current_username', return_value="testuser") # Needed for error formatting
    def setUp(self, mock_get_current_username, mock_get_api_type_config):
        """Set up a handler instance for testing."""
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
        # Mock the requests session used by the handler
        self.handler.session = MagicMock(spec=requests.Session)
        self.mock_post = self.handler.session.post


    @patch('WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler.prep_corrected_conversation')
    @patch('WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler.handle_sse_and_json_stream')
    def test_handle_streaming_success(self, mock_handle_stream_util, mock_prep_convo):
        """Test successful streaming using the utility function."""
        mock_prep_convo.return_value = [{"role": "user", "content": "Prepared message"}]
        # Simulate the utility function yielding SSE formatted strings
        mock_handle_stream_util.return_value = iter([
            'data: {"id":"1","choices":[{"delta":{"content":"Hello"}}]}',
            'data: {"id":"1","choices":[{"delta":{"content":" world"}}]}',
            'data: {"id":"1","choices":[{"delta":{}, "finish_reason":"stop"}]}', 
            'data: [DONE]'
        ])

        # Mock the response object the utility function expects
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        # mock_response.__iter__.return_value = iter([]) # <-- Reverted
        self.mock_post.return_value.__enter__.return_value = mock_response # Simulate context manager

        # Call the method
        result_generator = self.handler.handle_streaming(prompt="Test prompt")
        results = list(result_generator)

        # Assertions
        mock_prep_convo.assert_called_once_with(None, None, "Test prompt")
        self.mock_post.assert_called_once() # Check that POST was called
        args, kwargs = self.mock_post.call_args
        self.assertEqual(args[0], "http://mock-openai.com/v1/chat/completions")
        self.assertTrue(kwargs['json']['stream'])
        self.assertEqual(kwargs['json']['messages'], [{"role": "user", "content": "Prepared message"}])

        # Check that the utility was called correctly
        mock_handle_stream_util.assert_called_once()
        call_args, call_kwargs = mock_handle_stream_util.call_args
        self.assertEqual(call_kwargs['response'], mock_response)
        self.assertTrue(callable(call_kwargs['extract_content_callback']))
        self.assertEqual(call_kwargs['output_format'], 'openai')
        self.assertEqual(call_kwargs['strip_start_stop_line_breaks'], True)

        # Check that the yielded results are exactly what the utility returned
        self.assertEqual(results, [
            'data: {"id":"1","choices":[{"delta":{"content":"Hello"}}]}',
            'data: {"id":"1","choices":[{"delta":{"content":" world"}}]}',
            'data: {"id":"1","choices":[{"delta":{}, "finish_reason":"stop"}]}',
            'data: [DONE]'
        ])
        mock_response.raise_for_status.assert_called_once() # Make sure status check happened

    @patch('WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler.prep_corrected_conversation')
    @patch('WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler.api_utils.build_response_json', return_value='{\"error\": \"mocked\"}')
    @patch('WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler.api_utils.sse_format', side_effect=lambda d, f: f"sse: {d} format: {f}")
    @patch('WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler.get_current_username', return_value='testuser-mocked')
    def test_handle_streaming_request_exception(self, mock_get_username, mock_sse_format, mock_build_json, mock_prep_convo):
        """Test streaming handling of requests.RequestException."""
        mock_prep_convo.return_value = [{"role": "user", "content": "Prepared"}]
        # Simulate POST raising an exception
        request_error = requests.exceptions.RequestException("Connection failed")
        self.mock_post.side_effect = request_error

        result_generator = self.handler.handle_streaming(prompt="Test prompt")
        results = list(result_generator)

        # Assertions
        self.mock_post.assert_called_once()
        mock_build_json.assert_called_once_with(
             token=f"Error communicating with OpenAI API: {request_error}",
             finish_reason="stop",
             current_username="testuser-mocked"
        )
        # Check that sse_format was called twice (once for error, once for DONE)
        self.assertEqual(mock_sse_format.call_count, 2)
        expected_calls = [
             call('{\"error\": \"mocked\"}', 'openai'),
             call("[DONE]", 'openai')
        ]
        mock_sse_format.assert_has_calls(expected_calls)

        # Check the final yielded results
        self.assertEqual(results, [
             'sse: {\"error\": \"mocked\"} format: openai',
             'sse: [DONE] format: openai'
        ])

    @patch('WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler.prep_corrected_conversation')
    @patch('WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler.handle_sse_and_json_stream')
    @patch('WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler.api_utils.build_response_json', return_value='{\"error\": \"unexpected\"}')
    @patch('WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler.api_utils.sse_format', side_effect=lambda d, f: f"sse: {d} format: {f}")
    @patch('WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler.get_current_username', return_value='testuser-mocked')
    def test_handle_streaming_unexpected_exception(self, mock_get_username, mock_sse_format, mock_build_json, mock_handle_stream_util, mock_prep_convo):
        """Test streaming handling of unexpected exceptions AFTER request starts."""
        mock_prep_convo.return_value = [{"role": "user", "content": "Prepared"}]
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        # mock_response.__iter__.return_value = iter([]) # <-- Reverted
        self.mock_post.return_value.__enter__.return_value = mock_response

        # Simulate the utility function raising an unexpected error
        unexpected_error = ValueError("Something broke inside stream")
        mock_handle_stream_util.side_effect = unexpected_error

        result_generator = self.handler.handle_streaming(prompt="Test prompt")
        results = list(result_generator)

        # Assertions
        self.mock_post.assert_called_once()
        mock_handle_stream_util.assert_called_once() # Called once before it raises error
        mock_build_json.assert_called_once_with(
             token=f"An unexpected error occurred: {unexpected_error}",
             finish_reason="stop",
             current_username="testuser-mocked"
        )
        # Check that sse_format was called twice (error + DONE)
        self.assertEqual(mock_sse_format.call_count, 2)
        expected_calls = [
             call('{\"error\": \"unexpected\"}', 'openai'),
             call("[DONE]", 'openai')
        ]
        mock_sse_format.assert_has_calls(expected_calls)

        self.assertEqual(results, [
             'sse: {\"error\": \"unexpected\"} format: openai',
             'sse: [DONE] format: openai'
        ])


    @patch('WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler.prep_corrected_conversation')
    @patch('WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler.api_utils.remove_assistant_prefix')
    def test_handle_non_streaming_success(self, mock_remove_prefix, mock_prep_convo):
        """Test successful non-streaming call."""
        mock_remove_prefix.return_value = "Hello there!"
        self.handler.stream = False
        mock_prep_convo.return_value = [{"role": "user", "content": "Prepared message"}]

        # Simulate successful API response - CORRECT STRUCTURE
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "chatcmpl-123",
            "object": "chat.completion",
            "created": 1677652288,
            "model": "gpt-4-vision-preview",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "\n\n Assistant: Hello there!" # Content is here
                },
                "finish_reason": "stop"
            }],
            "usage": {"prompt_tokens": 9, "completion_tokens": 12, "total_tokens": 21}
        }
        self.mock_post.return_value = mock_response

        result = self.handler.handle_non_streaming(prompt="Test prompt")

        # Assertions
        mock_prep_convo.assert_called_once_with(None, None, "Test prompt")
        self.mock_post.assert_called_once()
        args, kwargs = self.mock_post.call_args
        self.assertEqual(args[0], "http://mock-openai.com/v1/chat/completions")
        self.assertFalse(kwargs['json']['stream']) # stream=False
        self.assertEqual(kwargs['json']['messages'], [{"role": "user", "content": "Prepared message"}])
        mock_response.raise_for_status.assert_called_once()
        # Assert call with the string *after* lstrip() would have been applied
        mock_remove_prefix.assert_called_once_with("Assistant: Hello there!")
        self.assertEqual(result, "Hello there!") # Check result matches mock return

    @patch('WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler.prep_corrected_conversation')
    @patch('time.sleep', return_value=None) # Mock sleep to speed up test
    def test_handle_non_streaming_retry_then_success(self, mock_sleep, mock_prep_convo):
        """Test non-streaming retry logic."""
        self.handler.stream = False
        mock_prep_convo.return_value = [{"role": "user", "content": "Prepared"}]

        # Simulate first failure, then success
        mock_fail_response = MagicMock(spec=requests.Response)
        mock_fail_response.status_code = 500
        mock_fail_response.raise_for_status.side_effect = requests.exceptions.HTTPError("Server Error")

        mock_success_response = MagicMock(spec=requests.Response)
        mock_success_response.status_code = 200
        mock_success_response.json.return_value = {
            "choices": [{"message": {"content": "Success!"}}]
        }

        # Make post return failure then success
        self.mock_post.side_effect = [
            mock_fail_response,
            mock_success_response
        ]

        result = self.handler.handle_non_streaming(prompt="Test prompt")

        # Assertions
        self.assertEqual(self.mock_post.call_count, 2) # Called twice (1 fail, 1 success)
        # Ensure raise_for_status was called on both responses
        mock_fail_response.raise_for_status.assert_called_once()
        mock_success_response.raise_for_status.assert_called_once()
        self.assertEqual(result, "Success!")

    @patch('WilmerAI.Middleware.llmapis.openai_chat_api_image_specific_handler.prep_corrected_conversation')
    @patch('time.sleep', return_value=None)
    def test_handle_non_streaming_retry_limit_reached(self, mock_sleep, mock_prep_convo):
        """Test non-streaming raises exception after hitting retry limit."""
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

        self.assertEqual(self.mock_post.call_count, 3) # Default retries = 3
        self.assertEqual(cm.exception, http_error) # Check if the correct exception is raised


if __name__ == '__main__':
    unittest.main() 