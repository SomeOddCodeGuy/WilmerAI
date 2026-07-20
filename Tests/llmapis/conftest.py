# Tests/llmapis/conftest.py

import pytest


@pytest.fixture(autouse=True)
def _hermetic_connect_timeout(mocker):
    """BaseApiTransport.__init__ resolves the connect timeout from the real user
    config on disk, so any test constructing a concrete handler without patching
    it silently depends on the repo's shipped config files. Default it here;
    tests asserting specific values re-patch locally, which overrides this."""
    mocker.patch(
        "Middleware.llmapis.handlers.base.base_api_transport.get_connect_timeout",
        return_value=10)
