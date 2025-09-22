# Tests/conftest.py

import pytest

from Middleware.api.api_server import ApiServer
from Middleware.api.app import app as flask_app


@pytest.fixture(scope="session")
def app():
    """
    Session-wide test Flask application.
    Ensures routes are registered once per test session.
    """
    # ApiServer registers routes onto the app object during initialization.
    ApiServer(app_instance=flask_app)
    flask_app.config.update({"TESTING": True})
    yield flask_app


@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()
