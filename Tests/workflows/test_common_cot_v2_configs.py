import json
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
COMMON_WORKFLOW_DIRECTORY = REPOSITORY_ROOT / "Public" / "Configs" / "Workflows" / "_common"
V2_WORKFLOWS = (
    "General_CoT_v2.json",
    "General_With_Vision_DiscussionId_CoT_v2.json",
)
V2_SHARED_WORKFLOW_DIRECTORIES = (
    "_shared_manual_cot_v2",
    "_shared_manual_cot_v2_discussionid",
)
V2_REASONING_ROUTES = (
    "fast-reasoning",
    "general-reasoning",
)

V2_REASONING_OUTPUT_VARIABLES = (
    ("General_CoT_v2.json", "{agent1Output}"),
    ("General_With_Vision_DiscussionId_CoT_v2.json", "{agent2Output}"),
)


def _load_workflow(filename):
    with (COMMON_WORKFLOW_DIRECTORY / filename).open(encoding="utf-8") as workflow_file:
        return json.load(workflow_file)


@pytest.mark.parametrize("filename", V2_WORKFLOWS)
def test_v2_cot_workflows_keep_tool_execution_on_the_responder(filename):
    nodes = _load_workflow(filename)
    reasoner = next(node for node in nodes if node.get("agentName") == "Reasoner Agent")
    responder = next(node for node in nodes if node.get("title") == "Responding Agent")

    assert [node for node in nodes if node.get("allowTools")] == [responder]
    assert reasoner.get("allowTools", False) is False
    assert reasoner["appendNativeToolExchange"] is True
    assert responder["allowTools"] is True
    assert responder["appendNativeToolExchange"] is True


@pytest.mark.parametrize("filename", V2_WORKFLOWS)
def test_v2_cot_workflows_preserve_tool_provenance_in_both_llm_nodes(filename):
    nodes = _load_workflow(filename)
    reasoner = next(node for node in nodes if node.get("agentName") == "Reasoner Agent")
    responder = next(node for node in nodes if node.get("title") == "Responding Agent")

    for node in (reasoner, responder):
        assert node["includeToolCallsInConversation"] is True
        assert node["addUserAssistantTags"] is False

    assert "Tool definitions, schemas, and catalogs describe capabilities" in responder["prompt"]
    assert "Do not repeat a tool call unless" in responder["prompt"]


@pytest.mark.parametrize(("filename", "reasoning_output"), V2_REASONING_OUTPUT_VARIABLES)
def test_v2_cot_workflows_forward_the_full_reasoning_without_an_extractor(filename, reasoning_output):
    nodes = _load_workflow(filename)
    responder = next(node for node in nodes if node.get("title") == "Responding Agent")

    assert all(node.get("type") != "TagTextExtractor" for node in nodes)
    assert f"<analysis_reasoning>\n{reasoning_output}\n</analysis_reasoning>" in responder["prompt"]


@pytest.mark.parametrize("filename", V2_WORKFLOWS)
def test_v2_cot_uses_one_reasoner_and_one_responder_llm_call(filename):
    nodes = _load_workflow(filename)
    standard_nodes = [node for node in nodes if node.get("type", "Standard") == "Standard"]

    assert [node["title"] for node in standard_nodes] == [
        "Reasoner: Think then Settle",
        "Responding Agent",
    ]


@pytest.mark.parametrize("filename", V2_WORKFLOWS)
def test_v2_cot_reasoner_challenges_and_reconciles_before_settling(filename):
    nodes = _load_workflow(filename)
    reasoner = next(node for node in nodes if node.get("agentName") == "Reasoner Agent")
    system_prompt = reasoner["systemPrompt"]

    stages = (
        "1. FRAME:",
        "2. DERIVE:",
        "3. CHALLENGE:",
        "4. RECONCILE:",
        "5. SETTLE:",
    )
    assert [system_prompt.index(stage) for stage in stages] == sorted(
        system_prompt.index(stage) for stage in stages
    )
    assert "Only after challenge and reconciliation, decide what the Responder should do" in system_prompt
    assert "choose exactly one final status" not in system_prompt
    assert "<brief>" not in system_prompt


