# Tests/workflow_python_scripts/_isevendays_mcp_scripts/test_mcp_service_discoverer.py

import json

import pytest
import requests

from Public.workflow_python_scripts._isevendays_mcp_scripts.mcp_service_discoverer import MCPServiceDiscoverer

MCPO_URL = "http://localhost:8889"


def _time_service_schema():
    """A minimal MCPO-style OpenAPI schema for a 'time' service."""
    return {
        "openapi": "3.1.0",
        "info": {"title": "time", "version": "1.0"},
        "paths": {
            "/current": {
                "post": {
                    "operationId": "get_current_time",
                    "description": "Get the current time in a timezone",
                    "requestBody": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/TimeForm"}
                            }
                        }
                    },
                }
            }
        },
        "components": {
            "schemas": {
                "TimeForm": {
                    "type": "object",
                    "properties": {
                        "timezone": {"type": "string", "description": "IANA timezone"}
                    },
                    "required": ["timezone"],
                }
            }
        },
    }


# ---------------------------------------------------------------------------
# fetch_service_schema (MCPO HTTP layer, fully mocked)
# ---------------------------------------------------------------------------


def test_fetch_service_schema_success(mocker):
    """
    Tests that a successful HTTP response is parsed and returned as the schema,
    and that the request targets <mcpo_url>/<service>/openapi.json.
    """
    # Arrange
    schema = _time_service_schema()
    mock_response = mocker.MagicMock()
    mock_response.json.return_value = schema
    mock_get = mocker.patch(
        "Public.workflow_python_scripts._isevendays_mcp_scripts.mcp_service_discoverer.requests.get",
        return_value=mock_response,
    )
    discoverer = MCPServiceDiscoverer(mcpo_url=MCPO_URL)

    # Act
    result = discoverer.fetch_service_schema("time")

    # Assert
    assert result == schema
    mock_get.assert_called_once_with(f"{MCPO_URL}/time/openapi.json", timeout=30)


def test_fetch_service_schema_returns_none_on_timeout(mocker):
    """
    Tests that a request timeout is swallowed and None is returned.
    """
    mocker.patch(
        "Public.workflow_python_scripts._isevendays_mcp_scripts.mcp_service_discoverer.requests.get",
        side_effect=requests.exceptions.Timeout,
    )
    assert MCPServiceDiscoverer(mcpo_url=MCPO_URL).fetch_service_schema("time") is None


def test_fetch_service_schema_returns_none_on_http_error(mocker):
    """
    Tests that an HTTP error status results in None.
    """
    mock_response = mocker.MagicMock()
    mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("404")
    mocker.patch(
        "Public.workflow_python_scripts._isevendays_mcp_scripts.mcp_service_discoverer.requests.get",
        return_value=mock_response,
    )
    assert MCPServiceDiscoverer(mcpo_url=MCPO_URL).fetch_service_schema("time") is None


def test_fetch_service_schema_returns_none_on_invalid_json(mocker):
    """
    Tests that a non-JSON response body results in None.
    """
    mock_response = mocker.MagicMock()
    mock_response.json.side_effect = json.JSONDecodeError("bad", "doc", 0)
    mocker.patch(
        "Public.workflow_python_scripts._isevendays_mcp_scripts.mcp_service_discoverer.requests.get",
        return_value=mock_response,
    )
    assert MCPServiceDiscoverer(mcpo_url=MCPO_URL).fetch_service_schema("time") is None


# ---------------------------------------------------------------------------
# validate_tool_schema
# ---------------------------------------------------------------------------


def test_validate_tool_schema_accepts_schema_with_paths():
    discoverer = MCPServiceDiscoverer(mcpo_url=MCPO_URL)
    assert discoverer.validate_tool_schema(_time_service_schema(), "time") is True


def test_validate_tool_schema_rejects_missing_paths_or_non_dict():
    discoverer = MCPServiceDiscoverer(mcpo_url=MCPO_URL)
    assert discoverer.validate_tool_schema({"info": {}}, "time") is False
    assert discoverer.validate_tool_schema("not a dict", "time") is False


