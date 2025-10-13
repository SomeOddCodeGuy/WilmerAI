# /Middleware/services/llm_dispatch_service.py

import logging
from copy import deepcopy
from typing import Dict, Any, Optional

from Middleware.utilities.prompt_extraction_utils import extract_last_n_turns
from Middleware.utilities.prompt_template_utils import (
    format_user_turn_with_template, add_assistant_end_token_to_user_turn,
    format_system_prompt_with_template, get_formatted_last_n_turns_as_string,
    format_assistant_turn_with_template
)
# Import the new context object
from Middleware.workflows.models.execution_context import ExecutionContext

logger = logging.getLogger(__name__)


class LLMDispatchService:
    """Formats prompts based on API type and dispatches them to an LLM handler."""

    @staticmethod
    def dispatch(
            context: ExecutionContext,
            image_message: Optional[Dict] = None
    ) -> Any:
        """
        Prepares prompts and dispatches them to the configured LLM handler.

        Args:
            context (ExecutionContext): The context object containing all runtime state.
            image_message (Optional[Dict]): An optional message containing image data.

        Returns:
            Any: The raw response from the LLM handler (e.g., a string or a generator).
        """
        # All required data is now pulled from the context object
        llm_handler = context.llm_handler
        config = context.config

        workflow_variable_service = context.workflow_variable_service

        message_copy = deepcopy(context.messages)
        llm_takes_images = llm_handler.takes_image_collection

        # 1. Get and apply variables to base prompts from the node config
        system_prompt = workflow_variable_service.apply_variables(
            prompt=config.get("systemPrompt", ""),
            context=context  # Pass the whole context
        )

        prompt = config.get("prompt", "")
        if prompt:
            prompt = workflow_variable_service.apply_variables(
                prompt=prompt,
                context=context  # Pass the whole context
            )
            use_last_n_messages = False
        else:
            use_last_n_messages = True

        # 2. Prepare inputs and call LLM based on API type
        if not llm_handler.takes_message_collection:
            # === COMPLETIONS API LOGIC ===
            if use_last_n_messages:
                last_messages_to_send = config.get("lastMessagesToSendInsteadOfPrompt", 5)
                prompt = get_formatted_last_n_turns_as_string(
                    message_copy, last_messages_to_send + 1,
                    template_file_name=llm_handler.prompt_template_file_name,
                    isChatCompletion=False
                )
            if config.get("addUserTurnTemplate"):
                prompt = format_user_turn_with_template(prompt, llm_handler.prompt_template_file_name, False)
            if config.get("addOpenEndedAssistantTurnTemplate"):
                prompt = format_assistant_turn_with_template(prompt, llm_handler.prompt_template_file_name, False)
            if llm_handler.add_generation_prompt:
                prompt = add_assistant_end_token_to_user_turn(prompt, llm_handler.prompt_template_file_name, False)

            system_prompt = format_system_prompt_with_template(
                system_prompt, llm_handler.prompt_template_file_name, False)

            conversation_arg = [image_message] if image_message else None

            return llm_handler.llm.get_response_from_llm(
                conversation=conversation_arg, system_prompt=system_prompt,
                prompt=prompt, llm_takes_images=llm_takes_images,
                request_id=getattr(context, 'request_id', None)
            )
        else:
            # === CHAT API LOGIC ===
            collection = []
            if system_prompt:
                collection.append({"role": "system", "content": system_prompt})

            if use_last_n_messages:
                last_messages_to_send = config.get("lastMessagesToSendInsteadOfPrompt", 5)
                last_n_turns = extract_last_n_turns(message_copy, last_messages_to_send, True)
                collection.extend(last_n_turns)
            else:
                collection.append({"role": "user", "content": prompt})

            if image_message:
                collection.append(image_message)

            return llm_handler.llm.get_response_from_llm(
                conversation=collection, llm_takes_images=llm_takes_images,
                request_id=getattr(context, 'request_id', None)
            )
