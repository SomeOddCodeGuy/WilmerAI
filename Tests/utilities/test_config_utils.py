import json
import os
from unittest.mock import mock_open

import pytest

from Middleware.common import instance_global_variables
from Middleware.utilities import config_utils


@pytest.fixture
def mock_user_config():
    """Provides a mock user configuration dictionary."""
    return {
        "port": 5001,
        "customWorkflowOverride": False,
        "customWorkflow": "MyWorkflow",
        "routingConfig": "main_routing",
        "categorizationWorkflow": "main_categorizer",
        "discussionIdMemoryFileWorkflowSettings": "memory_settings",
        "fileMemoryToolWorkflow": "file_memory_tool",
        "chatSummaryToolWorkflow": "summary_tool",
        "conversationMemoryToolWorkflow": "convo_memory_tool",
        "recentMemoryToolWorkflow": "recent_memory_tool",
        "discussionDirectory": "/mock/discussions",
        "sqlLiteDirectory": "/mock/db",
        "endpointConfigsSubDirectory": "test_endpoints",
        "workflowConfigsSubDirectoryOverride": "shared_workflows",
        "presetConfigsSubDirectoryOverride": "shared_presets",
        "chatPromptTemplateName": "test_template",
        "useFileLogging": True
    }


class TestConfigUtils:
    """
    Test suite for the configuration utility functions in config_utils.py.
    """

    @pytest.fixture(autouse=True)
    def reset_globals(self):
        """Resets global variables before each test to ensure isolation."""
        original_users = instance_global_variables.USERS
        original_config_dir = instance_global_variables.CONFIG_DIRECTORY
        original_public_dir = instance_global_variables.PUBLIC_DIRECTORY
        original_sqlite_dir = instance_global_variables.USER_LEVEL_SQLITE_DIRECTORY
        original_discussion_dir = instance_global_variables.DISCUSSION_DIRECTORY
        yield
        instance_global_variables.USERS = original_users
        instance_global_variables.CONFIG_DIRECTORY = original_config_dir
        instance_global_variables.PUBLIC_DIRECTORY = original_public_dir
        instance_global_variables.USER_LEVEL_SQLITE_DIRECTORY = original_sqlite_dir
        instance_global_variables.DISCUSSION_DIRECTORY = original_discussion_dir
        instance_global_variables.clear_request_user()

    def test_get_project_root_directory_path(self, mocker):
        """
        Verifies that the project root path is correctly calculated by navigating up
        from the current file's location.
        """
        mocker.patch('os.path.abspath', return_value='/root/Middleware/utilities/config_utils.py')
        mock_dirname = mocker.patch('os.path.dirname')
        mock_dirname.side_effect = [
            '/root/Middleware/utilities',  # dirname of abspath
            '/root/Middleware',  # dirname of util_dir
            '/root'  # dirname of middleware_dir
        ]

        result = config_utils.get_project_root_directory_path()

        assert result == '/root'
        assert mock_dirname.call_count == 3

    def test_load_config(self, mocker):
        """
        Tests that a JSON config file is correctly opened, read, and parsed.
        """
        mock_json_data = '{"key": "value", "number": 123}'
        mocker.patch('builtins.open', mock_open(read_data=mock_json_data))

        config_data = config_utils.load_config('/fake/path/to/config.json')

        assert config_data == {"key": "value", "number": 123}

    @pytest.mark.parametrize("config_data, config_property, expected", [
        ({"key": "value"}, "key", "value"),
        ({"key": ""}, "key", None),
        ({"other_key": "value"}, "key", None),
        ({}, "key", None),
        (None, "key", None)
    ], ids=["exists", "exists_empty", "not_exists", "empty_dict", "none_dict"])
    def test_get_config_property_if_exists(self, config_data, config_property, expected):
        """
        Tests the helper for safely retrieving a property from a dictionary.
        """
        assert config_utils.get_config_property_if_exists(config_property, config_data) == expected

    def test_get_current_username_from_single_user(self):
        """
        Verifies that the username is taken from USERS when it has exactly one entry.
        """
        instance_global_variables.USERS = ["global_user"]

        username = config_utils.get_current_username()

        assert username == "global_user"

    def test_get_current_username_from_file(self, mocker):
        """
        Verifies that the username is read from the _current-user.json file
        when USERS is None (no --User arg).
        """
        instance_global_variables.USERS = None
        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value='/fake/config')
        mock_json_data = '{"currentUser": "file_user"}'
        mocker.patch('builtins.open', mock_open(read_data=mock_json_data))
        mock_join = mocker.patch('os.path.join')

        username = config_utils.get_current_username()

        assert username == "file_user"
        mock_join.assert_called_once_with('/fake/config', 'Users', '_current-user.json')

    def test_get_user_config(self, mocker, mock_user_config):
        """
        Tests that the correct user-specific JSON config file is loaded.
        """
        mocker.patch('Middleware.utilities.config_utils.get_current_username', return_value='test_user')
        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value='/fake/config')
        mocker.patch('builtins.open', mock_open(read_data=json.dumps(mock_user_config)))
        mock_join = mocker.patch('os.path.join', return_value='/fake/config/Users/test_user.json')

        config = config_utils.get_user_config()

        assert config == mock_user_config
        mock_join.assert_called_once_with('/fake/config', 'Users', 'test_user.json')

    def test_get_config_value(self, mocker, mock_user_config):
        """
        Tests that a specific value can be retrieved from the user's config.
        """
        mocker.patch('Middleware.utilities.config_utils.get_user_config', return_value=mock_user_config)

        assert config_utils.get_config_value('port') == 5001
        assert config_utils.get_config_value('non_existent_key') is None

    def test_get_root_config_directory_from_global(self):
        """
        Verifies that the config directory is taken from the global variable if set.
        """
        instance_global_variables.CONFIG_DIRECTORY = '/global/config/dir'

        path = config_utils.get_root_config_directory()

        assert path == '/global/config/dir'

    def test_get_root_config_directory_from_project_root(self, mocker):
        """
        Verifies that the config directory is calculated relative to the project root
        when the global variable is not set.
        """
        instance_global_variables.CONFIG_DIRECTORY = None
        mocker.patch('Middleware.utilities.config_utils.get_project_root_directory_path', return_value='/proj')
        mocker.patch('os.path.join', return_value='/proj/Public/Configs')

        path = config_utils.get_root_config_directory()

        assert path == '/proj/Public/Configs'

    def test_get_root_config_directory_empty_string_falls_back_to_public(self, mocker):
        """An empty-string CONFIG_DIRECTORY must fall back to {public}/Configs, not return ''.

        This is reachable when a user passes '/' as the ConfigDirectory, since
        '/'.rstrip('/\\\\') == ''. A truthy guard (not 'is not None') handles it;
        a revert to 'is not None' would return os.path.join('') == '' and is caught here.
        """
        instance_global_variables.CONFIG_DIRECTORY = ''
        mocker.patch(
            'Middleware.utilities.config_utils.get_root_public_directory',
            return_value='/proj/Public',
        )

        path = config_utils.get_root_config_directory()

        assert path == os.path.join('/proj/Public', 'Configs')

    def test_get_discussion_file_path(self, mocker, mock_user_config):
        """
        Tests construction of a path to a discussion-specific file.
        Files are grouped in a subdirectory named after the discussion_id.
        """
        mocker.patch('Middleware.utilities.config_utils.get_config_value',
                     return_value=mock_user_config['discussionDirectory'])
        mock_makedirs = mocker.patch('os.makedirs')
        mocker.patch('os.path.exists', return_value=False)
        mocker.patch('os.path.join', side_effect=os.path.join)

        path = config_utils.get_discussion_file_path('discussion123', 'memories')

        expected_dir = os.path.join('/mock/discussions', 'discussion123')
        expected = os.path.join(expected_dir, 'memories.json')
        assert path == expected
        mock_makedirs.assert_called_once_with(expected_dir, exist_ok=True)

    def test_get_discussion_file_path_legacy_fallback(self, mocker, mock_user_config):
        """
        Tests that if the nested file does not exist but a legacy flat file does,
        the legacy path is returned for backwards compatibility.
        """
        mocker.patch('Middleware.utilities.config_utils.get_config_value',
                     return_value=mock_user_config['discussionDirectory'])
        mocker.patch('os.makedirs')
        mocker.patch('os.path.join', side_effect=os.path.join)

        nested = os.path.join('/mock/discussions', 'disc1', 'memories.json')
        legacy = os.path.join('/mock/discussions', 'disc1_memories.json')
        mocker.patch('os.path.exists', side_effect=lambda p: p == legacy)

        path = config_utils.get_discussion_file_path('disc1', 'memories')

        assert path == legacy

    def test_get_discussion_file_path_prefers_nested_over_legacy(self, mocker, mock_user_config):
        """
        Tests that if the nested file already exists, it is preferred even if
        a legacy flat file also exists.
        """
        mocker.patch('Middleware.utilities.config_utils.get_config_value',
                     return_value=mock_user_config['discussionDirectory'])
        mocker.patch('os.makedirs')
        mocker.patch('os.path.join', side_effect=os.path.join)

        nested = os.path.join('/mock/discussions', 'disc1', 'memories.json')
        mocker.patch('os.path.exists', return_value=True)

        path = config_utils.get_discussion_file_path('disc1', 'memories')

        assert path == nested

    def test_get_discussion_file_path_falls_back_when_empty(self, mocker):
        """
        Tests that an empty discussionDirectory falls back to {public_root}/DiscussionIds.
        """
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value='')
        mocker.patch('Middleware.utilities.config_utils.get_root_public_directory',
                     return_value='/project/Public')
        mocker.patch('Middleware.utilities.config_utils.get_project_root_directory_path',
                     return_value='/project')
        mock_makedirs = mocker.patch('os.makedirs')
        mocker.patch('os.path.exists', return_value=False)
        mocker.patch('os.path.join', side_effect=os.path.join)

        path = config_utils.get_discussion_file_path('disc1', 'memories')

        base_dir = os.path.join('/project/Public', 'DiscussionIds')
        expected_dir = os.path.join(base_dir, 'disc1')
        expected = os.path.join(expected_dir, 'memories.json')
        assert path == expected
        mock_makedirs.assert_called_once_with(expected_dir, exist_ok=True)

    def test_get_discussion_file_path_falls_back_when_none(self, mocker):
        """
        Tests that a None discussionDirectory falls back to {public_root}/DiscussionIds.
        """
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=None)
        mocker.patch('Middleware.utilities.config_utils.get_root_public_directory',
                     return_value='/project/Public')
        mocker.patch('Middleware.utilities.config_utils.get_project_root_directory_path',
                     return_value='/project')
        mock_makedirs = mocker.patch('os.makedirs')
        mocker.patch('os.path.exists', return_value=False)
        mocker.patch('os.path.join', side_effect=os.path.join)

        path = config_utils.get_discussion_file_path('disc1', 'chat_summary')

        base_dir = os.path.join('/project/Public', 'DiscussionIds')
        expected_dir = os.path.join(base_dir, 'disc1')
        expected = os.path.join(expected_dir, 'chat_summary.json')
        assert path == expected
        mock_makedirs.assert_called_once_with(expected_dir, exist_ok=True)

    def test_get_discussion_file_path_falls_back_when_directory_cannot_be_created(self, mocker):
        """
        Tests that an uncreatable discussionDirectory falls back to the legacy
        location under Public/DiscussionIds as a last resort.
        """
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value='D:\\Temp')
        mocker.patch('Middleware.utilities.config_utils.get_project_root_directory_path',
                     return_value='/project')
        mock_makedirs = mocker.patch('os.makedirs', side_effect=[OSError("bad path"), None])
        mocker.patch('os.path.exists', return_value=False)
        mocker.patch('os.path.join', side_effect=os.path.join)

        path = config_utils.get_discussion_file_path('disc1', 'memories')

        legacy_base_dir = os.path.join('/project', 'Public', 'DiscussionIds')
        expected_dir = os.path.join(legacy_base_dir, 'disc1')
        expected = os.path.join(expected_dir, 'memories.json')
        assert path == expected
        assert mock_makedirs.call_count == 2

    def test_get_discussion_file_path_sticks_to_legacy_folder_when_present(self, mocker):
        """
        Legacy stickiness: if the new target folder (under --PublicDirectory)
        does not exist but the discussion folder already exists at the
        pre-refactor location ({project_root}/Public/DiscussionIds/{disc}),
        that legacy folder is used for reads and writes so existing data is
        not stranded.
        """
        instance_global_variables.PUBLIC_DIRECTORY = '/shared/alice/Public'
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=None)
        mocker.patch('Middleware.utilities.config_utils.get_project_root_directory_path',
                     return_value='/project')
        mocker.patch('os.makedirs')
        mocker.patch('os.path.join', side_effect=os.path.join)

        target_folder = os.path.join('/shared/alice/Public', 'DiscussionIds', 'disc1')
        legacy_folder = os.path.join('/project', 'Public', 'DiscussionIds', 'disc1')
        mocker.patch('os.path.exists', side_effect=lambda p: p == legacy_folder)

        path = config_utils.get_discussion_file_path('disc1', 'memories')

        assert path == os.path.join(legacy_folder, 'memories.json')
        assert target_folder not in path

    def test_get_discussion_file_path_respects_cli_override(self, mocker):
        """
        The --DiscussionDirectory CLI flag takes precedence over both user
        config and the PublicDirectory-based default.
        """
        instance_global_variables.DISCUSSION_DIRECTORY = '/cli/discussions'
        mocker.patch('Middleware.utilities.config_utils.get_config_value',
                     return_value='/user/config/discussions')
        mocker.patch('Middleware.utilities.config_utils.get_root_public_directory',
                     return_value='/project/Public')
        mocker.patch('Middleware.utilities.config_utils.get_project_root_directory_path',
                     return_value='/project')
        mocker.patch('os.makedirs')
        mocker.patch('os.path.exists', return_value=False)
        mocker.patch('os.path.join', side_effect=os.path.join)

        path = config_utils.get_discussion_file_path('disc1', 'memories')

        assert path == os.path.join('/cli/discussions', 'disc1', 'memories.json')

    def test_get_discussion_file_path_uses_public_directory_default(self, mocker):
        """
        When --PublicDirectory is set and no per-file override is in play,
        discussions land at {PublicDirectory}/DiscussionIds/ (a sibling of
        Configs, not inside it).
        """
        instance_global_variables.PUBLIC_DIRECTORY = '/shared/alice/Public'
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=None)
        mocker.patch('Middleware.utilities.config_utils.get_project_root_directory_path',
                     return_value='/project')
        mocker.patch('os.makedirs')
        mocker.patch('os.path.exists', return_value=False)
        mocker.patch('os.path.join', side_effect=os.path.join)

        path = config_utils.get_discussion_file_path('disc1', 'memories')

        expected = os.path.join('/shared/alice/Public', 'DiscussionIds', 'disc1', 'memories.json')
        assert path == expected
        assert 'Configs' not in path

    def test_get_discussion_file_path_no_legacy_fallback_with_api_key_hash(self, mocker, mock_user_config):
        """
        Tests that the legacy fallback is skipped when api_key_hash is provided.
        Per Encryption.md, API key isolation is a new feature with no pre-existing
        legacy files, so we must not leak into the base directory.
        """
        mocker.patch('Middleware.utilities.config_utils.get_config_value',
                     return_value=mock_user_config['discussionDirectory'])
        mocker.patch('os.makedirs')
        mocker.patch('os.path.join', side_effect=os.path.join)

        nested = os.path.join('/mock/discussions', 'userhash', 'disc1', 'memories.json')
        legacy = os.path.join('/mock/discussions', 'disc1_memories.json')
        mocker.patch('os.path.exists', side_effect=lambda p: p == legacy)

        path = config_utils.get_discussion_file_path('disc1', 'memories', api_key_hash='userhash')

        assert path == nested

    def test_get_discussion_file_path_raises_on_none_discussion_id(self):
        """Tests that get_discussion_file_path raises ValueError when discussion_id is None."""
        with pytest.raises(ValueError, match="discussion_id is required"):
            config_utils.get_discussion_file_path(None, 'memories')

    def test_get_custom_dblite_filepath_with_config(self, mocker, mock_user_config):
        """
        Tests that the SQLite path is correctly retrieved from user config
        when no CLI override is set.
        """
        mocker.patch('Middleware.utilities.config_utils.get_config_value',
                     return_value=mock_user_config['sqlLiteDirectory'])

        path = config_utils.get_custom_dblite_filepath()

        assert path == '/mock/db'

    def test_get_custom_dblite_filepath_no_config(self, mocker):
        """
        Tests that the SQLite path falls back to {public_root}/SqlLiteDBs
        when no CLI override and no user config are present. The DB directory
        is a sibling of Configs under Public, not inside Configs.
        """
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=None)
        mocker.patch('Middleware.utilities.config_utils.get_root_public_directory',
                     return_value='/project/Public')

        path = config_utils.get_custom_dblite_filepath()

        assert path == os.path.join('/project/Public', 'SqlLiteDBs')
        assert 'Configs' not in path

    def test_get_custom_dblite_filepath_cli_override(self, mocker, mock_user_config):
        """
        The --UserLevelSqlLiteDirectory CLI flag takes precedence over both
        user config and the PublicDirectory-based default.
        """
        instance_global_variables.USER_LEVEL_SQLITE_DIRECTORY = '/cli/sqlite'
        mocker.patch('Middleware.utilities.config_utils.get_config_value',
                     return_value=mock_user_config['sqlLiteDirectory'])
        mocker.patch('Middleware.utilities.config_utils.get_root_public_directory',
                     return_value='/project/Public')

        path = config_utils.get_custom_dblite_filepath()

        assert path == '/cli/sqlite'

    def test_get_custom_dblite_filepath_uses_public_directory_default(self, mocker):
        """
        When --PublicDirectory is set and no per-file override is in play,
        SQLite databases land at {PublicDirectory}/SqlLiteDBs/.
        """
        instance_global_variables.PUBLIC_DIRECTORY = '/shared/alice/Public'
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=None)

        path = config_utils.get_custom_dblite_filepath()

        assert path == os.path.join('/shared/alice/Public', 'SqlLiteDBs')
        assert 'Configs' not in path

    def test_get_root_config_directory_derives_from_public_directory(self, mocker):
        """
        When --PublicDirectory is set but --ConfigDirectory is not,
        get_root_config_directory returns {PublicDirectory}/Configs/.
        """
        instance_global_variables.PUBLIC_DIRECTORY = '/shared/alice/Public'
        instance_global_variables.CONFIG_DIRECTORY = None

        path = config_utils.get_root_config_directory()

        assert path == os.path.join('/shared/alice/Public', 'Configs')

    def test_get_root_config_directory_config_cli_wins_over_public(self, mocker):
        """
        --ConfigDirectory takes precedence over --PublicDirectory for config
        resolution (backwards compat for installations already using
        --ConfigDirectory).
        """
        instance_global_variables.PUBLIC_DIRECTORY = '/shared/alice/Public'
        instance_global_variables.CONFIG_DIRECTORY = '/legacy/custom-config-dir'

        path = config_utils.get_root_config_directory()

        assert path == '/legacy/custom-config-dir'

    def test_get_root_public_directory_defaults_to_project_public(self, mocker):
        """
        Without --PublicDirectory, the public root defaults to
        {project_root}/Public (the in-tree location).
        """
        instance_global_variables.PUBLIC_DIRECTORY = None
        mocker.patch('Middleware.utilities.config_utils.get_project_root_directory_path',
                     return_value='/project')

        path = config_utils.get_root_public_directory()

        assert path == os.path.join('/project', 'Public')

    def test_get_endpoint_subdirectory(self, mocker, mock_user_config):
        """
        Tests retrieval of the endpoint subdirectory.
        """
        mocker.patch('Middleware.utilities.config_utils.get_config_value',
                     return_value=mock_user_config['endpointConfigsSubDirectory'])

        assert config_utils.get_endpoint_subdirectory() == 'test_endpoints'

    def test_get_preset_subdirectory_override_exists(self, mocker, mock_user_config):
        """
        Tests that the preset subdirectory override is used when it exists.
        """
        mocker.patch('Middleware.utilities.config_utils.get_config_value',
                     return_value=mock_user_config['presetConfigsSubDirectoryOverride'])

        assert config_utils.get_preset_subdirectory_override() == 'shared_presets'

    def test_get_preset_subdirectory_override_fallback(self, mocker):
        """
        Tests that the preset subdirectory falls back to the current username when the override is not set.
        """
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=None)
        mocker.patch('Middleware.utilities.config_utils.get_current_username', return_value='default_user')

        assert config_utils.get_preset_subdirectory_override() == 'default_user'

    def test_get_workflow_subdirectory_override_exists(self, mocker, mock_user_config):
        """
        Tests that the workflow subdirectory override is used when it exists.
        """
        mocker.patch('Middleware.utilities.config_utils.get_config_value',
                     return_value=mock_user_config['workflowConfigsSubDirectoryOverride'])

        expected = os.path.join('_overrides', 'shared_workflows')
        assert config_utils.get_workflow_subdirectory_override() == expected

    def test_get_workflow_subdirectory_override_fallback(self, mocker):
        """
        Tests that the workflow subdirectory falls back to the current username when the override is not set.
        """
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=None)
        mocker.patch('Middleware.utilities.config_utils.get_current_username', return_value='default_user')

        assert config_utils.get_workflow_subdirectory_override() == 'default_user'

    def test_get_workflow_path_with_override(self, mocker):
        """
        Tests that the workflow path uses the explicit override when provided.
        """
        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value='/fake/config')

        path = config_utils.get_workflow_path('MyWorkflow', user_folder_override='custom_folder')

        expected = os.path.join('/fake/config', 'Workflows', 'custom_folder', 'MyWorkflow.json')
        assert path == expected

    def test_get_workflow_path_uses_subdirectory_override(self, mocker):
        """
        Tests that the workflow path uses the user config subdirectory override when no explicit override is provided.
        """
        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value='/fake/config')
        mocker.patch('Middleware.utilities.config_utils.get_workflow_subdirectory_override',
                     return_value=os.path.join('_overrides', 'shared_workflows'))

        path = config_utils.get_workflow_path('MyWorkflow')

        expected = os.path.join('/fake/config', 'Workflows', '_overrides', 'shared_workflows', 'MyWorkflow.json')
        assert path == expected

    def test_get_workflow_path_fallback_to_username(self, mocker):
        """
        Tests that the workflow path falls back to the username when no overrides are set.
        """
        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value='/fake/config')
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=None)
        mocker.patch('Middleware.utilities.config_utils.get_current_username', return_value='test_user')

        path = config_utils.get_workflow_path('MyWorkflow')

        expected = os.path.join('/fake/config', 'Workflows', 'test_user', 'MyWorkflow.json')
        assert path == expected

    def test_get_workflow_subdirectory_override_empty_string(self, mocker):
        """
        Tests that an empty string override falls back to the current username.
        """
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value='')
        mocker.patch('Middleware.utilities.config_utils.get_current_username', return_value='default_user')

        assert config_utils.get_workflow_subdirectory_override() == 'default_user'

    def test_get_workflow_subdirectory_override_whitespace_only(self, mocker):
        """
        Tests that a whitespace-only override is treated as truthy and used within _overrides.
        This documents current behavior where whitespace strings are not stripped.
        """
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value='   ')

        expected = os.path.join('_overrides', '   ')
        assert config_utils.get_workflow_subdirectory_override() == expected

    def test_get_workflow_subdirectory_override_with_special_characters(self, mocker):
        """
        Tests that special characters in the override are preserved as-is.
        This documents that no sanitization occurs on the subdirectory name.
        """
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value='my-workflows_v2.0')

        expected = os.path.join('_overrides', 'my-workflows_v2.0')
        assert config_utils.get_workflow_subdirectory_override() == expected

    def test_get_workflow_path_with_path_traversal_characters(self, mocker):
        """
        Tests behavior with path traversal characters in the subdirectory override.
        This documents that path traversal is not sanitized (trust the config file).
        """
        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value='/fake/config')
        mocker.patch('Middleware.utilities.config_utils.get_workflow_subdirectory_override',
                     return_value=os.path.join('_overrides', '../parent_folder'))

        path = config_utils.get_workflow_path('MyWorkflow')

        expected = os.path.join('/fake/config', 'Workflows', '_overrides', '../parent_folder', 'MyWorkflow.json')
        assert path == expected

    def test_get_workflow_path_with_empty_string_node_override(self, mocker):
        """
        Tests that an empty string node-level override is still used (truthy check).
        """
        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value='/fake/config')
        mocker.patch('Middleware.utilities.config_utils.get_workflow_subdirectory_override',
                     return_value=os.path.join('_overrides', 'shared_workflows'))

        path = config_utils.get_workflow_path('MyWorkflow', user_folder_override='')

        expected = os.path.join('/fake/config', 'Workflows', '_overrides', 'shared_workflows', 'MyWorkflow.json')
        assert path == expected

    def test_get_workflow_path_with_absolute_workflow_name(self, mocker):
        """
        Tests behavior when workflow name contains path separators.
        This documents that workflow names are used as-is without sanitization.
        """
        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value='/fake/config')
        mocker.patch('Middleware.utilities.config_utils.get_current_username', return_value='test_user')
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=None)

        path = config_utils.get_workflow_path('subfolder/MyWorkflow')

        expected = os.path.join('/fake/config', 'Workflows', 'test_user', 'subfolder/MyWorkflow.json')
        assert path == expected

    def test_get_workflow_path_precedence_node_over_user_config(self, mocker):
        """
        Tests that node-level user_folder_override takes precedence over user config subdirectory override.
        """
        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value='/fake/config')
        mocker.patch('Middleware.utilities.config_utils.get_workflow_subdirectory_override',
                     return_value=os.path.join('_overrides', 'user_config_override'))

        path = config_utils.get_workflow_path('MyWorkflow', user_folder_override='node_override')

        expected = os.path.join('/fake/config', 'Workflows', 'node_override', 'MyWorkflow.json')
        assert path == expected

    def test_get_workflow_subdirectory_override_with_unicode(self, mocker):
        """
        Tests that Unicode characters in the override are preserved.
        """
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value='workflows-日本語')

        expected = os.path.join('_overrides', 'workflows-日本語')
        assert config_utils.get_workflow_subdirectory_override() == expected

    def test_get_workflow_path_with_very_long_override(self, mocker):
        """
        Tests behavior with a very long subdirectory override name.
        """
        long_name = 'a' * 500
        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value='/fake/config')
        mocker.patch('Middleware.utilities.config_utils.get_workflow_subdirectory_override',
                     return_value=os.path.join('_overrides', long_name))

        path = config_utils.get_workflow_path('MyWorkflow')

        expected = os.path.join('/fake/config', 'Workflows', '_overrides', long_name, 'MyWorkflow.json')
        assert path == expected

    def test_get_shared_workflows_folder_default(self, mocker):
        """
        Tests that the shared workflows folder returns '_shared' by default.
        """
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=None)

        assert config_utils.get_shared_workflows_folder() == '_shared'

    def test_get_shared_workflows_folder_with_override(self, mocker):
        """
        Tests that the shared workflows folder uses the override when set.
        """
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value='custom_shared')

        assert config_utils.get_shared_workflows_folder() == 'custom_shared'

    def test_get_shared_workflows_folder_empty_override(self, mocker):
        """
        Tests that an empty string override falls back to '_shared'.
        """
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value='')

        assert config_utils.get_shared_workflows_folder() == '_shared'

    def test_get_available_shared_workflows(self, mocker, tmp_path):
        """
        Tests that available workflow folders are correctly listed from the shared folder.
        The function lists subfolders (not files) in _shared/.
        """
        workflows_dir = tmp_path / 'Workflows' / '_shared'
        workflows_dir.mkdir(parents=True)
        (workflows_dir / 'coding-workflow').mkdir()  # Folder - should be included
        (workflows_dir / 'general-workflow').mkdir()  # Folder - should be included
        (workflows_dir / '_hidden-folder').mkdir()  # Should be excluded (starts with _)
        (workflows_dir / 'SomeFile.json').write_text('{}')  # Should be excluded (not a folder)

        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value=str(tmp_path))
        mocker.patch('Middleware.utilities.config_utils.get_shared_workflows_folder', return_value='_shared')

        workflows = config_utils.get_available_shared_workflows()

        assert workflows == ['coding-workflow', 'general-workflow']

    def test_get_available_shared_workflows_empty_directory(self, mocker, tmp_path):
        """
        Tests that empty list is returned for empty directory.
        """
        workflows_dir = tmp_path / 'Workflows' / '_shared'
        workflows_dir.mkdir(parents=True)

        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value=str(tmp_path))
        mocker.patch('Middleware.utilities.config_utils.get_shared_workflows_folder', return_value='_shared')

        workflows = config_utils.get_available_shared_workflows()

        assert workflows == []

    def test_get_available_shared_workflows_directory_not_exists(self, mocker, tmp_path):
        """
        Tests that empty list is returned when directory doesn't exist.
        """
        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value=str(tmp_path))
        mocker.patch('Middleware.utilities.config_utils.get_shared_workflows_folder', return_value='_shared')

        workflows = config_utils.get_available_shared_workflows()

        assert workflows == []

    def test_workflow_exists_in_shared_folder_true(self, mocker, tmp_path):
        """
        Tests that workflow_exists_in_shared_folder returns True when folder exists.
        """
        workflows_dir = tmp_path / 'Workflows' / '_shared'
        workflows_dir.mkdir(parents=True)
        (workflows_dir / 'coding-workflow').mkdir()

        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value=str(tmp_path))
        mocker.patch('Middleware.utilities.config_utils.get_shared_workflows_folder', return_value='_shared')

        assert config_utils.workflow_exists_in_shared_folder('coding-workflow') is True

    def test_workflow_exists_in_shared_folder_file_not_folder(self, mocker, tmp_path):
        """
        Tests that workflow_exists_in_shared_folder returns False when a file exists but not a folder.
        """
        workflows_dir = tmp_path / 'Workflows' / '_shared'
        workflows_dir.mkdir(parents=True)
        (workflows_dir / 'some-workflow.json').write_text('{}')

        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value=str(tmp_path))
        mocker.patch('Middleware.utilities.config_utils.get_shared_workflows_folder', return_value='_shared')

        assert config_utils.workflow_exists_in_shared_folder('some-workflow.json') is False
        assert config_utils.workflow_exists_in_shared_folder('some-workflow') is False

    def test_workflow_exists_in_shared_folder_false(self, mocker, tmp_path):
        """
        Tests that workflow_exists_in_shared_folder returns False when folder doesn't exist.
        """
        workflows_dir = tmp_path / 'Workflows' / '_shared'
        workflows_dir.mkdir(parents=True)

        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value=str(tmp_path))
        mocker.patch('Middleware.utilities.config_utils.get_shared_workflows_folder', return_value='_shared')

        assert config_utils.workflow_exists_in_shared_folder('NonExistent') is False

    def test_workflow_exists_in_shared_folder_directory_not_exists(self, mocker, tmp_path):
        """
        Tests that workflow_exists_in_shared_folder returns False when _shared directory doesn't exist.
        """
        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value=str(tmp_path))
        mocker.patch('Middleware.utilities.config_utils.get_shared_workflows_folder', return_value='_shared')

        assert config_utils.workflow_exists_in_shared_folder('AnyWorkflow') is False


