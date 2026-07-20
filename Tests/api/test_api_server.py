# Tests/api/test_api_server.py

import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import Middleware.api.api_server as api_server_module
from Middleware.api.api_server import ApiServer
from Middleware.api.handlers.base.base_api_handler import BaseApiHandler
from Middleware.common import instance_global_variables


def _handlers_root():
    """Returns the real handlers directory used by ApiServer for discovery."""
    return os.path.join(os.path.dirname(api_server_module.__file__), 'handlers')


class MockApiHandler(BaseApiHandler):
    """A concrete mock handler for testing."""

    def register_routes(self, app):
        pass


class AbstractMockHandler(BaseApiHandler):
    """An abstract handler subclass (register_routes deliberately not implemented)."""
    pass


def test_discover_and_register_handlers(mocker):
    """
    Tests that ApiServer correctly discovers and registers handlers, importing
    the module via its exact dotted path under Middleware.api.handlers.
    """
    mocker.patch('os.walk', return_value=[
        (os.path.join(_handlers_root(), 'impl'), [], ['my_handler.py'])
    ])

    mock_module = SimpleNamespace()
    mock_module.MockApiHandler = MockApiHandler
    mock_module.some_other_variable = 42

    mock_import = mocker.patch('importlib.import_module', return_value=mock_module)

    mock_register = mocker.patch.object(MockApiHandler, 'register_routes')

    mock_app = MagicMock()
    server = ApiServer(app_instance=mock_app)

    mock_import.assert_called_once_with('Middleware.api.handlers.impl.my_handler')
    mock_register.assert_called_once_with(mock_app)


def test_discover_skips_dunder_and_base_files(mocker):
    """Files starting with '__' or 'base_' are never imported."""
    mocker.patch('os.walk', return_value=[
        (_handlers_root(), [], ['__init__.py', 'base_x.py']),
        (os.path.join(_handlers_root(), 'base'), [], ['base_api_handler.py']),
    ])
    mock_import = mocker.patch('importlib.import_module')

    ApiServer(app_instance=MagicMock())

    mock_import.assert_not_called()


def test_discover_skips_non_python_files(mocker):
    """Non-.py files in the handlers tree are never imported."""
    mocker.patch('os.walk', return_value=[
        (_handlers_root(), [], ['readme.md', 'handler.pyc']),
    ])
    mock_import = mocker.patch('importlib.import_module')

    ApiServer(app_instance=MagicMock())

    mock_import.assert_not_called()


def test_discover_tolerates_import_error_and_continues(mocker, caplog):
    """An ImportError from one handler module is logged and does not stop discovery."""
    mocker.patch('os.walk', return_value=[
        (os.path.join(_handlers_root(), 'impl'), [], ['broken_handler.py', 'good_handler.py'])
    ])

    good_module = SimpleNamespace()
    good_module.MockApiHandler = MockApiHandler

    def import_side_effect(name):
        if name.endswith('broken_handler'):
            raise ImportError("boom")
        return good_module

    mocker.patch('importlib.import_module', side_effect=import_side_effect)
    mock_register = mocker.patch.object(MockApiHandler, 'register_routes')

    mock_app = MagicMock()
    with caplog.at_level('ERROR', logger='Middleware.api.api_server'):
        ApiServer(app_instance=mock_app)

    # The failure was logged and registration continued with the good handler.
    assert 'broken_handler' in caplog.text
    mock_register.assert_called_once_with(mock_app)


def test_discover_tolerates_registration_exception_and_continues(mocker, caplog):
    """A handler whose register_routes raises hits the generic exception path:
    the failure is logged and discovery continues with the next handler module."""
    mocker.patch('os.walk', return_value=[
        (os.path.join(_handlers_root(), 'impl'), [], ['raising_handler.py', 'good_handler.py'])
    ])

    class RaisingHandler(BaseApiHandler):
        def register_routes(self, app):
            raise RuntimeError("registration exploded")

    raising_module = SimpleNamespace()
    raising_module.RaisingHandler = RaisingHandler
    good_module = SimpleNamespace()
    good_module.MockApiHandler = MockApiHandler

    def import_side_effect(name):
        if name.endswith('raising_handler'):
            return raising_module
        return good_module

    mocker.patch('importlib.import_module', side_effect=import_side_effect)
    mock_register = mocker.patch.object(MockApiHandler, 'register_routes')

    mock_app = MagicMock()
    with caplog.at_level('ERROR', logger='Middleware.api.api_server'):
        ApiServer(app_instance=mock_app)

    assert ('Failed to load or register handler from '
            'Middleware.api.handlers.impl.raising_handler') in caplog.text
    mock_register.assert_called_once_with(mock_app)


def test_discover_trims_trailing_dot_from_module_path(mocker):
    """A file named exactly '.py' produces a module path ending in '.'; the
    trailing dot is trimmed before import instead of crashing discovery."""
    mocker.patch('os.walk', return_value=[
        (_handlers_root(), [], ['.py'])
    ])
    mock_import = mocker.patch('importlib.import_module', return_value=SimpleNamespace())

    ApiServer(app_instance=MagicMock())

    mock_import.assert_called_once_with('Middleware.api.handlers')


