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
        yield
        instance_global_variables.USERS = original_users
        instance_global_variables.CONFIG_DIRECTORY = original_config_dir
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
        Tests that an empty discussionDirectory falls back to Public/DiscussionIds.
        """
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value='')
        mocker.patch('Middleware.utilities.config_utils.get_project_root_directory_path',
                     return_value='/project')
        mock_makedirs = mocker.patch('os.makedirs')
        mocker.patch('os.path.exists', return_value=False)
        mocker.patch('os.path.join', side_effect=os.path.join)

        path = config_utils.get_discussion_file_path('disc1', 'memories')

        base_dir = os.path.join('/project', 'Public', 'DiscussionIds')
        expected_dir = os.path.join(base_dir, 'disc1')
        expected = os.path.join(expected_dir, 'memories.json')
        assert path == expected
        mock_makedirs.assert_called_once_with(expected_dir, exist_ok=True)

    def test_get_discussion_file_path_falls_back_when_none(self, mocker):
        """
        Tests that a None discussionDirectory falls back to Public/DiscussionIds.
        """
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=None)
        mocker.patch('Middleware.utilities.config_utils.get_project_root_directory_path',
                     return_value='/project')
        mock_makedirs = mocker.patch('os.makedirs')
        mocker.patch('os.path.exists', return_value=False)
        mocker.patch('os.path.join', side_effect=os.path.join)

        path = config_utils.get_discussion_file_path('disc1', 'chat_summary')

        base_dir = os.path.join('/project', 'Public', 'DiscussionIds')
        expected_dir = os.path.join(base_dir, 'disc1')
        expected = os.path.join(expected_dir, 'chat_summary.json')
        assert path == expected
        mock_makedirs.assert_called_once_with(expected_dir, exist_ok=True)

    def test_get_discussion_file_path_falls_back_when_directory_cannot_be_created(self, mocker):
        """
        Tests that an invalid/uncreatable discussionDirectory (e.g. a Windows path
        on macOS) falls back to Public/DiscussionIds.
        """
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value='D:\\Temp')
        mocker.patch('Middleware.utilities.config_utils.get_project_root_directory_path',
                     return_value='/project')
        mock_makedirs = mocker.patch('os.makedirs', side_effect=[OSError("bad path"), None])
        mocker.patch('os.path.exists', return_value=False)
        mocker.patch('os.path.join', side_effect=os.path.join)

        path = config_utils.get_discussion_file_path('disc1', 'memories')

        base_dir = os.path.join('/project', 'Public', 'DiscussionIds')
        expected_dir = os.path.join(base_dir, 'disc1')
        expected = os.path.join(expected_dir, 'memories.json')
        assert path == expected
        assert mock_makedirs.call_count == 2

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
        Tests that the SQLite path is correctly retrieved from user config.
        """
        mocker.patch('Middleware.utilities.config_utils.get_config_value',
                     return_value=mock_user_config['sqlLiteDirectory'])

        path = config_utils.get_custom_dblite_filepath()

        assert path == '/mock/db'

    def test_get_custom_dblite_filepath_no_config(self, mocker):
        """
        Tests that the SQLite path falls back to the project root if not in config.
        """
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=None)
        mocker.patch('Middleware.utilities.config_utils.get_project_root_directory_path', return_value='/project/root')

        path = config_utils.get_custom_dblite_filepath()

        assert path == '/project/root'

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