class TestGetConnectTimeout:
    """Tests for the get_connect_timeout function."""

    def test_returns_config_value_when_present(self, mocker):
        """Tests that the configured value is returned when present."""
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=60)
        assert config_utils.get_connect_timeout() == 60

    def test_returns_default_30_when_missing(self, mocker):
        """Tests that 30 is returned when the config key is missing (None)."""
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=None)
        assert config_utils.get_connect_timeout() == 30

    def test_converts_string_to_int(self, mocker):
        """Tests that a string config value is converted to int."""
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value="45")
        assert config_utils.get_connect_timeout() == 45

    def test_zero_value_returns_minimum_of_one(self, mocker):
        """Tests that a value of 0 is clamped to the minimum of 1."""
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=0)
        assert config_utils.get_connect_timeout() == 1

    def test_negative_value_returns_minimum_of_one(self, mocker):
        """Tests that a negative value is clamped to the minimum of 1."""
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=-5)
        assert config_utils.get_connect_timeout() == 1


class TestGetDiscussionCondensationTrackerFilePath:
    """Tests for the get_discussion_condensation_tracker_file_path function."""

    def test_returns_correct_path(self, mocker):
        """Tests that the condensation tracker file path is correctly constructed."""
        mocker.patch('Middleware.utilities.config_utils.get_config_value',
                     return_value='/mock/discussions')
        mocker.patch('os.makedirs')
        mocker.patch('os.path.exists', return_value=False)
        mocker.patch('os.path.join', side_effect=os.path.join)

        result = config_utils.get_discussion_condensation_tracker_file_path('disc123')

        expected = os.path.join('/mock/discussions', 'disc123', 'condensation_tracker.json')
        assert result == expected

    def test_delegates_to_get_discussion_file_path(self, mocker):
        """Tests that it delegates to get_discussion_file_path with the correct file_name."""
        mock_get_path = mocker.patch(
            'Middleware.utilities.config_utils.get_discussion_file_path',
            return_value='/mock/discussions/disc123/condensation_tracker.json'
        )

        result = config_utils.get_discussion_condensation_tracker_file_path('disc123')

        mock_get_path.assert_called_once_with('disc123', 'condensation_tracker', api_key_hash=None)
        assert result == '/mock/discussions/disc123/condensation_tracker.json'


