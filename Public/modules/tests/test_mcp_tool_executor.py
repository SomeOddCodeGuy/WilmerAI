import json
import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import requests

# Adjust import paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../..")))

import WilmerAI.Public.modules.mcp_tool_executor as mcp_tool_executor

class TestMcpToolExecutor(unittest.TestCase):
    
    def setUp(self):
        # Sample messages for testing
        self.messages = [
            {"role": "system", "content": "You are a helpful assistant with access to MCP services: time, weather."},
            {"role": "user", "content": "What time is it?"},
            {"role": "assistant", "content": "Let me check the time for you."}
        ]
        
        # Sample tool call (using operationId format)
        self.tool_call = {
            "name": "get_current_time", # Assume operationId is now simpler
            "parameters": {
                "timezone": "UTC"
            }
        }
        
        # Sample OpenAPI schema info (how it might look in tool_execution_map)
        self.time_tool_details = {
             "service": "time",
             "path": "/current",
             "method": "get",
             "openapi_params": [
                 {"name": "timezone", "in": "query", "required": True, "schema": {"type": "string"}}
             ]
             # No request_body_schema for this GET request
        }

        # Mock response for time service
        self.time_response = {
            "current_time": "2023-07-22T14:30:00Z",
            "timezone": "UTC"
        }

    # Patch requests.request, as used by the refactored _perform_http_request
    @patch('requests.request')
    def test_execute_tool_call(self, mock_request):
        """Test executing a simple GET tool call with query parameter."""
        # Mock the response from the tool server
        mock_tool_response = MagicMock()
        mock_tool_response.status_code = 200 # Ensure success status
        mock_tool_response.json.return_value = self.time_response
        mock_request.return_value = mock_tool_response
        
        # Construct the tool_execution_map using details from setUp
        tool_execution_map = {
            self.tool_call["name"]: self.time_tool_details
        }

        mcpo_url = "http://localhost:8889"

        # Call the function with the correct map structure
        result = mcp_tool_executor.execute_tool_call(self.tool_call, mcpo_url, tool_execution_map)
        
        # --- Assertions --- 
        
        # 1. Verify the actual API call made via requests.request
        expected_url = f"{mcpo_url}/{self.time_tool_details['service']}{self.time_tool_details['path']}"
        mock_request.assert_called_once_with(
            method="get",                     # Use keyword arg
            url=expected_url,              # Use keyword arg
            params=self.tool_call['parameters'], # query parameters for GET
            json=None,                      # Check for json=None
            timeout=15                 # Default timeout
        )
        
        # 2. Verify the final result returned by the function matches the mocked API response
        self.assertEqual(result, self.time_response)

    @patch('WilmerAI.Public.modules.mcp_tool_executor.execute_tool_call')
    @patch('WilmerAI.Public.modules.mcp_tool_executor.extract_tool_calls')
    def test_invoke_with_tool_call(self, mock_extract, mock_execute):
        # Setup mocks
        # Use the updated tool call name from setUp
        tool_call_json = {"name": self.tool_call["name"], "parameters": self.tool_call["parameters"]}
        mock_extract.return_value = [tool_call_json] # Simulate extraction
        mock_execute.return_value = self.time_response
        
        # Add assistant message with tool call
        messages = self.messages.copy()
        # Ensure the assistant message actually contains the required JSON structure
        messages.append({
            "role": "assistant", 
            "content": f'```json\n{{"tool_calls": [{json.dumps(tool_call_json)}]}}\n```'
        })
        
        # Call the function, providing the required tool_execution_map
        # The specific map content doesn't matter here as execute_tool_call is mocked
        dummy_tool_map = {self.tool_call["name"]: {"service": "mock"}}
        result = mcp_tool_executor.Invoke(messages, tool_execution_map=dummy_tool_map)
        
        # Assertions
        self.assertTrue(result["has_tool_call"])
        self.assertEqual(len(result["tool_results"]), 1)
        self.assertEqual(result["tool_results"][0]["result"], self.time_response)
        
        # Verify mocks were called
        mock_extract.assert_called_once()
        # Assert execute_tool_call was called with the extracted tool_call and the dummy map
        mock_execute.assert_called_once_with(tool_call_json, mcp_tool_executor.DEFAULT_MCPO_URL, dummy_tool_map)

    @patch('WilmerAI.Public.modules.mcp_tool_executor.extract_tool_calls')
    def test_invoke_with_no_tool_call(self, mock_extract):
        # Setup mock to return no tool calls
        mock_extract.return_value = []
        
        # Call the function - tool_execution_map is not strictly needed if no calls found
        result = mcp_tool_executor.Invoke(self.messages, tool_execution_map={})
        
        # Assertions
        self.assertFalse(result["has_tool_call"])
        self.assertNotIn("tool_results", result)
        # Ensure the original assistant message (if any) is returned
        self.assertEqual(result.get("response"), "Let me check the time for you.")
        
        # Verify mock was called
        mock_extract.assert_called_once()

    def test_extract_tool_calls_tool_calls_format(self):
        # Test with tool_calls format
        tool_call_data = {"name": "get_current_time", "parameters": {"timezone": "UTC"}}
        content = f'```json\n{{"tool_calls": [{json.dumps(tool_call_data)}]}}\n```'
        
        tool_calls = mcp_tool_executor.extract_tool_calls(content)
        
        # Assert that the function extracts one tool call for this format
        self.assertEqual(len(tool_calls), 1)
        self.assertEqual(tool_calls[0]["name"], tool_call_data["name"])
        self.assertEqual(tool_calls[0]["parameters"], tool_call_data["parameters"])

    def test_extract_tool_calls_with_unsubstituted_variables(self):
        """Test that unsubstituted variables are handled gracefully (returns empty)"""
        # Test with unsubstituted Jinja2 variables
        content = '{"tool_calls": [{"name": "{{ tool_name }}", "parameters": {"timezone": "{{ timezone }}"}}]}'
        tool_calls = mcp_tool_executor.extract_tool_calls(content)
        
        # Updated behavior: The function returns the call with variables intact.
        self.assertEqual(len(tool_calls), 1)
        self.assertEqual(tool_calls[0]["name"], "{{ tool_name }}")
        self.assertEqual(tool_calls[0]["parameters"], {"timezone": "{{ timezone }}"})

    def test_extract_tool_calls_with_malformed_json(self):
        """Test that malformed JSON is handled gracefully (returns empty)"""
        test_cases = [
            # Case 1: Missing closing brace
            '{"tool_calls": [{"name": "test"',
            # Case 2: Invalid JSON structure
            '[{ "system", Available Tools: [|{{|"type": "function"...',
            # Case 3: Mixed quotes (json.loads handles this)
            # Case 4: Invalid tool call format inside list
            '{"tool_calls": ["not_a_dict"]}',
            # Case 5: Not a JSON object
            '[1, 2, 3]'
        ]
        for content in test_cases:
             with self.subTest(content=content):
                 tool_calls = mcp_tool_executor.extract_tool_calls(content)
                 self.assertEqual(len(tool_calls), 0)

    def test_validate_tool_call_format(self):
        """Test the basic format validation for tool calls."""
        valid_call = {"name": "tool_abc", "parameters": {"p1": "v1"}}
        invalid_calls = [
            None,
            [],
            {"parameters": {}}, # Missing name
            {"name": "", "parameters": {}}, # Empty name
            {"name": "tool_abc"}, # Missing parameters
            {"name": "tool_abc", "parameters": []} # Parameters not a dict
        ]
        
        self.assertTrue(mcp_tool_executor.validate_tool_call_format(valid_call))
        for call in invalid_calls:
            with self.subTest(call=call):
                 self.assertFalse(mcp_tool_executor.validate_tool_call_format(call))

    # Patch requests.request, as used by the refactored _perform_http_request
    @patch('requests.request')
    def test_execute_tool_call_post_missing_request_body_schema(self, mock_request):
        """Test POST fails gracefully (sends body=None) if map lacks request_body_schema."""
        # --- Mock Setup ---
        # Mock a 422 error like in the logs to fully simulate
        mock_response = MagicMock()
        mock_response.status_code = 422
        mock_response.reason = "Unprocessable Entity"
        mock_response.text = '{"detail":[{"type":"missing","loc":["body"],"msg":"Field required","input":null}]}'
        # Configure raise_for_status to raise an HTTPError similar to requests
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "422 Client Error: Unprocessable Entity for url: ...", response=mock_response
        )
        mock_request.return_value = mock_response

        mcpo_url = "http://localhost:8889"
        tool_call = {
            "name": "submit_data",
            "parameters": {"data": "some_value", "id": 123} # Params intended for body
        }
        # CRITICAL: Define the map entry *without* request_body_schema
        tool_execution_map = {
            "submit_data": {
                "service": "data_processor",
                "path": "/submit",
                "method": "post"
                # "request_body_schema": {"type": "object"}, # <-- This is missing!
                # "openapi_params": [] # Assume no query/path params
            }
        }

        # --- Call ---
        result = mcp_tool_executor.execute_tool_call(tool_call, mcpo_url, tool_execution_map)

        # --- Assertions ---
        # 1. Verify the HTTP call was made with body=None (json=None)
        expected_url = f"{mcpo_url}/{tool_execution_map['submit_data']['service']}{tool_execution_map['submit_data']['path']}"
        mock_request.assert_called_once_with(
            method="post",
            url=expected_url,
            params={}, # No query params defined
            json=None, # <--- Assert body is None
            timeout=15
        )

        # 2. Verify an error response was returned due to the 422 from the server
        self.assertIn("error", result)
        self.assertEqual(result["status"], "error")
        # Make the assertion less brittle: Check if the expected error prefix is present
        expected_error_prefix = "Tool execution failed: 422 Client Error: Unprocessable Entity for url:"
        self.assertTrue(
            result["error"].startswith(expected_error_prefix),
            f"Error message '{result['error']}' does not start with expected prefix '{expected_error_prefix}'"
        )
        self.assertIn("Field required", result["error"]) # Check for the server detail

    def test_prepare_request_params_post_with_body_schema(self):
        """
        Test _prepare_request_params correctly assigns remaining params to body
        when request_body_schema is present in execution_details for POST.
        """
        # LLM parameters, all intended for the request body
        parameters = {
            "query": "search term",
            "search_depth": "advanced",
            "max_results": 5
        }
        
        # Execution details indicating a POST request with a defined body schema
        # and no query/path/header/cookie parameters defined in openapi_params
        execution_details = {
            "service": "search_service",
            "path": "/search",
            "method": "post",
            "request_body_schema": { # Key indicating body is expected
                "type": "object",
                "properties": { # Schema might define expected body props
                     "query": {"type": "string"},
                     "search_depth": {"type": "string"},
                     "max_results": {"type": "integer"}
                     # Schema might differ slightly, but its presence matters
                 }
            },
            "openapi_params": [] # No query/path/etc. parameters defined
        }
        
        # Call the function under test
        query_params, body_params, path_params = mcp_tool_executor._prepare_request_params(
            parameters, execution_details
        )
        
        # Assertions
        self.assertEqual(query_params, {}, "Query parameters should be empty")
        self.assertEqual(path_params, {}, "Path parameters should be empty")
        self.assertIsNotNone(body_params, "Body parameters should not be None")
        self.assertEqual(body_params, parameters, "Body parameters should contain all original LLM parameters")

if __name__ == '__main__':
    unittest.main() 