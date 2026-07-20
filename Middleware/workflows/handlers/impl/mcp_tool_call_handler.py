# /Middleware/workflows/handlers/impl/mcp_tool_call_handler.py

import logging
from typing import Any, Dict

from Middleware.workflows.tools.mcp_client_tool import MCPClient, MCPToolCallError
from Middleware.workflows.handlers.base.base_workflow_node_handler import BaseHandler
from Middleware.workflows.handlers.impl.extension_node_helpers import maybe_stream, validate_timeout
from Middleware.workflows.models.execution_context import ExecutionContext

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 30
_VALID_ON_ERROR = ("raise", "return")


class MCPToolCallHandler(BaseHandler):
    """
    Handles the execution of 'MCPToolCall' nodes.

    A deterministic, workflow-driven MCP tool invocation: the node config names a
    server (defined in `Public/Configs/MCPServers/`), a tool, and a JSON
    arguments object. The workflow author controls when and what is called; the
    LLM is not in the loop.
    """

    def __init__(self, **kwargs):
        """Initializes the handler and its reusable MCP client.

        Args:
            **kwargs (Any): Keyword arguments forwarded to the base handler.
        """
        super().__init__(**kwargs)
        self.mcp_client = MCPClient()

    def handle(self, context: ExecutionContext) -> Any:
        """
        Invokes a single MCP tool as configured on the node and returns the result.

        Args:
            context (ExecutionContext): The central object containing all runtime data for the node.

        Returns:
            Any: The tool result as a string, or a streaming generator wrapping it
                 when `context.stream` is True.

        Raises:
            ValueError: If required config is missing, an enum field has an invalid
                value, or `timeout` is not a positive number.
            MCPToolCallError: When `onError` is "raise" and the MCP call fails.
        """
        config = context.config

        server = config.get("server")
        if not server:
            raise ValueError("MCPToolCall node requires a 'server' field.")
        tool = config.get("tool")
        if not tool:
            raise ValueError("MCPToolCall node requires a 'tool' field.")

        timeout = validate_timeout(config.get("timeout", _DEFAULT_TIMEOUT_SECONDS), "MCPToolCall")
        on_error = config.get("onError", "raise")

        if on_error not in _VALID_ON_ERROR:
            raise ValueError(
                f"MCPToolCall 'onError' must be one of {_VALID_ON_ERROR}; got {on_error!r}."
            )

        resolved_server = self.workflow_variable_service.apply_variables(str(server), context)
        resolved_tool = self.workflow_variable_service.apply_variables(str(tool), context)
        arguments = self._resolve_arguments(config.get("arguments"), context)

        logger.debug(
            "MCPToolCall invoking %s.%s (timeout=%s)",
            resolved_server, resolved_tool, timeout,
        )

        try:
            result = self.mcp_client.call_tool(
                server_name=resolved_server,
                tool_name=resolved_tool,
                arguments=arguments,
                timeout=timeout,
            )
        except MCPToolCallError as exc:
            logger.warning("MCPToolCall failed: %s", exc)
            if on_error == "raise":
                raise
            return maybe_stream(str(exc), context)

        return maybe_stream(result, context)

    def _resolve_arguments(
        self,
        arguments_template: Any,
        context: ExecutionContext,
    ) -> Dict[str, Any]:
        """Resolves workflow variables in the node's arguments template into a plain dict.

        Args:
            arguments_template (Any): The raw ``arguments`` config; ``None`` yields an empty dict.
            context (ExecutionContext): The runtime context used to resolve workflow variables.

        Returns:
            Dict[str, Any]: The arguments with all variables resolved and keys coerced to str.

        Raises:
            ValueError: If ``arguments_template`` is neither ``None`` nor a dict.
        """
        if arguments_template is None:
            return {}
        if not isinstance(arguments_template, dict):
            raise ValueError("MCPToolCall 'arguments' must be a JSON object.")

        resolved: Dict[str, Any] = {}
        for key, value in arguments_template.items():
            resolved[str(key)] = self._resolve_value(value, context)
        return resolved

    def _resolve_value(self, value: Any, context: ExecutionContext) -> Any:
        """Recursively resolves workflow variables in a value, descending into dicts and lists.

        Args:
            value (Any): The value to resolve; strings are substituted, containers recursed into.
            context (ExecutionContext): The runtime context used to resolve workflow variables.

        Returns:
            Any: The value with all string variables resolved, preserving structure and scalars.
        """
        if isinstance(value, str):
            return self.workflow_variable_service.apply_variables(value, context)
        if isinstance(value, dict):
            return {k: self._resolve_value(v, context) for k, v in value.items()}
        if isinstance(value, list):
            return [self._resolve_value(item, context) for item in value]
        return value