class TestGetDiscussionVisionResponsesFilePath:
    """Tests for the get_discussion_vision_responses_file_path function."""

    def test_returns_correct_path(self, mocker):
        """Tests that the vision responses file path is correctly constructed."""
        mocker.patch('Middleware.utilities.config_utils.get_config_value',
                     return_value='/mock/discussions')
        mocker.patch('os.makedirs')
        mocker.patch('os.path.exists', return_value=False)
        mocker.patch('os.path.join', side_effect=os.path.join)

        result = config_utils.get_discussion_vision_responses_file_path('disc456')

        expected = os.path.join('/mock/discussions', 'disc456', 'vision_responses.json')
        assert result == expected

    def test_delegates_to_get_discussion_file_path(self, mocker):
        """Tests that it delegates to get_discussion_file_path with the correct file_name."""
        mock_get_path = mocker.patch(
            'Middleware.utilities.config_utils.get_discussion_file_path',
            return_value='/mock/discussions/disc456_vision_responses.json'
        )

        result = config_utils.get_discussion_vision_responses_file_path('disc456')

        mock_get_path.assert_called_once_with('disc456', 'vision_responses', api_key_hash=None)
        assert result == '/mock/discussions/disc456_vision_responses.json'


class TestGetMaxCategorizationAttempts:
    """Tests for the get_max_categorization_attempts function."""

    def test_returns_config_value_when_present(self, mocker):
        """Tests that the configured value is returned when present."""
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=3)
        assert config_utils.get_max_categorization_attempts() == 3

    def test_returns_default_1_when_missing(self, mocker):
        """Tests that 1 is returned when the config key is missing (None)."""
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=None)
        assert config_utils.get_max_categorization_attempts() == 1

    def test_converts_string_to_int(self, mocker):
        """Tests that a string config value is converted to int."""
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value="5")
        assert config_utils.get_max_categorization_attempts() == 5


    def test_zero_value_returns_minimum_of_one(self, mocker):
        """Tests that a value of 0 is clamped to the minimum of 1."""
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=0)
        assert config_utils.get_max_categorization_attempts() == 1

    def test_negative_value_returns_minimum_of_one(self, mocker):
        """Tests that a negative value is clamped to the minimum of 1."""
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=-3)
        assert config_utils.get_max_categorization_attempts() == 1