@pytest.mark.parametrize("filename", V2_WORKFLOWS)
def test_v2_cot_adversarial_review_checks_general_reasoning_failure_modes(filename):
    nodes = _load_workflow(filename)
    reasoner = next(node for node in nodes if node.get("agentName") == "Reasoner Agent")
    system_prompt = reasoner["systemPrompt"]

    assert "Make the strongest evidence-based case against them" in system_prompt
    assert "disconfirming evidence" in system_prompt
    assert "counterexamples" in system_prompt
    assert "overlooked constraints" in system_prompt
    assert "hidden assumptions" in system_prompt
    assert "inconsistent details" in system_prompt
    assert "failure modes" in system_prompt
    assert "materially plausible competing explanation" in system_prompt


@pytest.mark.parametrize("filename", V2_WORKFLOWS)
def test_v2_cot_prompts_use_the_token_ceiling_instead_of_word_caps(filename):
    nodes = _load_workflow(filename)
    reasoner = next(node for node in nodes if node.get("agentName") == "Reasoner Agent")
    reasoner_prompt = reasoner["systemPrompt"] + reasoner["prompt"]

    assert "roughly 600 words" not in reasoner_prompt
    assert "roughly 250 words" not in reasoner_prompt
    assert "use as much of the configured output budget as is genuinely needed" in reasoner_prompt
    assert "conversational or creative work" in reasoner_prompt
    assert "Do not treat the configured token ceiling as a target" in reasoner_prompt
    assert "finish the reasoning before reaching it" in reasoner_prompt
    assert "brief" not in reasoner_prompt.lower()


@pytest.mark.parametrize("filename", V2_WORKFLOWS)
def test_v2_cot_responder_uses_full_reasoning_without_visible_reconsideration(filename):
    nodes = _load_workflow(filename)
    responder = next(node for node in nodes if node.get("title") == "Responding Agent")

    assert "Use the above as your own reasoning" in responder["prompt"]
    assert "follow its settled conclusion" in responder["prompt"]
    assert "Do not repeat or reconstruct the reasoning" in responder["prompt"]
    assert "Never begin a claim and then reverse it" in responder["prompt"]
    assert "Do not expose the reasoning process" in responder["prompt"]
    assert "Status is a phase signal" not in responder["prompt"]
    assert "UNAVAILABLE" not in responder["prompt"]


def test_v2_cot_discussionid_blocks_images_on_reasoner_and_responder():
    nodes = _load_workflow("General_With_Vision_DiscussionId_CoT_v2.json")
    reasoner = next(node for node in nodes if node.get("agentName") == "Reasoner Agent")
    responder = next(node for node in nodes if node.get("title") == "Responding Agent")

    assert len([node for node in nodes if node.get("type") == "ImageProcessor"]) == 1
    assert reasoner["acceptImages"] is False
    assert responder["acceptImages"] is False
    assert "maxImagesToSend" not in reasoner
    assert "maxImagesToSend" not in responder


@pytest.mark.parametrize("shared_directory", V2_SHARED_WORKFLOW_DIRECTORIES)
@pytest.mark.parametrize("route", V2_REASONING_ROUTES)
def test_v2_cot_shipped_reasoning_routes_use_the_bounded_token_budget(shared_directory, route):
    workflow_path = (
        REPOSITORY_ROOT
        / "Public"
        / "Configs"
        / "Workflows"
        / shared_directory
        / route
        / "_DefaultWorkflow.json"
    )
    with workflow_path.open(encoding="utf-8") as workflow_file:
        workflow = json.load(workflow_file)

    assert workflow["ThinkingResponseTokenSize"] == 8096
