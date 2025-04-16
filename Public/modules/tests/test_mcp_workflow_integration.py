import json
import unittest
from unittest.mock import patch, MagicMock
import sys
import os
from typing import Dict, List
import requests

# Adjust import paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../WilmerAI")))

import WilmerAI.Public.modules.mcp_workflow_integration as mcp_workflow_integration
from WilmerAI.Public.modules.mcp_workflow_integration import (
    MCPIntegrationError,
    MCPMessageParsingError,
    MCPConfigurationError,
    MCPToolExecutionError,
    parse_string_messages
)
from WilmerAI.Public.modules.mcp_tool_executor import DEFAULT_MCPO_URL

# Mock the weather service requests
def mock_mcp_service_response(*args, **kwargs):
    response = requests.Response()
    response.status_code = 200
    
    if "weather" in args[0]:
        response._content = json.dumps({
            "paths": {
                "/weather/current": {
                    "get": {
                        "operationId": "tool_endpoint_weather_get_current_weather_get",
                        "description": "Get the current weather"
                    }
                }
            }
        }).encode()
    elif "time" in args[0]:
        response._content = json.dumps({
            "paths": {
                "/time/current": {
                    "get": {
                        "operationId": "tool_endpoint_time_get_current_time_get",
                        "description": "Get the current time"
                    }
                }
            }
        }).encode()
    return response