class TestGetEncryptUsingApiKey:
    """Tests for the get_encrypt_using_api_key function."""

    def test_returns_true_when_enabled(self, mocker):
        """Tests that True is returned when the config value is True."""
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=True)
        assert config_utils.get_encrypt_using_api_key() is True

    def test_returns_false_when_disabled(self, mocker):
        """Tests that False is returned when the config value is False."""
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=False)
        assert config_utils.get_encrypt_using_api_key() is False

    def test_returns_false_when_missing(self, mocker):
        """Tests that False is returned when the config key is missing (None)."""
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=None)
        assert config_utils.get_encrypt_using_api_key() is False


class TestRequestAwareUsername:
    """Tests for request-aware get_current_username and get_user_config_for."""

    @pytest.fixture(autouse=True)
    def reset_globals(self):
        """Resets global variables before each test to ensure isolation."""
        original_users = instance_global_variables.USERS
        yield
        instance_global_variables.USERS = original_users
        instance_global_variables.clear_request_user()

    def test_request_user_takes_precedence_over_single_user(self):
        """Request-scoped user takes precedence over USERS[0] in single-user mode."""
        instance_global_variables.USERS = ["global_user"]
        instance_global_variables.set_request_user("request_user")

        assert config_utils.get_current_username() == "request_user"

    def test_single_user_used_when_no_request_user(self):
        """USERS[0] is returned in single-user mode when no request user is set."""
        instance_global_variables.USERS = ["global_user"]
        instance_global_variables.clear_request_user()

        assert config_utils.get_current_username() == "global_user"

    def test_multi_user_no_request_user_raises(self):
        """In multi-user mode, raises RuntimeError when no request user is set."""
        instance_global_variables.USERS = ["user-one", "user-two"]
        instance_global_variables.clear_request_user()

        with pytest.raises(RuntimeError, match="Multi-user mode active"):
            config_utils.get_current_username()

    def test_multi_user_with_request_user_works(self):
        """In multi-user mode, returns the request-scoped user."""
        instance_global_variables.USERS = ["user-one", "user-two"]
        instance_global_variables.set_request_user("user-two")

        assert config_utils.get_current_username() == "user-two"

    def test_file_fallback_when_no_user_set(self, mocker):
        """Falls back to _current-user.json when USERS is None."""
        instance_global_variables.USERS = None
        instance_global_variables.clear_request_user()
        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value='/fake/config')
        mock_json_data = '{"currentUser": "file_user"}'
        mocker.patch('builtins.open', mock_open(read_data=mock_json_data))
        mocker.patch('os.path.join')

        assert config_utils.get_current_username() == "file_user"

    def test_get_user_config_for_loads_specific_user(self, mocker):
        """get_user_config_for loads the config for the specified user, not the current user."""
        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value='/fake/config')
        expected_config = {"port": 5002, "allowSharedWorkflows": True}
        mocker.patch('builtins.open', mock_open(read_data=json.dumps(expected_config)))
        mocker.patch('os.path.join', return_value='/fake/config/Users/other_user.json')

        result = config_utils.get_user_config_for('Other_User')

        assert result == expected_config

    def test_get_user_config_delegates_to_get_user_config_for(self, mocker):
        """get_user_config delegates to get_user_config_for with the current username."""
        mocker.patch('Middleware.utilities.config_utils.get_current_username', return_value='test_user')
        mock_config_for = mocker.patch('Middleware.utilities.config_utils.get_user_config_for',
                                       return_value={"port": 5001})

        result = config_utils.get_user_config()

        mock_config_for.assert_called_once_with('test_user')
        assert result == {"port": 5001}


