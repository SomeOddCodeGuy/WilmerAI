# /Middleware/workflows/handlers/impl/specialized_node_handler.py

import logging
import time
from copy import deepcopy
from typing import Any, Dict, Generator

from Middleware.common import instance_global_variables
from Middleware.exceptions.early_termination_exception import EarlyTerminationException
from Middleware.services.llm_dispatch_service import LLMDispatchService
from Middleware.services.locking_service import LockingService
from Middleware.utilities.file_utils import load_custom_file, save_custom_file
from Middleware.workflows.handlers.base.base_workflow_node_handler import BaseHandler
from Middleware.workflows.models.execution_context import ExecutionContext

logger = logging.getLogger(__name__)


class SpecializedNodeHandler(BaseHandler):
    """
    A router for miscellaneous workflow nodes like "WorkflowLock", "GetCustomFile", and "SaveCustomFile".
    """

    def __init__(self, **kwargs):
        """
        Initializes the SpecializedNodeHandler and its required services.

        Args:
            **kwargs: Keyword arguments passed to the base handler.
        """
        super().__init__(**kwargs)
        self.locking_service = LockingService()

    def handle(self, context: ExecutionContext) -> Any:
        """
        Dispatches execution to the appropriate handler based on the node's type.

        Args:
            context (ExecutionContext): The central object containing all runtime data for the node.

        Returns:
            Any: The result from the specific node handler that was called.
        """
        node_type = context.config.get("type")
        logger.debug(f"Handling specialized node of type: {node_type}")

        if node_type == "WorkflowLock":
            return self.handle_workflow_lock(context)

        elif node_type == "GetCustomFile":
            return self.handle_get_custom_file(context)

        elif node_type == "SaveCustomFile":
            return self.handle_save_custom_file(context)

        elif node_type == "ImageProcessor":
            return self.handle_image_processor_node(context)

        elif node_type == "StaticResponse":
            return self.handle_static_response(context)

        raise ValueError(f"Unknown specialized node type: {node_type}")

    def _stream_static_content(self, content: str) -> Generator[Dict[str, Any], None, None]:
        """
        A generator that yields a static string word by word to simulate a stream.
        This mimics the raw output format of an LLM API handler.
        """
        words = content.split()
        if not words:
            yield {'token': '', 'finish_reason': 'stop'}
            return

        words_per_second = 50
        delay = 1.0 / words_per_second

        for word in words:
            time.sleep(delay)
            # Yield in the standardized dictionary format expected by the WorkflowProcessor
            yield {'token': word + ' ', 'finish_reason': None}

        # Signal the end of the stream
        yield {'token': '', 'finish_reason': 'stop'}

    def handle_static_response(self, context: ExecutionContext) -> Any:
        """
        Handles the logic for a "StaticResponse" node.

        Returns a hardcoded string, resolving any workflow variables within it.
        If streaming is enabled for the node, it returns a generator that
        yields the string word-by-word.
        """
        content_template = context.config.get("content", "")

        resolved_content = self.workflow_variable_service.apply_variables(
            content_template, context
        )

        if context.stream:
            logger.debug("Returning static content as a stream.")
            return self._stream_static_content(resolved_content)
        else:
            logger.debug("Returning static content as a single string.")
            return resolved_content

    def handle_workflow_lock(self, context: ExecutionContext) -> None:
        """
        Handles the logic for a "WorkflowLock" node.

        This method checks for an existing lock. If a lock is found, it raises an
        EarlyTerminationException to stop the workflow. Otherwise, it acquires a new lock.

        Args:
            context (ExecutionContext): The central object containing all runtime data for the node.

        Raises:
            ValueError: If the 'workflowLockId' is missing from the node configuration.
            EarlyTerminationException: If an active lock is found for the specified ID.
        """
        workflow_lock_id = context.config.get("workflowLockId")
        if not workflow_lock_id:
            raise ValueError("A WorkflowLock node must have a 'workflowLockId'.")

        if self.locking_service.get_lock(workflow_lock_id):
            logger.info(f"Lock for {workflow_lock_id} is active, terminating workflow.")
            raise EarlyTerminationException(f"Workflow is locked by {workflow_lock_id}.")
        else:
            self.locking_service.create_node_lock(instance_global_variables.INSTANCE_ID, context.workflow_id,
                                                  workflow_lock_id)
            logger.info(
                f"Lock for {workflow_lock_id} acquired by Instance '{instance_global_variables.INSTANCE_ID}' / Workflow '{context.workflow_id}'.")

    def handle_get_custom_file(self, context: ExecutionContext) -> str:
        """
        Handles the logic for a "GetCustomFile" node by loading a file's content.

        Args:
            context (ExecutionContext): The central object containing all runtime data for the node.

        Returns:
            str: The content of the specified file, processed with the given delimiters.
        """
        filepath = context.config.get("filepath")
        if not filepath:
            return "No filepath specified"

        delimiter = context.config.get("delimiter")
        custom_return_delimiter = context.config.get("customReturnDelimiter")

        if delimiter is None:
            delimiter = custom_return_delimiter if custom_return_delimiter is not None else "\n"
        if custom_return_delimiter is None:
            custom_return_delimiter = delimiter

        return load_custom_file(filepath=filepath, delimiter=delimiter, custom_delimiter=custom_return_delimiter)

    def handle_save_custom_file(self, context: ExecutionContext) -> str:
        """
        Handles the logic for a "SaveCustomFile" node by saving content to a file.

        Args:
            context (ExecutionContext): The central object containing all runtime data for the node.

        Returns:
            str: A message indicating the result of the save operation.
        """
        filepath = context.config.get("filepath")
        if not filepath:
            return "No filepath specified"

        content_template = context.config.get("content")
        if content_template is None:
            return "No content specified"

        # Resolve any workflow variables within the content
        resolved_content = self.workflow_variable_service.apply_variables(
            content_template, context
        )

        try:
            save_custom_file(filepath=filepath, content=resolved_content)
            return f"File successfully saved to {filepath}"
        except Exception as e:
            logger.error(f"Failed to save file to {filepath}. Error: {e}")
            return f"Error saving file: {e}"

    def handle_image_processor_node(self, context: ExecutionContext) -> str:
        """
        Handles the logic for an "ImageProcessor" node.

        This method extracts images from the conversation history, sends them to a vision
        LLM for analysis, and returns the combined descriptions. It can optionally
        insert these descriptions back into the conversation history as a new user message.

        Args:
            context (ExecutionContext): The central object containing all runtime data for the node.

        Returns:
            str: A consolidated string of all image descriptions generated by the vision LLM.
        """
        text_messages = [msg for msg in context.messages if msg.get("role") != "images"]
        image_messages = [msg for msg in context.messages if msg.get("role") == "images"]
        if not image_messages:
            logger.debug("No images found in conversation.")
            return "There were no images attached to the message"

        llm_responses = []
        for img_msg in image_messages:
            # Create a deep copy of the context to avoid side effects.
            temp_context = deepcopy(context)
            # Set the messages for this specific call to include all text context
            # plus the single image being processed.
            temp_context.messages = text_messages + [img_msg]

            response = LLMDispatchService.dispatch(context=temp_context, image_message=img_msg)
            llm_responses.append(response)

        image_descriptions = "\n-------------\n".join(filter(None, llm_responses))

        if context.config.get("addAsUserMessage", False):
            message_template = context.config.get("message",
                                                  "[SYSTEM: The user recently added one or more images to the conversation. "
                                                  "The images have been analyzed by an advanced vision AI, which has described them"
                                                  " in detail. The descriptions of the images can be found below:\n\n"
                                                  "<vision_llm_response>\n[IMAGE_BLOCK]\n</vision_llm_response>]")

            final_message = self.workflow_variable_service.apply_variables(message_template, context)
            final_message = final_message.replace("[IMAGE_BLOCK]", image_descriptions)

            # Insert before the last message (which is usually the user's prompt)
            insert_index = len(context.messages) - 1 if len(context.messages) > 1 else len(context.messages)
            context.messages.insert(insert_index, {"role": "user", "content": final_message})

        return image_descriptions
