# Middleware/llmapis/handlers/impl/litellm_api_handler.py

"""
LiteLLM API handler.

Routes requests through a LiteLLM proxy (https://github.com/BerriAI/litellm),
which provides a unified OpenAI-compatible Chat Completions endpoint for 100+
LLM providers (Anthropic, Bedrock, Vertex, Gemini, Cohere, Mistral, etc.).

Since the LiteLLM proxy speaks the OpenAI Chat Completions format, this handler
extends OpenAiApiHandler and inherits all its payload and response parsing logic.
Users configure their LiteLLM proxy URL as the endpoint in their WilmerAI config.
"""

import logging

from Middleware.llmapis.handlers.impl.openai_api_handler import OpenAiApiHandler

logger = logging.getLogger(__name__)


class LiteLLMApiHandler(OpenAiApiHandler):
    """
    Handles interactions with a LiteLLM proxy via OpenAI-compatible Chat Completions.

    Inherits all behavior from OpenAiApiHandler. The proxy URL and API key
    are configured via the standard WilmerAI endpoint configuration file.
    """

    pass
