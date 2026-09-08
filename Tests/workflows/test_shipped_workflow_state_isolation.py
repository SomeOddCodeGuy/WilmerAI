"""Regression coverage for mutable state paths in shipped workflows."""

import json
import os

from Middleware.utilities.config_utils import get_project_root_directory_path


def _configs_root():
    return os.path.join(get_project_root_directory_path(), "Public", "Configs")


def _load_json(path):
    with open(path, "r", encoding="utf-8") as config_file:
        return json.load(config_file)


def _walk_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def test_vector_memory_assistant_has_no_unscoped_custom_file_writers():
    """Its noncanonical persona paths are read-only; mutable memory uses built-in nodes."""
    workflow_root = os.path.join(
        _configs_root(), "Workflows", "_example_assistant_with_vector_memory"
    )
    saw_quality_memory = False
    saw_static_read = False

    for filename in os.listdir(workflow_root):
        if not filename.endswith(".json"):
            continue
        config = _load_json(os.path.join(workflow_root, filename))
        for mapping in _walk_dicts(config):
            node_type = mapping.get("type")
            saw_quality_memory = saw_quality_memory or node_type == "QualityMemory"
            if node_type == "GetCustomFile" and "filepath" in mapping:
                saw_static_read = True
            if node_type == "SaveCustomFile":
                filepath = mapping.get("filepath", "")
                assert filepath.startswith("{Discussion_Directory}/")

    assert saw_quality_memory
    assert saw_static_read
