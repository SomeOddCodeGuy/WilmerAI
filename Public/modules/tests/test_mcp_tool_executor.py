import json
import unittest
from unittest.mock import patch, MagicMock, mock_open
import sys
import os
import requests

# Adjust import paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../..")))

import WilmerAI.Public.modules.mcp_tool_executor as mcp_tool_executor
import WilmerAI.Public.modules.ensure_system_prompt as ensure_system_prompt
from WilmerAI.Public.modules.mcp_service_discoverer import MCPServiceDiscoverer

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

# ADDED: TestEnsureSystemPrompt class from test_mcp_integration.py
class TestEnsureSystemPrompt(unittest.TestCase):
    """Tests for the ensure_system_prompt.py module's Invoke function"""

    def test_ensure_prompt_with_discovery(self):
        """Test ensure_system_prompt.Invoke when system prompt exists and needs tools"""
        # Patch the discoverer CLASS, its __init__ and the target method
        with patch('WilmerAI.Public.modules.ensure_system_prompt.MCPServiceDiscoverer') as MockDiscoverer, \
             patch('WilmerAI.Public.modules.ensure_system_prompt.load_default_prompt') as mock_load_default, \
             patch('WilmerAI.Public.modules.ensure_system_prompt._integrate_tools_into_prompt') as mock_integrate, \
             patch('WilmerAI.Public.modules.ensure_system_prompt._format_mcp_tools_for_llm_prompt') as mock_format:

            # --- Mock Setup ---
            # Configure the mock INSTANCE that will be returned when MCPServiceDiscoverer() is called
            mock_discoverer_instance = MockDiscoverer.return_value
            mock_discovered_tools = {"get_weather": {"service": "weather", "llm_schema": {}}}
            mock_discoverer_instance.discover_mcp_tools.return_value = mock_discovered_tools

            prompt_content = "System prompt mentioning time service"
            messages_input = [{"role": "system", "content": prompt_content}]
            mock_format.return_value = "Available Tools: [formatted weather tool]"
            mock_integrate.return_value = f"{prompt_content}\\n\\nAvailable Tools: [formatted weather tool]"
            user_identified_services_input = "weather"

            # --- Call ---
            result = ensure_system_prompt.Invoke(
                messages_input,
                user_identified_services=user_identified_services_input
            )

            # --- Assertions ---
            # Check the call on the MOCK INSTANCE's method
            mock_discoverer_instance.discover_mcp_tools.assert_called_once_with(["weather"])
            mock_format.assert_called_once_with(mock_discovered_tools)
            mock_integrate.assert_called_once_with(prompt_content, mock_format.return_value)
            self.assertIn("messages", result)
            self.assertIn("chat_system_prompt", result)
            self.assertIn("discovered_tools_map", result)
            self.assertEqual(result["chat_system_prompt"], mock_integrate.return_value)
            self.assertEqual(result["discovered_tools_map"], mock_discovered_tools)
            self.assertEqual(len(result["messages"]), 1)
            self.assertEqual(result["messages"][0]["content"], mock_integrate.return_value)
            mock_load_default.assert_not_called()

    def test_ensure_prompt_no_tools_found(self):
        """Test ensure_system_prompt.Invoke when no tools are discovered"""
        # Patch the discoverer CLASS
        with patch('WilmerAI.Public.modules.ensure_system_prompt.MCPServiceDiscoverer') as MockDiscoverer, \
             patch('WilmerAI.Public.modules.ensure_system_prompt.load_default_prompt') as mock_load_default, \
             patch('WilmerAI.Public.modules.ensure_system_prompt._integrate_tools_into_prompt') as mock_integrate, \
             patch('WilmerAI.Public.modules.ensure_system_prompt._format_mcp_tools_for_llm_prompt') as mock_format:

            # --- Mock Setup ---
            # Configure the mock INSTANCE
            mock_discoverer_instance = MockDiscoverer.return_value
            mock_discoverer_instance.discover_mcp_tools.return_value = {} # No tools found

            prompt_content = "System prompt mentioning service-x <required_format>"
            messages_input = [{"role": "system", "content": prompt_content}]
            user_identified_services_input = "service-x"
            mock_format.return_value = "" # Expected format when no tools

            # --- Call ---
            result = ensure_system_prompt.Invoke(
                messages_input,
                user_identified_services=user_identified_services_input
            )

            # --- Assertions ---
            # Check the call on the MOCK INSTANCE's method
            mock_discoverer_instance.discover_mcp_tools.assert_called_once_with(["service-x"])
            mock_format.assert_called_once_with({}) # Called with empty map
            # Integration SHOULD happen because prompt lacks "Available Tools:"
            mock_integrate.assert_called_once_with(prompt_content, "")
            self.assertEqual(result["chat_system_prompt"], mock_integrate.return_value) # Check that the integrated prompt is returned
            self.assertEqual(result["discovered_tools_map"], {})
            self.assertEqual(result["messages"][0]["content"], mock_integrate.return_value) # Check integrated prompt in messages
            mock_load_default.assert_not_called()

    def test_ensure_prompt_no_initial_prompt(self):
        """Test ensure_system_prompt.Invoke when no system prompt exists initially"""
        # Patch the discoverer CLASS, load_default_prompt, and other helpers
        with patch('WilmerAI.Public.modules.ensure_system_prompt.load_default_prompt') as mock_load_default, \
             patch('WilmerAI.Public.modules.ensure_system_prompt.MCPServiceDiscoverer') as MockDiscoverer, \
             patch('WilmerAI.Public.modules.ensure_system_prompt._integrate_tools_into_prompt') as mock_integrate, \
             patch('WilmerAI.Public.modules.ensure_system_prompt._format_mcp_tools_for_llm_prompt') as mock_format:

            # --- Mock Setup ---
            # Configure the mock INSTANCE
            mock_discoverer_instance = MockDiscoverer.return_value
            mock_discovered_tools = {"get_weather": {"service": "weather", "llm_schema": {}}}
            mock_discoverer_instance.discover_mcp_tools.return_value = mock_discovered_tools

            # Mock load_default_prompt return value
            default_prompt_content = "Default Prompt Content"
            mock_load_default.return_value = default_prompt_content

            messages_input = [{"role": "user", "content": "Hello"}]
            mock_format.return_value = "Available Tools: [formatted weather tool]"
            mock_integrate.return_value = f"{default_prompt_content}\\n\\nAvailable Tools: [formatted weather tool]"
            user_identified_services_input = "weather"

            # --- Call ---
            result = ensure_system_prompt.Invoke(
                messages_input,
                user_identified_services=user_identified_services_input,
                default_prompt_path="/fake/path.txt"
            )

            # --- Assertions ---
            mock_load_default.assert_called_once_with("/fake/path.txt") # Assert load_default_prompt was called
            # Check the call on the MOCK INSTANCE's method
            mock_discoverer_instance.discover_mcp_tools.assert_called_once_with(["weather"])
            mock_format.assert_called_once_with(mock_discovered_tools)
            mock_integrate.assert_called_once_with(default_prompt_content, mock_format.return_value)
            self.assertEqual(len(result["messages"]), 2)
            self.assertEqual(result["messages"][0]["role"], "system")
            self.assertEqual(result["messages"][0]["content"], mock_integrate.return_value)
            self.assertEqual(result["chat_system_prompt"], mock_integrate.return_value)
            self.assertEqual(result["discovered_tools_map"], mock_discovered_tools)

    @patch('WilmerAI.Public.modules.ensure_system_prompt.MCPServiceDiscoverer.discover_mcp_tools')
    @patch('WilmerAI.Public.modules.ensure_system_prompt.load_default_prompt')
    def test_ensure_prompt_with_generator_input(self, mock_load_prompt, mock_discover_tools):
        """Test ensure_system_prompt handles generator input for user_identified_services."""
        # --- GIVEN ---
        # Mock dependencies
        # Use a simpler default prompt that _integrate_tools_into_prompt can append to
        mock_load_prompt.return_value = "Default system prompt."
        mock_discover_tools.return_value = {
            "get_time": {"service": "time", "summary": "Gets time", "llm_schema": {"name": "get_time", "description": "Gets time"}} # Add llm_schema for format test
        }
        
        initial_messages = [
            {"role": "user", "content": "Check time and weather"} # No initial system prompt
        ]
        
        # Create a generator for the services
        def service_generator():
            yield "time"
            yield ", " # Simulate potential comma separation
            yield "weather"
            
        # --- WHEN ---
        # Call Invoke with the generator
        result = ensure_system_prompt.Invoke(
            initial_messages,
            user_identified_services=service_generator(), # Pass the generator
            mcpo_url="http://fake-mcp:8889"
        )
        
        # --- THEN ---
        # 1. Verify discover_mcp_tools was called with the aggregated list
        mock_discover_tools.assert_called_once_with(['time', 'weather'])
        
        # 2. Verify the system prompt was correctly added and formatted
        self.assertEqual(len(result["messages"]), 2) # User + System
        system_msg = result["messages"][0]
        self.assertEqual(system_msg["role"], "system")
        self.assertIn("Default system prompt.", system_msg["content"]) # Check base prompt
        self.assertIn("Available Tools:", system_msg["content"])      # Check tool section header
        self.assertIn("\"name\": \"get_time\"", system_msg["content"]) # Check tool formatting (using llm_schema)
        self.assertIn("<required_format>", system_msg["content"])     # Check required format section

        # 3. Verify returned system prompt and discovered tools map
        self.assertEqual(result["chat_system_prompt"], system_msg["content"])
        self.assertEqual(result["discovered_tools_map"], mock_discover_tools.return_value)

if __name__ == '__main__':
    unittest.main() 