class TestMcpWorkflowIntegration(unittest.TestCase):
    
    def setUp(self):
        # Sample messages for testing
        self.messages = [
            {"role": "system", "content": "You are a helpful assistant with access to MCP services: time, weather."},
            {"role": "user", "content": "What time is it?"}
        ]
        
        self.tool_execution_map = {
            "tool_endpoint_time_get_current_time_get": {"service": "time", "path": "/time/current", "method": "get"},
            "tool_endpoint_weather_get_current_weather_get": {"service": "weather", "path": "/weather/current", "method": "get"}
        }
        
        # Sample tool call
        self.tool_call = {
            "name": "tool_endpoint_time_get_current_time_get",
            "parameters": {
                "timezone": "UTC"
            }
        }
        
        # Sample tool result
        self.tool_result = {
            "current_time": "2023-07-22T14:30:00Z",
            "timezone": "UTC"
        }
        
        # Sample LLM response content that triggers a tool call
        self.llm_response_content_with_tool_call = '```json\n{"tool_calls": [{"name": "tool_endpoint_time_get_current_time_get", "parameters": {"timezone": "UTC"}}]}\n```'
        
        # Sample LLM response content without tool call
        self.response_content_without_tool_call = "The current time is 2:30 PM UTC."
        
        # No need for requests patching in current tests

    def tearDown(self):
        pass # Nothing needed currently

    @patch('WilmerAI.Public.modules.mcp_workflow_integration.mcp_tool_executor.Invoke')
    def test_invoke_with_no_tool_call(self, mock_executor_invoke):
        # Setup mock to return no tool call
        mock_executor_invoke.return_value = {
            "response": self.response_content_without_tool_call,
            "has_tool_call": False,
            "tool_results": []
        }
        
        result = mcp_workflow_integration.Invoke(
            self.messages, 
            self.response_content_without_tool_call, # Arg 2 is original_response
            tool_execution_map=self.tool_execution_map
        )
        
        # Verify the executor was called correctly
        expected_messages_to_executor = self.messages + [{"role": "assistant", "content": self.response_content_without_tool_call}]
        mock_executor_invoke.assert_called_once_with(
            messages=expected_messages_to_executor, 
            mcpo_url=DEFAULT_MCPO_URL, 
            tool_execution_map=self.tool_execution_map
        )
        
        # Verify the final result is the original response
        self.assertEqual(result, self.response_content_without_tool_call)

    @patch('WilmerAI.Public.modules.mcp_workflow_integration.mcp_tool_executor.Invoke')
    def test_invoke_with_tool_call(self, mock_executor_invoke):
        """Test that the Invoke function handles tool calls correctly"""
        # Setup mock to return a tool call result
        mock_executor_invoke.return_value = {
            "response": self.llm_response_content_with_tool_call, # Executor got this response
            "has_tool_call": True,
            "tool_results": [
                {
                    "tool_call": self.tool_call,
                    "result": self.tool_result
                }
            ]
        }
        
        # Test invocation, passing the response that contains the tool call trigger
        result = mcp_workflow_integration.Invoke(
            self.messages, 
            self.llm_response_content_with_tool_call, 
            tool_execution_map=self.tool_execution_map
        )
        
        # Verify the executor was called correctly
        expected_messages_to_executor = self.messages + [{"role": "assistant", "content": self.llm_response_content_with_tool_call}]
        mock_executor_invoke.assert_called_once_with(
            messages=expected_messages_to_executor, 
            mcpo_url=DEFAULT_MCPO_URL, 
            tool_execution_map=self.tool_execution_map
        )
        
        # Verify the final result is the formatted tool result
        expected_formatted_result = mcp_workflow_integration.format_results_only([
            {
                "tool_call": self.tool_call,
                "result": self.tool_result
            }
        ])
        self.assertEqual(result, expected_formatted_result)

    # --- Tests for format_results_only --- 
    def test_format_results_only_no_results(self):
        result = mcp_workflow_integration.format_results_only([])
        self.assertEqual(result, "")
        
    def test_format_results_only_single_result(self):
        tool_results = [
            {
                "tool_call": self.tool_call,
                "result": self.tool_result
            }
        ]
        result = mcp_workflow_integration.format_results_only(tool_results)
        self.assertIn("Tool Results:", result)
        self.assertIn("Tool:", result)
        self.assertIn(f"Name: {self.tool_call['name']}", result)
        self.assertIn("Parameters:", result)
        self.assertIn("UTC", result) # Check parameter value
        self.assertIn("Result:", result)
        self.assertIn(self.tool_result['current_time'], result)

    def test_format_results_only_multiple_results(self):
        tool_results = [
            {
                "tool_call": self.tool_call,
                "result": self.tool_result
            },
            {
                "tool_call": {"name": "tool_endpoint_weather_get_current_weather_get", "parameters": {"location": "London"}},
                "result": {"temp": "15C", "condition": "Cloudy"}
            }
        ]
        result = mcp_workflow_integration.format_results_only(tool_results)
        self.assertIn("Tool Results:", result)
        self.assertEqual(result.count("Tool:"), 2)
        self.assertIn(self.tool_call['name'], result)
        self.assertIn("tool_endpoint_weather_get_current_weather_get", result)
        self.assertIn("London", result)
        self.assertIn("15C", result)

    def test_format_results_only_with_error(self):
        error_result = {"error": "Service unavailable", "status": "error"}
        tool_results = [
            {
                "tool_call": self.tool_call,
                "result": error_result
            }
        ]
        result = mcp_workflow_integration.format_results_only(tool_results)
        self.assertIn("Tool Results:", result)
        self.assertIn("Tool:", result)
        self.assertIn(f"Name: {self.tool_call['name']}", result)
        self.assertNotIn("Result:", result) # Should show Error instead
        self.assertIn("Error: Service unavailable", result)
        self.assertIn("Status: error", result)

    # --- Tests for Invoke Argument Handling --- 
    @patch('WilmerAI.Public.modules.mcp_workflow_integration.mcp_tool_executor.Invoke')
    def test_invoke_with_messages_kwarg(self, mock_executor_invoke):
        """Test Invoke accepts messages as a kwarg (no original_response)."""
        mock_executor_invoke.return_value = {"response": "", "has_tool_call": False}
        
        result = mcp_workflow_integration.Invoke(
            messages=self.messages, # Use kwarg
            tool_execution_map=self.tool_execution_map
        )
        
        mock_executor_invoke.assert_called_once_with(
            messages=self.messages, 
            mcpo_url=DEFAULT_MCPO_URL, 
            tool_execution_map=self.tool_execution_map
        )
        self.assertEqual(result, "")
        
    @patch('WilmerAI.Public.modules.mcp_workflow_integration.mcp_tool_executor.Invoke')
    def test_invoke_with_messages_arg(self, mock_executor_invoke):
        """Test Invoke accepts messages as first positional arg (no original_response)."""
        mock_executor_invoke.return_value = {"response": "", "has_tool_call": False}

        result = mcp_workflow_integration.Invoke(
            self.messages, # Positional arg 1
            tool_execution_map=self.tool_execution_map
        )
        
        mock_executor_invoke.assert_called_once_with(
            messages=self.messages, 
            mcpo_url=DEFAULT_MCPO_URL, 
            tool_execution_map=self.tool_execution_map
        )
        self.assertEqual(result, "")
        
    @patch('WilmerAI.Public.modules.mcp_workflow_integration.mcp_tool_executor.Invoke')
    def test_invoke_with_messages_and_response_kwargs(self, mock_executor_invoke):
        """Test Invoke works with both messages and original_response as kwargs."""
        original_response = "I'll help you with that."
        mock_executor_invoke.return_value = {"response": original_response, "has_tool_call": False}

        result = mcp_workflow_integration.Invoke(
            messages=self.messages,
            original_response=original_response,
            tool_execution_map=self.tool_execution_map
        )

        expected_messages_to_executor = self.messages + [{"role": "assistant", "content": original_response}]
        mock_executor_invoke.assert_called_once_with(
            messages=expected_messages_to_executor,
            mcpo_url=DEFAULT_MCPO_URL,
            tool_execution_map=self.tool_execution_map
        )
        self.assertEqual(result, original_response)
        
    @patch('WilmerAI.Public.modules.mcp_workflow_integration.mcp_tool_executor.Invoke')
    def test_invoke_with_stringified_messages_list(self, mock_executor):
        """Test Invoke with messages provided as a stringified list."""
        # Use json.dumps to create a valid JSON string
        messages_str = json.dumps(self.messages)
        mock_executor.return_value = {"response": "", "has_tool_call": False}

        result = mcp_workflow_integration.Invoke(
            messages_str, # First arg is messages
            tool_execution_map=self.tool_execution_map
        )

        # Now, the executor should be called with the PARSED messages list
        mock_executor.assert_called_once_with(
            messages=self.messages, 
            mcpo_url=DEFAULT_MCPO_URL, 
            tool_execution_map=self.tool_execution_map
        )
        self.assertEqual(result, "")

    @patch('WilmerAI.Public.modules.mcp_workflow_integration.mcp_tool_executor.Invoke')
    def test_invoke_with_stringified_messages_list_and_response(self, mock_executor):
        """Test Invoke with stringified messages list and original_response."""
        # Use json.dumps to create a valid JSON string
        messages_str = json.dumps(self.messages)
        original_response = "Okay, checking..."
        mock_executor.return_value = {"response": original_response, "has_tool_call": False}

        result = mcp_workflow_integration.Invoke(
            messages_str, 
            original_response,
            tool_execution_map=self.tool_execution_map
        )

        # Executor should be called with the PARSED messages list + the original response
        expected_messages_to_executor = self.messages + [{"role": "assistant", "content": original_response}]
        mock_executor.assert_called_once_with(
            messages=expected_messages_to_executor, 
            mcpo_url=DEFAULT_MCPO_URL, 
            tool_execution_map=self.tool_execution_map
        )
        self.assertEqual(result, original_response)
            
    @patch('WilmerAI.Public.modules.mcp_workflow_integration.mcp_tool_executor.Invoke')
    def test_invoke_with_simple_string_message(self, mock_executor):
        """Test Invoke with a simple user message string (with prefix)."""
        message_str = "user: Hello there"
        expected_parsed = [{"role": "user", "content": "Hello there"}] # Result of parse_string_messages
        mock_executor.return_value = {"response": "", "has_tool_call": False}
        
        result = mcp_workflow_integration.Invoke(message_str, tool_execution_map=self.tool_execution_map)
        
        mock_executor.assert_called_once_with(
            messages=expected_parsed,
            mcpo_url=DEFAULT_MCPO_URL,
            tool_execution_map=self.tool_execution_map
        )
        self.assertEqual(result, "")

    @patch('WilmerAI.Public.modules.mcp_workflow_integration.mcp_tool_executor.Invoke')
    def test_invoke_with_simple_string_message_no_prefix(self, mock_executor):
        """Test Invoke with a simple user message string (no prefix)."""
        message_str = "Hello there"
        expected_parsed = [{"role": "user", "content": "Hello there"}] # Default to user
        mock_executor.return_value = {"response": "", "has_tool_call": False}
        
        result = mcp_workflow_integration.Invoke(message_str, tool_execution_map=self.tool_execution_map)
        
        mock_executor.assert_called_once_with(
            messages=expected_parsed,
            mcpo_url=DEFAULT_MCPO_URL,
            tool_execution_map=self.tool_execution_map
        )
        self.assertEqual(result, "")

    @patch('WilmerAI.Public.modules.mcp_workflow_integration.mcp_tool_executor.Invoke')
    def test_invoke_with_simple_string_message_and_response(self, mock_executor):
        """Test Invoke with a simple user message string and response, triggering tool."""
        message_str = "user: What time is it?"
        original_response = self.llm_response_content_with_tool_call
        expected_parsed = [{"role": "user", "content": "What time is it?"}]
        expected_tool_result_format = mcp_workflow_integration.format_results_only([{"tool_call": self.tool_call, "result": self.tool_result}])

        mock_executor.return_value = {
            "response": original_response,
            "has_tool_call": True,
            "tool_results": [{"tool_call": self.tool_call, "result": self.tool_result}]
        }
        
        result = mcp_workflow_integration.Invoke(message_str, original_response, tool_execution_map=self.tool_execution_map)
        
        expected_messages_to_executor = expected_parsed + [{"role": "assistant", "content": original_response}]
        mock_executor.assert_called_once_with(
            messages=expected_messages_to_executor,
            mcpo_url=DEFAULT_MCPO_URL,
            tool_execution_map=self.tool_execution_map
        )
        self.assertEqual(result, expected_tool_result_format)
        
    @patch('WilmerAI.Public.modules.mcp_workflow_integration.mcp_tool_executor.Invoke')
    def test_invoke_with_production_like_string_message(self, mock_executor):
        """Test Invoke handles production-like message formats (long string with prefix)."""
        # Simulate a long message string potentially split across lines but passed as one string
        message_str = (
            "user: Hello! How can I assist you today? Let's have a friendly and engaging conversation.\n"
            "Here are a few things we could do:\n\n"
            "1. **Trivia**: I can ask you questions on a topic of your choice, or you can quiz me.\n"
            "2. **Word association**: I say a word, and you respond with the first word that comes to your mind.\n"
            "3. **Story building**: We can take turns adding sentences to create a story.\n"
            "4. **Jokes**: I can tell you some jokes, or you can try to make me laugh.\n"
            "5. **General conversation**: We can discuss a wide range of topics."
        )
        
        # Use the actual parsing logic to get the expected result
        expected_parsed = mcp_workflow_integration.parse_string_messages(message_str) 
        self.assertEqual(len(expected_parsed), 1)
        self.assertEqual(expected_parsed[0]['role'], 'user')
        self.assertTrue(expected_parsed[0]['content'].startswith("Hello! How can I assist"))

        mock_executor.return_value = {"response": "", "has_tool_call": False}

        result = mcp_workflow_integration.Invoke(message_str, tool_execution_map=self.tool_execution_map)

        # Check that the executor was called with the correctly parsed message list
        mock_executor.assert_called_once_with(
            messages=expected_parsed, # Should be List[Dict]
            mcpo_url=DEFAULT_MCPO_URL,
            tool_execution_map=self.tool_execution_map
        )
        self.assertEqual(result, "")

    # --- Tests for Error Handling and Validation --- 
    def test_invoke_with_malformed_messages_list(self):
        """Test Invoke raises error for list with invalid dicts during init."""
        malformed_messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant"} # Missing 'content' key
        ]
        with self.assertRaisesRegex(MCPMessageParsingError, "invalid message dictionaries"):
            mcp_workflow_integration.Invoke(malformed_messages, tool_execution_map=self.tool_execution_map)

    def test_invoke_with_malformed_stringified_list(self):
        """Test Invoke raises error for stringified list with invalid dicts during init."""
        # Use json.dumps on a malformed list to create a valid JSON string of invalid data
        malformed_messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant"} # Missing 'content' key
        ]
        malformed_messages_str = json.dumps(malformed_messages)

        with self.assertRaisesRegex(MCPMessageParsingError, "invalid message dictionaries"):
            mcp_workflow_integration.Invoke(malformed_messages_str, tool_execution_map=self.tool_execution_map)

    def test_invoke_with_invalid_messages_type(self):
        """Test Invoke raises error for invalid messages type during init."""
        invalid_messages = 12345
        with self.assertRaisesRegex(MCPMessageParsingError, "must be a list or string"):
            mcp_workflow_integration.Invoke(invalid_messages, tool_execution_map=self.tool_execution_map)

    @patch('WilmerAI.Public.modules.mcp_workflow_integration.mcp_tool_executor.Invoke')
    def test_tool_execution_with_validation_success(self, mock_executor):
        """Test successful tool execution when validation is enabled."""
        mock_executor.return_value = {
            "response": self.llm_response_content_with_tool_call,
            "has_tool_call": True,
            "tool_results": [{"tool_call": self.tool_call, "result": self.tool_result}] # No errors
        }
        expected_result = mcp_workflow_integration.format_results_only([{"tool_call": self.tool_call, "result": self.tool_result}])
        
        result = mcp_workflow_integration.Invoke(
            self.messages, 
            self.llm_response_content_with_tool_call,
            tool_execution_map=self.tool_execution_map,
            validate_execution=True
        )
        self.assertEqual(result, expected_result)
        mock_executor.assert_called_once()

    @patch('WilmerAI.Public.modules.mcp_workflow_integration.mcp_tool_executor.Invoke')
    def test_tool_execution_with_validation_failure(self, mock_executor):
        """Test tool execution returns formatted error when validation fails."""
        error_detail = {"error": "Tool failed", "status": "error", "timestamp": "now"}
        mock_executor.return_value = {
            "response": self.llm_response_content_with_tool_call,
            "has_tool_call": True,
            "tool_results": [{"tool_call": self.tool_call, "result": error_detail}]
        }

        # Expect the Invoke function to catch the MCPToolExecutionError and return a formatted string
        expected_error_string = f"Tool execution failed: Tool execution validation failed - Details: {json.dumps([error_detail], indent=2)}"
        
        result = mcp_workflow_integration.Invoke(
            self.messages, 
            self.llm_response_content_with_tool_call,
            tool_execution_map=self.tool_execution_map,
            validate_execution=True
        )
        
        self.assertEqual(result, expected_error_string)
        mock_executor.assert_called_once() # Ensure executor was still called
        
    def test_node_type_validation_valid(self):
        """Test Invoke proceeds with a valid node_type."""
        with patch('WilmerAI.Public.modules.mcp_workflow_integration.mcp_tool_executor.Invoke') as mock_executor:
            mock_executor.return_value = {"response": "", "has_tool_call": False}
            # Should initialize and run without raising error
            result = mcp_workflow_integration.Invoke(
            self.messages, 
            node_type='PythonModule', 
            tool_execution_map=self.tool_execution_map
            )
            self.assertEqual(result, "") # Expect normal operation (no tool calls in this setup)
            mock_executor.assert_called_once()

    def test_node_type_validation_invalid(self):
        """Test Invoke raises MCPConfigurationError during init with an invalid node_type."""
        with self.assertRaisesRegex(MCPConfigurationError, "Invalid node type: InvalidNodeType"):
             # The error is raised during MCPWorkflowHandler initialization
                mcp_workflow_integration.Invoke(
                    self.messages,
                 node_type='InvalidNodeType', 
                 tool_execution_map=self.tool_execution_map
             )

    def test_invoke_missing_tool_map(self):
        """Test Invoke raises MCPConfigurationError during init if tool_execution_map is missing."""
        # The error is now raised by _parse_tool_execution_map_static
        expected_error_message = "tool_execution_map must be a dict or string, received <class 'NoneType'>"
        try:
            mcp_workflow_integration.Invoke(
                messages=self.messages, # Use a valid message list
                tool_execution_map=None
            )
            self.fail("MCPConfigurationError was not raised") # Fail if no exception
        except MCPConfigurationError as e:
            self.assertEqual(str(e), expected_error_message)
        except Exception as e:
            self.fail(f"Unexpected exception raised: {type(e).__name__}: {e}")

    def test_invoke_invalid_tool_map_string(self):
        """Test Invoke raises MCPConfigurationError during init for unparsable tool_map string."""
        invalid_map_str = "{'key': 'value'" # Malformed string
        with self.assertRaisesRegex(MCPConfigurationError, "Failed to parse tool_execution_map string"):
             # Error raised during MCPWorkflowHandler initialization
             mcp_workflow_integration.Invoke(self.messages, tool_execution_map=invalid_map_str)
            
    def test_invoke_invalid_tool_map_type(self):
        """Test Invoke raises MCPConfigurationError during init for wrong tool_map type."""
        invalid_map_type = 123
        with self.assertRaisesRegex(MCPConfigurationError, "must be a dict or string"):
             # Error raised during MCPWorkflowHandler initialization
            mcp_workflow_integration.Invoke(self.messages, tool_execution_map=invalid_map_type)

if __name__ == '__main__':
    unittest.main() 