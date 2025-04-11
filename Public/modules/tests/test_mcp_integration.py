import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock, mock_open
import requests
import ast
import re

# Add the parent directory to sys.path to import the modules
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

import mcp_tool_executor
import mcp_workflow_integration
import ensure_system_prompt # Import the module we now need to test
from mcp_service_discoverer import MCPServiceDiscoverer
from mcp_workflow_integration import MCPConfigurationError

class TestMCPToolExecutor(unittest.TestCase):
    """Tests for mcp_tool_executor.py functions that remain"""
    
    def setUp(self):
        """Set up common variables for tests."""
        self.mcpo_url = "http://localhost:8889"

    def test_extract_tool_calls_valid_json(self):
        """Test extracting tool calls from a valid JSON string"""
        # Valid tool calls JSON
        json_text = '''```json
        {
            "tool_calls": [
                {
                    "name": "get_time",
                    "parameters": {
                        "timezone": "UTC"
                    }
                }
            ]
        }
        ```'''
        
        result = mcp_tool_executor.extract_tool_calls(json_text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "get_time")
        self.assertEqual(result[0]["parameters"]["timezone"], "UTC")
    
    def test_extract_tool_calls_no_code_fence(self):
        """Test extracting tool calls from JSON without code fence"""
        json_text = '''{
            "tool_calls": [
                {
                    "name": "get_time",
                    "parameters": {
                        "timezone": "UTC"
                    }
                }
            ]
        }'''
        
        result = mcp_tool_executor.extract_tool_calls(json_text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "get_time")
    
    def test_extract_tool_calls_invalid_json(self):
        """Test extracting tool calls from invalid JSON"""
        json_text = '''This is not JSON at all'''
        result = mcp_tool_executor.extract_tool_calls(json_text)
        self.assertEqual(result, [])
    
    def test_extract_tool_calls_malformed_structure(self):
        """Test extracting tool calls from JSON with incorrect structure"""
        json_text = '''{
            "not_tool_calls": []
        }'''
        result = mcp_tool_executor.extract_tool_calls(json_text)
        self.assertEqual(result, [])
    
    def test_extract_tool_calls_json_embedded_in_text(self):
        """Test extracting tool calls when JSON is embedded within surrounding text"""
        # Input text with JSON embedded but not in a markdown fence
        text_with_embedded_json = """Okay, I will use the tool now.
        {
            "tool_calls": [
                {
                    "name": "search_docs",
                    "parameters": {
                        "query": "latest updates"
                    }
                }
            ]
        }
        Let me know if you need anything else."""

        # Expected result (what it *should* return if robust)
        expected_calls = [
            {
                "name": "search_docs",
                "parameters": {
                    "query": "latest updates"
                }
            }
        ]
        
        # Current hypothesized behavior: Will likely return []
        result = mcp_tool_executor.extract_tool_calls(text_with_embedded_json)
        
        # This assertion will currently FAIL, demonstrating the issue
        self.assertEqual(result, expected_calls, "Function failed to extract JSON embedded directly in text")

    def test_extract_tool_calls_json_embedded_no_fence(self):
        """Test extracting tool calls when JSON is embedded directly in text without markdown"""
        # Input text with JSON embedded but not in a markdown fence, with text before and after
        text_with_embedded_json = """Okay, I will use the tool now. Here is the call:
        {
            "tool_calls": [
                {
                    "name": "search_docs",
                    "parameters": {
                        "query": "latest updates"
                    }
                }
            ]
        }
        Let me know if you need anything else."""

        expected_calls = [
            {
                "name": "search_docs",
                "parameters": {
                    "query": "latest updates"
                }
            }
        ]

        result = mcp_tool_executor.extract_tool_calls(text_with_embedded_json)
        # This assertion is expected to fail with the current implementation
        self.assertEqual(result, expected_calls, "Function failed to extract JSON embedded directly in text without markdown fences")

    @patch('requests.request')
    def test_execute_tool_call(self, mock_request):
        """Test executing tool calls with GET (query params) and POST (body params)."""
        mcpo_url = self.mcpo_url

        # --- Mock successful response --- 
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"result": "success"}
        mock_request.return_value = mock_response

        # --- Test GET request with Query Parameters --- 
        get_tool_call = {
            "name": "get_time_query",
            "parameters": {"timezone": "UTC", "format": "iso"}
        }
        get_tool_execution_map = {
            "get_time_query": {
                "service": "time",
                "path": "/current",
                "method": "get",
                "openapi_params": [ # Indicate parameters are in the query
                    {"name": "timezone", "in": "query"},
                    {"name": "format", "in": "query"}
                ]
            }
        }

        result_get = mcp_tool_executor.execute_tool_call(get_tool_call, mcpo_url, get_tool_execution_map)

        # Verify GET request was made correctly via requests.request
        mock_request.assert_any_call(
            method="get", # Use keyword arg
            url=f"{mcpo_url}/time/current", # Use keyword arg
            params={"timezone": "UTC", "format": "iso"},
            json=None, # Explicitly check for json=None if it's always passed
            timeout=15
        )
        self.assertEqual(result_get, {"result": "success"})

        # --- Reset mock for next sub-test within this method --- 
        mock_request.reset_mock()
        # Re-assign mock response as reset clears it
        mock_request.return_value = mock_response

        # --- Test POST request with Body Parameters --- 
        post_tool_call = {
            "name": "set_alarm",
            "parameters": {"time": "08:00", "label": "Wake up"} # This whole dict is the body
        }
        post_tool_execution_map = {
            "set_alarm": {
                "service": "alarm",
                "path": "/set",
                "method": "post",
                "request_body_schema": {"type": "object"} # Indicate body params expected
                # openapi_params would be empty or None if no query/path/header params
            }
        }

        result_post = mcp_tool_executor.execute_tool_call(post_tool_call, mcpo_url, post_tool_execution_map)

        # Verify POST request was made correctly via requests.request
        mock_request.assert_called_once_with(
            method="post", # Use keyword arg
            url=f"{mcpo_url}/alarm/set", # Use keyword arg
            params={}, 
            json={"time": "08:00", "label": "Wake up"}, 
            timeout=15
        )
        self.assertEqual(result_post, {"result": "success"})

    @patch('requests.request')
    def test_execute_tool_call_path_params(self, mock_request):
        """Test executing a tool call with path parameters."""
        mcpo_url = self.mcpo_url
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"user_data": "details"}
        mock_request.reset_mock() # Reset mock before setting return value
        mock_request.return_value = mock_response

        tool_call = {
            "name": "get_user_details",
            "parameters": {"userId": "abc123", "include_history": "true"} # Path and Query param
        }
        tool_execution_map = {
            "get_user_details": {
                "service": "users",
                "path": "/{userId}/info", # Path template relative to service
                "method": "get",
                "openapi_params": [
                    {"name": "userId", "in": "path"}, # Path parameter
                    {"name": "include_history", "in": "query"} # Query parameter
                ]
            }
        }

        result = mcp_tool_executor.execute_tool_call(tool_call, mcpo_url, tool_execution_map)

        # Verify the URL has path param substituted and query params are separate
        expected_url = f"{mcpo_url}/users/abc123/info"
        mock_request.assert_called_once_with(
            method="get", # Use keyword arg
            url=expected_url, # Use keyword arg
            params={"include_history": "true"},
            json=None, # Explicitly check for json=None
            timeout=15
        )
        self.assertEqual(result, {"user_data": "details"})

    @patch('requests.request')
    def test_execute_tool_call_missing_path_param(self, mock_request):
        """Test executing a tool call when a required path parameter is missing."""
        mcpo_url = self.mcpo_url

        tool_call = {
            "name": "get_user_details",
            "parameters": {"include_history": "true"} # Missing 'userId'
        }
        tool_execution_map = {
            "get_user_details": {
                "service": "users",
                "path": "/user/{userId}/info", # Path template requires userId
                "method": "get",
                "openapi_params": [
                    {"name": "userId", "in": "path"},
                    {"name": "include_history", "in": "query"}
                ]
            }
        }

        result = mcp_tool_executor.execute_tool_call(tool_call, mcpo_url, tool_execution_map)

        # Verify an error response is returned and no HTTP call is made
        self.assertIn("error", result)
        self.assertEqual(result["status"], "error")
        # Check for the specific error message about missing keys
        self.assertIn("Missing required path parameter(s)", result["error"])
        self.assertIn("userId", result["error"]) 
        mock_request.assert_not_called() # Ensure the request was not even attempted

    @patch('requests.request')
    def test_execute_tool_call_error(self, mock_request):
        """Test handling network errors during tool execution."""
        mcpo_url = self.mcpo_url
        # Mock error response
        mock_request.side_effect = requests.exceptions.RequestException("Network error")

        tool_call = {
            "name": "get_time",
            "parameters": {"timezone": "UTC"}
        }
        # Updated map structure needed for the call to proceed to the request phase
        tool_execution_map = {
            "get_time": {
                "service": "time",
                "path": "/current",
                "method": "get",
                "openapi_params": [{"name": "timezone", "in": "query"}]
            }
        }

        result = mcp_tool_executor.execute_tool_call(tool_call, mcpo_url, tool_execution_map)

        # Verify error structure from _perform_http_request
        self.assertIn("error", result)
        self.assertEqual(result["status"], "error")
        self.assertIn("timestamp", result)

    def test_format_error_response(self):
        """Test formatting an error response"""
        result = mcp_tool_executor.format_error_response("Test error")
        
        self.assertEqual(result["error"], "Test error")
        self.assertEqual(result["status"], "error")
        self.assertIn("timestamp", result)

    def test_format_mcp_tools_for_llm_prompt(self):
        """Test _format_mcp_tools_for_llm_prompt formats correctly"""
        tools_map = {
            "get_time": {"llm_schema": {"type": "function", "name": "get_time", "description": "Get time"}}
        }
        expected_json = json.dumps([{"type": "function", "name": "get_time", "description": "Get time"}], indent=2)
        
        result = mcp_tool_executor._format_mcp_tools_for_llm_prompt(tools_map)
        
        self.assertIn("Available Tools:", result)
        self.assertIn(expected_json, result)
        self.assertIn("<required_format>", result)

    def test_format_mcp_tools_for_llm_prompt_empty(self):
        """Test _format_mcp_tools_for_llm_prompt handles empty map"""
        result = mcp_tool_executor._format_mcp_tools_for_llm_prompt({})
        self.assertEqual(result, "")

    @patch('re.search')
    @patch('re.sub')
    def test_integrate_tools_into_prompt_replace(self, mock_sub, mock_search):
        """Test _integrate_tools_into_prompt replaces existing section"""
        original_prompt = "Hello\n\nAvailable Tools: old tools\n\n<required_format>"
        tools_section = "Available Tools: new tools"

        # Simulate finding the section by returning a mock match object
        mock_match = MagicMock()
        # Configure the mock match object to return desired start/end indices
        mock_match.start.return_value = 6 # Index where "Available Tools:" starts
        mock_match.end.return_value = 28   # Index where "<required_format>" starts (or end of match)
        mock_search.return_value = mock_match

        # Mock re.sub behaviour (though not strictly necessary if match logic is correct)
        # Let's assume for simplicity the direct string manipulation happens
        # expected_result = "Hello\n\nAvailable Tools: new tools<required_format>"
        # mock_sub.return_value = expected_result

        result = mcp_tool_executor._integrate_tools_into_prompt(original_prompt, tools_section)

        mock_search.assert_called_once()
        mock_sub.assert_not_called() # We are testing the string manipulation path now

        # Verify the result manually based on the expected start/end indices
        expected_result = original_prompt[:mock_match.start()] + tools_section.strip() + original_prompt[mock_match.end():]
        self.assertEqual(result, expected_result)

    @patch('re.search')
    @patch('re.sub')
    def test_integrate_tools_into_prompt_append(self, mock_sub, mock_search):
        """Test _integrate_tools_into_prompt appends when section not found"""
        original_prompt = "Hello"
        tools_section = "Available Tools: new tools"
        mock_search.return_value = False # Simulate not finding the section
        
        result = mcp_tool_executor._integrate_tools_into_prompt(original_prompt, tools_section)
        
        mock_search.assert_called_once()
        mock_sub.assert_not_called()
        self.assertTrue(result.startswith(original_prompt))
        self.assertTrue(result.endswith(tools_section))
        self.assertIn("\n\n", result) # Check for separator

    def test_invoke_missing_tool_map_with_tool_call(self):
        """Test Invoke returns error and has_tool_call=False when map is missing but calls exist."""
        # Assistant message with a valid tool call structure
        messages = [
            {"role": "user", "content": "What time is it?"},
            {"role": "assistant", "content": """```json
            {
                "tool_calls": [
                    {
                        "name": "get_time",
                        "parameters": { "timezone": "UTC" }
                    }
                ]
            }
            ```"""}
        ]
        mcpo_url = self.mcpo_url
        # Explicitly pass None for the tool_execution_map
        tool_execution_map = None

        # Call Invoke without a tool map
        result = mcp_tool_executor.Invoke(
            messages=messages, 
            mcpo_url=mcpo_url, 
            tool_execution_map=tool_execution_map
        )

        # Assertions to demonstrate the potentially misleading behavior
        self.assertIn("error", result, "Result should contain an 'error' key")
        self.assertTrue(result.get("has_tool_call"), "has_tool_call should be True because calls were detected, even if not executed")
        self.assertIn("no tool_execution_map provided", result.get("error", ""), "Error message should mention the missing map")
        # Optionally check that the original response is still returned
        self.assertEqual(result.get("response"), messages[-1]["content"])

    def test_extract_tool_calls_embedded_with_leading_json(self):
        """Test extracting tool calls when other JSON precedes it in text (no fences)."""
        # Input text with unrelated JSON before the tool_calls JSON, no markdown fences
        text_with_leading_json = """Some preliminary text. 
        Here is unrelated info: {"info": "details", "value": 123}.
        Now, use the tool: {"tool_calls": [{"name": "real_tool", "parameters": {"p1": "v1"}}]}
        Okay, done."""

        expected_calls = [
            {
                "name": "real_tool",
                "parameters": {
                    "p1": "v1"
                }
            }
        ]

        result = mcp_tool_executor.extract_tool_calls(text_with_leading_json)
        
        # This assertion might fail if the brace matching logic latches onto the first JSON object
        self.assertEqual(result, expected_calls, "Function failed to extract correct JSON when preceded by other JSON")

    # Test added to demonstrate path parameter name sensitivity
    @patch('requests.request')
    def test_execute_tool_call_path_param_typo(self, mock_request):
        """Test execute_tool_call succeeds when LLM provides path param name with a typo (due to normalization)."""
        mcpo_url = self.mcpo_url

        # --- Mock successful response ---
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"user_data": "details_from_typo_test"}
        mock_request.return_value = mock_response

        # Tool map expects 'userId' in the path, defined via openapi_params
        tool_execution_map = {
            "get_user_details_typo": {
                "service": "users",
                "path": "/{userId}/info", # Corrected path relative to service
                "method": "get",
                "openapi_params": [
                    {"name": "userId", "in": "path"}, # Schema definition uses 'userId'
                ]
            }
        }

        # LLM provides 'user_id' (typo/variation) instead of 'userId'
        tool_call = {
            "name": "get_user_details_typo",
            "parameters": {"user_id": "abc123"} 
        }

        result = mcp_tool_executor.execute_tool_call(tool_call, mcpo_url, tool_execution_map)

        # --- Assertions ---
        # 1. HTTP request should be made successfully
        expected_url = f"{mcpo_url}/users/abc123/info"
        mock_request.assert_called_once_with(
            method="get", # Use keyword arg
            url=expected_url, # Use keyword arg
            params={}, 
            json=None, # Explicitly check for json=None
            timeout=15
        )
        
        # 2. The result should match the mocked successful response
        self.assertEqual(result, {"user_data": "details_from_typo_test"})
        self.assertNotIn("error", result)


