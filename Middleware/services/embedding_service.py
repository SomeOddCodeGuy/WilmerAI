# Middleware/services/embedding_service.py

import logging
from typing import List, Optional

from Middleware.common.constants import EMBEDDING_API_TYPES
from Middleware.llmapis.handlers.impl.embedding_api_handler import EmbeddingApiHandler
from Middleware.utilities.config_utils import get_api_type_config, get_endpoint_config

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Resolves an embeddings endpoint configuration and provides batch embedding.

    Embedding endpoints reuse the ordinary Endpoints/ config files and ApiTypes/
    registry; the only distinguishing feature is an ApiType whose 'type' is one
    of EMBEDDING_API_TYPES. Presets and prompt templates do not apply to
    embeddings and are ignored entirely.
    """

    def __init__(self, endpoint_name: str):
        """
        Loads the endpoint and API type configuration and builds the handler.

        Args:
            endpoint_name (str): The name of the endpoint config file to use.

        Raises:
            ValueError: If the endpoint's ApiType is not an embeddings type.
        """
        endpoint_file = get_endpoint_config(endpoint_name)
        api_type_config = get_api_type_config(endpoint_file.get("apiTypeConfigFileName", ""))
        api_type = api_type_config.get("type", "")
        if api_type not in EMBEDDING_API_TYPES:
            raise ValueError(
                f"Endpoint '{endpoint_name}' has API type '{api_type}', which is not an embeddings type. "
                f"An embeddings endpoint must use an ApiType whose 'type' is one of: {EMBEDDING_API_TYPES}")

        api_key = endpoint_file.get("apiKey", "")
        self.endpoint_name = endpoint_name
        self.model_name = endpoint_file.get("modelNameToSendToAPI", "")
        self._handler = EmbeddingApiHandler(
            base_url=endpoint_file["endpoint"],
            api_key=api_key,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + api_key
            },
            api_type=api_type,
            model_name=self.model_name,
            dont_include_model=endpoint_file.get("dontIncludeModel", False),
        )

    def get_embeddings(self, texts: List[str], request_id: Optional[str] = None) -> Optional[List[List[float]]]:
        """
        Embeds a batch of texts via the configured endpoint.

        Args:
            texts (List[str]): The texts to embed.
            request_id (Optional[str]): The request ID for cancellation tracking.

        Returns:
            Optional[List[List[float]]]: One vector per text in input order, an
            empty list for empty input, or None if the request was cancelled.
        """
        return self._handler.get_embeddings(texts, request_id=request_id)

    def close(self):
        """Closes the underlying HTTP session to release keep-alive connections."""
        self._handler.close()
