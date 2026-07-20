# /Middleware/services/llm_dispatch_service.py

import json
import logging
from typing import Any, List, Optional, Tuple

from Middleware.utilities.prompt_extraction_utils import (
    extract_last_n_turns,
    extract_last_turns_by_estimated_token_limit,
)
from Middleware.utilities.prompt_template_utils import (
    format_user_turn_with_template, add_assistant_end_token_to_user_turn,
    format_system_prompt_with_template, get_formatted_last_n_turns_as_string,
    format_assistant_turn_with_template
)
from Middleware.utilities.config_utils import (
    get_estimation_level_multiplier,
    is_context_clamp_enabled,
    compute_endpoint_window_budget,
    CONTEXT_CLAMP_KEY,
    CONTEXT_WINDOW_BUDGET_HEADROOM_TOKENS,
    ESTIMATION_LEVEL_KEY,
    DEFAULT_ESTIMATION_LEVEL,
)
from Middleware.utilities.structured_output_utils import (
    build_tool_calls_result,
    build_tool_enforcement_schema,
    build_tools_description_text,
    get_structured_output_config,
    load_structured_output_schema,
    parse_constrained_tool_response,
)
from Middleware.utilities.text_utils import rough_estimate_token_length
from Middleware.workflows.models.execution_context import ExecutionContext

logger = logging.getLogger(__name__)

# --- Pre-send context clamp tuning -------------------------------------------------
# Tokens held back from the endpoint window when computing the conversation budget,
# to cover chat-template framing (BOS/EOS, the trailing generation prompt, role
# headers) and estimation slack not captured by message content alone. Aliased from
# config_utils so dispatch and the variable manager reserve the same headroom.
_CLAMP_HEADROOM_TOKENS = CONTEXT_WINDOW_BUDGET_HEADROOM_TOKENS
# Per-message overhead added to each message's estimated content size to account for
# chat-template role/delimiter tokens (e.g. <|start_header_id|>role<|end_header_id|>
# ... <|eot_id|>) that wrap every message but are not part of its content string.
_CLAMP_PER_MESSAGE_OVERHEAD_TOKENS = 8

# Config key that turns the pre-send context clamp on (resolved per node by the
# shared config_utils.is_context_clamp_enabled: node > endpoint > user > default OFF,
# so dispatch and the variable manager cannot drift). OFF by default so an upgrade
# never silently trims an existing config; the shipped user configs opt in. (Note:
# this clamp DOES change the outgoing payload by trimming messages, it is a Wilmer
# behavior toggle, not a model parameter.) Aliased here only for the user-facing log
# strings below.
_CLAMP_ENABLED_KEY = CONTEXT_CLAMP_KEY