class TestMCPWorkflowIntegration(unittest.TestCase):
    """Tests for mcp_workflow_integration.py functions"""
    
    def setUp(self):
        """Set up common variables for MCPWorkflowIntegration tests."""
        self.mcpo_url = "http://example.com"
        self.default_tool_map_dict = {"dummy_op": {"service": "dummy_svc", "path": "/", "method": "get"}}
        self.default_tool_map_str = json.dumps(self.default_tool_map_dict)
        self.valid_messages_list = [{"role": "user", "content": "Hello"}]
        self.valid_messages_str_list = json.dumps(self.valid_messages_list)
        self.valid_messages_plain_str = "user: Just a string"
        self.parsed_plain_str_message = [{"role": "user", "content": "Just a string"}] # Expected parse result

    def test_parse_string_messages(self):
        """Test parsing string messages"""
        # Test with user prefix
        result = mcp_workflow_integration.parse_string_messages("user: Hello")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["role"], "user")
        self.assertEqual(result[0]["content"], "Hello")
        
        # Test with assistant prefix
        result = mcp_workflow_integration.parse_string_messages("assistant: Hello")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["role"], "assistant")
        self.assertEqual(result[0]["content"], "Hello")
        
        # Test without prefix
        result = mcp_workflow_integration.parse_string_messages("Hello")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["role"], "user")
        self.assertEqual(result[0]["content"], "Hello")
    
    def test_validate_node_type(self):
        """Test validating node types"""
        self.assertTrue(mcp_workflow_integration.validate_node_type("Standard"))
        self.assertTrue(mcp_workflow_integration.validate_node_type("PythonModule"))
        self.assertFalse(mcp_workflow_integration.validate_node_type("InvalidType"))
    
    def test_format_results_only(self):
        """Test formatting results only"""
        tool_results = [
            {
                "tool_call": {
                    "name": "get_time",
                    "parameters": {"timezone": "UTC"}
                },
                "result": {"time": "12:00:00"}
            }
        ]
        
        result = mcp_workflow_integration.format_results_only(tool_results)
        
        self.assertIn("Tool Results:", result)
        self.assertIn("Name: get_time", result)
        self.assertIn('"time": "12:00:00"', result)
        
        # Test with error
        tool_results = [
            {
                "tool_call": {
                    "name": "get_time",
                    "parameters": {"timezone": "UTC"}
                },
                "result": {"error": "Not found", "status": "error"}
            }
        ]
        
        result = mcp_workflow_integration.format_results_only(tool_results)
        
        self.assertIn("Error: Not found", result)
        self.assertIn("Status: error", result)

    def test_handler_initialization_future_state(self):
        """Test handler initialization with pre-parsed data."""
        kwargs = {
            "messages": self.valid_messages_list,
            "original_response": "Original response",
            "mcpo_url": self.mcpo_url,
            "tool_execution_map": self.default_tool_map_dict,
            "validate_execution": True,
            "node_type": "Standard"
        }
        handler = mcp_workflow_integration.MCPWorkflowHandler(**kwargs)
        self.assertEqual(handler.messages, kwargs["messages"])
        self.assertEqual(handler.original_response, kwargs["original_response"])
        self.assertEqual(handler.mcpo_url, kwargs["mcpo_url"])
        self.assertEqual(handler.tool_execution_map, kwargs["tool_execution_map"])
        self.assertEqual(handler.validate_execution, kwargs["validate_execution"])
        self.assertEqual(handler.node_type, kwargs["node_type"])

    @patch('mcp_tool_executor.Invoke')
    def test_handler_execute_tools_success(self, mock_mcp_invoke):
        """Test handler's execute_tools method successfully calls executor and formats result."""
        # Mock executor response
        mock_mcp_invoke.return_value = {
            "has_tool_call": True,
            "tool_results": [
                {
                    "tool_call": {
                        "name": "get_time",
                        "parameters": {"timezone": "UTC"}
                    },
                    "result": {"time": "12:00:00"}
                }
            ],
            "response": "Executor original response"
        }
        
        messages = self.valid_messages_list
        original_response = "Handler original response"
        mcpo_url = self.mcpo_url
        tool_execution_map = self.default_tool_map_dict
        
        kwargs = {
            'messages': messages,
            'original_response': original_response,
            'mcpo_url': mcpo_url,
            'tool_execution_map': tool_execution_map,
            'validate_execution': False
        }

        handler = mcp_workflow_integration.MCPWorkflowHandler(**kwargs)
        result = handler.execute_tools()
        
        # Should return formatted tool results
        self.assertIn("Tool Results:", result)
        self.assertIn("Name: get_time", result)
        self.assertIn('"time": "12:00:00"', result)
        # Should NOT contain the original response text
        self.assertNotIn("Handler original response", result)
        self.assertNotIn("Executor original response", result)
        
        # Verify executor was called correctly
        expected_messages = messages + [{"role": "assistant", "content": original_response}]
        mock_mcp_invoke.assert_called_once_with(messages=expected_messages, mcpo_url=mcpo_url, tool_execution_map=tool_execution_map)

    @patch('mcp_tool_executor.Invoke')
    def test_handler_execute_tools_no_call(self, mock_mcp_invoke):
        """Test handler's execute_tools method returns original response when no tool call."""
        # Mock executor response indicating no tool call
        mock_mcp_invoke.return_value = {
            "has_tool_call": False,
            "tool_results": [],
            "response": "Executor original response"
        }

        kwargs = {
            'messages': self.valid_messages_list,
            'original_response': "Handler original response",
            'tool_execution_map': self.default_tool_map_dict,
            'mcpo_url': self.mcpo_url
        }
        handler = mcp_workflow_integration.MCPWorkflowHandler(**kwargs)
        result = handler.execute_tools()

        # Should return the original response passed FROM THE EXECUTOR when no tool call processed
        self.assertEqual(result, "Executor original response")
        # Verify the executor (mock_mcp_invoke) was called
        expected_messages_no_call = kwargs['messages'] + [{"role": "assistant", "content": handler.original_response}]
        mock_mcp_invoke.assert_called_once_with(messages=expected_messages_no_call, mcpo_url=handler.mcpo_url, tool_execution_map=handler.tool_execution_map)

    @patch('mcp_workflow_integration.MCPWorkflowHandler')
    def test_invoke(self, MockMCPWorkflowHandler):
        """Test the main Invoke function orchestrates correctly."""
        mock_handler_instance = MockMCPWorkflowHandler.return_value
        mock_handler_instance.execute_tools.return_value = "Expected Execution Result"
        args = (self.valid_messages_list, "arg2")
        kwargs = {
            "tool_execution_map": self.default_tool_map_dict,
            "key1": "value1",
            "key2": "value2"
        }
        result = mcp_workflow_integration.Invoke(*args, **kwargs)
        self.assertEqual(result, "Expected Execution Result")
        MockMCPWorkflowHandler.assert_called_once()
        call_args, call_kwargs = MockMCPWorkflowHandler.call_args
        self.assertEqual(call_kwargs.get('messages'), self.valid_messages_list)
        self.assertEqual(call_kwargs.get('original_response'), "arg2")
        self.assertEqual(call_kwargs.get('tool_execution_map'), self.default_tool_map_dict)
        self.assertEqual(call_kwargs.get('key1'), "value1")
        self.assertEqual(call_kwargs.get('key2'), "value2")
        mock_handler_instance.execute_tools.assert_called_once_with()

    @patch('mcp_workflow_integration.MCPWorkflowHandler')
    def test_invoke_parses_string_messages_list(self, MockHandler):
        """Test Invoke parses messages string list before calling Handler."""
        MockHandler.return_value.execute_tools.return_value = "Success" # Mock execute return

        mcp_workflow_integration.Invoke(
            messages=self.valid_messages_str_list, # Input as string
            tool_execution_map=self.default_tool_map_dict # Input as dict
        )

        # Assert Handler was called with the *parsed* list
        MockHandler.assert_called_once()
        call_args, call_kwargs = MockHandler.call_args
        # Check the 'messages' kwarg passed to the Handler constructor
        self.assertEqual(call_kwargs.get('messages'), self.valid_messages_list)
        self.assertEqual(call_kwargs.get('tool_execution_map'), self.default_tool_map_dict)

    @patch('mcp_workflow_integration.MCPWorkflowHandler')
    def test_invoke_parses_plain_string_message(self, MockHandler):
        """Test Invoke parses a plain string message before calling Handler."""
        MockHandler.return_value.execute_tools.return_value = "Success"

        mcp_workflow_integration.Invoke(
            messages=self.valid_messages_plain_str, # Input as plain string
            tool_execution_map=self.default_tool_map_dict
        )

        MockHandler.assert_called_once()
        call_args, call_kwargs = MockHandler.call_args
        self.assertEqual(call_kwargs.get('messages'), self.parsed_plain_str_message) # Expect parsed list
        self.assertEqual(call_kwargs.get('tool_execution_map'), self.default_tool_map_dict)

    @patch('mcp_workflow_integration.MCPWorkflowHandler')
    def test_invoke_parses_string_tool_map(self, MockHandler):
        """Test Invoke parses tool_execution_map string before calling Handler."""
        MockHandler.return_value.execute_tools.return_value = "Success"

        mcp_workflow_integration.Invoke(
            messages=self.valid_messages_list, # Input as list
            tool_execution_map=self.default_tool_map_str # Input as string
        )

        MockHandler.assert_called_once()
        call_args, call_kwargs = MockHandler.call_args
        self.assertEqual(call_kwargs.get('messages'), self.valid_messages_list)
        self.assertEqual(call_kwargs.get('tool_execution_map'), self.default_tool_map_dict) # Expect parsed dict

    @patch('mcp_workflow_integration.MCPWorkflowHandler')
    def test_invoke_raises_message_parsing_error_invalid_list_content(self, MockHandler):
        """Test Invoke raises MCPMessageParsingError for invalid message format."""
        invalid_messages_str = '[{"role": "user"}]' # Missing 'content' key

        with self.assertRaisesRegex(mcp_workflow_integration.MCPMessageParsingError, "invalid message dictionaries"):
            mcp_workflow_integration.Invoke(
                messages=invalid_messages_str,
                tool_execution_map=self.default_tool_map_dict
            )
        MockHandler.assert_not_called() # Handler should not be instantiated

    @patch('mcp_workflow_integration.MCPWorkflowHandler')
    def test_invoke_raises_message_parsing_error_invalid_type(self, MockHandler):
        """Test Invoke raises MCPMessageParsingError for invalid message type."""
        invalid_messages_type = 12345

        with self.assertRaisesRegex(mcp_workflow_integration.MCPMessageParsingError, "must be a list or string"):
             mcp_workflow_integration.Invoke(
                 messages=invalid_messages_type,
                 tool_execution_map=self.default_tool_map_dict
             )
        MockHandler.assert_not_called()

    @patch('mcp_workflow_integration.MCPWorkflowHandler')
    def test_invoke_raises_config_error_for_invalid_map_type(self, MockHandler):
        """Test Invoke raises MCPConfigurationError for invalid tool map type."""
        invalid_map = 123 # Not a dict or string

        with self.assertRaisesRegex(mcp_workflow_integration.MCPConfigurationError, "must be a dict or string"):
            mcp_workflow_integration.Invoke(
                messages=self.valid_messages_list,
                tool_execution_map=invalid_map
            )
        MockHandler.assert_not_called()

    @patch('mcp_workflow_integration.MCPWorkflowHandler')
    def test_invoke_raises_config_error_for_bad_map_json(self, MockHandler):
        """Test Invoke raises MCPConfigurationError for unparsable tool map string."""
        bad_json_map_str = '{"key": "value"' # Malformed JSON

        with self.assertRaisesRegex(mcp_workflow_integration.MCPConfigurationError, "Failed to parse tool_execution_map string"):
            mcp_workflow_integration.Invoke(
                messages=self.valid_messages_list,
                tool_execution_map=bad_json_map_str
            )
        MockHandler.assert_not_called()

    def test_invoke_missing_tool_map(self):
        """Test Invoke raises MCPConfigurationError if tool_execution_map is missing."""
        # The error is now raised by _parse_tool_execution_map_static
        expected_error_message = "tool_execution_map must be a dict or string, received <class 'NoneType'>"
        try:
            mcp_workflow_integration.Invoke(
                messages=self.valid_messages_list,
                tool_execution_map=None
            )
            self.fail("MCPConfigurationError was not raised") # Fail if no exception
        except MCPConfigurationError as e:
            self.assertEqual(str(e), expected_error_message)
        except Exception as e:
            self.fail(f"Unexpected exception raised: {type(e).__name__}: {e}")


