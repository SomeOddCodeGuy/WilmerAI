# /Middleware/services/llm_dispatch_service.py

import logging
from copy import deepcopy
from typing import Dict, Any, Optional, List

from Middleware.utilities.prompt_template_utils import (
    format_user_turn_with_template, add_assistant_end_token_to_user_turn,
    format_system_prompt_with_template, get_formatted_last_n_turns_as_string,
    format_assistant_turn_with_template
)
from Middleware.utilities.prompt_extraction_utils import extract_last_n_turns

logger = logging.getLogger(__name__)


class LLMDispatchService:
    """
    A stateless service to prepare prompts and dispatch them to an LLM handler.

    This service is responsible for formatting prompts and messages
    based on the LLM API type (chat vs. completions) and dispatching
    them to the appropriate LLM handler for processing.
    """

    @staticmethod
    def dispatch(
            llm_handler: Any,
            workflow_variable_service: Any,
            config: Dict,
            messages: List[Dict[str, str]],
            agent_outputs: Optional[Dict],
            image_message: Optional[Dict] = None
    ) -> Any:
        """
        Prepares inputs and calls the LLM, handling both chat and completion APIs.

        This method applies variables to prompts, formats the conversation
        based on the LLM's API type (chat or completions), and dispatches
        the final payload to the `llm_handler` to get a response.

        Args:
            llm_handler (Any): The LLM API handler (e.g., OllamaChatHandler).
            workflow_variable_service (Any): The service to apply variables to prompts.
            config (Dict): The workflow node configuration.
            messages (List[Dict[str, str]]): The conversation history as a list of
                                             role/content dictionaries.
            agent_outputs (Optional[Dict]): A dictionary of outputs from previous
                                            non-responding nodes in the workflow.
            image_message (Optional[Dict]): An optional message containing image data.

        Returns:
            Any: The response from the LLM, which can be a string, a stream of
                 events, or another data type depending on the LLM handler.
        """
        message_copy = deepcopy(messages)
        llm_takes_images = llm_handler.takes_image_collection

        # 1. Get and apply variables to base prompts from the node config
        system_prompt = workflow_variable_service.apply_variables(
            prompt=config.get("systemPrompt", ""), llm_handler=llm_handler,
            messages=message_copy, agent_outputs=agent_outputs, config=config
        )
        prompt = config.get("prompt", "")
        if prompt:
            prompt = workflow_variable_service.apply_variables(
                prompt=prompt, llm_handler=llm_handler, messages=message_copy,
                agent_outputs=agent_outputs, config=config
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
                prompt=prompt, llm_takes_images=llm_takes_images
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
                conversation=collection, llm_takes_images=llm_takes_images
            )