# /Middleware/workflows/handlers/impl/specialized_node_handler.py
import logging
from typing import Dict, Any, List

from Middleware.exceptions.early_termination_exception import EarlyTerminationException
from Middleware.services.llm_dispatch_service import LLMDispatchService
from Middleware.common import instance_global_variables
from Middleware.services.locking_service import LockingService
from Middleware.utilities.file_utils import load_custom_file
from Middleware.workflows.handlers.base.base_workflow_node_handler import BaseHandler

logger = logging.getLogger(__name__)


class SpecializedNodeHandler(BaseHandler):
    """
    Handles specialized, single-purpose workflow nodes.

    This class acts as a dispatcher for various node types that don't fit
    into other categories, such as "WorkflowLock", "GetCustomFile", and
    "ImageProcessor". It routes execution to the appropriate internal method
    based on the node's "type" field.
    """

    def __init__(self, **kwargs):
        """
        Initializes the SpecializedNodeHandler.

        This constructor sets up the handler by initializing its base class and
        instantiating required services like the LockingService.

        Args:
            **kwargs: Arbitrary keyword arguments passed to the base handler.
        """
        super().__init__(**kwargs)
        self.locking_service = LockingService()

    def handle(self, config: Dict, messages: List[Dict], request_id: str, workflow_id: str,
               discussion_id: str, agent_outputs: Dict, stream: bool) -> Any:
        """
        Dispatches execution based on the specialized node's type.

        This method serves as the main entry point for the handler. It inspects
        the "type" field within the node's configuration and calls the
        corresponding internal method to perform the required action.

        Args:
            config (Dict): The configuration dictionary for the specific node.
            messages (List[Dict]): The history of the conversation, as role/content pairs.
            request_id (str): The unique identifier for the current request.
            workflow_id (str): The unique identifier for the current workflow run.
            discussion_id (str): The identifier for the conversational context.
            agent_outputs (Dict): A dictionary containing outputs from previous nodes.
            stream (bool): Flag indicating if the response should be streamed.

        Returns:
            Any: The result from the specific handler method called. This can be
                 None for locking, or a string for file content/image descriptions.

        Raises:
            ValueError: If the 'type' in the config is unknown or not supported.
        """
        node_type = config.get("type")
        logger.debug(f"Handling specialized node of type: {node_type}")

        if node_type == "WorkflowLock":
            # This node only needs config and workflow_id. The others are ignored.
            return self.handle_workflow_lock(config, workflow_id)

        if node_type == "GetCustomFile":
            # This node only needs the config.
            return self.handle_get_custom_file(config)

        if node_type == "ImageProcessor":
            # This node needs config, messages, and agent_outputs.
            return self.handle_image_processor_node(config, messages, agent_outputs)

        raise ValueError(f"Unknown specialized node type: {node_type}")

    def handle_workflow_lock(self, config: Dict, workflow_id: str) -> None:
        """
        Handles the "WorkflowLock" node logic.

        Checks if a lock exists for the given 'workflowLockId'. If a lock is
        active, it raises an EarlyTerminationException to stop the workflow.
        Otherwise, it creates a new lock for the current instance and workflow.

        Args:
            config (Dict): The configuration for the "WorkflowLock" node,
                           which must contain a 'workflowLockId'.
            workflow_id (str): The ID of the currently executing workflow.

        Returns:
            None

        Raises:
            ValueError: If 'workflowLockId' is not provided in the node config.
            EarlyTerminationException: If an existing lock is found.
        """
        workflow_lock_id = config.get("workflowLockId")
        if not workflow_lock_id:
            raise ValueError("A WorkflowLock node must have a 'workflowLockId'.")

        if self.locking_service.get_lock(workflow_lock_id):
            logger.info(f"Lock for {workflow_lock_id} is active, terminating workflow.")
            raise EarlyTerminationException(f"Workflow is locked by {workflow_lock_id}.")
        else:
            self.locking_service.create_node_lock(instance_global_variables.INSTANCE_ID, workflow_id, workflow_lock_id)
            logger.info(
                f"Lock for {workflow_lock_id} acquired by Instance '{instance_global_variables.INSTANCE_ID}' / Workflow '{workflow_id}'.")

    def handle_get_custom_file(self, config: Dict) -> str:
        """
        Handles the "GetCustomFile" node logic.

        Loads content from a specified file path. It allows for custom
        delimiters to be used when reading the file and for formatting the
        returned string.

        Args:
            config (Dict): The configuration for the "GetCustomFile" node,
                           containing 'filepath' and optional delimiters.

        Returns:
            str: The content of the file as a single string, or a message if
                 the filepath is not specified.
        """
        filepath = config.get("filepath")
        if not filepath:
            return "No filepath specified"

        delimiter = config.get("delimiter")
        custom_return_delimiter = config.get("customReturnDelimiter")

        if delimiter is None:
            delimiter = custom_return_delimiter if custom_return_delimiter is not None else "\n"
        if custom_return_delimiter is None:
            custom_return_delimiter = delimiter

        return load_custom_file(filepath=filepath, delimiter=delimiter, custom_delimiter=custom_return_delimiter)

    def handle_image_processor_node(self, config: Dict, messages: List[Dict], agent_outputs: Dict) -> str:
        """
        Handles the "ImageProcessor" node logic.

        This function identifies image messages within the conversation history
        and sends each one to an LLM for analysis via the LLMDispatchService.
        It compiles the resulting descriptions and can optionally inject them
        back into the conversation history for context in subsequent nodes.

        Args:
            config (Dict): The configuration for the "ImageProcessor" node.
            messages (List[Dict]): The conversation history, which may be modified.
            agent_outputs (Dict): A dictionary of outputs from previous nodes.

        Returns:
            str: A consolidated string containing all AI-generated image
                 descriptions, or a message indicating no images were found.
        """
        image_messages = [msg for msg in messages if msg.get("role") == "images"]
        if not image_messages:
            logger.debug("No images found in conversation.")
            return "There were no images attached to the message"

        llm_responses = []
        for img_msg in image_messages:
            # Call the shared service directly, removing the dependency on a previous implementation.
            response = LLMDispatchService.dispatch(
                llm_handler=self.llm_handler,
                workflow_variable_service=self.workflow_variable_service,
                config=config,
                messages=messages,
                agent_outputs=agent_outputs,
                image_message=img_msg
            )
            llm_responses.append(response)

        image_descriptions = "\n-------------\n".join(filter(None, llm_responses))

        # This logic correctly preserves the side effect of modifying the 'messages' list for subsequent nodes.
        if config.get("addAsUserMessage", False):
            message_template = config.get("message",
                                          "[SYSTEM: The user recently added one or more images to the conversation. "
                                          "The images have been analyzed by an advanced vision AI, which has described them"
                                          " in detail. The descriptions of the images can be found below:\n\n"
                                          "<vision_llm_response>\n[IMAGE_BLOCK]\n</vision_llm_response>]")

            final_message = self.workflow_variable_service.apply_variables(
                message_template, self.llm_handler, messages, agent_outputs, config=config
            )
            final_message = final_message.replace("[IMAGE_BLOCK]", image_descriptions)

            # Insert before the last message (which is usually the user's prompt)
            insert_index = len(messages) - 1 if len(messages) > 1 else len(messages)
            messages.insert(insert_index, {"role": "user", "content": final_message})

        return image_descriptions