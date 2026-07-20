import logging

import requests

from Middleware.utilities.config_utils import get_user_config

logger = logging.getLogger(__name__)

# Split connect/read timeouts (seconds) so a host that accepts the connection but
# never responds cannot hang the workflow (and the client request) indefinitely.
# Mirrors the offline researcher client. The read budget is generous because a
# top-N full-article fetch can return a large body from the local API.
_CONNECT_TIMEOUT_SECONDS = 5
_READ_TIMEOUT_SECONDS = 60


class OfflineWikiApiClient:
    """
    A client to interact with the OfflineWikipediaTextApi
    (https://github.com/SomeOddCodeGuy/OfflineWikipediaTextApi).
    """

    def __init__(self, activateWikiApi=False, baseurl='127.0.0.1', port=5728):
        """
        Initialize the OfflineWikiApiClient.

        The initialization fetches configuration settings to determine
        if the offline Wikipedia API should be used and sets the base URL
        and port for API requests. Defaults to default of the API project.
        """
        config = get_user_config()
        self.use_offline_wiki_api = config.get('useOfflineWikiApi', activateWikiApi)
        self.base_url = f"http://{config.get('offlineWikiApiHost', baseurl)}:{config.get('offlineWikiApiPort', port)}"

    def _get_logged(self, path, params):
        """
        Performs a GET against the API and logs the response.

        Args:
            path (str): The endpoint path under the base URL, without a leading slash.
            params (dict): Query string parameters for the request.

        Returns:
            requests.Response: The response; always has status 200 or 404.

        Raises:
            Exception: If the response status is anything other than 200 or 404.
        """
        response = requests.get(f"{self.base_url}/{path}", params=params,
                                timeout=(_CONNECT_TIMEOUT_SECONDS, _READ_TIMEOUT_SECONDS))
        logger.info(f"Response Status Code: {response.status_code}")
        # Full article bodies can be large; keep them out of INFO-level logs.
        logger.debug(f"Response Text: {response.text}")
        if response.status_code not in (200, 404):
            raise Exception(f"Error: {response.status_code}, {response.text}")
        return response

    def get_wiki_summary_by_prompt(self, prompt, percentile=0.5, num_results=1):
        """
        Get the first paragraph of the matching wikipedia article based on a prompt.

        Args:
            prompt (str): The prompt to generate the summaries.
            percentile (float): The relevance percentile to match summaries. Default is 0.5.
            num_results (int): The number of results to return. Default is 1.

        Returns:
            list: A list of summary dicts, or a single-item fallback list (also dicts)
                when the API is disabled or nothing matched.

        Raises:
            Exception: If the API request fails (except for 404s which return a not found message).
        """
        if not self.use_offline_wiki_api:
            return [{"title": "Offline Wiki Disabled", "text": "No additional information provided"}]

        response = self._get_logged("summaries", {
            'prompt': prompt,
            'percentile': percentile,
            'num_results': num_results
        })
        if response.status_code == 404:
            return [{"title": "Not Found",
                     "text": f"No summaries found for '{prompt}'. The information may not be available in the offline database."}]
        return response.json()

    # DEPRECATED. REMOVING SOON
    def get_full_wiki_article_by_prompt(self, prompt, percentile=0.5, num_results=1):
        """
        Get full text of Wikipedia articles based on a prompt.

        Args:
            prompt (str): The prompt to generate the articles.
            percentile (float): The relevance percentile to match articles. Default is 0.5.
            num_results (int): The number of results to return. Default is 1.

        Returns:
            list: A list of article texts.

        Raises:
            Exception: If the API request fails (except for 404s which return a not found message).
        """
        if not self.use_offline_wiki_api:
            return ["No additional information provided"]

        response = self._get_logged("articles", {
            'prompt': prompt,
            'percentile': percentile,
            'num_results': num_results
        })
        if response.status_code == 404:
            return [f"No articles found for '{prompt}'. The information may not be available in the offline database."]
        return [result.get('text', "No text element found") for result in response.json()]

    def get_top_full_wiki_article_by_prompt(self, prompt, percentile=0.5, num_results=10):
        """
        Get full text of Wikipedia articles based on a prompt.

        Args:
            prompt (str): The prompt to generate the articles.
            percentile (float): The relevance percentile to match articles. Default is 0.5.
            num_results (int): The number of results to return. Default is 10.

        Returns:
            list: A list containing the article text.

        Raises:
            Exception: If the API request fails (except for 404s which return a not found message).
        """
        if not self.use_offline_wiki_api:
            return ["No additional information provided"]

        response = self._get_logged("top_article", {
            'prompt': prompt,
            'percentile': percentile,
            'num_results': num_results
        })
        if response.status_code == 404:
            return [f"No article found for '{prompt}'. The information may not be available in the offline database."]
        return [response.json().get('text', "No text element found")]

    def get_top_n_full_wiki_articles_by_prompt(self, prompt, percentile=0.5, num_results=10, top_n_articles=3):
        """
        Get top N full text of Wikipedia articles based on a prompt.

        Args:
            prompt (str): The prompt to generate the articles.
            percentile (float): The relevance percentile to match articles. Default is 0.5.
            num_results (int): The number of results to return. Default is 10.
            top_n_articles (int): The number of top articles to return. Default is 3.

        Returns:
            list: The full result dicts (title/text) reported by the API, or a
                single-item fallback list when the API is disabled or nothing matched.

        Raises:
            Exception: If the API request fails (except for 404s which return a not found message).
        """
        if not self.use_offline_wiki_api:
            return ["No additional information provided"]

        response = self._get_logged("top_n_articles", {
            'prompt': prompt,
            'percentile': percentile,
            'num_results': num_results,
            'num_top_articles': top_n_articles
        })
        if response.status_code == 404:
            return [f"No articles found for '{prompt}'. The information may not be available in the offline database."]
        return response.json()
