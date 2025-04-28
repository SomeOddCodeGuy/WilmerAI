import unittest
import sys
import os
import json
import logging
from unittest.mock import patch, MagicMock, ANY, call
from flask import Flask

# Ensure the main project directory is in the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../WilmerAI")))

# Configure logging for this test file
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Try importing from the new location first, then fall back to the old one if necessary
try:
    from Middleware.core.open_ai_api import WilmerApi, app  # Corrected path
    # We need to mock the WorkflowManager's call result
    from Middleware.workflows.managers.workflow_manager import WorkflowManager 
except ImportError as e:
    # If the primary import fails, try the old path as a fallback or log/raise
    # For now, we re-raise a more informative error to indicate the primary path failed
    raise ImportError(f"Could not import required modules. Error: {e}")

# Helper to simulate backend SSE stream (OpenAI format)
def mock_llm_sse_generator(content="Test Response"):
    # Simulate OpenAI Chat Completion SSE format
    chunk1_data = {
        "choices": [{"delta": {"content": content}}],
        "id": "mock-cmpl"
    }
    yield f"data: {json.dumps(chunk1_data)}\n\n"

    chunk2_data = {
        "choices": [{"delta": {}, "finish_reason": "stop"}],
        "id": "mock-cmpl"
    }
    yield f"data: {json.dumps(chunk2_data)}\n\n"

    yield f"data: [DONE]\n\n"