# The per-endpoint estimation level (wilmerContextEstimationLevel) that scales the
# real (window - n_predict) portion of the budget lives in config_utils, since it
# applies to every endpoint-derived token budget (not just dispatch): see
# config_utils.get_estimation_level_multiplier and ESTIMATION_LEVEL_KEY /
# DEFAULT_ESTIMATION_LEVEL, imported above.


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
    def _gather_recent_images(messages, config, max_images):
        """Collect image data from the most recent messages.

        Used on the dispatch paths that send a text prompt string rather than
        the conversation itself: the prompt cannot carry image data, so images
        must be gathered from recent messages and attached explicitly or the
        vision-capable LLM never sees them.

        Args:
            messages (list): The full conversation messages.
            config (dict): The node config; its lastMessagesToSendInsteadOfPrompt
                bounds how far back to look (default 5, matching the completions
                text window so images never come from messages whose text is not
                in the prompt).
            max_images (int): Maximum number of images to return. 0 means no limit.

        Returns:
            list: The gathered base64 image strings, oldest first.
        """
        image_lookback = config.get("lastMessagesToSendInsteadOfPrompt", 5)
        all_images = []
        for msg in messages[-image_lookback:]:
            if "images" in msg and msg["images"]:
                all_images.extend(msg["images"])
        if max_images > 0:
            all_images = all_images[-max_images:]
        return all_images

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
    def _estimate_tokens_for_tools(tools) -> int:
        """Estimate the token cost of forwarded tool definitions.

        Tool schemas are sent to the backend and count against the context
        window, so they must be subtracted from the conversation budget on
        tool-enabled nodes. Estimated by serializing the tool list to JSON and
        running it through ``rough_estimate_token_length`` (which overestimates).

        Args:
            tools: The tool definition list (OpenAI format), or None.

        Returns:
            int: Estimated token count, or 0 when there are no tools.
        """
        if not tools:
            return 0
        try:
            serialized = json.dumps(tools)
        except (TypeError, ValueError):
            return 0
        return rough_estimate_token_length(serialized)

    @staticmethod
    def _estimate_collection_tokens(messages) -> int:
        """Sum the estimated content tokens across a message list.

        Used only to report the before/after size when the clamp reduces a
        conversation (the INFO line); it is not part of the budget math.

        Args:
            messages (list): The message list to measure.

        Returns:
            int: The summed estimated token count of the message contents.
        """
        return sum(rough_estimate_token_length(m.get("content") or "") for m in messages)

    @staticmethod
    def _context_clamp_enabled(context) -> bool:
        """Resolve whether the pre-send context clamp is on for this node.

        Delegates to the shared ``config_utils.is_context_clamp_enabled`` (node >
        endpoint > user > default OFF) so dispatch and the workflow variable manager
        gate on the clamp identically.

        Args:
            context (ExecutionContext): The node execution context.

        Returns:
            bool: True if the clamp should run for this dispatch.
        """
        endpoint_config = getattr(getattr(context.llm_handler, "llm", None), "endpoint_file", None)
        return is_context_clamp_enabled(context.config, endpoint_config)

    @staticmethod
    def _log_context_window_clamp(config, llm_handler, before_tokens, after_tokens, dropped_messages) -> None:
        """Emit a single INFO line when the clamp actually reduced the prompt.

        Names the control and the disable/tune path so an operator can see, in
        plain sight, that conversation was dropped *by this specific control* and
        how to change it. No-op when nothing was reduced.

        Args:
            config (dict): The node config (for the node title).
            llm_handler: The node's LLM handler (for window / response / level).
            before_tokens (int): Estimated tokens before the clamp.
            after_tokens (int): Estimated tokens after the clamp.
            dropped_messages (int): Whole messages dropped to fit the budget.
        """
        if after_tokens >= before_tokens:
            return
        title = config.get("title") or config.get("agentName") or "unknown"
        llm = getattr(llm_handler, "llm", None)
        endpoint_config = getattr(llm, "endpoint_file", None)
        endpoint_config = endpoint_config if isinstance(endpoint_config, dict) else {}
        window = endpoint_config.get("maxContextTokenSize")
        n_predict = getattr(llm, "max_tokens", None)
        level = endpoint_config.get(ESTIMATION_LEVEL_KEY) or DEFAULT_ESTIMATION_LEVEL
        # The clamp reduces a conversation only by dropping whole oldest messages
        # (it never truncates content), so any reduction reported here is a drop.
        detail = f"dropped the {dropped_messages} oldest message(s)"
        logger.info(
            "Context-window clamp [%s] reduced node '%s' from ~%d to ~%d estimated tokens to fit "
            "this endpoint's window (window=%s, response=%s, estimation level '%s'); %s. Wilmer's "
            "token estimate is deliberately conservative; set %s=false (node/endpoint/user) to "
            "disable, or raise %s on this endpoint (conservative -> balanced -> aggressive -> "
            "xaggressive) to reclaim context if the estimate runs high for your model.",
            _CLAMP_ENABLED_KEY, title, before_tokens, after_tokens, window, n_predict, level, detail,
            _CLAMP_ENABLED_KEY, ESTIMATION_LEVEL_KEY,
        )

    @staticmethod
    def _compute_conversation_token_budget(llm_handler, system_prompt, tools) -> Optional[int]:
        """Compute the tokens available for conversation content before THIS node's
        endpoint window would be exceeded.

        ``budget = (endpoint_window - n_predict) * estimation_level``
        ``         - est(system_prompt) - est(tools) - headroom``

        The window basis ``(window - n_predict) * estimation_level - headroom`` comes
        from the shared ``config_utils.compute_endpoint_window_budget`` (so dispatch
        and the variable manager cannot drift). Dispatch then refines it with the
        system prompt and tool schemas, which only it knows at send time. The budget
        is per node from its own endpoint window (``maxContextTokenSize``) and response
        budget (``maxResponseSizeInTokens`` -> ``n_predict``); there is no global
        constant. ``conservative`` (1.0) reproduces the unscaled budget exactly.

        Args:
            llm_handler: The node's LLM handler (``llm_handler.llm`` carries the
                resolved endpoint config and ``max_tokens``).
            system_prompt (str): The node's fully-substituted system prompt.
            tools: The tool definitions being forwarded (or None).

        Returns:
            Optional[int]: The conversation token budget, or None when the
            endpoint window is unknown (e.g. not configured, or a mocked handler
            in tests), in which case the clamp is disabled (no-op). A non-None
            value may be <= 0 for a misconfigured node (its response/system
            budget alone approaches the window); callers still trim to it (down
            to empty) to avoid a hard context-overflow rejection.
        """
        llm = getattr(llm_handler, "llm", None)
        endpoint_config = getattr(llm, "endpoint_file", None)
        base_budget = compute_endpoint_window_budget(
            endpoint_config, getattr(llm, "max_tokens", 0), _CLAMP_HEADROOM_TOKENS)
        if base_budget is None:
            return None

        # Refine the shared window basis with what only dispatch knows at send time:
        # the system prompt and forwarded tool schemas (both already in conservative
        # estimate space, so subtracted after the level has scaled the base).
        system_tokens = rough_estimate_token_length(system_prompt) if system_prompt else 0
        tool_tokens = LLMDispatchService._estimate_tokens_for_tools(tools)
        budget = base_budget - system_tokens - tool_tokens

        if budget <= 0:
            window = endpoint_config.get("maxContextTokenSize")
            logger.warning(
                "Pre-send clamp: computed conversation budget %d <= 0 (endpoint window %s, "
                "system ~%d, tools ~%d, headroom %d). The node's response and system budget "
                "alone approach the window; the conversation will be trimmed aggressively. "
                "Consider raising maxContextTokenSize or lowering maxResponseSizeInTokens "
                "for this node's endpoint.",
                budget, window, system_tokens, tool_tokens, _CLAMP_HEADROOM_TOKENS,
            )
        return budget

    @staticmethod
    def _trim_messages_to_token_budget(messages, budget):
        """Return the most-recent messages that fit within ``budget`` estimated tokens.

        Drops whole messages oldest-first, always keeping at least the single most
        recent message. Conversation content is NEVER truncated: if the single
        most-recent message alone exceeds the budget, it is kept WHOLE and a warning
        is logged (we cannot send nothing, and silently dropping part of a message
        would destroy context the operator cannot see was removed). The backend may
        then reject it, a visible failure beats silent corruption. Per-message
        chat-template overhead is included in the estimate, and the estimator
        overestimates, so the result is conservatively under budget.

        A None budget disables trimming and the input list is returned unchanged
        (same object), preserving existing behavior when the endpoint window is
        unknown.

        Args:
            messages (list): Conversation messages in chronological order.
            budget (Optional[int]): The estimated token budget, or None to disable.

        Returns:
            list: The retained messages in chronological order. A new list when a
            budget is applied; the original object when budget is None or empty.
        """
        if budget is None or not messages:
            return messages

        overhead = _CLAMP_PER_MESSAGE_OVERHEAD_TOKENS
        selected = []
        used = 0
        for message in reversed(messages):
            cost = rough_estimate_token_length(message.get("content") or "") + overhead
            if not selected or used + cost <= budget:
                selected.append(message)
                used += cost
            else:
                break
        selected.reverse()

        if used > budget and budget > 0:
            # Reachable only when the most-recent message alone exceeds the budget
            # (it is then the only one selected). We keep it WHOLE rather than
            # truncate its content: dropping part of a conversation message would
            # silently destroy context, and we cannot send nothing. Warn so the
            # operator sees it, and let the backend reject it as a visible failure.
            # Bounding the embedded conversation variable is the supported defense.
            # (budget <= 0 is the misconfig case already warned about when the
            # budget was computed, so it is not re-warned here.)
            single_tokens = rough_estimate_token_length(selected[0].get("content") or "")
            logger.warning(
                "Pre-send clamp: the single most-recent conversation message is ~%d "
                "estimated tokens, which alone exceeds the conversation budget of ~%d. "
                "Wilmer does not truncate conversation content, so it is sent whole and "
                "the backend may reject it for context overflow. Shorten that message, "
                "raise this endpoint's maxContextTokenSize, or raise %s.",
                single_tokens, budget, ESTIMATION_LEVEL_KEY,
            )
        # NOTE: routine reduction reporting (whole oldest messages dropped) happens
        # once at the dispatch layer (INFO, naming the control); only the
        # un-trimmable oversized-message case warns here, as it is a genuine problem
        # the operator must see regardless of the INFO path.
        return selected

    @staticmethod
    def _clamp_chat_collection_to_budget(collection, budget) -> None:
        """Trim a chat ``collection`` in place so it fits ``budget`` tokens.

        Leading system message(s) are preserved (their tokens were already
        subtracted when computing the budget); only the conversation body is
        trimmed, oldest-first, keeping the most recent message whole (content is
        never truncated). No-op when ``budget`` is None or the body already fits.

        Args:
            collection (list): The message collection to modify in place.
            budget (Optional[int]): The conversation token budget, or None.
        """
        if budget is None or not collection:
            return
        lead = 0
        while lead < len(collection) and collection[lead].get("role") == "system":
            lead += 1
        body = collection[lead:]
        if not body:
            return
        trimmed = LLMDispatchService._trim_messages_to_token_budget(body, budget)
        collection[:] = collection[:lead] + trimmed

    @staticmethod
    def _warn_if_authored_prompt_overflows(prompt, budget, config, llm_handler) -> None:
        """Warn, without modifying, when an operator-authored prompt overflows the budget.

        The node's ``prompt`` field is authored content (instructions, safety
        rules, an embedded conversation variable). It is NEVER truncated: silently
        dropping part of it would change the model's behavior in ways the operator
        cannot see or consent to. When it exceeds the window budget, Wilmer logs a
        warning and leaves it intact, so the backend rejects it as a visible failure
        rather than Wilmer mangling it. The supported defense against
        conversation-driven overflow is to bound the embedded conversation variable
        (e.g. maxEstimatedTokensInVariable) so the conversation, not the authored
        prompt, is what gives way.

        Args:
            prompt (str): The rendered, authored prompt.
            budget (Optional[int]): The conversation token budget, or None when the
                clamp is disabled or the endpoint window is unknown.
            config (dict): The node config (for the node title).
            llm_handler: The node's LLM handler (for window context).
        """
        if budget is None or not prompt:
            return
        prompt_tokens = rough_estimate_token_length(prompt)
        if prompt_tokens <= budget:
            return
        title = config.get("title") or config.get("agentName") or "unknown"
        llm = getattr(llm_handler, "llm", None)
        endpoint_config = getattr(llm, "endpoint_file", None)
        endpoint_config = endpoint_config if isinstance(endpoint_config, dict) else {}
        window = endpoint_config.get("maxContextTokenSize")
        logger.warning(
            "Node '%s' authored prompt is ~%d estimated tokens, over this endpoint's "
            "usable budget of ~%d (window=%s). Wilmer does NOT truncate an authored "
            "prompt (that would silently drop your instructions); it is sent as-is and "
            "the backend may reject it. To fit, shorten the prompt, bound the embedded "
            "conversation variable (e.g. maxEstimatedTokensInVariable), or raise %s or "
            "the endpoint window.",
            title, prompt_tokens, budget, window, ESTIMATION_LEVEL_KEY,
        )

    @staticmethod
    def _execute_constrained_tool_round(llm_handler, call_kwargs: dict, tools: list,
                                        tool_choice, schema: dict,
                                        request_id: Optional[str]) -> Any:
        """
        Runs a tool-enforcement round constrained by a structured-output schema.

        The backend call carries the schema (attached per the endpoint's ApiType
        mechanism) instead of native tools, and its text output is parsed back
        into Wilmer's internal tool-call dict. Because some backends accept a
        constraint field without enforcing it (llama.cpp fails open on bad
        grammars; some servers silently ignore the field), the parse result is
        never assumed: one redraw is attempted on a failed parse, after which
        the raw text is returned as-is with an error logged.

        Streaming calls are buffered: the client declared this round machine-
        consumed by pinning tool_choice, and the constrained output is a single
        short JSON object. The converted call is re-emitted as standard
        streaming chunks.

        Args:
            llm_handler: The node's LLM handler.
            call_kwargs (dict): Keyword arguments for get_response_from_llm,
                without the schema.
            tools (list): The request's tool definitions (for parse validation).
            tool_choice: The request's tool_choice value.
            schema (dict): The enforcement schema to attach.
            request_id (Optional[str]): Request ID, checked before a redraw.

        Returns:
            Any: A tool-call dict, a synthetic streaming generator, or the raw
            response when both attempts fail to parse.
        """
        from Middleware.services.cancellation_service import cancellation_service

        def call_once():
            return llm_handler.llm.get_response_from_llm(
                **call_kwargs, structured_output_schema=schema)

        def collect(result):
            # Buffers a streaming generator into (text, was_stream); passthrough
            # for strings. Dict results are native tool calls already.
            if isinstance(result, (str, dict)) or result is None:
                return result, False
            tokens = []
            for chunk in result:
                if isinstance(chunk, dict):
                    tokens.append(chunk.get('token') or '')
            return "".join(tokens), True

        def empty_stream():
            # Streaming consumers type-gate on isinstance(x, Generator); a bare
            # iter(()) would fail that check and leak into the SSE body.
            yield from ()

        result, was_stream = collect(call_once())
        if isinstance(result, dict):
            return result  # backend natively enforced and parsed; already correct
        parsed = parse_constrained_tool_response(result, tools, tool_choice)
        if parsed is None:
            if request_id and cancellation_service.is_cancelled(request_id):
                return result if not was_stream else empty_stream()
            logger.warning("Constrained tool round returned unparseable output; redrawing once.")
            result, was_stream = collect(call_once())
            if isinstance(result, dict):
                return result
            parsed = parse_constrained_tool_response(result, tools, tool_choice)

        if parsed is None:
            if request_id and cancellation_service.is_cancelled(request_id):
                # Cancellation landed during the redraw; not a backend fault.
                return result if not was_stream else empty_stream()
            logger.error(
                "Constrained tool round failed to produce a valid tool call after a "
                "redraw; the backend likely accepted the constraint field without "
                "enforcing it. Returning the raw output.")
            if not was_stream:
                return result
            raw_text = result

            def raw_stream():
                yield {'token': raw_text, 'finish_reason': None}
                yield {'token': '', 'finish_reason': 'stop'}
            return raw_stream()

        converted = build_tool_calls_result(parsed)
        if not was_stream:
            return converted

        tool_calls = [dict(call, index=i) for i, call in enumerate(converted['tool_calls'])]

        def tool_call_stream():
            yield {'token': '', 'tool_calls': tool_calls, 'finish_reason': None}
            yield {'token': '', 'finish_reason': 'tool_calls'}
        return tool_call_stream()

    @staticmethod
    def _extract_trailing_tool_exchange(messages: List[dict]) -> Tuple[int, List[dict]]:
        """
        Identifies the trailing tool exchange of a conversation, if any.

        The trailing exchange is the final assistant ``tool_calls`` turn plus the
        contiguous ``role: "tool"`` result(s) that follow it, ignoring any
        assistant filler appended after them (empty content, or the bare
        "Assistant:" prompt added by chatCompleteAddMissingAssistant). This is
        the live exchange the frontend just executed (the one the model must
        respond to next), as opposed to earlier, completed exchanges buried in
        the conversation.

        Used by ``appendNativeToolExchange``: an authored-prompt node opting in
        has this exchange delivered natively (as real messages after the
        authored prompt) instead of rendered into the text transcript, so the
        model generates from the standard post-tool-result position.

        Args:
            messages (List[dict]): The conversation messages.

        Returns:
            Tuple[int, List[dict]]: The index where the exchange begins and the
            exchange messages (assistant tool_calls turn followed by its tool
            results, trailing filler excluded). ``(len(messages), [])`` when the
            conversation does not end with a tool exchange.
        """
        no_exchange = (len(messages), [])
        idx = len(messages) - 1
        # Skip trailing assistant filler (no tool_calls, empty/"Assistant:" content).
        while idx >= 0:
            message = messages[idx]
            if not isinstance(message, dict) or message.get("role") != "assistant" \
                    or message.get("tool_calls"):
                break
            content = message.get("content")
            stripped = content.strip() if isinstance(content, str) else ""
            if stripped and stripped != "Assistant:":
                break
            idx -= 1
        # Collect the contiguous tool results.
        end = idx
        while idx >= 0 and isinstance(messages[idx], dict) and messages[idx].get("role") == "tool":
            idx -= 1
        if idx == end:
            return no_exchange
        # The message immediately before the results must be the assistant turn
        # that made the call(s).
        if idx >= 0 and isinstance(messages[idx], dict) and messages[idx].get("role") == "assistant" \
                and isinstance(messages[idx].get("tool_calls"), list) and messages[idx]["tool_calls"]:
            return idx, messages[idx:end + 1]
        return no_exchange

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

        if context.messages is None:
            raise ValueError("ExecutionContext.messages must not be None when dispatching to LLM")

        # Per-message dict copies isolate the caller's conversation from the in-place
        # key surgery below (_apply_image_limit deletes/replaces the "images" key).
        # Nothing downstream mutates a nested value in place (the extraction utils
        # filter/slice, and format_messages_with_template deep-copies internally), so
        # deep-copying the whole history on every dispatch was redundant work.
        message_copy = [dict(msg) for msg in context.messages]

        # appendNativeToolExchange: on an authored-prompt (non-collection) node
        # bound to a chat-completions endpoint, deliver the trailing tool exchange
        # (the assistant tool_calls turn the frontend just executed plus its
        # role:"tool" results) as native messages after the authored prompt,
        # instead of rendering it into the text transcript. The exchange is
        # removed from the messages the prompt variables render from (for THIS
        # node only), so the model sees it exactly once, natively, and generates
        # from the standard post-tool-result position. Collection-mode nodes
        # already send native turns, so the flag is inert there; completions
        # endpoints cannot carry structured turns, so it is inert there too.
        # An endpoint whose backing model's chat template cannot render tool
        # turns (old models, strict alternation templates without tool support)
        # opts out via "backendSupportsToolTurns": false in its endpoint config;
        # the node then falls back to the text-transcript behavior, so one old
        # backend never requires editing every workflow that sets the flag.
        exchange_endpoint_file = getattr(getattr(llm_handler, "llm", None), "endpoint_file", None)
        backend_supports_tool_turns = (
            exchange_endpoint_file.get("backendSupportsToolTurns", True)
            if isinstance(exchange_endpoint_file, dict) else True)
        native_tool_exchange = []
        if config.get("appendNativeToolExchange", False) \
                and config.get("prompt", "") \
                and llm_handler.takes_message_collection \
                and backend_supports_tool_turns:
            exchange_start, native_tool_exchange = \
                LLMDispatchService._extract_trailing_tool_exchange(message_copy)
            if native_tool_exchange:
                logger.debug(
                    "appendNativeToolExchange: delivering trailing tool exchange "
                    "(%d message(s)) natively; excluding it from prompt variables.",
                    len(native_tool_exchange))
                message_copy = message_copy[:exchange_start]

        # 1. Get and apply variables to base prompts from the node config.
        # While the variables render, context.messages is swapped to the
        # exchange-trimmed copy (a no-op when the feature did not engage) so
        # every conversation variable excludes the natively-delivered exchange;
        # the original list is restored before anything else sees the context.
        original_messages = context.messages
        try:
            if native_tool_exchange:
                context.messages = message_copy
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
        finally:
            context.messages = original_messages

        # Determine whether this node should receive tool definitions.
        # Only nodes with "allowTools": true in their config will forward
        # tools to the LLM; all others (memory nodes, summarizers, etc.)
        # silently suppress them so the LLM doesn't attempt tool calls.
        allow_tools = config.get("allowTools", False)
        tools_to_send = context.tools if allow_tools else None
        tool_choice_to_send = context.tool_choice if allow_tools else None

        # Tool enforcement via structured output: when the client DEMANDS a call
        # (forced-function or "required" tool_choice, never "auto") and the
        # endpoint's API type declares a structuredOutput mechanism, this round
        # is constrained instead of steered. Native tools/tool_choice are
        # dropped from the payload (the combination with an explicit schema is
        # unsupported on llama.cpp and Ollama) and the tool definitions are
        # injected as text (grammar backends do not show the model the schema);
        # the guaranteed-JSON output is converted back into a tool_calls
        # response after the call. Backends that enforce tool_choice natively
        # and declare no mechanism (e.g. Claude) never enter this path.
        tool_enforcement_schema = None
        enforced_tools = None
        enforced_tool_choice = None
        if tools_to_send and llm_handler.takes_message_collection:
            endpoint_api_type = getattr(getattr(llm_handler, "llm", None), "api_type_config", None)
            if get_structured_output_config(endpoint_api_type):
                tool_enforcement_schema = build_tool_enforcement_schema(
                    tools_to_send, tool_choice_to_send)
        if tool_enforcement_schema:
            logger.debug("Tool-enforcement round: constraining via structured output "
                         "and dropping native tools from the payload.")
            description = build_tools_description_text(tools_to_send, tool_choice_to_send)
            if description:
                system_prompt = f"{system_prompt}\n\n{description}" if system_prompt else description
            enforced_tools = tools_to_send
            enforced_tool_choice = tool_choice_to_send
            tools_to_send = None
            tool_choice_to_send = None

        # Author-declared structured output: a node may pin its own output shape
        # via "structuredOutputFile" (a schema in Configs/StructuredOutputs/).
        # The schema rides the same ApiType mechanism; the node's output IS the
        # constrained JSON text (no conversion). The author must describe the
        # desired structure in the node's prompts; grammar backends do not
        # show the model the schema. Colliding with an engaged tool-enforcement
        # round is a configuration error, not a silent precedence pick.
        node_output_schema = None
        structured_output_file = config.get("structuredOutputFile")
        if structured_output_file:
            if tool_enforcement_schema:
                raise ValueError(
                    "Node declares structuredOutputFile while a tool-enforcement round "
                    "is active (forced/required tool_choice with allowTools). These "
                    "constraints conflict; remove one.")
            if not llm_handler.takes_message_collection:
                logger.warning(
                    "structuredOutputFile is set on a node bound to a completions-"
                    "paradigm endpoint; structured output is not supported there "
                    "and the setting is ignored.")
            else:
                node_output_schema = load_structured_output_schema(structured_output_file)
                if tools_to_send:
                    logger.warning(
                        "structuredOutputFile is set on a node that is also forwarding "
                        "native tool definitions (non-forcing tool_choice). Most backends "
                        "cannot combine an explicit schema with native tools; the schema "
                        "will constrain the output and native tool calls will not occur.")

        # The pre-send context clamp is the master switch for all context-window
        # awareness. Resolve it once (node > endpoint > user > default OFF); when it
        # is OFF, Wilmer makes no window-based budgeting decisions and the endpoint
        # estimation level is inert (see below), so behavior is the raw pre-feature
        # path.
        clamp_enabled = LLMDispatchService._context_clamp_enabled(context)

        # Per-endpoint estimation level for THIS node's endpoint. It calibrates
        # Wilmer's deliberately conservative token estimator for the endpoint's
        # model and scales every token budget Wilmer derives for a prompt bound to
        # this endpoint (the clamp budget below and the doer-cap slice). It applies
        # ONLY when the clamp is enabled (the clamp governs all context-window
        # awareness); with the clamp off it is inert (1.0, no scaling), so a level
        # set on an endpoint whose clamp is off does nothing. 'conservative' (the
        # default) is also 1.0. It is never sent to the inference engine.
        endpoint_config = getattr(getattr(llm_handler, "llm", None), "endpoint_file", None)
        estimation_multiplier = (
            get_estimation_level_multiplier(endpoint_config) if clamp_enabled else 1.0)

        # Final pre-send safety clamp budget: the tokens available for conversation
        # content before THIS node's endpoint window (minus its response budget,
        # system prompt, forwarded tool schemas, and a small headroom) is exceeded.
        # Computed once per node and applied in both API branches below. It is the
        # systemic safety net that keeps any node (categorizer, planner, doer,
        # responder) from being rejected for context overflow, complementing (and
        # subsuming) the opt-in per-node lastMessagesToSendInsteadOfPromptMaxTokenSize
        # cap. None disables the clamp (every clamp helper below no-ops), which also
        # happens when the endpoint window is unknown.
        conversation_token_budget = (
            LLMDispatchService._compute_conversation_token_budget(
                llm_handler, system_prompt, tools_to_send)
            if clamp_enabled else None)

        # 2. Prepare inputs and call LLM based on API type
        if not llm_handler.takes_message_collection:
            # === COMPLETIONS API LOGIC ===
            if use_last_n_messages:
                last_messages_to_send = config.get("lastMessagesToSendInsteadOfPrompt", 5)
                source_messages = message_copy
                # Optional token ceiling on top of the message-count cap so a long
                # agentic conversation cannot overflow the endpoint window, scaled by
                # this endpoint's estimation level (see the chat-API branch for the
                # same logic).
                max_conversation_tokens = config.get("lastMessagesToSendInsteadOfPromptMaxTokenSize")
                if max_conversation_tokens:
                    source_messages = extract_last_turns_by_estimated_token_limit(
                        extract_last_n_turns(message_copy, last_messages_to_send, True),
                        int(max_conversation_tokens * estimation_multiplier))
                # Final safety clamp on the message slice before it is formatted to a
                # string, so the rendered prompt fits the node's endpoint window.
                if conversation_token_budget is not None:
                    before_tokens = LLMDispatchService._estimate_collection_tokens(source_messages)
                    before_count = len(source_messages)
                    source_messages = LLMDispatchService._trim_messages_to_token_budget(
                        source_messages, conversation_token_budget)
                    LLMDispatchService._log_context_window_clamp(
                        config, llm_handler, before_tokens,
                        LLMDispatchService._estimate_collection_tokens(source_messages),
                        before_count - len(source_messages))
                prompt = get_formatted_last_n_turns_as_string(
                    source_messages, last_messages_to_send + 1,
                    template_file_name=llm_handler.prompt_template_file_name,
                    isChatCompletion=False
                )
            else:
                # The prompt came from the node config: it is the operator's authored
                # template (instructions, safety rules, an embedded conversation
                # variable, etc.) and must NEVER be silently truncated. Chopping it
                # would drop authored content the operator cannot see was removed and
                # change the output without their consent. If it overflows we warn and
                # send it as-is (a visible backend rejection beats silent mangling).
                # The correct defense against conversation-driven overflow is to bound
                # the embedded conversation variable when it is built, not here.
                LLMDispatchService._warn_if_authored_prompt_overflows(
                    prompt, conversation_token_budget, config, llm_handler)
            if config.get("addUserTurnTemplate"):
                prompt = format_user_turn_with_template(prompt, llm_handler.prompt_template_file_name, False)
            if config.get("addOpenEndedAssistantTurnTemplate"):
                prompt = format_assistant_turn_with_template(prompt, llm_handler.prompt_template_file_name, False)
            if llm_handler.add_generation_prompt:
                prompt = add_assistant_end_token_to_user_turn(prompt, llm_handler.prompt_template_file_name, False)

            system_prompt = format_system_prompt_with_template(
                system_prompt, llm_handler.prompt_template_file_name, False)

            # Completions handlers ignore `conversation` for text, but the
            # image-capable ones (koboldCppGenerateImageSpecific) read
            # per-message images from it. The prompt string cannot carry image
            # data, so pass gathered images in a minimal conversation.
            image_conversation = None
            if llm_takes_images:
                recent_images = LLMDispatchService._gather_recent_images(
                    message_copy, config, max_images)
                if recent_images:
                    image_conversation = [{"role": "user", "content": "", "images": recent_images}]

            return llm_handler.llm.get_response_from_llm(
                conversation=image_conversation, system_prompt=system_prompt,
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
                # Apply an optional token ceiling on top of the message-count cap so a
                # long agentic conversation (large tool results) cannot overflow the
                # endpoint window, scaled by this endpoint's estimation level. Keeps
                # the most recent messages within budget.
                max_conversation_tokens = config.get("lastMessagesToSendInsteadOfPromptMaxTokenSize")
                if max_conversation_tokens:
                    last_n_turns = extract_last_turns_by_estimated_token_limit(
                        last_n_turns, int(max_conversation_tokens * estimation_multiplier))
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
            else:
                user_msg = {"role": "user", "content": prompt}
                if llm_takes_images:
                    recent_images = LLMDispatchService._gather_recent_images(
                        message_copy, config, max_images)
                    if recent_images:
                        user_msg["images"] = recent_images
                collection.append(user_msg)
                # appendNativeToolExchange: the live tool exchange follows the
                # authored prompt as real messages, putting the model in the
                # standard generate-after-tool-result position. The exchange was
                # already excluded from the transcript the prompt rendered.
                if native_tool_exchange:
                    collection.extend(native_tool_exchange)
                # This user message IS the operator's authored prompt; never truncate
                # it. Warn if it overflows and send as-is (see the completions branch).
                LLMDispatchService._warn_if_authored_prompt_overflows(
                    prompt, conversation_token_budget, config, llm_handler)

            # Final pre-send safety clamp: trim the CONVERSATION body (oldest-first) to
            # fit the node's endpoint window. Conversation-only: it runs solely on the
            # last-N path, where the body is selected conversation messages, never on
            # the authored-prompt path (whose body is the operator's prompt, left
            # intact with a warning above). The leading system prompt is always
            # preserved. Placed BEFORE the user-message safety net so a user message
            # dropped by the clamp can still be recovered from the full conversation.
            if use_last_n_messages and conversation_token_budget is not None:
                before_tokens = LLMDispatchService._estimate_collection_tokens(collection)
                before_count = len(collection)
                LLMDispatchService._clamp_chat_collection_to_budget(collection, conversation_token_budget)
                LLMDispatchService._log_context_window_clamp(
                    config, llm_handler, before_tokens,
                    LLMDispatchService._estimate_collection_tokens(collection),
                    before_count - len(collection))

            if use_last_n_messages:
                # Safety net: if the message window contains no user messages
                # (common in long agentic tool-calling chains where tool-role
                # messages separate assistants, or after the clamp drops the
                # oldest messages), insert the most recent user message from the
                # full conversation so backend chat templates that require a user
                # query don't reject the request.
                LLMDispatchService._ensure_user_message_present(collection, message_copy)

            final_kwargs = dict(
                conversation=collection, llm_takes_images=llm_takes_images,
                request_id=getattr(context, 'request_id', None),
                tools=tools_to_send,
                tool_choice=tool_choice_to_send,
            )
            if tool_enforcement_schema:
                return LLMDispatchService._execute_constrained_tool_round(
                    llm_handler, final_kwargs, enforced_tools, enforced_tool_choice,
                    tool_enforcement_schema, getattr(context, 'request_id', None))
            if node_output_schema is not None:
                final_kwargs["structured_output_schema"] = node_output_schema
            return llm_handler.llm.get_response_from_llm(**final_kwargs)
