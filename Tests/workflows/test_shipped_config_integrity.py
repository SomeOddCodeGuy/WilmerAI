"""Offline syntax and static reference checks for shipped configurations."""

import json
from pathlib import Path

import pytest

from Middleware.common.constants import VALID_NODE_TYPES
from Middleware.utilities.config_utils import get_project_root_directory_path


@pytest.fixture
def shipped_configs():
    root = Path(get_project_root_directory_path())
    configs = {
        path.relative_to(root): json.loads(path.read_text(encoding="utf-8"))
        for path in (root / "Public/Configs").rglob("*.json")
    }
    assert configs, "No shipping configuration files were inspected"
    return root, configs


def test_all_shipped_json_configs_parse(shipped_configs):
    _, configs = shipped_configs
    assert any(path.parts[2] == "Users" for path in configs)
    assert any(path.parts[2] == "Workflows" for path in configs)


def test_shipped_workflow_node_types_and_static_assets_exist(shipped_configs):
    root, configs = shipped_configs
    inspected = 0
    for path, data in configs.items():
        if path.parts[2] != "Workflows":
            continue
        nodes = data if isinstance(data, list) else data.get("nodes", [])
        assert isinstance(nodes, list), path
        for node in nodes:
            inspected += 1
            assert isinstance(node, dict), path
            node_type = node.get("type", "Standard")
            assert node_type in VALID_NODE_TYPES, (path, node_type)
            if node_type == "PythonModule":
                assert (root / node["module_path"]).is_file(), path
            folder = node.get("workflowUserFolderOverride")
            if folder and node_type in {"CustomWorkflow", "ConditionalCustomWorkflow", "ConversationChunkProcessor"}:
                targets = (
                    node.get("conditionalWorkflows", {}).values()
                    if node_type == "ConditionalCustomWorkflow"
                    else [node.get("workflowName")]
                )
                for target in targets:
                    assert isinstance(target, str), path
                    if "{" not in folder and "{" not in target:
                        assert (root / "Public/Configs/Workflows" / folder / f"{target}.json").is_file(), (path, target)
    assert inspected > 0, "No workflow nodes were inspected"