class TestGetRedactLogOutput:
    """Tests for the get_redact_log_output function."""

    def test_returns_true_when_enabled(self, mocker):
        """Tests that True is returned when the config value is True."""
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=True)
        assert config_utils.get_redact_log_output() is True

    def test_returns_false_when_disabled(self, mocker):
        """Tests that False is returned when the config value is False."""
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=False)
        assert config_utils.get_redact_log_output() is False

    def test_returns_false_when_missing(self, mocker):
        """Tests that False is returned when the config key is missing (None)."""
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=None)
        assert config_utils.get_redact_log_output() is False


class TestLoadMcpServerConfig:
    """Tests for the load_mcp_server_config function."""

    def test_loads_named_server_from_mcpservers_directory(self, mocker):
        """Verifies the config file is resolved under MCPServers/<name>.json and parsed."""
        mocker.patch(
            'Middleware.utilities.config_utils.get_root_config_directory',
            return_value='/fake/config',
        )
        mock_join = mocker.patch('os.path.join', return_value='/fake/config/MCPServers/filesystem.json')
        mock_data = json.dumps({"transport": "stdio", "command": "echo"})
        mocker.patch('builtins.open', mock_open(read_data=mock_data))

        config = config_utils.load_mcp_server_config('filesystem')

        assert config == {"transport": "stdio", "command": "echo"}
        mock_join.assert_called_once_with('/fake/config', 'MCPServers', 'filesystem.json')


