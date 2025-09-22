# Tests/api/test_api_server.py

from types import SimpleNamespace
from unittest.mock import MagicMock

from Middleware.api.api_server import ApiServer
from Middleware.api.handlers.base.base_api_handler import BaseApiHandler


class MockApiHandler(BaseApiHandler):
    """A concrete mock handler for testing."""

    def register_routes(self, app):
        pass


def test_discover_and_register_handlers(mocker):
    """
    Tests that ApiServer correctly discovers and registers handlers.
    """
    mocker.patch('os.walk', return_value=[
        ('/path/to/handlers/impl', [], ['my_handler.py'])
    ])

    mock_module = SimpleNamespace()
    mock_module.MockApiHandler = MockApiHandler
    mock_module.some_other_variable = 42

    mocker.patch('importlib.import_module', return_value=mock_module)

    mock_register = mocker.patch.object(MockApiHandler, 'register_routes')

    mock_app = MagicMock()
    server = ApiServer(app_instance=mock_app)

    mock_register.assert_called_once_with(mock_app)


def test_api_server_run(mocker):
    """
    Tests that ApiServer.run() calls the Flask app's run method correctly.
    """
    mocker.patch('Middleware.api.api_server.get_application_port', return_value=9999)
    mock_app = MagicMock()
    mock_app.run = MagicMock()

    mocker.patch.object(ApiServer, '_discover_and_register_handlers')

    server = ApiServer(app_instance=mock_app)
    server.run(debug=True)

    mock_app.run.assert_called_once_with(host='0.0.0.0', port=9999, debug=True)
