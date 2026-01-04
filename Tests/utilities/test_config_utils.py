# Tests/utilities/test_config_utils.py

import json
import os
from unittest.mock import mock_open

import pytest

from Middleware.common import instance_global_variables
from Middleware.utilities import config_utils


# Fixture to provide a consistent mock user configuration dictionary for multiple tests
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

    # We patch the global variables before each test and restore them after.
    @pytest.fixture(autouse=True)
    def reset_globals(self):
        """Resets global variables before each test to ensure isolation."""
        original_user = instance_global_variables.USER
        original_config_dir = instance_global_variables.CONFIG_DIRECTORY
        yield
        instance_global_variables.USER = original_user
        instance_global_variables.CONFIG_DIRECTORY = original_config_dir

    def test_get_project_root_directory_path(self, mocker):
        """
        Verifies that the project root path is correctly calculated by navigating up
        from the current file's location.
        """
        # Arrange
        mocker.patch('os.path.abspath', return_value='/root/Middleware/utilities/config_utils.py')
        mock_dirname = mocker.patch('os.path.dirname')
        mock_dirname.side_effect = [
            '/root/Middleware/utilities',  # dirname of abspath
            '/root/Middleware',  # dirname of util_dir
            '/root'  # dirname of middleware_dir
        ]

        # Act
        result = config_utils.get_project_root_directory_path()

        # Assert
        assert result == '/root'
        assert mock_dirname.call_count == 3

    def test_load_config(self, mocker):
        """
        Tests that a JSON config file is correctly opened, read, and parsed.
        """
        # Arrange
        mock_json_data = '{"key": "value", "number": 123}'
        mocker.patch('builtins.open', mock_open(read_data=mock_json_data))

        # Act
        config_data = config_utils.load_config('/fake/path/to/config.json')

        # Assert
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

    def test_get_current_username_from_global(self):
        """
        Verifies that the username is taken from the global variable if set.
        """
        # Arrange
        instance_global_variables.USER = "global_user"

        # Act
        username = config_utils.get_current_username()

        # Assert
        assert username == "global_user"

    def test_get_current_username_from_file(self, mocker):
        """
        Verifies that the username is read from the _current-user.json file
        when the global variable is not set.
        """
        # Arrange
        instance_global_variables.USER = None
        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value='/fake/config')
        mock_json_data = '{"currentUser": "file_user"}'
        mocker.patch('builtins.open', mock_open(read_data=mock_json_data))
        mock_join = mocker.patch('os.path.join')

        # Act
        username = config_utils.get_current_username()

        # Assert
        assert username == "file_user"
        mock_join.assert_called_once_with('/fake/config', 'Users', '_current-user.json')

    def test_get_user_config(self, mocker, mock_user_config):
        """
        Tests that the correct user-specific JSON config file is loaded.
        """
        # Arrange
        mocker.patch('Middleware.utilities.config_utils.get_current_username', return_value='test_user')
        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value='/fake/config')
        mocker.patch('builtins.open', mock_open(read_data=json.dumps(mock_user_config)))
        mock_join = mocker.patch('os.path.join', return_value='/fake/config/Users/test_user.json')

        # Act
        config = config_utils.get_user_config()

        # Assert
        assert config == mock_user_config
        mock_join.assert_called_once_with('/fake/config', 'Users', 'test_user.json')

    def test_get_config_value(self, mocker, mock_user_config):
        """
        Tests that a specific value can be retrieved from the user's config.
        """
        # Arrange
        mocker.patch('Middleware.utilities.config_utils.get_user_config', return_value=mock_user_config)

        # Act & Assert
        assert config_utils.get_config_value('port') == 5001
        assert config_utils.get_config_value('non_existent_key') is None

    def test_get_root_config_directory_from_global(self):
        """
        Verifies that the config directory is taken from the global variable if set.
        """
        # Arrange
        instance_global_variables.CONFIG_DIRECTORY = '/global/config/dir'

        # Act
        path = config_utils.get_root_config_directory()

        # Assert
        assert path == '/global/config/dir'

    def test_get_root_config_directory_from_project_root(self, mocker):
        """
        Verifies that the config directory is calculated relative to the project root
        when the global variable is not set.
        """
        # Arrange
        instance_global_variables.CONFIG_DIRECTORY = None
        mocker.patch('Middleware.utilities.config_utils.get_project_root_directory_path', return_value='/proj')
        mocker.patch('os.path.join', return_value='/proj/Public/Configs')

        # Act
        path = config_utils.get_root_config_directory()

        # Assert
        assert path == '/proj/Public/Configs'

    def test_get_discussion_file_path(self, mocker, mock_user_config):
        """
        Tests construction of a path to a discussion-specific file.
        """
        # Arrange
        mocker.patch('Middleware.utilities.config_utils.get_config_value',
                     return_value=mock_user_config['discussionDirectory'])
        mocker.patch('os.path.join', side_effect=os.path.join)

        # Act
        path = config_utils.get_discussion_file_path('discussion123', 'memories')

        # Assert
        expected = os.path.join('/mock/discussions', 'discussion123_memories.json')
        assert path == expected

    def test_get_custom_dblite_filepath_with_config(self, mocker, mock_user_config):
        """
        Tests that the SQLite path is correctly retrieved from user config.
        """
        # Arrange
        mocker.patch('Middleware.utilities.config_utils.get_config_value',
                     return_value=mock_user_config['sqlLiteDirectory'])

        # Act
        path = config_utils.get_custom_dblite_filepath()

        # Assert
        assert path == '/mock/db'

    def test_get_custom_dblite_filepath_no_config(self, mocker):
        """
        Tests that the SQLite path falls back to the project root if not in config.
        """
        # Arrange
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=None)
        mocker.patch('Middleware.utilities.config_utils.get_project_root_directory_path', return_value='/project/root')

        # Act
        path = config_utils.get_custom_dblite_filepath()

        # Assert
        assert path == '/project/root'

    def test_get_endpoint_subdirectory(self, mocker, mock_user_config):
        """
        Tests retrieval of the endpoint subdirectory.
        """
        # Arrange
        mocker.patch('Middleware.utilities.config_utils.get_config_value',
                     return_value=mock_user_config['endpointConfigsSubDirectory'])

        # Act & Assert
        assert config_utils.get_endpoint_subdirectory() == 'test_endpoints'

    def test_get_preset_subdirectory_override_exists(self, mocker, mock_user_config):
        """
        Tests that the preset subdirectory override is used when it exists.
        """
        # Arrange
        mocker.patch('Middleware.utilities.config_utils.get_config_value',
                     return_value=mock_user_config['presetConfigsSubDirectoryOverride'])

        # Act & Assert
        assert config_utils.get_preset_subdirectory_override() == 'shared_presets'

    def test_get_preset_subdirectory_override_fallback(self, mocker):
        """
        Tests that the preset subdirectory falls back to the current username when the override is not set.
        """
        # Arrange
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=None)
        mocker.patch('Middleware.utilities.config_utils.get_current_username', return_value='default_user')

        # Act & Assert
        assert config_utils.get_preset_subdirectory_override() == 'default_user'

    def test_get_workflow_subdirectory_override_exists(self, mocker, mock_user_config):
        """
        Tests that the workflow subdirectory override is used when it exists.
        """
        # Arrange
        mocker.patch('Middleware.utilities.config_utils.get_config_value',
                     return_value=mock_user_config['workflowConfigsSubDirectoryOverride'])

        # Act & Assert - should return _overrides/<override>
        expected = os.path.join('_overrides', 'shared_workflows')
        assert config_utils.get_workflow_subdirectory_override() == expected

    def test_get_workflow_subdirectory_override_fallback(self, mocker):
        """
        Tests that the workflow subdirectory falls back to the current username when the override is not set.
        """
        # Arrange
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=None)
        mocker.patch('Middleware.utilities.config_utils.get_current_username', return_value='default_user')

        # Act & Assert
        assert config_utils.get_workflow_subdirectory_override() == 'default_user'

    def test_get_workflow_path_with_override(self, mocker):
        """
        Tests that the workflow path uses the explicit override when provided.
        """
        # Arrange
        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value='/fake/config')

        # Act
        path = config_utils.get_workflow_path('MyWorkflow', user_folder_override='custom_folder')

        # Assert
        expected = os.path.join('/fake/config', 'Workflows', 'custom_folder', 'MyWorkflow.json')
        assert path == expected

    def test_get_workflow_path_uses_subdirectory_override(self, mocker):
        """
        Tests that the workflow path uses the user config subdirectory override when no explicit override is provided.
        """
        # Arrange
        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value='/fake/config')
        mocker.patch('Middleware.utilities.config_utils.get_workflow_subdirectory_override',
                     return_value=os.path.join('_overrides', 'shared_workflows'))

        # Act
        path = config_utils.get_workflow_path('MyWorkflow')

        # Assert
        expected = os.path.join('/fake/config', 'Workflows', '_overrides', 'shared_workflows', 'MyWorkflow.json')
        assert path == expected

    def test_get_workflow_path_fallback_to_username(self, mocker):
        """
        Tests that the workflow path falls back to the username when no overrides are set.
        """
        # Arrange
        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value='/fake/config')
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=None)
        mocker.patch('Middleware.utilities.config_utils.get_current_username', return_value='test_user')

        # Act
        path = config_utils.get_workflow_path('MyWorkflow')

        # Assert
        expected = os.path.join('/fake/config', 'Workflows', 'test_user', 'MyWorkflow.json')
        assert path == expected

    def test_get_workflow_subdirectory_override_empty_string(self, mocker):
        """
        Tests that an empty string override falls back to the current username.
        """
        # Arrange
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value='')
        mocker.patch('Middleware.utilities.config_utils.get_current_username', return_value='default_user')

        # Act & Assert
        assert config_utils.get_workflow_subdirectory_override() == 'default_user'

    def test_get_workflow_subdirectory_override_whitespace_only(self, mocker):
        """
        Tests that a whitespace-only override is treated as truthy and used within _overrides.
        This documents current behavior where whitespace strings are not stripped.
        """
        # Arrange
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value='   ')

        # Act & Assert - whitespace is preserved within _overrides path
        expected = os.path.join('_overrides', '   ')
        assert config_utils.get_workflow_subdirectory_override() == expected

    def test_get_workflow_subdirectory_override_with_special_characters(self, mocker):
        """
        Tests that special characters in the override are preserved as-is.
        This documents that no sanitization occurs on the subdirectory name.
        """
        # Arrange
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value='my-workflows_v2.0')

        # Act & Assert - should be within _overrides
        expected = os.path.join('_overrides', 'my-workflows_v2.0')
        assert config_utils.get_workflow_subdirectory_override() == expected

    def test_get_workflow_path_with_path_traversal_characters(self, mocker):
        """
        Tests behavior with path traversal characters in the subdirectory override.
        This documents that path traversal is not sanitized (trust the config file).
        """
        # Arrange
        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value='/fake/config')
        mocker.patch('Middleware.utilities.config_utils.get_workflow_subdirectory_override',
                     return_value=os.path.join('_overrides', '../parent_folder'))

        # Act
        path = config_utils.get_workflow_path('MyWorkflow')

        # Assert - path traversal characters are preserved within _overrides structure
        expected = os.path.join('/fake/config', 'Workflows', '_overrides', '../parent_folder', 'MyWorkflow.json')
        assert path == expected

    def test_get_workflow_path_with_empty_string_node_override(self, mocker):
        """
        Tests that an empty string node-level override is still used (truthy check).
        """
        # Arrange
        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value='/fake/config')
        mocker.patch('Middleware.utilities.config_utils.get_workflow_subdirectory_override',
                     return_value=os.path.join('_overrides', 'shared_workflows'))

        # Act - empty string is falsy, so it should fall back to get_workflow_subdirectory_override
        path = config_utils.get_workflow_path('MyWorkflow', user_folder_override='')

        # Assert - empty string is falsy, so should use subdirectory override
        expected = os.path.join('/fake/config', 'Workflows', '_overrides', 'shared_workflows', 'MyWorkflow.json')
        assert path == expected

    def test_get_workflow_path_with_absolute_workflow_name(self, mocker):
        """
        Tests behavior when workflow name contains path separators.
        This documents that workflow names are used as-is without sanitization.
        """
        # Arrange
        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value='/fake/config')
        mocker.patch('Middleware.utilities.config_utils.get_current_username', return_value='test_user')
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=None)

        # Act
        path = config_utils.get_workflow_path('subfolder/MyWorkflow')

        # Assert - path separators in workflow name are preserved
        expected = os.path.join('/fake/config', 'Workflows', 'test_user', 'subfolder/MyWorkflow.json')
        assert path == expected

    def test_get_workflow_path_precedence_node_over_user_config(self, mocker):
        """
        Tests that node-level user_folder_override takes precedence over user config subdirectory override.
        """
        # Arrange
        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value='/fake/config')
        mocker.patch('Middleware.utilities.config_utils.get_workflow_subdirectory_override',
                     return_value=os.path.join('_overrides', 'user_config_override'))

        # Act
        path = config_utils.get_workflow_path('MyWorkflow', user_folder_override='node_override')

        # Assert - node override should win (it's used as-is, not within _overrides)
        expected = os.path.join('/fake/config', 'Workflows', 'node_override', 'MyWorkflow.json')
        assert path == expected

    def test_get_workflow_subdirectory_override_with_unicode(self, mocker):
        """
        Tests that Unicode characters in the override are preserved.
        """
        # Arrange
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value='workflows-日本語')

        # Act & Assert - should be within _overrides
        expected = os.path.join('_overrides', 'workflows-日本語')
        assert config_utils.get_workflow_subdirectory_override() == expected

    def test_get_workflow_path_with_very_long_override(self, mocker):
        """
        Tests behavior with a very long subdirectory override name.
        """
        # Arrange
        long_name = 'a' * 500
        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value='/fake/config')
        mocker.patch('Middleware.utilities.config_utils.get_workflow_subdirectory_override',
                     return_value=os.path.join('_overrides', long_name))

        # Act
        path = config_utils.get_workflow_path('MyWorkflow')

        # Assert - long names are preserved within _overrides
        expected = os.path.join('/fake/config', 'Workflows', '_overrides', long_name, 'MyWorkflow.json')
        assert path == expected

    # Tests for shared workflows functionality

    def test_get_shared_workflows_folder_default(self, mocker):
        """
        Tests that the shared workflows folder returns '_shared' by default.
        """
        # Arrange
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value=None)

        # Act & Assert - should return _shared when no override is set
        assert config_utils.get_shared_workflows_folder() == '_shared'

    def test_get_shared_workflows_folder_with_override(self, mocker):
        """
        Tests that the shared workflows folder uses the override when set.
        """
        # Arrange
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value='custom_shared')

        # Act & Assert - should return the override value
        assert config_utils.get_shared_workflows_folder() == 'custom_shared'

    def test_get_shared_workflows_folder_empty_override(self, mocker):
        """
        Tests that an empty string override falls back to '_shared'.
        """
        # Arrange
        mocker.patch('Middleware.utilities.config_utils.get_config_value', return_value='')

        # Act & Assert - empty string is falsy, should return _shared
        assert config_utils.get_shared_workflows_folder() == '_shared'

    def test_get_available_shared_workflows(self, mocker, tmp_path):
        """
        Tests that available workflow folders are correctly listed from the shared folder.
        The function lists subfolders (not files) in _shared/.
        """
        # Arrange
        workflows_dir = tmp_path / 'Workflows' / '_shared'
        workflows_dir.mkdir(parents=True)
        (workflows_dir / 'coding-workflow').mkdir()  # Folder - should be included
        (workflows_dir / 'general-workflow').mkdir()  # Folder - should be included
        (workflows_dir / '_hidden-folder').mkdir()  # Should be excluded (starts with _)
        (workflows_dir / 'SomeFile.json').write_text('{}')  # Should be excluded (not a folder)

        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value=str(tmp_path))
        mocker.patch('Middleware.utilities.config_utils.get_shared_workflows_folder', return_value='_shared')

        # Act
        workflows = config_utils.get_available_shared_workflows()

        # Assert
        assert workflows == ['coding-workflow', 'general-workflow']

    def test_get_available_shared_workflows_empty_directory(self, mocker, tmp_path):
        """
        Tests that empty list is returned for empty directory.
        """
        # Arrange
        workflows_dir = tmp_path / 'Workflows' / '_shared'
        workflows_dir.mkdir(parents=True)

        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value=str(tmp_path))
        mocker.patch('Middleware.utilities.config_utils.get_shared_workflows_folder', return_value='_shared')

        # Act
        workflows = config_utils.get_available_shared_workflows()

        # Assert
        assert workflows == []

    def test_get_available_shared_workflows_directory_not_exists(self, mocker, tmp_path):
        """
        Tests that empty list is returned when directory doesn't exist.
        """
        # Arrange
        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value=str(tmp_path))
        mocker.patch('Middleware.utilities.config_utils.get_shared_workflows_folder', return_value='_shared')

        # Act
        workflows = config_utils.get_available_shared_workflows()

        # Assert
        assert workflows == []

    def test_workflow_exists_in_shared_folder_true(self, mocker, tmp_path):
        """
        Tests that workflow_exists_in_shared_folder returns True when folder exists.
        """
        # Arrange
        workflows_dir = tmp_path / 'Workflows' / '_shared'
        workflows_dir.mkdir(parents=True)
        (workflows_dir / 'coding-workflow').mkdir()  # Create a folder

        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value=str(tmp_path))
        mocker.patch('Middleware.utilities.config_utils.get_shared_workflows_folder', return_value='_shared')

        # Act & Assert
        assert config_utils.workflow_exists_in_shared_folder('coding-workflow') is True

    def test_workflow_exists_in_shared_folder_file_not_folder(self, mocker, tmp_path):
        """
        Tests that workflow_exists_in_shared_folder returns False when a file exists but not a folder.
        """
        # Arrange
        workflows_dir = tmp_path / 'Workflows' / '_shared'
        workflows_dir.mkdir(parents=True)
        (workflows_dir / 'some-workflow.json').write_text('{}')  # File, not folder

        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value=str(tmp_path))
        mocker.patch('Middleware.utilities.config_utils.get_shared_workflows_folder', return_value='_shared')

        # Act & Assert - files should NOT be detected, only folders
        assert config_utils.workflow_exists_in_shared_folder('some-workflow.json') is False
        assert config_utils.workflow_exists_in_shared_folder('some-workflow') is False

    def test_workflow_exists_in_shared_folder_false(self, mocker, tmp_path):
        """
        Tests that workflow_exists_in_shared_folder returns False when folder doesn't exist.
        """
        # Arrange
        workflows_dir = tmp_path / 'Workflows' / '_shared'
        workflows_dir.mkdir(parents=True)

        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value=str(tmp_path))
        mocker.patch('Middleware.utilities.config_utils.get_shared_workflows_folder', return_value='_shared')

        # Act & Assert
        assert config_utils.workflow_exists_in_shared_folder('NonExistent') is False

    def test_workflow_exists_in_shared_folder_directory_not_exists(self, mocker, tmp_path):
        """
        Tests that workflow_exists_in_shared_folder returns False when _shared directory doesn't exist.
        """
        # Arrange
        mocker.patch('Middleware.utilities.config_utils.get_root_config_directory', return_value=str(tmp_path))
        mocker.patch('Middleware.utilities.config_utils.get_shared_workflows_folder', return_value='_shared')

        # Act & Assert
        assert config_utils.workflow_exists_in_shared_folder('AnyWorkflow') is False
