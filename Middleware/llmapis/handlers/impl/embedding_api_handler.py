# /Middleware/llmapis/handlers/impl/embedding_api_handler.py

import logging
from typing import Dict, List, Optional

from Middleware.common.constants import EMBEDDING_API_TYPES
from Middleware.llmapis.handlers.base.base_api_transport import BaseApiTransport

logger = logging.getLogger(__name__)


class EmbeddingApiHandler(BaseApiTransport):
    """
    Transport-level handler for embeddings endpoints.

    Deliberately a sibling of LlmApiHandler rather than a subclass: embeddings
    have no streaming, no prompt templates, and no samplers, so this class adds
    only URL construction, payload shaping, and response parsing for the two
    supported API flavors on top of the shared BaseApiTransport (which supplies
    the session, retry policy, timeouts, and cancellation handling).

    Supported API types (the ApiType config's 'type' field):
        - "openAIEmbeddings": POST {base}/v1/embeddings, response {"data": [{"index", "embedding"}]}
          (OpenAI, llama.cpp server with --embedding, and most compatible servers)
        - "ollamaEmbeddings": POST {base}/api/embed, response {"embeddings": [[...], ...]}
    """

    def __init__(self, base_url: str, api_key: str, headers: Dict[str, str], api_type: str,
                 model_name: str, dont_include_model: bool = False, suppress_retries: bool = True,
                 read_timeout: int = 120):
        """
        Initializes the embedding handler.

        Args:
            base_url (str): The base URL of the embeddings API.
            api_key (str): The API key for authentication.
            headers (Dict[str, str]): HTTP headers for requests.
            api_type (str): One of EMBEDDING_API_TYPES.
            model_name (str): The embedding model name to request.
            dont_include_model (bool): If True, omits the model from the payload.
            suppress_retries (bool): Forwarded to the transport retry policy.
                Defaults to True: embedding calls sit inline in memory search and
                write flows, where callers degrade to keyword search on failure,
                so it is better to fail fast than stack retries against a down
                endpoint.
            read_timeout (int): Per-request read timeout in seconds. Embeddings
                return in seconds, not hours; the short default keeps a wedged
                endpoint from stalling a memory node.

        Raises:
            ValueError: If api_type is not a recognized embeddings API type.
        """
        if api_type not in EMBEDDING_API_TYPES:
            raise ValueError(
                f"Unsupported embeddings API type '{api_type}'. Expected one of: {EMBEDDING_API_TYPES}")
        super().__init__(base_url=base_url, api_key=api_key, headers=headers,
                         suppress_retries=suppress_retries, read_timeout=read_timeout)
        self.api_type = api_type
        self.model_name = model_name
        self.dont_include_model = dont_include_model

    def _get_api_endpoint_url(self) -> str:
        """Constructs the full embeddings endpoint URL for the configured API type."""
        base = self.base_url.rstrip('/')
        if self.api_type == "ollamaEmbeddings":
            return f"{base}/api/embed"
        return f"{base}/v1/embeddings"

    def _prepare_payload(self, texts: List[str]) -> Dict:
        """Builds the request payload. Both supported APIs accept {'model', 'input'}."""
        payload = {"input": texts}
        if not self.dont_include_model:
            payload["model"] = self.model_name
        return payload

    def _parse_response(self, response_json: Dict) -> List[List[float]]:
        """
        Extracts the embedding vectors from a response body.

        Args:
            response_json (Dict): The parsed JSON response.

        Returns:
            List[List[float]]: One vector per input text, in input order.

        Raises:
            ValueError: If the response does not contain a usable embeddings list.
        """
        if not isinstance(response_json, dict):
            raise ValueError(
                f"Embeddings response was not a JSON object: {type(response_json).__name__}")

        if self.api_type == "ollamaEmbeddings":
            embeddings = response_json.get("embeddings")
        else:
            data = response_json.get("data")
            if not isinstance(data, list):
                raise ValueError(f"Embeddings response missing 'data' list. Keys: {list(response_json)}")
            # The API returns an index per item; sort defensively rather than
            # assuming response order matches input order.
            try:
                embeddings = [item.get("embedding") for item in
                              sorted(data, key=lambda item: item.get("index", 0))]
            except (TypeError, AttributeError) as e:
                raise ValueError(f"Embeddings response 'data' entries were malformed: {e}") from e

        if not isinstance(embeddings, list) or not all(isinstance(vec, list) and vec for vec in embeddings):
            raise ValueError("Embeddings response did not contain a list of non-empty vectors.")
        return embeddings

    def get_embeddings(self, texts: List[str], request_id: Optional[str] = None) -> Optional[List[List[float]]]:
        """
        Embeds a batch of texts.

        Args:
            texts (List[str]): The texts to embed.
            request_id (Optional[str]): The request ID for cancellation tracking.

        Returns:
            Optional[List[List[float]]]: One vector per input text, in input
            order; an empty list for empty input; or None if the request was
            cancelled.

        Raises:
            ValueError: If the response is malformed or the vector count does
                not match the input count.
            requests.exceptions.RequestException: On network failure after retries.
        """
        if not texts:
            return []

        payload = self._prepare_payload(texts)
        response_json = self.execute_non_streaming_post(
            self._get_api_endpoint_url(), payload, request_id=request_id)
        if response_json is None:
            return None

        embeddings = self._parse_response(response_json)
        if len(embeddings) != len(texts):
            raise ValueError(
                f"Embeddings response count mismatch: sent {len(texts)} texts, received {len(embeddings)} vectors.")
        return embeddings
