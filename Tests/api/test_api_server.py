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


def test_api_server_has_no_run_method():
    """
    ApiServer no longer owns a run() method.  Port resolution and server
    startup are handled by the entry-point scripts (server.py, run_eventlet.py,
    run_waitress.py) so that multi-user mode can resolve the port before Flask
    is involved.
    """
    assert not hasattr(ApiServer, 'run')