# ---------------------------------------------------------------------------
# create_llm_schema (OpenAPI -> LLM function schema)
# ---------------------------------------------------------------------------


def test_create_llm_schema_resolves_request_body_ref():
    """
    Tests that requestBody properties behind a local $ref are resolved into
    the LLM schema's parameters, including the required list.
    """
    # Arrange
    schema = _time_service_schema()
    endpoint = schema["paths"]["/current"]["post"]
    discoverer = MCPServiceDiscoverer(mcpo_url=MCPO_URL)

    # Act
    llm_schema = discoverer.create_llm_schema(endpoint, schema)

    # Assert
    assert llm_schema["type"] == "function"
    assert llm_schema["name"] == "get_current_time"
    assert llm_schema["parameters"]["properties"]["timezone"]["type"] == "string"
    assert llm_schema["parameters"]["required"] == ["timezone"]


def test_create_llm_schema_handles_query_parameters():
    """
    Tests that entries in the OpenAPI 'parameters' list (query/path) are
    mapped into LLM schema properties with enum/default preserved.
    """
    # Arrange
    endpoint = {
        "operationId": "search",
        "summary": "Search things",
        "parameters": [
            {
                "name": "q",
                "in": "query",
                "required": True,
                "schema": {"type": "string"},
                "description": "Query string",
            },
            {
                "name": "limit",
                "in": "query",
                "schema": {"type": "integer", "default": 10, "enum": [10, 20]},
            },
        ],
    }
    discoverer = MCPServiceDiscoverer(mcpo_url=MCPO_URL)

    # Act
    llm_schema = discoverer.create_llm_schema(endpoint, {})

    # Assert
    props = llm_schema["parameters"]["properties"]
    assert props["q"]["description"] == "Query string"
    assert props["limit"]["default"] == 10
    assert props["limit"]["enum"] == [10, 20]
    assert llm_schema["parameters"]["required"] == ["q"]


def test_create_llm_schema_no_parameters_drops_required():
    """
    Tests that an endpoint with no parameters yields a schema without a
    'required' list but with the standard empty properties structure.
    """
    discoverer = MCPServiceDiscoverer(mcpo_url=MCPO_URL)
    llm_schema = discoverer.create_llm_schema({"operationId": "ping"}, {})
    assert "required" not in llm_schema["parameters"]
    assert llm_schema["parameters"]["properties"] == {}


# ---------------------------------------------------------------------------
# process_service_schema / discover_mcp_tools / discover_and_validate_mcp_tools
# ---------------------------------------------------------------------------


def test_process_service_schema_extracts_tools_and_skips_missing_operation_id():
    """
    Tests that processing extracts tools keyed by operationId, records the
    execution details (service/path/method/request body), and skips
    endpoints lacking an operationId.
    """
    # Arrange
    schema = _time_service_schema()
    schema["paths"]["/undocumented"] = {"get": {"description": "no operationId"}}
    discoverer = MCPServiceDiscoverer(mcpo_url=MCPO_URL)

    # Act
    tools = discoverer.process_service_schema(schema, "time")

    # Assert
    assert list(tools.keys()) == ["get_current_time"]
    entry = tools["get_current_time"]
    assert entry["service"] == "time"
    assert entry["path"] == "/current"
    assert entry["method"] == "post"
    assert entry["request_body_schema"] == {"$ref": "#/components/schemas/TimeForm"}
    assert entry["llm_schema"]["name"] == "get_current_time"


def test_discover_mcp_tools_merges_services_and_skips_failures(mocker):
    """
    Tests that discovery fetches each requested service, skips ones whose
    schema cannot be fetched, and merges the rest into a single map.
    """
    # Arrange: 'time' fetches fine, 'weather' fails.
    discoverer = MCPServiceDiscoverer(mcpo_url=MCPO_URL)
    mocker.patch.object(
        discoverer,
        "fetch_service_schema",
        side_effect=lambda name: _time_service_schema() if name == "time" else None,
    )

    # Act
    tools = discoverer.discover_mcp_tools(["time", "weather"])

    # Assert
    assert set(tools.keys()) == {"get_current_time"}


