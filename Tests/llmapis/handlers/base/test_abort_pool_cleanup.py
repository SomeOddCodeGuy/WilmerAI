"""Check cancellation cleanup at a real Requests session boundary, without I/O."""
from unittest.mock import Mock

import requests

from Middleware.llmapis.handlers.base.base_api_transport import _AbortHandle


def test_abort_closes_owned_adapter_pools():
    session = requests.Session()
    adapters = list(session.adapters.values())
    for adapter in adapters:
        adapter.poolmanager.clear = Mock(wraps=adapter.poolmanager.clear)
    try:
        _AbortHandle(session, 'review-adapter-cleanup', 'non-streaming').abort()
        assert all(adapter.poolmanager.clear.called for adapter in adapters)
    finally:
        for adapter in adapters:
            adapter.close()