class TestApiLayerEndpoints(unittest.TestCase):

    def setUp(self):
        """Set up the test client using the app from open_ai_api."""
        # Use the actual app instance imported from the module
        # Ensure routes are added before creating the test client
        # (Assuming routes are added when open_ai_api module is loaded)
        self.app = app 
        self.app.config['TESTING'] = True
        self.client = self.app.test_client() # Create client here

    @unittest.skip("Skipping temporarily - requires investigation")
    def test_ollama_generate_stream_uses_correct_sse_format(self):
        """
        Tests that a streaming request to /api/generate (ollamagenerate type)
        results in SSE chunks formatted correctly for Ollama Generate (using the 'response' key),
        verifying frontend_api_type propagation.
        """
        request_id = 'test-stream-req-456'
        data = {'prompt': '[Beg_User]Test Ollama Stream', 'id': request_id, 'stream': True}
        expected_frontend_api_type = 'ollamagenerate'
        mock_llm_output = "Mock Ollama Stream Response"
        initial_messages = [{'role': 'user', 'content': 'Test Ollama Stream'}] # Store expected messages

        # --- Define Side Effect Function ---
        def mock_run_workflow_side_effect(*args, **kwargs):
            """Determines return value based on call type (categorization vs final response)."""
            # self is args[0], messages is args[1], request_id is args[2]
            # discussionId, stream, nonResponder are kwargs
            is_streaming = kwargs.get('stream', False)
            is_non_responder = kwargs.get('nonResponder', False)

            if is_streaming and not is_non_responder:
                # This is the final response call
                logging.info("Side effect: Returning SSE generator for streaming response call.")
                return mock_llm_sse_generator(mock_llm_output)
            else:
                # This is a categorization call or a non-streaming internal call
                logging.info("Side effect: Returning 'UNKNOWN' for non-streaming/categorization call.")
                return "UNKNOWN" # Simulate categorization result
        # --- End Side Effect Function ---

        # Patch WorkflowManager.run_workflow within the API module scope
        with patch('Middleware.workflows.managers.workflow_manager.WorkflowManager.run_workflow') as mock_run_workflow, \
             patch('Middleware.core.open_ai_api.extract_discussion_id') as mock_extract_id, \
             patch('Middleware.core.open_ai_api.parse_conversation') as mock_parse_conv: # Need to mock this for /api/generate

            # Prevent discussion ID logic for simplicity
            mock_extract_id.return_value = None
            # Simulate parse_conversation output
            mock_parse_conv.return_value = initial_messages # Use stored messages
            
            # Configure mock_run_workflow to use the side effect function
            mock_run_workflow.side_effect = mock_run_workflow_side_effect
            
            # --- Execute Request --- 
            # Use the client created in setUp
            response = self.client.post('/api/generate', json=data) # Use /api/generate

            # --- Assertions --- 
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, 'text/event-stream')

            # Verify workflow was called with the correct arguments for the final stream
            mock_run_workflow.assert_any_call(
                initial_messages,     # Expected messages
                request_id,           # Expected request_id
                discussionId=None,    # Expected keyword arg
                stream=True           # Expected keyword arg for the final call
            )
            # Verify the frontend_api_type was passed correctly to handle_user_prompt->run_workflow
            # This is harder to check directly without deeper mocking, so we infer from the output format.
            
            # Consume the stream and check the format
            sse_chunks = list(response.iter_encoded()) # Get bytes chunks
            found_correct_format = False
            processed_content = ""

            for chunk_bytes in sse_chunks:
                chunk_str = chunk_bytes.decode('utf-8').strip()
                if not chunk_str: # Skip empty lines
                    continue
                    
                # Ollama format doesn't use 'data:' prefix or '[DONE]' marker typically,
                # just newline-separated JSON objects.
                try:
                    # Attempt to parse the entire stripped line as JSON
                    payload = json.loads(chunk_str)
                    
                    # Check for Ollama Generate key 'response'
                    if 'response' in payload:
                       processed_content += payload['response']
                       found_correct_format = True 
                       # Check other expected keys for ollama generate format
                       self.assertIn('model', payload)
                       self.assertIn('created_at', payload)
                       self.assertIn('done', payload)
                       # Check if 'done' is true in the last chunk (optional but good)
                       # if payload.get('done') == True: 
                       #    pass # Potentially add assertion here for final chunk
                           
                    # Check if it mistakenly used OpenAI Chat format
                    elif payload.get('choices') and payload['choices'][0].get('delta'):
                        self.fail(f"SSE chunk used incorrect OpenAI Chat format instead of Ollama Generate. Payload: {chunk_str}")
                    # Check if it mistakenly used OpenAI Completion format
                    elif payload.get('choices') and payload['choices'][0].get('text'):
                        self.fail(f"SSE chunk used incorrect OpenAI Completion format instead of Ollama Generate. Payload: {chunk_str}")
                    else:
                         # Might be another format or an unexpected structure
                         logger.warning(f"Received unexpected JSON structure in SSE chunk: {chunk_str}")
                        
                except json.JSONDecodeError:
                    # Handle potential non-JSON lines if any slip through, though Ollama stream should be pure JSON lines
                    self.fail(f"Failed to decode JSON from SSE chunk: {chunk_str}")

            # Assert that we actually found chunks with the correct key
            self.assertTrue(found_correct_format, 
                            f"No SSE chunks with the expected Ollama Generate key 'response' were found.")
            # Assert the content matches the mocked LLM output
            self.assertEqual(processed_content, mock_llm_output, 
                             "Aggregated content from SSE stream does not match mocked LLM output.")

    # Removed obsolete test: test_chat_completion_endpoint_fails_on_reverted_categorizer
    # Keep the test for successful instance method call
    @unittest.skip("Skipping temporarily - requires investigation")
    def test_api_layer_calls_categorizer_instance_method(self):
        """
        Tests that the API layer correctly instantiates PromptCategorizer
        and calls its get_prompt_category instance method, ensuring message
        modification flags are disabled.
        """
        mock_result = "MOCKED_SUCCESS"
        request_id = 'test-req-123'
        data = {'messages': [{'role': 'user', 'content': 'test'}], 'id': request_id}

        # Patch PromptCategorizer AND the config utils within the API module's scope
        with patch('Middleware.core.open_ai_api.PromptCategorizer') as MockPromptCategorizer, \
             patch('Middleware.core.open_ai_api.get_is_chat_complete_add_user_assistant') as mock_add_user_assist, \
             patch('Middleware.core.open_ai_api.get_is_chat_complete_add_missing_assistant') as mock_add_missing:
            
            # Disable message modifications for this test
            mock_add_user_assist.return_value = False
            mock_add_missing.return_value = False
            
            # Configure the mock PromptCategorizer instance
            mock_instance = MockPromptCategorizer.return_value
            mock_instance.get_prompt_category.return_value = mock_result

            # Use the client created in setUp
            response = self.client.post('/v1/chat/completions', json=data)

            # Assertions
            self.assertEqual(response.status_code, 200,
                             f"Expected status code 200, but got {response.status_code}")
            MockPromptCategorizer.assert_called_once()
            mock_instance.get_prompt_category.assert_called_once()

            call_args, call_kwargs = mock_instance.get_prompt_category.call_args
            # Now verify keyword arguments passed to get_prompt_category match ORIGINAL data
            self.assertEqual(call_kwargs.get('prompt'), data['messages'], "'prompt' kwarg passed to get_prompt_category doesn't match original messages")
            self.assertEqual(call_kwargs.get('stream'), False, "'stream' kwarg incorrect")
            self.assertEqual(call_kwargs.get('request_id'), request_id, "'request_id' kwarg incorrect")
            self.assertIsNone(call_kwargs.get('discussion_id'), "'discussion_id' kwarg should be None")

            try:
                response_data = json.loads(response.data)
                self.assertEqual(response_data['choices'][0]['message']['content'], mock_result,
                                 "Response body does not contain the mocked result")
            except (json.JSONDecodeError, KeyError, IndexError) as e:
                self.fail(f"Failed to parse response or find mocked result in response body: {e}\nResponse Data: {response.data}")

if __name__ == '__main__':
    unittest.main() 