def test_discover_excludes_abstract_handler_classes(mocker, caplog):
    """Abstract BaseApiHandler subclasses are skipped, not instantiated."""
    mocker.patch('os.walk', return_value=[
        (os.path.join(_handlers_root(), 'impl'), [], ['mixed_handler.py'])
    ])

    mock_module = SimpleNamespace()
    mock_module.AbstractMockHandler = AbstractMockHandler
    mock_module.MockApiHandler = MockApiHandler

    mocker.patch('importlib.import_module', return_value=mock_module)
    mock_register = mocker.patch.object(MockApiHandler, 'register_routes')

    mock_app = MagicMock()
    with caplog.at_level('ERROR', logger='Middleware.api.api_server'):
        ApiServer(app_instance=mock_app)

    # Only the concrete handler registered; instantiating the abstract one
    # would have raised TypeError and been logged as a failure.
    mock_register.assert_called_once_with(mock_app)
    assert 'Failed to load or register' not in caplog.text


def test_concurrency_middleware_applied_when_semaphore_configured(mocker):
    """When a request semaphore exists, wsgi_app is wrapped with the configured timeout."""
    mocker.patch('os.walk', return_value=[])
    semaphore = MagicMock(name='semaphore')
    mocker.patch(
        'Middleware.common.instance_global_variables.get_request_semaphore',
        return_value=semaphore
    )
    mocker.patch.object(instance_global_variables, 'CONCURRENCY_TIMEOUT', 321)
    mock_middleware_cls = mocker.patch(
        'Middleware.api.concurrency_middleware.ConcurrencyLimitMiddleware'
    )

    mock_app = MagicMock()
    original_wsgi_app = mock_app.wsgi_app

    ApiServer(app_instance=mock_app)

    mock_middleware_cls.assert_called_once_with(
        original_wsgi_app, semaphore, acquire_timeout=321
    )
    assert mock_app.wsgi_app is mock_middleware_cls.return_value


def test_concurrency_middleware_not_applied_without_semaphore(mocker):
    """When no request semaphore is configured, wsgi_app is left untouched."""
    mocker.patch('os.walk', return_value=[])
    mocker.patch(
        'Middleware.common.instance_global_variables.get_request_semaphore',
        return_value=None
    )
    mock_middleware_cls = mocker.patch(
        'Middleware.api.concurrency_middleware.ConcurrencyLimitMiddleware'
    )

    mock_app = MagicMock()
    original_wsgi_app = mock_app.wsgi_app

    ApiServer(app_instance=mock_app)

    mock_middleware_cls.assert_not_called()
    assert mock_app.wsgi_app is original_wsgi_app


# Every endpoint documented in Docs (Developer Api.md section 3 and the
# Adaptable_Front_End_Api user guide), plus the un-prefixed OpenAI aliases the
# handlers register for clients that omit /v1. Losing any of these breaks a
# documented client integration.
DOCUMENTED_ROUTES = [
    ('/v1/models', 'GET'),
    ('/v1/completions', 'POST'),
    ('/v1/chat/completions', 'POST'),
    ('/models', 'GET'),
    ('/completions', 'POST'),
    ('/chat/completions', 'POST'),
    ('/api/generate', 'POST'),
    ('/api/generate', 'DELETE'),
    ('/api/chat', 'POST'),
    ('/api/chat', 'DELETE'),
    ('/api/tags', 'GET'),
    ('/api/version', 'GET'),
]


def test_real_handler_discovery_registers_all_documented_endpoints(app):
    """End-to-end registration completeness: real discovery over the real
    handlers tree (session app fixture) must expose every documented route
    with its documented HTTP method."""
    registered = set()
    for rule in app.url_map.iter_rules():
        for method in rule.methods:
            registered.add((rule.rule, method))

    missing = [pair for pair in DOCUMENTED_ROUTES if pair not in registered]
    assert missing == [], f"Documented endpoints missing from the Flask app: {missing}"


def test_app_json_serializes_unicode_unescaped():
    """Pins the Flask 2.3 migration in app.py: ensure_ascii must be disabled on
    the app's JSON provider (the legacy JSON_AS_ASCII config key is dead), so
    non-streaming responses emit raw UTF-8 instead of \\uXXXX escapes."""
    from flask import jsonify
    from Middleware.api.app import app as flask_app

    assert flask_app.json.ensure_ascii is False

    with flask_app.test_request_context():
        raw = jsonify({"content": "héllo 世界"}).get_data()

    assert "世界".encode("utf-8") in raw
    assert b"\\u" not in raw


def test_api_server_has_no_run_method():
    """
    ApiServer no longer owns a run() method.  Port resolution and server
    startup are handled by the entry-point scripts (server.py, run_eventlet.py,
    run_waitress.py) so that multi-user mode can resolve the port before Flask
    is involved.
    """
    assert not hasattr(ApiServer, 'run')