class TestGetEstimationLevelMultiplier:
    """Tests for get_estimation_level_multiplier, the single source of truth that
    maps wilmerContextEstimationLevel to a budget multiplier. Default conservative
    (1.0) everywhere it is absent, so configs that never set it are unchanged."""

    def test_missing_key_returns_conservative_no_warning(self, caplog):
        """A config without the key defaults to conservative (1.0) and stays silent
        (absence is the norm, not a misconfiguration)."""
        with caplog.at_level("WARNING"):
            assert config_utils.get_estimation_level_multiplier({}) == 1.0
        assert not caplog.records

    def test_none_value_returns_conservative_no_warning(self, caplog):
        with caplog.at_level("WARNING"):
            assert config_utils.get_estimation_level_multiplier(
                {config_utils.ESTIMATION_LEVEL_KEY: None}) == 1.0
        assert not caplog.records

    def test_non_dict_returns_conservative_no_warning(self, caplog):
        """A non-dict (e.g. a mocked endpoint_file, or None) yields conservative
        without warning; this is the 'no config available' path, not a misconfig."""
        with caplog.at_level("WARNING"):
            assert config_utils.get_estimation_level_multiplier(None) == 1.0
            assert config_utils.get_estimation_level_multiplier("nope") == 1.0
        assert not caplog.records

    @pytest.mark.parametrize("level,expected", [
        ("conservative", 1.0),
        ("balanced", 1.25),
        ("aggressive", 1.5),
        ("xaggressive", 1.85),
    ])
    def test_each_valid_level(self, level, expected):
        assert config_utils.get_estimation_level_multiplier(
            {config_utils.ESTIMATION_LEVEL_KEY: level}) == expected

    def test_case_and_whitespace_insensitive(self):
        assert config_utils.get_estimation_level_multiplier(
            {config_utils.ESTIMATION_LEVEL_KEY: "  Balanced  "}) == 1.25

    def test_unknown_string_warns_once_and_defaults(self, caplog):
        """An unrecognized level falls back to conservative and warns exactly once."""
        with caplog.at_level("WARNING"):
            result = config_utils.get_estimation_level_multiplier(
                {config_utils.ESTIMATION_LEVEL_KEY: "ultra"})
        assert result == 1.0
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1
        assert config_utils.ESTIMATION_LEVEL_KEY in warnings[0].message

    def test_non_string_warns_once_and_defaults(self, caplog):
        """A non-string (e.g. a number) falls back to conservative and warns once."""
        with caplog.at_level("WARNING"):
            result = config_utils.get_estimation_level_multiplier(
                {config_utils.ESTIMATION_LEVEL_KEY: 1.5})
        assert result == 1.0
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1

    def test_all_levels_monotonic_increasing(self):
        """The four levels must be strictly increasing so a higher level always
        reclaims at least as much window (conservative is the safe floor)."""
        values = [config_utils.ESTIMATION_LEVEL_MULTIPLIERS[k]
                  for k in ("conservative", "balanced", "aggressive", "xaggressive")]
        assert values == sorted(values)
        assert values[0] == 1.0
        assert all(a < b for a, b in zip(values, values[1:]))