class TestEnsureSystemPrompt(unittest.TestCase):
    """Tests for the ensure_system_prompt.py module's Invoke function"""

    @patch('ensure_system_prompt.load_default_prompt')
    @patch('mcp_service_discoverer.MCPServiceDiscoverer.discover_mcp_tools')
    @patch('ensure_system_prompt._integrate_tools_into_prompt')
    @patch('ensure_system_prompt._format_mcp_tools_for_llm_prompt')
    def test_ensure_prompt_with_discovery(self, mock_format, mock_integrate, mock_discover, mock_load_default):
        """Test ensure_system_prompt.Invoke when system prompt exists and needs tools"""
        # --- Mock Setup ---
        prompt_content = "System prompt mentioning time service" # This content is now less relevant for extraction
        messages_input = [{"role": "system", "content": prompt_content}]

        # mock_extract is removed, no longer needed
        mock_discovered_tools = {"get_weather": {"service": "weather", "llm_schema": {}}} # Assume weather tool discovered
        mock_discover.return_value = mock_discovered_tools
        mock_format.return_value = "Available Tools: [formatted weather tool]"
        # Integrate will use the original prompt_content and the formatted tools section
        mock_integrate.return_value = f"{prompt_content}\\n\\nAvailable Tools: [formatted weather tool]"
        user_identified_services_input = "weather" # The only source for service names now

        # --- Call ---
        result = ensure_system_prompt.Invoke(
            messages_input,
            user_identified_services=user_identified_services_input
        )

        # --- Assertions ---
        # mock_extract.assert_called_once_with(prompt_content) # Removed assertion
        # Discover should only be called with services identified by the user/workflow node
        mock_discover.assert_called_once_with(["weather"])
        mock_format.assert_called_once_with(mock_discovered_tools)
        # Integrate uses the original prompt and the formatted tools
        mock_integrate.assert_called_once_with(prompt_content, mock_format.return_value)
        self.assertIn("messages", result)
        self.assertIn("chat_system_prompt", result)
        self.assertIn("discovered_tools_map", result)
        self.assertEqual(result["chat_system_prompt"], mock_integrate.return_value)
        self.assertEqual(result["discovered_tools_map"], mock_discovered_tools)
        self.assertEqual(len(result["messages"]), 1)
        self.assertEqual(result["messages"][0]["content"], mock_integrate.return_value)
        mock_load_default.assert_not_called()

    @patch('ensure_system_prompt.load_default_prompt')
    @patch('mcp_service_discoverer.MCPServiceDiscoverer.discover_mcp_tools')
    @patch('mcp_prompt_utils._integrate_tools_into_prompt') # Ensure this path is correct if moved
    @patch('ensure_system_prompt._format_mcp_tools_for_llm_prompt')
    def test_ensure_prompt_no_tools_found(self, mock_format, mock_integrate, mock_discover, mock_load_default):
        """Test ensure_system_prompt.Invoke when no tools are discovered"""
        # --- Mock Setup ---
        prompt_content = "System prompt mentioning service-x <required_format>"
        messages_input = [{"role": "system", "content": prompt_content}]

        # mock_extract removed
        mock_discover.return_value = {} # No tools found
        user_identified_services_input = "service-x" # User asked for service-x
        mock_format.return_value = "" # Format returns empty string if no tools

        # --- Call ---
        result = ensure_system_prompt.Invoke(
            messages_input,
            user_identified_services=user_identified_services_input
        )

        # --- Assertions ---
        # mock_extract.assert_called_once_with(prompt_content) # Removed assertion
        # Discover called with user-identified service
        mock_discover.assert_called_once_with(["service-x"])
        mock_format.assert_called_once_with({})
        # Integrate should *not* be called if no tools were formatted
        mock_integrate.assert_not_called()

        self.assertEqual(result["chat_system_prompt"], prompt_content) # Prompt remains unchanged
        self.assertEqual(result["discovered_tools_map"], {})
        self.assertEqual(result["messages"][0]["content"], prompt_content)
        mock_load_default.assert_not_called()

    @patch('builtins.open', new_callable=mock_open, read_data="Default Prompt Content")
    @patch('os.path.exists', return_value=True)
    @patch('mcp_service_discoverer.MCPServiceDiscoverer.discover_mcp_tools')
    @patch('ensure_system_prompt._integrate_tools_into_prompt')
    @patch('ensure_system_prompt._format_mcp_tools_for_llm_prompt')
    def test_ensure_prompt_no_initial_prompt(self, mock_format, mock_integrate, mock_discover, mock_exists, mock_file_open):
        """Test ensure_system_prompt.Invoke when no system prompt exists initially"""
        # --- Mock Setup ---
        messages_input = [{"role": "user", "content": "Hello"}]
        default_prompt_content = "Default Prompt Content"

        # mock_extract removed
        mock_discovered_tools = {"get_weather": {"service": "weather", "llm_schema": {}}}
        mock_discover.return_value = mock_discovered_tools
        mock_format.return_value = "Available Tools: [formatted weather tool]"
        mock_integrate.return_value = f"{default_prompt_content}\\n\\nAvailable Tools: [formatted weather tool]"
        user_identified_services_input = "weather" # User asked for weather

        # --- Call ---
        result = ensure_system_prompt.Invoke(
            messages_input,
            user_identified_services=user_identified_services_input,
            default_prompt_path="/fake/path.txt"
        )

        # --- Assertions ---
        mock_exists.assert_called_once_with("/fake/path.txt")
        mock_file_open.assert_called_once_with("/fake/path.txt", 'r')
        # mock_extract.assert_called_once_with(default_prompt_content) # Removed assertion
        # Discover called only with user-identified service
        mock_discover.assert_called_once_with(["weather"])
        mock_format.assert_called_once_with(mock_discovered_tools)
        # Integrate uses the loaded default prompt and the formatted tools
        mock_integrate.assert_called_once_with(default_prompt_content, mock_format.return_value)
        self.assertEqual(len(result["messages"]), 2)
        self.assertEqual(result["messages"][0]["role"], "system")
        self.assertEqual(result["messages"][0]["content"], mock_integrate.return_value)
        self.assertEqual(result["chat_system_prompt"], mock_integrate.return_value)
        self.assertEqual(result["discovered_tools_map"], mock_discovered_tools)


if __name__ == "__main__":
    # Add the module directory to the path before running tests
    # This ensures imports like 'from .mcp_service_discoverer import ...' work
    module_dir = os.path.dirname(os.path.abspath(__file__))
    parent_module_dir = os.path.dirname(module_dir)
    if parent_module_dir not in sys.path:
        sys.path.insert(0, parent_module_dir)
        print(f"Added {parent_module_dir} to sys.path for testing")

    unittest.main() 