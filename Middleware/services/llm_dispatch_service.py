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
from Middleware.workflows.models.execution_context import ExecutionContext

logger = logging.getLogger(__name__)


class LLMDispatchService:
    """
    Formats prompts based on API type and dispatches them to an LLM handler.

    This service is the single point of contact between the workflow layer and the
    underlying LLM API handlers. It reads the ExecutionContext to determine whether
    the target endpoint expects a chat-completion message collection or a single
    prompt string, applies variable substitution, and then calls the appropriate
    method on the handler.
    """

    @staticmethod
    def _apply_image_limit(messages, max_images):
        """Keep only the most recent *max_images* images across *messages*.

        Walks from newest to oldest message, counting images.  Once the
        budget is exhausted, images are removed from older messages.
        Modifies *messages* in place.

        Args:
            messages (list): The message list to modify in place.
            max_images (int): Maximum number of images to keep. 0 or less means no limit.
        """
        if max_images <= 0:
            return
        remaining = max_images
        for msg in reversed(messages):
            images = msg.get("images")
            if not images:
                continue
            if remaining <= 0:
                del msg["images"]
            elif len(images) <= remaining:
                remaining -= len(images)
            else:
                msg["images"] = images[-remaining:]
                remaining = 0

    @staticmethod
    def _merge_consecutive_assistant_messages(messages, delimiter="\n"):
        """Merge runs of consecutive assistant messages into a single message.

        Only fires on direct assistant-to-assistant adjacency.  The standard
        tool-call sequence (assistant with tool_calls -> tool -> assistant) is
        NOT considered consecutive because the tool-role message separates
        them.

        Content from each message in a run is joined with *delimiter*.
        Non-content keys (``tool_calls``, ``images``, etc.) from the first
        message in a run are preserved; subsequent messages' extra keys are
        discarded.

        Args:
            messages (list): The message list to modify in place.
            delimiter (str): String used to join content from consecutive assistant messages.
        """
        if len(messages) < 2:
            return
        merged = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            if msg.get("role") != "assistant":
                merged.append(msg)
                i += 1
                continue
            run_contents = [msg.get("content", "")]
            j = i + 1
            while j < len(messages) and messages[j].get("role") == "assistant":
                run_contents.append(messages[j].get("content", ""))
                j += 1
            if j - i > 1:
                # Merge: keep the first message's dict, replace content
                combined = {**msg, "content": delimiter.join(run_contents)}
                merged.append(combined)
            else:
                merged.append(msg)
            i = j
        messages[:] = merged

    @staticmethod
    def _insert_user_turns_between_assistant_messages(messages, text="Continue."):
        """Insert a synthetic user message between consecutive assistant messages.

        Only fires on direct assistant-to-assistant adjacency.  The standard
        tool-call sequence (assistant with tool_calls -> tool -> assistant) is
        NOT considered consecutive because the tool-role message separates
        them.

        Args:
            messages (list): The message list to modify in place.
            text (str): Content for the inserted synthetic user messages.
        """
        if len(messages) < 2:
            return
        result = [messages[0]]
        for i in range(1, len(messages)):
            if (messages[i].get("role") == "assistant"
                    and messages[i - 1].get("role") == "assistant"):
                result.append({"role": "user", "content": text})
            result.append(messages[i])
        messages[:] = result

    @staticmethod
    def _ensure_user_message_present(collection, full_messages):
        """Ensure the collection contains at least one user-role message.

        When ``lastMessagesToSendInsteadOfPrompt`` selects a window of only
        assistant and tool messages (common in agentic tool-calling flows),
        backend chat templates may reject the request because they require at
        least one user message.  This method finds the most recent user
        message from the full conversation and inserts it after any leading
        system messages.

        No-op if a user message already exists or if the full conversation
        contains no user messages.

        Args:
            collection (list): The message list to modify in place.
            full_messages (list): The complete conversation history to search for a user message.
        """
        if any(m.get("role") == "user" for m in collection):
            return

        last_user_msg = None
        for msg in reversed(full_messages):
            if msg.get("role") == "user":
                last_user_msg = msg
                break

        if last_user_msg is None:
            return

        insert_pos = 0
        for i, msg in enumerate(collection):
            if msg.get("role") == "system":
                insert_pos = i + 1
            else:
                break

        collection.insert(insert_pos, dict(last_user_msg))

    @staticmethod
    def dispatch(
            context: ExecutionContext,
            llm_takes_images: bool = False,
            max_images: int = 0
    ) -> Any:
        """
        Prepares prompts and dispatches them to the configured LLM handler.

        Args:
            context (ExecutionContext): The context object containing all runtime state.
            llm_takes_images (bool): If True, images on messages are preserved for the LLM.
            max_images (int): Maximum number of images to send.  0 means no limit.

        Returns:
            Any: The raw response from the LLM handler (e.g., a string or a generator).
        """
        # All required data is now pulled from the context object
        llm_handler = context.llm_handler
        config = context.config

        workflow_variable_service = context.workflow_variable_service

        message_copy = deepcopy(context.messages)

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

        # Determine whether this node should receive tool definitions.
        # Only nodes with "allowTools": true in their config will forward
        # tools to the LLM; all others (memory nodes, summarizers, etc.)
        # silently suppress them so the LLM doesn't attempt tool calls.
        allow_tools = config.get("allowTools", False)
        tools_to_send = context.tools if allow_tools else None
        tool_choice_to_send = context.tool_choice if allow_tools else None

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

            return llm_handler.llm.get_response_from_llm(
                conversation=None, system_prompt=system_prompt,
                prompt=prompt, llm_takes_images=llm_takes_images,
                request_id=getattr(context, 'request_id', None),
                tools=tools_to_send,
                tool_choice=tool_choice_to_send,
            )
        else:
            # === CHAT API LOGIC ===
            collection = []
            if system_prompt:
                collection.append({"role": "system", "content": system_prompt})

            if use_last_n_messages:
                last_messages_to_send = config.get("lastMessagesToSendInsteadOfPrompt", 5)
                last_n_turns = extract_last_n_turns(message_copy, last_messages_to_send, True)
                if llm_takes_images and max_images > 0:
                    LLMDispatchService._apply_image_limit(last_n_turns, max_images)
                collection.extend(last_n_turns)

                # Normalize consecutive assistant messages if configured.
                # Merge takes precedence if both are enabled.
                if config.get("mergeConsecutiveAssistantMessages", False):
                    delimiter = config.get("mergeConsecutiveAssistantMessagesDelimiter", "\n")
                    LLMDispatchService._merge_consecutive_assistant_messages(collection, delimiter)
                elif config.get("insertUserTurnBetweenAssistantMessages", False):
                    insert_text = config.get("insertedUserTurnText", "Continue.")
                    LLMDispatchService._insert_user_turns_between_assistant_messages(
                        collection, insert_text
                    )

                # Safety net: if the message window contains no user messages
                # (common in long agentic tool-calling chains where tool-role
                # messages separate assistants), insert the most recent user
                # message from the full conversation so backend chat templates
                # that require a user query don't reject the request.
                LLMDispatchService._ensure_user_message_present(collection, message_copy)
            else:
                user_msg = {"role": "user", "content": prompt}
                if llm_takes_images:
                    # When dispatching via a text prompt string (rather than the full
                    # conversation), image data is not embedded in the prompt text.
                    # Images must be gathered from recent messages and attached
                    # explicitly to the outgoing user message; otherwise they are
                    # silently dropped and the vision-capable LLM never sees them.
                    image_lookback = config.get("lastMessagesToSendInsteadOfPrompt", 10)
                    all_images = []
                    for msg in message_copy[-image_lookback:]:
                        if "images" in msg and msg["images"]:
                            all_images.extend(msg["images"])
                    if max_images > 0:
                        all_images = all_images[-max_images:]
                    if all_images:
                        user_msg["images"] = all_images
                collection.append(user_msg)

            return llm_handler.llm.get_response_from_llm(
                conversation=collection, llm_takes_images=llm_takes_images,
                request_id=getattr(context, 'request_id', None),
                tools=tools_to_send,
                tool_choice=tool_choice_to_send,
            )
