import json
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
COMMON_WORKFLOW_DIRECTORY = REPOSITORY_ROOT / "Public" / "Configs" / "Workflows" / "_common"
FULL_REASONING_COT_WORKFLOWS = (
    "General_CoT.json",
    "General_With_Vision_DiscussionId_CoT.json",
)


def _load_workflow(filename):
    with (COMMON_WORKFLOW_DIRECTORY / filename).open(encoding="utf-8") as workflow_file:
        return json.load(workflow_file)


def _reasoner_and_responder(nodes):
    responder = next(node for node in nodes if node.get("title") == "Responding Agent")
    reasoner = next(
        node for node in nodes
        if node.get("type") == "Standard" and node is not responder
    )
    return reasoner, responder


@pytest.mark.parametrize("filename", FULL_REASONING_COT_WORKFLOWS)
def test_full_reasoning_cot_keeps_tool_execution_on_the_responder(filename):
    nodes = _load_workflow(filename)
    reasoner, responder = _reasoner_and_responder(nodes)

    assert [node for node in nodes if node.get("allowTools")] == [responder]
    assert reasoner.get("allowTools", False) is False
    assert reasoner["appendNativeToolExchange"] is True
    assert responder["allowTools"] is True
    assert responder["appendNativeToolExchange"] is True


@pytest.mark.parametrize("filename", FULL_REASONING_COT_WORKFLOWS)
def test_full_reasoning_cot_preserves_tool_provenance_in_both_llm_nodes(filename):
    nodes = _load_workflow(filename)
    reasoner, responder = _reasoner_and_responder(nodes)

    for node in (reasoner, responder):
        assert node["includeToolCallsInConversation"] is True
        assert node["addUserAssistantTags"] is False

    assert "describes capabilities only" in reasoner["systemPrompt"]
    assert "must never emit a tool call" in reasoner["systemPrompt"]
    assert "Tool definitions, schemas, and catalogs describe capabilities" in responder["prompt"]
    assert "Do not repeat a tool call unless" in responder["prompt"]


@pytest.mark.parametrize("filename", FULL_REASONING_COT_WORKFLOWS)
def test_full_reasoning_cot_retains_its_full_reasoning_handoff(filename):
    nodes = _load_workflow(filename)
    _, responder = _reasoner_and_responder(nodes)

    assert all(node.get("type") != "TagTextExtractor" for node in nodes)
    assert "<reasoning>" in responder["prompt"]
    assert "Status: exactly one of READY" not in responder["prompt"]
