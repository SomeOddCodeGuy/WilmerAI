# /Middleware/workflows/models/execution_context.py
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

# Forward reference to avoid circular imports
if False:
    from Middleware.models.llm_handler import LlmHandler
    from Middleware.workflows.managers.workflow_variable_manager import WorkflowVariableManager


@dataclass
class ExecutionContext:
    """
    A unified context object holding all state for a single node's execution.

    Attributes:
        request_id (str): The unique identifier for the incoming request.
        workflow_id (str): The identifier for the current workflow being executed.
        discussion_id (Optional[str]): The identifier for the conversation or discussion thread.
        config (Dict[str, Any]): The configuration specific to the current node being executed.
        messages (List[Dict[str, str]]): The complete history of the conversation.
        stream (bool): A flag indicating whether the final response should be streamed.
        workflow_config (Dict[str, Any]): The top-level configuration for the entire workflow.
        agent_inputs (Dict[str, Any]): Inputs passed from a parent workflow to a sub-workflow.
        agent_outputs (Dict[str, Any]): Outputs from previously executed nodes in the current workflow.
        llm_handler (Optional['LlmHandler']): The language model handler instance for the current node.
        workflow_variable_service (Optional['WorkflowVariableManager']): The service for resolving dynamic variables.
        workflow_manager (Optional[Any]): A reference to the main workflow manager, used for invoking sub-workflows.
        node_handlers (Dict[str, Any]): A registry of all available node handlers.
    """
    # --- Fields WITHOUT default values ---
    request_id: str
    workflow_id: str
    discussion_id: Optional[str]
    config: Dict[str, Any]
    messages: List[Dict[str, str]]
    stream: bool

    # --- Fields WITH default values ---
    workflow_config: Dict[str, Any] = field(default_factory=dict)
    agent_inputs: Dict[str, Any] = field(default_factory=dict)
    agent_outputs: Dict[str, Any] = field(default_factory=dict)
    llm_handler: Optional['LlmHandler'] = None
    workflow_variable_service: Optional['WorkflowVariableManager'] = None
    workflow_manager: Optional[Any] = None
    node_handlers: Dict[str, Any] = field(default_factory=dict)
