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
        assert path == '/mock/discussions/discussion123_memories.json'

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
