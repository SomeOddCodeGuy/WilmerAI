# /Middleware/workflows/handlers/impl/specialized_node_handler.py

import logging
import re
from copy import deepcopy
from typing import Any, Union, List

from Middleware.common import instance_global_variables
from Middleware.exceptions.early_termination_exception import EarlyTerminationException
from Middleware.services.llm_dispatch_service import LLMDispatchService
from Middleware.services.locking_service import LockingService
from Middleware.utilities.file_utils import load_custom_file, save_custom_file
from Middleware.utilities.streaming_utils import stream_static_content
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

        Raises:
            ValueError: If the node 'type' is unknown or not handled by this class.
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
        elif node_type == "ArithmeticProcessor":
            return self.handle_arithmetic_processor(context)
        elif node_type == "Conditional":
            return self.handle_conditional(context)
        elif node_type == "StringConcatenator":
            return self.handle_string_concatenator(context)

        raise ValueError(f"Unknown specialized node type: {node_type}")

    def _parse_operand(self, s: str) -> Union[float, str, bool]:
        """
        Parses a string operand into its appropriate Python type.

        This helper function converts a string from a conditional expression into a float,
        a boolean (for "TRUE" or "FALSE"), or a string. It strips quotes from
        string literals.

        Args:
            s (str): The string operand to parse.

        Returns:
            Union[float, str, bool]: The parsed operand in its inferred type.
        """
        s = s.strip()
        s_upper = s.upper()

        if s_upper == 'TRUE':
            return True
        if s_upper == 'FALSE':
            return False

        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            return s[1:-1]
        try:
            return float(s)
        except ValueError:
            return s

    def handle_static_response(self, context: ExecutionContext) -> Any:
        """
        Handles the logic for a "StaticResponse" node.

        This method returns a hardcoded string from the node's 'content' field after
        resolving any workflow variables. If streaming is enabled for the workflow,
        it returns a generator that yields the content word-by-word.

        Args:
            context (ExecutionContext): The central object containing all runtime data for the node.

        Returns:
            Any: The resolved content as a single string or a generator for streaming.
        """
        content_template = context.config.get("content", "")

        resolved_content = self.workflow_variable_service.apply_variables(
            content_template, context
        )

        if context.stream:
            logger.debug("Returning static content as a stream.")
            return stream_static_content(resolved_content)
        else:
            logger.debug("Returning static content as a single string.")
            return resolved_content

    def handle_arithmetic_processor(self, context: ExecutionContext) -> str:
        """
        Handles the logic for an "ArithmeticProcessor" node.

        This method evaluates a simple arithmetic expression (e.g., "10 + 5", "{agent1Output} / 2")
        from the node's 'expression' field. It returns the result as a string, or "-1"
        if the expression is invalid, malformed, or results in an error like division by zero.

        Args:
            context (ExecutionContext): The central object containing all runtime data for the node.

        Returns:
            str: The result of the calculation as a string, or "-1" on failure.
        """
        expression_template = context.config.get("expression")
        if not expression_template:
            logger.warning("ArithmeticProcessor node is missing 'expression'.")
            return "-1"

        resolved_expression = self.workflow_variable_service.apply_variables(
            expression_template, context
        ).strip()

        try:
            match = re.match(r'^(-?\d+(?:\.\d+)?)\s*([+\-*/])\s*(-?\d+(?:\.\d+)?)$', resolved_expression)
            if not match:
                logger.warning(
                    f"Invalid arithmetic expression format: '{resolved_expression}'. Expected 'number operator number'.")
                return "-1"

            num1_str, operator, num2_str = match.groups()
            num1 = float(num1_str)
            num2 = float(num2_str)

            result = 0.0
            if operator == '+':
                result = num1 + num2
            elif operator == '-':
                result = num1 - num2
            elif operator == '*':
                result = num1 * num2
            elif operator == '/':
                if num2 == 0:
                    logger.warning(f"Division by zero in expression: '{resolved_expression}'")
                    return "-1"
                result = num1 / num2

            if result.is_integer():
                return str(int(result))
            return str(result)

        except (ValueError, TypeError):
            logger.warning(f"Could not parse numbers in expression: '{resolved_expression}'")
            return "-1"

    def handle_conditional(self, context: ExecutionContext) -> str:
        """
        Handles the logic for a "Conditional" node.

        This method evaluates a potentially complex logical expression from the node's
        'condition' field. The expression can include comparisons, AND/OR operators,
        and parentheses. It returns "TRUE" or "FALSE" as a string based on the outcome.

        Args:
            context (ExecutionContext): The central object containing all runtime data for the node.

        Returns:
            str: "TRUE" if the condition evaluates to true, "FALSE" otherwise.
        """
        condition_template = context.config.get("condition")
        if not condition_template:
            logger.warning("Conditional node is missing 'condition'.")
            logger.info("Conditional node failed. Returning FALSE")
            return "FALSE"

        resolved_condition = self.workflow_variable_service.apply_variables(
            condition_template, context
        )

        try:
            result = self._evaluate_logical_expression(resolved_condition)
            if result:
                logger.info("Conditional node returned TRUE.")
                return "TRUE"
            else:
                logger.info("Conditional node returned FALSE.")
                return "FALSE"
        except Exception as e:
            logger.warning(f"Error evaluating condition '{resolved_condition}': {e}")
            logger.info("Conditional node failed. Returning FALSE")
            return "FALSE"

    def _evaluate_logical_expression(self, expression: str) -> bool:
        """
        Evaluates a complete logical expression string.

        This method orchestrates the conversion from infix notation to Reverse
        Polish Notation (RPN) and then evaluates the RPN queue to get the final
        boolean result.

        Args:
            expression (str): The logical expression to evaluate.

        Returns:
            bool: The result of the evaluated expression.
        """
        rpn_queue = self._infix_to_rpn(expression)
        return self._evaluate_rpn(rpn_queue)

    def _infix_to_rpn(self, expression: str) -> List[Any]:
        """
        Converts an infix logical expression to Reverse Polish Notation (RPN).

        This method implements the Shunting-yard algorithm to correctly handle operator
        precedence (AND before OR) and parentheses, producing an RPN queue
        that can be evaluated sequentially.

        Args:
            expression (str): The infix expression string.

        Returns:
            List[Any]: A list representing the expression in RPN.

        Raises:
            ValueError: If the expression has mismatched parentheses or a syntax error.
        """
        precedence = {'OR': 1, 'AND': 2}

        token_regex = re.compile(r"""
            \s*(
            \d+(?:\.\d+)?|       # Numbers (int or float)
            '[^']*'|             # Single-quoted strings
            "[^"]*"|             # Double-quoted strings
            ==|!=|>=|<=|>|<|     # Comparison operators
            \(|\)|               # Parentheses
            \bAND\b|\bOR\b|      # Logical operators (case-insensitive due to re.I)
            [a-zA-Z_][a-zA-Z0-9_]* # Words (for TRUE, FALSE, or variable outputs)
            )\s*
        """, re.VERBOSE | re.IGNORECASE)

        tokens = [token for token in token_regex.findall(expression) if token]

        output_queue = []
        operator_stack = []

        # This is a temporary list to buffer a comparison (e.g., [value, operator, value])
        comp_buffer = []

        def flush_comp_buffer():
            nonlocal comp_buffer
            if not comp_buffer:
                return
            if len(comp_buffer) == 1:
                output_queue.append(self._parse_operand(comp_buffer[0]))
            elif len(comp_buffer) == 3:
                output_queue.append(tuple(comp_buffer))
            else:
                raise ValueError(f"Invalid comparison format: {' '.join(comp_buffer)}")
            comp_buffer = []

        for token in tokens:
            token_upper = token.upper()

            if token not in ['(', ')', '==', '!=', '>=', '<=', '>', '<'] and token_upper not in ['AND', 'OR']:
                comp_buffer.append(token)
            elif token in ['==', '!=', '>=', '<=', '>', '<']:
                if len(comp_buffer) != 1:
                    raise ValueError(f"Syntax error: Operator '{token}' must follow a single value.")
                comp_buffer.append(token)
            elif token == '(':
                flush_comp_buffer()
                operator_stack.append(token)
            elif token == ')':
                flush_comp_buffer()
                while operator_stack and operator_stack[-1] != '(':
                    output_queue.append(operator_stack.pop())
                if not operator_stack or operator_stack.pop() != '(':
                    raise ValueError("Mismatched parentheses: missing '('")
            elif token_upper in ['AND', 'OR']:
                flush_comp_buffer()
                while (operator_stack and operator_stack[-1] != '(' and
                       precedence.get(operator_stack[-1].upper(), 0) >= precedence[token_upper]):
                    output_queue.append(operator_stack.pop())
                operator_stack.append(token)

        flush_comp_buffer()

        while operator_stack:
            op = operator_stack.pop()
            if op == '(':
                raise ValueError("Mismatched parentheses: missing ')'")
            output_queue.append(op)

        return output_queue

    def _evaluate_rpn(self, rpn_queue: List[Any]) -> bool:
        """
        Evaluates an expression in Reverse Polish Notation (RPN).

        This method processes an RPN queue, using a stack to perform comparisons
        and logical operations in the correct order to arrive at a final boolean result.

        Args:
            rpn_queue (List[Any]): The expression represented as an RPN queue.

        Returns:
            bool: The final boolean result of the expression.

        Raises:
            ValueError: If the RPN queue is malformed or has insufficient operands for an operator.
        """
        value_stack = []

        for token in rpn_queue:
            if isinstance(token, tuple):  # It's a comparison tuple
                lhs = self._parse_operand(token[0])
                op = token[1]
                rhs = self._parse_operand(token[2])
                value_stack.append(self._perform_comparison(lhs, op, rhs))
            elif isinstance(token, str) and token.upper() in ['AND', 'OR']:
                if len(value_stack) < 2:
                    raise ValueError(f"Syntax error: Not enough operands for '{token}'")
                rhs = bool(value_stack.pop())
                lhs = bool(value_stack.pop())
                if token.upper() == 'AND':
                    value_stack.append(lhs and rhs)
                else:  # OR
                    value_stack.append(lhs or rhs)
            else:  # It's a single operand
                value_stack.append(bool(token))

        if len(value_stack) != 1:
            raise ValueError("Invalid expression format.")

        return value_stack[0]

    def _perform_comparison(self, lhs, op, rhs) -> bool:
        """
        Performs a single comparison between two operands.

        This helper function handles ==, !=, >, <, >=, and <= comparisons. It gracefully
        handles type mismatches (e.g., comparing a number and a string) by returning False
        for invalid comparisons instead of raising an error.

        Args:
            lhs (Any): The left-hand side operand.
            op (str): The comparison operator string.
            rhs (Any): The right-hand side operand.

        Returns:
            bool: The result of the comparison.
        """
        try:
            if op == '==': return lhs == rhs
            if op == '!=': return lhs != rhs
            if isinstance(lhs, (int, float)) and isinstance(rhs, (int, float)):
                if op == '>': return lhs > rhs
                if op == '<': return lhs < rhs
                if op == '>=': return lhs >= rhs
                if op == '<=': return lhs <= rhs
            return False
        except TypeError:
            return False

    def handle_string_concatenator(self, context: ExecutionContext) -> Any:
        """
        Handles the logic for a "StringConcatenator" node.

        This method joins a list of strings from the 'strings' field using a specified
        'delimiter'. It resolves variables in each string before concatenation. If streaming
        is enabled, it returns the final string as a word-by-word generator.

        Args:
            context (ExecutionContext): The central object containing all runtime data for the node.

        Returns:
            Any: The concatenated string or a generator for streaming.
        """
        strings_template = context.config.get("strings", [])
        delimiter = context.config.get("delimiter", "")

        if not isinstance(strings_template, list):
            logger.warning("StringConcatenator 'strings' property must be a list.")
            return ""

        resolved_strings = []
        for item_template in strings_template:
            if isinstance(item_template, str):
                resolved_item = self.workflow_variable_service.apply_variables(
                    item_template, context
                )
                resolved_strings.append(resolved_item)
            else:
                resolved_strings.append(str(item_template))

        concatenated_string = delimiter.join(resolved_strings)

        if context.stream:
            logger.debug("Returning concatenated string as a stream.")
            return stream_static_content(concatenated_string)
        else:
            logger.debug("Returning concatenated string as a single string.")
            return concatenated_string

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
        Handles the logic for a "GetCustomFile" node.

        This method loads the content of a text file specified by the 'filepath' field.
        It reads the file and returns its content as a single string.

        Args:
            context (ExecutionContext): The central object containing all runtime data for the node.

        Returns:
            str: The content of the file, or an error message if the filepath is not specified.
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
        Handles the logic for a "SaveCustomFile" node.

        This method saves the provided 'content' to a file specified by 'filepath'.
        It resolves any variables in the content and filepath before writing the file.

        Args:
            context (ExecutionContext): The central object containing all runtime data for the node.

        Returns:
            str: A success or error message indicating the result of the save operation.
        """
        filepath = context.config.get("filepath")
        if not filepath:
            return "No filepath specified"

        content_template = context.config.get("content")
        if content_template is None:
            return "No content specified"

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

        This method processes images attached to the user's message. It uses a vision-capable
        LLM to generate a text description for each image. The combined descriptions are returned
        and can optionally be inserted back into the conversation history as a new user message.

        Args:
            context (ExecutionContext): The central object containing all runtime data for the node.

        Returns:
            str: The combined text descriptions of all processed images, or a message indicating no images were found.
        """
        text_messages = [msg for msg in context.messages if msg.get("role") != "images"]
        image_messages = [msg for msg in context.messages if msg.get("role") == "images"]
        if not image_messages:
            logger.debug("No images found in conversation.")
            return "There were no images attached to the message"

        llm_responses = []
        for img_msg in image_messages:
            temp_context = deepcopy(context)
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

            insert_index = len(context.messages) - 1 if len(context.messages) > 1 else len(context.messages)
            context.messages.insert(insert_index, {"role": "user", "content": final_message})

        return image_descriptions