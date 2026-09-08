"""Regression checks for conversation handoff in shipped CoT workflows."""

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from Middleware.services.llm_dispatch_service import LLMDispatchService
from Middleware.utilities.hashing_utils import hash_message_with_images
from Middleware.workflows.handlers.impl import specialized_node_handler as image_nodes
from Middleware.workflows.managers import workflow_variable_manager as variables
from Middleware.workflows.models.execution_context import ExecutionContext


ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "Public/Configs/Workflows/_common"
FILES = [
    "General_CoT.json",
    "General_With_Vision_DiscussionId_CoT.json",
    "General_CoT_v2.json",
    "General_With_Vision_DiscussionId_CoT_v2.json",
]


@pytest.fixture
def variable_service(monkeypatch):
    monkeypatch.setattr(variables, "get_user_config", lambda: {})
    monkeypatch.setattr(variables, "get_chat_template_name", lambda: "_chatonly")
    monkeypatch.setattr(variables, "get_separate_conversation_in_variables", lambda: False)
    monkeypatch.setattr(variables, "MemoryService", Mock)
    monkeypatch.setattr(variables, "TimestampService", Mock)
    monkeypatch.setattr(variables, "format_system_prompts", lambda **kwargs: {
        "chat_system_prompt": "Use plain text."
    })
    monkeypatch.setattr(variables, "get_formatted_last_turns_with_min_messages_and_token_limit_as_string",
                        lambda *args, **kwargs: "unused templated conversation")
    monkeypatch.setattr("Middleware.services.llm_dispatch_service.format_system_prompt_with_template",
                        lambda prompt, *args: prompt)
    monkeypatch.setattr("Middleware.services.llm_dispatch_service.format_user_turn_with_template",
                        lambda prompt, *args: prompt)
    return variables.WorkflowVariableManager()


@pytest.mark.parametrize("filename", FILES)
@pytest.mark.parametrize("chat_api", [True, False])
@pytest.mark.parametrize("tool_followup", [False, True])
def test_responder_retains_original_request(filename, chat_api, tool_followup, variable_service):
    nodes = json.loads((COMMON / filename).read_text())
    config = deepcopy(nodes[-1])
    config.update(minMessagesInVariable=10, maxEstimatedTokensInVariable=15000,
                  clampPromptToContextWindow=False)
    llm = Mock(endpoint_file={}, api_type_config={})
    llm.get_response_from_llm.return_value = "mocked response"
    handler = SimpleNamespace(llm=llm, takes_message_collection=chat_api, add_generation_prompt=False,
                              prompt_template_file_name="_chatonly")
    request = "Translate exactly this identifier: REVIEW_INPUT_7329."
    earlier_request = "Keep the earlier identifier REVIEW_HISTORY_2846 unchanged."
    messages = [
        {"role": "user", "content": earlier_request},
        {"role": "assistant", "content": "Understood."},
        {"role": "user", "content": request},
    ]
    if tool_followup:
        messages.extend([
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "review_call", "type": "function", "function": {
                    "name": "lookup", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "review_call", "content": "REVIEW_TOOL_RESULT"},
        ])
    context = ExecutionContext(
        request_id="local-review", workflow_id="local-review", discussion_id=None,
        config=config, messages=messages, stream=False, llm_handler=handler,
        workflow_variable_service=variable_service,
        agent_outputs={"agent1Output": "Follow the requested translation.",
                       "agent2Output": "Follow the requested translation."},
    )
    LLMDispatchService.dispatch(context)
    sent = llm.get_response_from_llm.call_args.kwargs
    payload = json.dumps(sent["conversation"]) if chat_api else sent["prompt"]
    assert "Follow the requested translation." in payload
    assert "{agent" not in payload
    if tool_followup:
        assert "REVIEW_TOOL_RESULT" in payload
    assert request in payload
    assert earlier_request in payload


@pytest.mark.parametrize("long_history", [False, True])
def test_vision_descriptions_follow_conversation_budget(variable_service, monkeypatch, long_history):
    configs = json.loads((COMMON / "General_With_Vision_DiscussionId_CoT_v2.json").read_text())
    description = "IMAGE_DESCRIPTION_2846"
    image_message = {"role": "user", "content": "Describe this image.", "images": ["mock-image"]}
    cache = {hash_message_with_images(image_message): description}
    monkeypatch.setattr(image_nodes, "get_discussion_vision_responses_file_path", lambda *a, **kw: "mock-cache")
    monkeypatch.setattr(image_nodes, "read_vision_responses", lambda *a, **kw: cache)
    writer = Mock()
    monkeypatch.setattr(image_nodes, "write_vision_responses", writer)
    messages = [deepcopy(image_message)]
    if long_history:
        messages.extend({"role": "user" if i % 2 == 0 else "assistant", "content": "later " * 1000}
                        for i in range(12))
    llm = Mock(endpoint_file={"maxContextTokenSize": 32786}, max_tokens=8096)
    handler = SimpleNamespace(llm=llm, takes_message_collection=True, prompt_template_file_name="_chatonly")
    context = ExecutionContext(
        request_id="vision-review", workflow_id="vision-review", discussion_id="mock-discussion",
        config=configs[0], messages=messages, stream=False, llm_handler=handler,
        workflow_variable_service=variable_service,
    )
    image_handler = image_nodes.SpecializedNodeHandler(workflow_manager=Mock(), workflow_variable_service=variable_service)
    output = image_handler.handle_image_processor_node(context)
    assert output == description
    assert sum(description in m.get("content", "") for m in messages) == 1
    writer.assert_not_called()
    llm.get_response_from_llm.assert_not_called()

    for node in configs[1:]:
        config = dict(node, minMessagesInVariable=10, maxEstimatedTokensInVariable=15000,
                      clampPromptToContextWindow=True)
        next_context = replace(context, config=config, agent_outputs={
            "agent1Output": output, "agent2Output": "Answer the latest request."
        })
        selected_conversation = variable_service.apply_variables("{chat_user_prompt_min_n_max_tokens}", next_context)
        LLMDispatchService.dispatch(next_context)
        payload = llm.get_response_from_llm.call_args.kwargs["conversation"][1]["content"]
        if long_history:
            assert description not in selected_conversation
            assert description not in payload
        else:
            assert payload.count(description) == 1
