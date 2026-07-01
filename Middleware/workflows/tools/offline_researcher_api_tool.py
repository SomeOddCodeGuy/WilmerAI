import logging

import requests

from Middleware.utilities.config_utils import get_user_config

logger = logging.getLogger(__name__)

NO_INFORMATION_FOUND_MESSAGE = "No pertinent information was found in the search"

# Connect-phase timeout (seconds). Bounds how long an unreachable host (e.g. a wrong
# IP/port) can hang on connect before failing, independent of the longer per-mode read
# timeout that the deep-research path may set.
_CONNECT_TIMEOUT_SECONDS = 5


class OfflineResearcherApiClient:
    """
    A client to interact with SomeOddCodeGuy's Offline Researcher service.

    The service exposes a single black-box endpoint that takes a research-style
    query and returns one synthesized prose answer along with the sources that
    contributed to it. This client only knows the POST /search contract; the
    iteration loop, intent classification, retrieval, and synthesis are all
    internal to the service.
    """

    def __init__(self, activate=False, baseurl='127.0.0.1', port=8890):
        """Initializes the OfflineResearcherApiClient.

        Reads the user config for the enable flag, host, and port; falls back
        to the constructor arguments when keys are absent.

        Args:
            activate (bool): Default enable flag if ``useOfflineResearcherApi`` is absent.
            baseurl (str): Default host if ``offlineResearcherApiHost`` is absent.
            port (int): Default port if ``offlineResearcherApiPort`` is absent.
        """
        config = get_user_config()
        self.use_offline_researcher_api = config.get('useOfflineResearcherApi', activate)
        self.base_url = (
            f"http://{config.get('offlineResearcherApiHost', baseurl)}"
            f":{config.get('offlineResearcherApiPort', port)}"
        )

    def search(self, query, mode, max_iterations=None, timeout_seconds=None):
        """
        Run a research query against the offline researcher service.

        Args:
            query (str): The research-style question.
            mode (str): One of "quick" or "deep". Other values are forwarded
                unchanged for forward-compatibility, but the node layer only
                exposes these two.
            max_iterations (int, optional): Per-request success target. When
                None, the service's mode-specific default is used.
            timeout_seconds (float, optional): HTTP read timeout for the POST.
                When None, the caller is expected to have picked a sensible
                mode-specific default before calling.

        Returns:
            dict: The parsed JSON body. On a transport-level failure, returns
                a synthesized error envelope shaped like the service's own
                error response so callers can treat both uniformly:
                {"status": "error", "reason": "...", "answer": None,
                 "no_information_found": False, "sources": []}
        """
        if not self.use_offline_researcher_api:
            return {
                "status": "error",
                "reason": "offline_researcher_disabled",
                "answer": None,
                "no_information_found": False,
                "sources": [],
            }

        url = f"{self.base_url}/search"
        payload = {"query": query, "mode": mode}
        if max_iterations is not None:
            payload["max_iterations"] = max_iterations

        # Separate connect/read timeouts so an unreachable host fails fast on connect
        # instead of waiting out the full (possibly long) read timeout.
        request_timeout = (
            (min(_CONNECT_TIMEOUT_SECONDS, timeout_seconds), timeout_seconds)
            if timeout_seconds is not None
            else None
        )
        try:
            response = requests.post(url, json=payload, timeout=request_timeout)
        except requests.exceptions.Timeout:
            logger.error(f"Offline researcher timed out after {timeout_seconds}s")
            return {
                "status": "error",
                "reason": "timeout",
                "answer": None,
                "no_information_found": False,
                "sources": [],
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"Offline researcher transport error: {e}")
            return {
                "status": "error",
                "reason": "transport_error",
                "answer": None,
                "no_information_found": False,
                "sources": [],
            }

        logger.debug(f"Offline researcher response status: {response.status_code}")
        if response.status_code == 200:
            try:
                return response.json()
            except ValueError:
                # A 200 with a non-JSON body (e.g. a misconfigured port hitting some
                # other local service) would otherwise raise out of search(), breaking
                # the documented "always returns an envelope" contract. Degrade instead.
                logger.error("Offline researcher returned a 200 with a non-JSON body")
                return {
                    "status": "error",
                    "reason": "invalid_json",
                    "answer": None,
                    "no_information_found": False,
                    "sources": [],
                }

        logger.error(f"Offline researcher returned {response.status_code}: {response.text[:500]}")
        return {
            "status": "error",
            "reason": f"http_{response.status_code}",
            "answer": None,
            "no_information_found": False,
            "sources": [],
        }
