import unittest
from unittest.mock import patch, MagicMock, call
import requests
import json
import os
import sys
import logging

# Add the parent directory (modules) to sys.path to allow importing MCPServiceDiscoverer
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

from mcp_service_discoverer import MCPServiceDiscoverer, DEFAULT_MCPO_URL

class TestMCPServiceDiscoverer(unittest.TestCase):
    """Tests for the MCPServiceDiscoverer class."""

    def setUp(self):
        """Set up for test methods."""
        self.default_url = DEFAULT_MCPO_URL
        self.custom_url = "http://custom-mcp.com:9000"
        self.discoverer_default = MCPServiceDiscoverer()
        self.discoverer_custom = MCPServiceDiscoverer(mcpo_url=self.custom_url)
        self.service_name = "test_service"

    def test_init_default_url(self):
        """Test initializer uses default URL if none provided."""
        self.assertEqual(self.discoverer_default.mcpo_url, self.default_url)

    def test_init_custom_url(self):
        """Test initializer uses provided custom URL."""
        self.assertEqual(self.discoverer_custom.mcpo_url, self.custom_url)

    @patch('requests.get')
    def test_fetch_service_schema_success(self, mock_get):
        """Test fetch_service_schema returns JSON on successful request."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        expected_schema = {"openapi": "3.0.0", "paths": {}}
        mock_response.json.return_value = expected_schema
        mock_get.return_value = mock_response

        schema = self.discoverer_default.fetch_service_schema(self.service_name)

        expected_url = f"{self.default_url}/{self.service_name}/openapi.json"
        mock_get.assert_called_once_with(expected_url, timeout=5)
        mock_response.raise_for_status.assert_called_once()
        self.assertEqual(schema, expected_schema)

    @patch('requests.get')
    def test_fetch_service_schema_timeout(self, mock_get):
        """Test fetch_service_schema returns None on timeout."""
        mock_get.side_effect = requests.exceptions.Timeout("Request timed out")
        schema = self.discoverer_default.fetch_service_schema(self.service_name)
        self.assertIsNone(schema)

    @patch('requests.get')
    def test_fetch_service_schema_http_error(self, mock_get):
        """Test fetch_service_schema returns None on HTTPError."""
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("404 Not Found")
        mock_get.return_value = mock_response
        schema = self.discoverer_default.fetch_service_schema(self.service_name)
        self.assertIsNone(schema)

    @patch('requests.get')
    def test_fetch_service_schema_request_exception(self, mock_get):
        """Test fetch_service_schema returns None on RequestException."""
        mock_get.side_effect = requests.exceptions.RequestException("Connection error")
        schema = self.discoverer_default.fetch_service_schema(self.service_name)
        self.assertIsNone(schema)

    @patch('requests.get')
    def test_fetch_service_schema_json_decode_error(self, mock_get):
        """Test fetch_service_schema returns None on JSONDecodeError."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = json.JSONDecodeError("Expecting value", "", 0)
        mock_get.return_value = mock_response
        schema = self.discoverer_default.fetch_service_schema(self.service_name)
        self.assertIsNone(schema)

    def test_validate_tool_schema_valid(self):
        """Test validate_tool_schema returns True for a valid basic schema."""
        valid_schema = {"paths": {}}
        self.assertTrue(self.discoverer_default.validate_tool_schema(valid_schema, self.service_name))

    def test_validate_tool_schema_missing_paths(self):
        """Test validate_tool_schema returns False if 'paths' key is missing."""
        invalid_schema = {"openapi": "3.0.0"}
        self.assertFalse(self.discoverer_default.validate_tool_schema(invalid_schema, self.service_name))

    def test_validate_tool_schema_not_dict(self):
        """Test validate_tool_schema returns False if input is not a dictionary."""
        self.assertFalse(self.discoverer_default.validate_tool_schema([], self.service_name))
        self.assertFalse(self.discoverer_default.validate_tool_schema("string", self.service_name))
        self.assertFalse(self.discoverer_default.validate_tool_schema(None, self.service_name))

    def test_validate_tool_definition_valid(self):
        """Test validate_tool_definition returns True for a valid LLM schema."""
        valid_tool = {
            "type": "function",
            "name": "test_func",
            "description": "A test function",
            "parameters": {
                "type": "object",
                "properties": {"param1": {"type": "string"}}
            }
        }
        self.assertTrue(self.discoverer_default.validate_tool_definition(valid_tool))

    def test_validate_tool_definition_valid_no_params(self):
        """Test validate_tool_definition returns True for a valid LLM schema with empty parameters."""
        valid_tool_no_params = {
            "type": "function",
            "name": "test_func_no_params",
            "description": "A test function with no parameters",
            "parameters": {"type": "object", "properties": {}} # Still requires this structure
        }
        self.assertTrue(self.discoverer_default.validate_tool_definition(valid_tool_no_params))

    def test_validate_tool_definition_missing_fields(self):
        """Test validate_tool_definition returns False if required fields are missing."""
        self.assertFalse(self.discoverer_default.validate_tool_definition({"type": "function", "name": "n"}))
        self.assertFalse(self.discoverer_default.validate_tool_definition({"type": "function", "description": "d", "parameters": {}}))

    def test_validate_tool_definition_invalid_type(self):
        """Test validate_tool_definition returns False if type is not 'function'."""
        invalid_tool = {"type": "method", "name": "n", "description": "d", "parameters": {}}
        self.assertFalse(self.discoverer_default.validate_tool_definition(invalid_tool))

    def test_validate_tool_definition_invalid_parameters_type(self):
        """Test validate_tool_definition returns False if parameters is not a dict."""
        invalid_tool = {"type": "function", "name": "n", "description": "d", "parameters": "string"}
        self.assertFalse(self.discoverer_default.validate_tool_definition(invalid_tool))

    def test_validate_tool_definition_invalid_parameters_structure(self):
        """Test validate_tool_definition returns False if parameters has wrong structure."""
        invalid_params_no_type = {"type": "function", "name": "n", "description": "d", "parameters": {"properties": {}}}
        invalid_params_no_props = {"type": "function", "name": "n", "description": "d", "parameters": {"type": "object"}}
        self.assertFalse(self.discoverer_default.validate_tool_definition(invalid_params_no_type))
        self.assertFalse(self.discoverer_default.validate_tool_definition(invalid_params_no_props))

    def test_create_llm_schema_basic(self):
        """Test create_llm_schema for a basic endpoint."""
        endpoint_details = {
            "operationId": "get_status",
            "summary": "Get service status",
            "description": "Returns the current status of the service.",
            "parameters": []
        }
        full_schema = {"paths": {"/status": {"get": endpoint_details}}}
        expected_llm_schema = {
            "type": "function",
            "name": "get_status",
            "description": "Returns the current status of the service.", # Uses description
            "parameters": {"type": "object", "properties": {}} # Empty params structure
        }
        llm_schema = self.discoverer_default.create_llm_schema(endpoint_details, full_schema)
        self.assertEqual(llm_schema, expected_llm_schema)

    def test_create_llm_schema_uses_summary_if_desc_missing(self):
        """Test create_llm_schema uses summary if description is missing."""
        endpoint_details = {"operationId": "get_summary", "summary": "Get summary only"}
        full_schema = {"paths": {"/summary": {"get": endpoint_details}}}
        llm_schema = self.discoverer_default.create_llm_schema(endpoint_details, full_schema)
        self.assertEqual(llm_schema["description"], "Get summary only")

    def test_create_llm_schema_with_query_params(self):
        """Test create_llm_schema with query parameters."""
        endpoint_details = {
            "operationId": "list_items",
            "summary": "List items",
            "parameters": [
                {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer"}, "description": "Max items"},
                {"name": "filter", "in": "query", "required": True, "schema": {"type": "string", "enum": ["A", "B"]}}
            ]
        }
        full_schema = {"paths": {"/items": {"get": endpoint_details}}}
        expected_params = {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max items"},
                "filter": {"type": "string", "description": "", "enum": ["A", "B"]}
            },
            "required": ["filter"]
        }
        llm_schema = self.discoverer_default.create_llm_schema(endpoint_details, full_schema)
        self.assertEqual(llm_schema["parameters"], expected_params)

    def test_create_llm_schema_with_path_params(self):
        """Test create_llm_schema includes path parameters."""
        endpoint_details = {
            "operationId": "get_item",
            "summary": "Get specific item",
            "parameters": [
                {"name": "item_id", "in": "path", "required": True, "schema": {"type": "string"}, "description": "ID of item"}
            ]
        }
        full_schema = {"paths": {"/items/{item_id}": {"get": endpoint_details}}}
        expected_params = {
            "type": "object",
            "properties": {
                "item_id": {"type": "string", "description": "ID of item"}
            },
            "required": ["item_id"]
        }
        llm_schema = self.discoverer_default.create_llm_schema(endpoint_details, full_schema)
        self.assertEqual(llm_schema["parameters"], expected_params)


    def test_create_llm_schema_with_request_body(self):
        """Test create_llm_schema with a requestBody."""
        endpoint_details = {
            "operationId": "create_item",
            "summary": "Create an item",
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "Item name"},
                                "value": {"type": "number"}
                            },
                            "required": ["name"]
                        }
                    }
                }
            }
        }
        full_schema = {"paths": {"/items": {"post": endpoint_details}}}
        expected_params = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Item name"},
                "value": {"type": "number", "description": ""}
            },
            "required": ["name"]
        }
        llm_schema = self.discoverer_default.create_llm_schema(endpoint_details, full_schema)
        self.assertEqual(llm_schema["parameters"], expected_params)

    def test_create_llm_schema_with_request_body_ref(self):
        """Test create_llm_schema with a requestBody referencing components/schemas."""
        endpoint_details = {
            "operationId": "update_item",
            "summary": "Update an item",
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/ItemUpdate"}
                    }
                }
            }
        }
        full_schema = {
            "paths": {"/items": {"put": endpoint_details}},
            "components": {
                "schemas": {
                    "ItemUpdate": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "enabled": {"type": "boolean", "default": True}
                        }
                    }
                }
            }
        }
        expected_params = {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": ""},
                "enabled": {"type": "boolean", "description": "", "default": True}
            }
            # No required field in this example schema
        }
        llm_schema = self.discoverer_default.create_llm_schema(endpoint_details, full_schema)
        self.assertEqual(llm_schema["parameters"], expected_params)

    def test_create_llm_schema_combined_params(self):
        """Test create_llm_schema combining path, query, and requestBody params."""
        endpoint_details = {
            "operationId": "complex_update",
            "parameters": [
                {"name": "item_id", "in": "path", "required": True, "schema": {"type": "string"}},
                {"name": "force", "in": "query", "schema": {"type": "boolean"}}
            ],
            "requestBody": {
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ItemData"}}}
            }
        }
        full_schema = {
            "paths": {"/items/{item_id}": {"patch": endpoint_details}},
            "components": {
                "schemas": {
                    "ItemData": {
                        "type": "object",
                        "properties": {"payload": {"type": "object"}},
                        "required": ["payload"]
                    }
                }
            }
        }
        expected_params = {
            "type": "object",
            "properties": {
                "item_id": {"type": "string", "description": ""},
                "force": {"type": "boolean", "description": ""},
                "payload": {"type": "object", "description": ""}
            },
            "required": ["item_id", "payload"]
        }
        llm_schema = self.discoverer_default.create_llm_schema(endpoint_details, full_schema)
        # Sort required list for consistent comparison
        if "required" in llm_schema["parameters"]:
            llm_schema["parameters"]["required"].sort()
        if "required" in expected_params:
            expected_params["required"].sort()
        self.assertEqual(llm_schema["parameters"], expected_params)

    def test_create_llm_schema_missing_operation_id(self):
        """Test create_llm_schema handles missing operationId gracefully."""
        endpoint_details = {"summary": "No ID here"}
        full_schema = {}
        # Expecting a placeholder or error structure, not an exception
        llm_schema = self.discoverer_default.create_llm_schema(endpoint_details, full_schema)
        self.assertIn("name", llm_schema)
        self.assertIn("Error: Missing operationId", llm_schema.get("description", ""))

    @patch.object(MCPServiceDiscoverer, 'create_llm_schema')
    def test_process_service_schema_valid(self, mock_create_llm):
        """Test process_service_schema extracts tools correctly."""
        op_id_1 = "get_data"
        op_id_2 = "post_data"
        details_1 = {"operationId": op_id_1, "summary": "Get"}
        details_2 = {"operationId": op_id_2, "summary": "Post"}
        schema = {
            "paths": {
                "/data": {"get": details_1, "post": details_2},
                "/nodata": {"get": {"summary": "No op id"}} # Should be skipped
            }
        }
        # Mock the LLM schema creation
        mock_llm_schema_1 = {"type": "function", "name": op_id_1}
        mock_llm_schema_2 = {"type": "function", "name": op_id_2}
        mock_create_llm.side_effect = [mock_llm_schema_1, mock_llm_schema_2]

        tools_map = self.discoverer_default.process_service_schema(schema, self.service_name)

        self.assertEqual(len(tools_map), 2)
        self.assertIn(op_id_1, tools_map)
        self.assertIn(op_id_2, tools_map)
        self.assertEqual(tools_map[op_id_1]["service"], self.service_name)
        self.assertEqual(tools_map[op_id_1]["path"], "/data")
        self.assertEqual(tools_map[op_id_1]["method"], "get")
        self.assertEqual(tools_map[op_id_1]["llm_schema"], mock_llm_schema_1)
        self.assertEqual(tools_map[op_id_2]["method"], "post")
        self.assertEqual(tools_map[op_id_2]["llm_schema"], mock_llm_schema_2)

        # Check that create_llm_schema was called correctly
        mock_create_llm.assert_has_calls([
            call(details_1, schema),
            call(details_2, schema)
        ], any_order=True)


    def test_process_service_schema_invalid_paths(self):
        """Test process_service_schema handles invalid 'paths' structure."""
        schema = {"paths": "not_a_dict"}
        tools_map = self.discoverer_default.process_service_schema(schema, self.service_name)
        self.assertEqual(tools_map, {})

    @patch.object(MCPServiceDiscoverer, 'fetch_service_schema')
    @patch.object(MCPServiceDiscoverer, 'process_service_schema')
    @patch.object(MCPServiceDiscoverer, 'validate_tool_schema')
    def test_discover_mcp_tools_success(self, mock_validate, mock_process, mock_fetch):
        """Test discover_mcp_tools combines results from multiple services."""
        service1, service2 = "time", "weather"
        schema1, schema2 = {"paths": {"/time": {"get": {"operationId": "get_time"}}}}, {"paths": {"/weather": {"get": {"operationId": "get_weather"}}}}
        tools1, tools2 = {"get_time": {"service": service1, "llm_schema": {}}}, {"get_weather": {"service": service2, "llm_schema": {}}}

        mock_fetch.side_effect = [schema1, schema2]
        mock_validate.return_value = True
        mock_process.side_effect = [tools1, tools2]

        all_tools = self.discoverer_default.discover_mcp_tools([service1, service2])

        mock_fetch.assert_has_calls([call(service1), call(service2)])
        mock_validate.assert_has_calls([call(schema1, service1), call(schema2, service2)])
        mock_process.assert_has_calls([call(schema1, service1), call(schema2, service2)])
        self.assertEqual(len(all_tools), 2)
        self.assertIn("get_time", all_tools)
        self.assertIn("get_weather", all_tools)

    @patch.object(MCPServiceDiscoverer, 'fetch_service_schema')
    @patch.object(MCPServiceDiscoverer, 'process_service_schema')
    @patch.object(MCPServiceDiscoverer, 'validate_tool_schema')
    def test_discover_mcp_tools_fetch_error_skips_service(self, mock_validate, mock_process, mock_fetch):
        """Test discover_mcp_tools skips service if fetch fails."""
        service1, service2 = "time", "weather"
        schema2 = {"paths": {"/weather": {"get": {"operationId": "get_weather"}}}}
        tools2 = {"get_weather": {"service": service2, "llm_schema": {}}}

        mock_fetch.side_effect = [None, schema2] # Simulate fetch fail for service1
        mock_validate.return_value = True # Assume schema2 is valid
        mock_process.return_value = tools2 # Only process schema2

        all_tools = self.discoverer_default.discover_mcp_tools([service1, service2])

        mock_fetch.assert_has_calls([call(service1), call(service2)])
        mock_validate.assert_called_once_with(schema2, service2) # Only called for schema2
        mock_process.assert_called_once_with(schema2, service2) # Only called for schema2
        self.assertEqual(len(all_tools), 1)
        self.assertNotIn("get_time", all_tools)
        self.assertIn("get_weather", all_tools)

    @patch.object(MCPServiceDiscoverer, 'fetch_service_schema')
    @patch.object(MCPServiceDiscoverer, 'process_service_schema')
    @patch.object(MCPServiceDiscoverer, 'validate_tool_schema')
    def test_discover_mcp_tools_process_error_skips_service(self, mock_validate, mock_process, mock_fetch):
        """Test discover_mcp_tools skips service if processing fails."""
        service1, service2 = "time", "weather"
        schema1, schema2 = {"paths": {}}, {"paths": {}}
        tools2 = {"get_weather": {"service": service2, "llm_schema": {}}}

        mock_fetch.side_effect = [schema1, schema2]
        mock_validate.return_value = True
        mock_process.side_effect = [Exception("Processing Error"), tools2] # Error on first

        all_tools = self.discoverer_default.discover_mcp_tools([service1, service2])

        mock_process.assert_has_calls([call(schema1, service1), call(schema2, service2)])
        self.assertEqual(len(all_tools), 1) # Only tools from service2
        self.assertIn("get_weather", all_tools)

    @patch.object(MCPServiceDiscoverer, 'fetch_service_schema')
    @patch.object(MCPServiceDiscoverer, 'process_service_schema')
    @patch.object(MCPServiceDiscoverer, 'validate_tool_schema')
    def test_discover_mcp_tools_duplicate_opid_overwrites(self, mock_validate, mock_process, mock_fetch):
        """Test discover_mcp_tools overwrites tools with duplicate operationIds."""
        service1, service2 = "serviceA", "serviceB"
        schema1, schema2 = {"paths": {}}, {"paths": {}}
        # Both services define "get_info"
        tools1 = {"get_info": {"service": service1, "path": "/pathA"}}
        tools2 = {"get_info": {"service": service2, "path": "/pathB"}}

        mock_fetch.side_effect = [schema1, schema2]
        mock_validate.return_value = True
        mock_process.side_effect = [tools1, tools2]

        all_tools = self.discoverer_default.discover_mcp_tools([service1, service2])

        self.assertEqual(len(all_tools), 1)
        self.assertIn("get_info", all_tools)
        # Assert that the tool from the *last* processed service (service2) remains
        self.assertEqual(all_tools["get_info"]["service"], service2)
        self.assertEqual(all_tools["get_info"]["path"], "/pathB")


    @patch.object(MCPServiceDiscoverer, 'discover_mcp_tools')
    @patch.object(MCPServiceDiscoverer, 'validate_tool_definition')
    def test_discover_and_validate_no_validation(self, mock_validate_def, mock_discover):
        """Test discover_and_validate skips validation when flag is False."""
        mock_discovered = {"tool1": {"llm_schema": {}}}
        mock_discover.return_value = mock_discovered
        services = ["svc1"]

        result = self.discoverer_default.discover_and_validate_mcp_tools(services, validate_llm_schema=False)

        mock_discover.assert_called_once_with(services)
        mock_validate_def.assert_not_called() # Validation should not be called
        self.assertEqual(result, mock_discovered)

    @patch.object(MCPServiceDiscoverer, 'discover_mcp_tools')
    @patch.object(MCPServiceDiscoverer, 'validate_tool_definition')
    def test_discover_and_validate_with_validation_some_valid(self, mock_validate_def, mock_discover):
        """Test discover_and_validate filters invalid tools when flag is True."""
        tool1_schema = {"type": "function", "name": "tool1", "description": "d", "parameters": {"type": "object", "properties": {}}}
        tool2_schema = {"type": "invalid"} # Invalid schema
        mock_discovered = {
            "tool1": {"llm_schema": tool1_schema},
            "tool2": {"llm_schema": tool2_schema}
        }
        mock_discover.return_value = mock_discovered
        # Mock validation: True for tool1, False for tool2
        mock_validate_def.side_effect = lambda schema: schema.get("type") == "function"
        services = ["svc1"]

        result = self.discoverer_default.discover_and_validate_mcp_tools(services, validate_llm_schema=True)

        mock_discover.assert_called_once_with(services)
        mock_validate_def.assert_has_calls([call(tool1_schema), call(tool2_schema)], any_order=True)
        self.assertEqual(len(result), 1)
        self.assertIn("tool1", result)
        self.assertNotIn("tool2", result)

    @patch.object(MCPServiceDiscoverer, 'discover_mcp_tools')
    @patch.object(MCPServiceDiscoverer, 'validate_tool_definition')
    def test_discover_and_validate_with_validation_none_valid(self, mock_validate_def, mock_discover):
        """Test discover_and_validate returns empty dict if all tools are invalid."""
        mock_discovered = {"tool1": {"llm_schema": {"type": "invalid"}}}
        mock_discover.return_value = mock_discovered
        mock_validate_def.return_value = False # All fail validation
        services = ["svc1"]

        result = self.discoverer_default.discover_and_validate_mcp_tools(services, validate_llm_schema=True)

        mock_discover.assert_called_once_with(services)
        mock_validate_def.assert_called_once()
        self.assertEqual(result, {})

    @patch.object(MCPServiceDiscoverer, 'discover_mcp_tools')
    def test_discover_and_validate_no_tools_discovered(self, mock_discover):
        """Test discover_and_validate returns empty if no tools discovered initially."""
        mock_discover.return_value = {}
        services = ["svc1"]

        result_no_validate = self.discoverer_default.discover_and_validate_mcp_tools(services, validate_llm_schema=False)
        result_validate = self.discoverer_default.discover_and_validate_mcp_tools(services, validate_llm_schema=True)

        self.assertEqual(result_no_validate, {})
        self.assertEqual(result_validate, {})
        # Ensure discover_mcp_tools was called twice
        self.assertEqual(mock_discover.call_count, 2)


if __name__ == "__main__":
    # Ensure logging is re-enabled if running standalone
    logging.disable(logging.NOTSET)
    unittest.main() 