class TestComputeEndpointWindowBudget:
    """Adversarial tests for the shared window-budget helper. It is the single basis
    for BOTH the dispatch clamp and the variable-manager cap, so any bug here corrupts
    both. budget = (window - n_predict) * level - headroom."""

    def test_basic_conservative(self):
        # (1000 - 200) * 1.0 - 512 = 288
        assert config_utils.compute_endpoint_window_budget({"maxContextTokenSize": 1000}, 200, 512) == 288

    def test_level_scales_window_minus_response_not_headroom(self):
        # aggressive: int((1000-200)*1.5) - 512 = 1200 - 512 = 688. Headroom subtracted AFTER scaling.
        ep = {"maxContextTokenSize": 1000, "wilmerContextEstimationLevel": "aggressive"}
        assert config_utils.compute_endpoint_window_budget(ep, 200, 512) == 688

    def test_headroom_is_not_inside_the_scaling(self):
        # If headroom were scaled, this would be int((1000-200-512)*1.85). Prove it is NOT:
        # the correct value is int((1000-200)*1.85) - 512 = 1480 - 512 = 968.
        ep = {"maxContextTokenSize": 1000, "wilmerContextEstimationLevel": "xaggressive"}
        assert config_utils.compute_endpoint_window_budget(ep, 200, 512) == 968
        assert config_utils.compute_endpoint_window_budget(ep, 200, 512) != int((1000 - 200 - 512) * 1.85)

    def test_none_when_endpoint_not_dict(self):
        for bad in (None, "65536", ["x"], 1000, 3.5):
            assert config_utils.compute_endpoint_window_budget(bad, 200, 512) is None

    def test_none_when_window_missing(self):
        assert config_utils.compute_endpoint_window_budget({}, 200, 512) is None

    def test_none_when_window_zero_or_negative(self):
        for bad in (0, -1, -100000):
            assert config_utils.compute_endpoint_window_budget({"maxContextTokenSize": bad}, 200, 512) is None

    def test_bool_window_rejected_not_treated_as_int(self):
        # True/False are int subclasses; a boolean window must be rejected, not read as 1/0.
        assert config_utils.compute_endpoint_window_budget({"maxContextTokenSize": True}, 0, 0) is None
        assert config_utils.compute_endpoint_window_budget({"maxContextTokenSize": False}, 0, 0) is None

    def test_string_window_rejected(self):
        assert config_utils.compute_endpoint_window_budget({"maxContextTokenSize": "1000"}, 200, 512) is None

    def test_float_window_accepted_and_floored(self):
        # 1000.9 -> int 1000; (1000 - 200) - 0 = 800.
        assert config_utils.compute_endpoint_window_budget({"maxContextTokenSize": 1000.9}, 200, 0) == 800

    def test_n_predict_non_numeric_treated_as_zero(self):
        assert config_utils.compute_endpoint_window_budget({"maxContextTokenSize": 1000}, "oops", 0) == 1000
        assert config_utils.compute_endpoint_window_budget({"maxContextTokenSize": 1000}, None, 0) == 1000
        assert config_utils.compute_endpoint_window_budget({"maxContextTokenSize": 1000}, [5], 0) == 1000

    def test_n_predict_bool_treated_as_zero(self):
        # True must NOT count as n_predict=1.
        assert config_utils.compute_endpoint_window_budget({"maxContextTokenSize": 1000}, True, 0) == 1000

    def test_n_predict_negative_treated_as_zero(self):
        assert config_utils.compute_endpoint_window_budget({"maxContextTokenSize": 1000}, -500, 0) == 1000

    def test_n_predict_exceeds_window_returns_negative_not_none(self):
        # Misconfig (response > window): a negative budget is RETURNED so callers can degrade,
        # NOT None (None would silently disable the clamp).
        budget = config_utils.compute_endpoint_window_budget({"maxContextTokenSize": 1000}, 2000, 512)
        assert budget == 1000 - 2000 - 512
        assert budget is not None

    def test_response_equals_window_gives_negative_headroom(self):
        assert config_utils.compute_endpoint_window_budget({"maxContextTokenSize": 1000}, 1000, 512) == -512

    def test_unknown_level_falls_back_to_conservative(self):
        ep = {"maxContextTokenSize": 1000, "wilmerContextEstimationLevel": "ludicrous"}
        assert config_utils.compute_endpoint_window_budget(ep, 200, 512) == 288  # 1.0, same as no level

    def test_zero_headroom(self):
        assert config_utils.compute_endpoint_window_budget({"maxContextTokenSize": 1000}, 200, 0) == 800

    def test_does_not_mutate_endpoint_config(self):
        ep = {"maxContextTokenSize": 65536, "wilmerContextEstimationLevel": "aggressive"}
        before = dict(ep)
        config_utils.compute_endpoint_window_budget(ep, 16000, 512)
        assert ep == before  # the window value is read, never changed

    def test_shared_headroom_constant_value(self):
        # Dispatch aliases this; if it ever changes, both subsystems move together.
        assert config_utils.CONTEXT_WINDOW_BUDGET_HEADROOM_TOKENS == 512


