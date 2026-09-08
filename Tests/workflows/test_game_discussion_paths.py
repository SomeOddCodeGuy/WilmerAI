"""Regression coverage for discussion-scoped files in shipped game workflows."""

import json
import os

from Middleware.utilities.config_utils import get_project_root_directory_path


_GAME_WORKFLOW_FOLDERS = ("_example_game_bot_with_file_memory",)
_PATH_FIELDS = ("filepath", "cursorDirectory", "returnFile")


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


def test_game_workflow_file_paths_use_canonical_discussion_directory():
    """Every shipped game state path inherits the API-key discussion scope."""
    workflow_root = os.path.join(_configs_root(), "Workflows")
    checked_paths = []

    for folder in _GAME_WORKFLOW_FOLDERS:
        folder_path = os.path.join(workflow_root, folder)
        for filename in os.listdir(folder_path):
            if not filename.endswith(".json"):
                continue
            config = _load_json(os.path.join(folder_path, filename))
            for mapping in _walk_dicts(config):
                for field in _PATH_FIELDS:
                    if field in mapping:
                        path = mapping[field]
                        checked_paths.append((folder, filename, field, path))
                        assert isinstance(path, str)
                        assert path == "{Discussion_Directory}" or path.startswith(
                            "{Discussion_Directory}/"
                        ), f"Unscoped game path in {folder}/{filename}: {field}={path!r}"

    assert checked_paths, "No shipped game workflow paths were inspected"


def test_game_user_configs_do_not_restore_deprecated_shared_path_variables():
    """The examples must not make a separate shared state root configurable."""
    users_root = os.path.join(_configs_root(), "Users")

    for filename in ("_example_game_bot_with_file_memory.json",):
        user_config = _load_json(os.path.join(users_root, filename))
        shared_variables = user_config.get("userWideWorkflowVariables", {})
        assert "gameTempDir" not in shared_variables
        assert "storyTempDir" not in shared_variables
