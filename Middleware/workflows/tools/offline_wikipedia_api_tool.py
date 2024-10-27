import requests

from Middleware.utilities.config_utils import get_user_config


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

    def get_full_article_by_title(self, title):
        """
        Get the full Wikipedia article text by title.

        Args:
            title (str): The title of the Wikipedia article.

        Returns:
            str: The text of the Wikipedia article if found, or a message if not.

        Raises:
            Exception: If the API request fails.
        """
        if not self.use_offline_wiki_api:
            return "No additional information provided"

        url = f"{self.base_url}/articles/{title}"
        response = requests.get(url)
        print(f"Response Status Code: {response.status_code}")
        print(f"Response Text: {response.text}")
        if response.status_code == 200:
            return response.json().get('text', "No text element found")
        else:
            raise Exception(f"Error: {response.status_code}, {response.text}")

    def get_wiki_summary_by_prompt(self, prompt, percentile=0.5, num_results=1):
        """
        Get the first paragraph of the matching wikipedia article based on a prompt.

        Args:
            prompt (str): The prompt to generate the summaries.
            percentile (float): The relevance percentile to match summaries. Default is 0.5.
            num_results (int): The number of results to return. Default is 1.

        Returns:
            list: A list of summary texts.

        Raises:
            Exception: If the API request fails.
        """
        if not self.use_offline_wiki_api:
            return ["No additional information provided"]

        url = f"{self.base_url}/summaries"
        params = {
            'prompt': prompt,
            'percentile': percentile,
            'num_results': num_results
        }
        response = requests.get(url, params=params)
        print(f"Response Status Code: {response.status_code}")
        print(f"Response Text: {response.text}")
        if response.status_code == 200:
            results = response.json()
            return [result.get('text', "No text element found") for result in results]
        else:
            raise Exception(f"Error: {response.status_code}, {response.text}")

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
            Exception: If the API request fails.
        """
        if not self.use_offline_wiki_api:
            return ["No additional information provided"]

        url = f"{self.base_url}/articles"
        params = {
            'prompt': prompt,
            'percentile': percentile,
            'num_results': num_results
        }
        response = requests.get(url, params=params)
        print(f"Response Status Code: {response.status_code}")
        print(f"Response Text: {response.text}")
        if response.status_code == 200:
            results = response.json()
            return [result.get('text', "No text element found") for result in results]
        else:
            raise Exception(f"Error: {response.status_code}, {response.text}")
