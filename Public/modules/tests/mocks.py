# Mock LlmHandlerService for initialization
class MockLlmHandlerServiceForInit:
    def load_model_from_config(*args, **kwargs):
        return AsyncMock()