import json
import os
from typing import Any, Dict, Generator, Optional, Union

import requests
from requests.adapters import HTTPAdapter
from urllib3 import Retry

from Middleware.models.open_ai_api_presets import OpenAiApiPresets
from Middleware.utilities.config_utils import get_openai_preset_path, get_endpoint_config
from Middleware.utilities.prompt_utils import check_stream_chunk_for_stop_string, truncate_at_stop_string


class OpenAiCompatibleApiService:
    """
    A service class that provides compatibility with OpenAI's API for interacting with LLMs.
    """

    def __init__(self, endpoint: str, presetname: str, max_truncate_length: int, max_new_tokens: int,
                 min_new_tokens: int, stream: bool = False):
        """
        Initializes the OpenAiCompatibleApiService with the given configuration.

        :param endpoint: The API endpoint URL for the LLM service.
        :param presetname: The name of the preset file containing API parameters.
        :param max_truncate_length: The maximum length to which the prompt can be truncated.
        :param max_new_tokens: The maximum number of new tokens to generate.
        :param min_new_tokens: The minimum number of new tokens to generate.
        :param stream: A boolean indicating whether to use streaming or not.
        """
        preset_file = get_openai_preset_path(presetname)
        endpoint_file = get_endpoint_config(endpoint)
        self.is_busy: bool = False

        if not os.path.exists(preset_file):
            raise FileNotFoundError(f'The preset file {preset_file} does not exist.')

        with open(preset_file) as file:
            preset = json.load(file)

        self._gen_input = OpenAiApiPresets(**preset)
        self._gen_input.truncation_length = max_truncate_length
        self._gen_input.min_tokens = min_new_tokens
        self._gen_input.max_tokens = max_new_tokens
        self._gen_input.max_new_tokens = max_new_tokens

        self.endpoint: str = endpoint_file["endpoint"]
        self.stream: bool = stream
        self._api = OpenAiApi()

    def get_response_from_llm(self, prompt: str) -> Union[Generator[str, None, None], Dict[str, Any], None]:
        """
        Sends a prompt to the LLM and returns the response.

        :param prompt: The prompt to send to the LLM.
        :return: A generator yielding chunks of the response if streaming, otherwise a dictionary with the result.
        """
        try:
            self.is_busy = True
            if self.stream:
                return self._api.invoke_streaming(prompt=prompt, endpoint=self.endpoint,
                                                  params=self._gen_input.to_json())
            else:
                result = self._api.invoke_non_streaming(prompt=prompt, endpoint=self.endpoint,
                                                        params=self._gen_input.to_json())
                print("######################################")
                print("Non-streaming output: ", result)
                print("######################################")
                return result
        except Exception as e:
            print("Exception in callApi:", e)
            return None
        finally:
            self.is_busy = False

    def is_busy(self) -> bool:
        """
        Checks if the service is currently busy processing a request.

        :return: True if busy, False otherwise.
        """
        return self.is_busy


class OpenAiApi:
    """
    A class that encapsulates the functionality to interact with the OpenAI API.
    """

    def __init__(self):
        """
        Initializes the OpenAiApi with the base URL and default headers.
        """
        self.base_url: str = "https://api.openai.com"
        self.headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "Authorization": "Bearer YOUR_API_KEY"  # Replace YOUR_API_KEY with your actual API key
        }
        self.session: requests.Session = requests.Session()
        retries: Retry = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        self.session.mount('http://', HTTPAdapter(max_retries=retries))
        self.session.mount('https://', HTTPAdapter(max_retries=retries))

    @staticmethod
    def invoke_streaming(prompt: str, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Generator[
        str, None, None]:
        """
        Invokes the streaming endpoint of the LLM API.

        :param prompt: The prompt to send to the LLM.
        :param endpoint: The API endpoint URL for the LLM service.
        :param params: Additional parameters to include in the API request.
        :return: A generator yielding chunks of the response.
        """
        url: str = endpoint + '/v1/completions'
        data: Dict[str, Any] = {"prompt": prompt, "stream": True, **(params or {})}

        print("Streaming flow!")
        with requests.post(url, json=data, stream=True) as r:
            for chunk in r.iter_content(chunk_size=1024, decode_unicode=True):
                truncated_text = check_stream_chunk_for_stop_string(chunk)
                if truncated_text is not None:
                    yield truncated_text  # Yield up to the stop string and stop
                    break
                yield chunk

    def invoke_non_streaming(self, prompt: str, endpoint: str, params: Dict[str, Any]) -> Optional[str]:
        """
        Invokes the non-streaming endpoint of the LLM API.

        :param prompt: The prompt to send to the LLM.
        :param endpoint: The API endpoint URL for the LLM service.
        :param params: Additional parameters to include in the API request.
        :return: The complete response from the LLM or None if an error occurs.
        """
        retries: int = 3  # Set the maximum number of retries
        for attempt in range(retries):
            try:
                url: str = endpoint + '/v1/completions'
                data: Dict[str, Any] = {"prompt": prompt, "stream": False, **(params or {})}
                print("Non-Streaming flow! Attempt:", attempt + 1)

                response = self.session.post(url, headers=self.headers, json=data, stream=True, timeout=14400)
                content = []
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:
                        content.append(chunk)
                full_content = b''.join(content).decode()
                payload = json.loads(full_content)
                print("response: ", response)
                print("payload: ", payload)

                if payload['choices'][0] and payload['choices'][0]['text']:
                    result_text = payload['choices'][0]['text']
                    result_text = truncate_at_stop_string(result_text)
                    return result_text
                else:
                    return ''
            except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
                print(f"Attempt {attempt + 1} failed with error: {e}")
                if attempt == retries - 1:  # Last attempt
                    return None
                continue  # Only continue if not the last attempt
            except Exception as e:
                print("Unexpected error:", e)
                return None