class TestIsContextClampEnabled:
    """Adversarial tests for the shared clamp resolution (node > endpoint > user >
    default OFF). Used by BOTH dispatch and the variable manager, so a precedence or
    coercion bug silently changes behavior everywhere."""

    @pytest.fixture(autouse=True)
    def _no_user_config(self, mocker):
        # User level defaults to {} (no flag); individual tests override return_value/side_effect.
        self._user = mocker.patch('Middleware.utilities.config_utils.get_user_config', return_value={})

    def test_default_off_when_absent_everywhere(self):
        assert config_utils.is_context_clamp_enabled({}, {}) is False

    def test_node_true(self):
        assert config_utils.is_context_clamp_enabled({"clampPromptToContextWindow": True}, {}) is True

    def test_node_false_overrides_endpoint_true(self):
        assert config_utils.is_context_clamp_enabled(
            {"clampPromptToContextWindow": False}, {"clampPromptToContextWindow": True}) is False

    def test_node_true_overrides_endpoint_false(self):
        assert config_utils.is_context_clamp_enabled(
            {"clampPromptToContextWindow": True}, {"clampPromptToContextWindow": False}) is True

    def test_endpoint_used_when_node_absent(self):
        assert config_utils.is_context_clamp_enabled({}, {"clampPromptToContextWindow": True}) is True

    def test_node_null_falls_through_to_endpoint(self):
        # Explicit JSON null at the node must NOT be read as False; fall through.
        assert config_utils.is_context_clamp_enabled(
            {"clampPromptToContextWindow": None}, {"clampPromptToContextWindow": True}) is True

    def test_endpoint_null_falls_through_to_user(self):
        self._user.return_value = {"clampPromptToContextWindow": True}
        assert config_utils.is_context_clamp_enabled({}, {"clampPromptToContextWindow": None}) is True

    def test_user_true_when_node_endpoint_absent(self):
        self._user.return_value = {"clampPromptToContextWindow": True}
        assert config_utils.is_context_clamp_enabled({}, {}) is True

    def test_user_false_when_node_endpoint_absent(self):
        self._user.return_value = {"clampPromptToContextWindow": False}
        assert config_utils.is_context_clamp_enabled({}, {}) is False

    def test_node_beats_user(self):
        self._user.return_value = {"clampPromptToContextWindow": True}
        assert config_utils.is_context_clamp_enabled({"clampPromptToContextWindow": False}, {}) is False

    def test_endpoint_beats_user(self):
        self._user.return_value = {"clampPromptToContextWindow": True}
        assert config_utils.is_context_clamp_enabled({}, {"clampPromptToContextWindow": False}) is False

    @pytest.mark.parametrize("val,expected", [
        ("true", True), ("True", True), ("TRUE", True), ("  true  ", True),
        ("1", True), ("yes", True), ("on", True),
        ("false", False), ("False", False), ("0", False), ("no", False),
        ("off", False), ("garbage", False), ("", False),
    ])
    def test_string_coercion(self, val, expected):
        assert config_utils.is_context_clamp_enabled({"clampPromptToContextWindow": val}, {}) is expected

    @pytest.mark.parametrize("val,expected", [
        (1, True), (0, False), (2, True), (-1, True),
        ([1], True), ([], False), ({"a": 1}, True), ({}, False),
    ])
    def test_non_string_non_bool_coercion(self, val, expected):
        assert config_utils.is_context_clamp_enabled({"clampPromptToContextWindow": val}, {}) is expected

    def test_node_not_dict_is_skipped_not_crashed(self):
        for bad in (None, "nope", ["x"], 5):
            assert config_utils.is_context_clamp_enabled(bad, {"clampPromptToContextWindow": True}) is True

    def test_endpoint_not_dict_is_skipped(self):
        assert config_utils.is_context_clamp_enabled({}, None) is False  # node {} -> ep None -> user {} -> default

    def test_user_config_raises_defaults_off(self):
        self._user.side_effect = RuntimeError("no user resolvable")
        assert config_utils.is_context_clamp_enabled({}, {}) is False

    def test_user_config_non_dict_ignored(self):
        self._user.return_value = "not a dict"
        assert config_utils.is_context_clamp_enabled({}, {}) is False

    def test_returns_real_bool_not_truthy(self):
        # Callers gate on identity in places; ensure a genuine bool comes back.
        assert config_utils.is_context_clamp_enabled({"clampPromptToContextWindow": "true"}, {}) is True
        assert config_utils.is_context_clamp_enabled({}, {}) is False