def test_discover_mcp_tools_empty_service_list_returns_empty():
    assert MCPServiceDiscoverer(mcpo_url=MCPO_URL).discover_mcp_tools([]) == {}


def test_discover_mcp_tools_prefers_native_registry_over_mcpo(mocker):
    """
    Tests that a service with an MCPServers/ registry entry is discovered
    through the native MCP SDK (tagged transport="mcp") and that no MCPO
    OpenAPI fetch happens for it.
    """
    # Arrange: 'time' is native; the MCPO fetch path must not be touched.
    discoverer = MCPServiceDiscoverer(mcpo_url=MCPO_URL)
    mocker.patch.object(discoverer, "is_native_service", return_value=True)
    mock_fetch = mocker.patch.object(discoverer, "fetch_service_schema")
    mocker.patch(
        "Middleware.workflows.tools.mcp_client_tool.MCPClient.list_tools",
        return_value={
            "get_current_time": {
                "llm_schema": {
                    "type": "function",
                    "name": "get_current_time",
                    "description": "Get the time",
                    "parameters": {"type": "object", "properties": {}},
                }
            }
        },
    )

    # Act
    tools = discoverer.discover_mcp_tools(["time"])

    # Assert: Native entry with transport tag; MCPO path untouched.
    assert tools["get_current_time"]["transport"] == "mcp"
    assert tools["get_current_time"]["service"] == "time"
    assert tools["get_current_time"]["llm_schema"]["name"] == "get_current_time"
    mock_fetch.assert_not_called()


def test_discover_native_tools_returns_empty_on_service_error(mocker):
    """
    Tests that a native discovery failure (e.g. server unreachable) yields an
    empty map instead of raising, so other services can still be discovered.
    """
    from Middleware.workflows.tools.mcp_client_tool import MCPToolCallError

    discoverer = MCPServiceDiscoverer(mcpo_url=MCPO_URL)
    mocker.patch(
        "Middleware.workflows.tools.mcp_client_tool.MCPClient.list_tools",
        side_effect=MCPToolCallError("connect failed"),
    )

    assert discoverer.discover_native_tools("time") == {}


def test_is_native_service_checks_mcpservers_registry(mocker):
    """
    Tests that native detection is based on the existence of the
    Public/Configs/MCPServers/<name>.json registry file.
    """
    discoverer = MCPServiceDiscoverer(mcpo_url=MCPO_URL)
    mock_isfile = mocker.patch(
        "Public.workflow_python_scripts._isevendays_mcp_scripts.mcp_service_discoverer.os.path.isfile", return_value=True
    )

    assert discoverer.is_native_service("time") is True
    checked_path = mock_isfile.call_args[0][0]
    assert checked_path.endswith("MCPServers/time.json") or checked_path.endswith(
        "MCPServers\\time.json"
    )


def test_discover_and_validate_excludes_invalid_llm_schemas(mocker):
    """
    Tests that when validate_llm_schema is True, tools whose generated LLM
    schema is structurally invalid are excluded from the results.
    """
    # Arrange: One valid tool and one with a broken llm_schema.
    discoverer = MCPServiceDiscoverer(mcpo_url=MCPO_URL)
    valid_entry = {
        "service": "time",
        "path": "/current",
        "method": "post",
        "llm_schema": {
            "type": "function",
            "name": "get_current_time",
            "description": "d",
            "parameters": {},
        },
    }
    invalid_entry = {
        "service": "time",
        "path": "/broken",
        "method": "get",
        "llm_schema": {"type": "function", "name": "broken"},  # missing fields
    }
    mocker.patch.object(
        discoverer,
        "discover_mcp_tools",
        return_value={"get_current_time": valid_entry, "broken": invalid_entry},
    )

    # Act
    tools = discoverer.discover_and_validate_mcp_tools(["time"], validate_llm_schema=True)

    # Assert
    assert set(tools.keys()) == {"get_current_time"}
