import json
import os
from typing import Any, Dict, Generator, Optional, Union, List

import requests
from requests.adapters import HTTPAdapter
from urllib3 import Retry

from Middleware.models.open_ai_api_presets import OpenAiApiPresets
from Middleware.utilities.config_utils import get_openai_preset_path, get_endpoint_config, \
    get_is_chat_complete_add_user_assistant, get_is_chat_complete_add_missing_assistant


class OpenAiLlmChatCompletionsApiService:
    """
    A service class that provides compatibility with OpenAI's API for interacting with LLMs.
    """

    def __init__(self, endpoint: str, model_name: str, presetname: str, stream: bool = False):
        """
        Initializes the OpenAiLlmChatCompletionsApiService with the given configuration.

        :param endpoint: The API endpoint URL for the LLM service.
        :param model_name: The model name to be used with the LLM service.
        :param presetname: The name of the preset file containing API parameters.
        :param stream: A boolean indicating whether to use streaming or not.
        """
        preset_file = get_openai_preset_path(presetname)
        endpoint_file = get_endpoint_config(endpoint)
        self.api_key = endpoint_file.get("apiKey", "")
        print("Api key found: " + self.api_key)
        self.endpoint_url = endpoint_file["endpoint"]
        self.model_name = model_name
        self.is_busy: bool = False

        if not os.path.exists(preset_file):
            raise FileNotFoundError(f'The preset file {preset_file} does not exist.')

        with open(preset_file) as file:
            preset = json.load(file)

        self._gen_input = OpenAiApiPresets(**preset)

        self.endpoint: str = endpoint_file["endpoint"]
        self.stream: bool = stream
        self._api = OpenAiChatCompletionsApi(self.api_key, self.endpoint_url)

    def get_response_from_llm(self, conversation: List[Dict[str, str]]) -> Union[
        Generator[str, None, None], Dict[str, Any], None]:
        """
        Sends a conversation to the LLM and returns the response.

        :param conversation: A list of dictionaries containing the conversation with roles and content.
        :return: A generator yielding chunks of the response if streaming, otherwise a dictionary with the result.
        """
        # Correct any "systemMes" roles to "system"
        corrected_conversation = [
            {**msg, "role": "system" if msg["role"] == "systemMes" else msg["role"]}
            for msg in conversation
        ]
        # Construct the full prompt from the conversation
        full_prompt = "".join(msg["content"] for msg in corrected_conversation)
        print("\n************************************************")
        print("Formatted_Prompt:", full_prompt)
        print("************************************************")
        try:
            self.is_busy = True

            if self.stream:
                self._gen_input.stream = True
                return self._api.invoke_streaming(messages=corrected_conversation, endpoint=self.endpoint,
                                                  model=self.model_name, params=self._gen_input.to_json())
            else:
                result = self._api.invoke_non_streaming(messages=corrected_conversation, endpoint=self.endpoint,
                                                        model_name=self.model_name,
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


class OpenAiChatCompletionsApi:
    """
    A class that encapsulates the functionality to interact with the OpenAI API.
    """

    def __init__(self, api_key: str, endpoint: str):
        """
        Initializes the OpenAiChatCompletionsApi with the base URL and default headers.

        :param api_key: The API key for authenticating requests to the OpenAI API.
        :param endpoint: The base URL for the OpenAI API endpoint.
        """
        self.base_url: str = endpoint
        self.headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key
        }
        self.session: requests.Session = requests.Session()
        retries: Retry = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        self.session.mount('http://', HTTPAdapter(max_retries=retries))
        self.session.mount('https://', HTTPAdapter(max_retries=retries))
        print("Initialized OpenAiChatCompletionsApi with retries configured.")
        self.endpoint: str = f"{self.base_url}/v1/chat/completions"

    def invoke_streaming(self, messages: List[Dict[str, str]], endpoint: str, model: str,
                         params: Optional[Dict[str, Any]] = None) -> Generator[str, None, None]:
        """
        Invokes the streaming endpoint of the LLM API for chat completions.

        :param messages: A list of dictionaries containing role and content information.
        :param endpoint: The API endpoint URL for the LLM service.
        :param model: The model identifier to use for generating completions. Defaults to "gpt-4o".
        :param params: Additional parameters to include in the API request.
        :return: A generator yielding chunks of the response in SSE format.
        """
        url: str = f"{endpoint}/v1/chat/completions"
        data: Dict[str, Any] = {"model": model, "stream": True, "messages": messages, **(params or {})}
        add_user_assistant = get_is_chat_complete_add_user_assistant()
        add_missing_assistant = get_is_chat_complete_add_missing_assistant()
        print(f"Streaming flow!")
        print(f"Sending request to {url} with data: {data}")

        def generate_sse_stream():
            def sse_format(data: str) -> str:
                return f"data: {data}\n\n"

            try:
                with requests.post(url, headers=self.headers, json=data, stream=True) as r:
                    print(data)
                    print(f"Response status code: {r.status_code}")
                    buffer = ""
                    first_chunk_buffer = ""  # Buffer for the first few chunks
                    first_chunk_processed = False
                    max_buffer_length = 100
                    for chunk in r.iter_content(chunk_size=1024, decode_unicode=True):
                        print("Chunk received: {}".format(chunk))
                        buffer += chunk
                        while "data:" in buffer:
                            data_pos = buffer.find("data:")
                            end_pos = buffer.find("\n", data_pos)
                            if end_pos == -1:
                                break
                            data_str = buffer[data_pos + 5:end_pos].strip()
                            buffer = buffer[end_pos + 1:]
                            if data_str == "[DONE]":
                                print("Stream done signal received.")
                                return
                            try:
                                chunk_data = json.loads(data_str)
                                for choice in chunk_data.get("choices", []):
                                    if "delta" in choice:
                                        content = choice["delta"].get("content", "")
                                        # Check if both booleans are true and process the first chunks
                                        if add_user_assistant and add_missing_assistant and not first_chunk_processed:
                                            first_chunk_buffer += content
                                            # Check if we have enough content to determine if it starts with "Assistant:"
                                            if "Assistant:" in first_chunk_buffer:
                                                if first_chunk_buffer.startswith("Assistant:"):
                                                    first_chunk_buffer = first_chunk_buffer[len("Assistant:"):].lstrip()
                                                first_chunk_processed = True
                                                content = first_chunk_buffer
                                            elif len(first_chunk_buffer) > max_buffer_length:
                                                # If buffer exceeds max length without "Assistant:", stop waiting
                                                first_chunk_processed = True
                                                content = first_chunk_buffer
                                            else:
                                                # If the buffer is not full but the stream has finished, yield the content
                                                if data_str == "[DONE]" or choice.get("finish_reason"):
                                                    first_chunk_processed = True
                                                    content = first_chunk_buffer
                                                else:
                                                    continue  # Wait for more chunks to accumulate
                                        completion_data = {
                                            "choices": [{
                                                "finish_reason": choice.get("finish_reason"),
                                                "index": choice.get("index"),
                                                "delta": {"content": content},
                                                "text": content
                                            }],
                                            "created": chunk_data.get("created"),
                                            "id": chunk_data.get("id"),
                                            "model": model,
                                            "object": "chat.completion.chunk"
                                        }
                                        yield sse_format(json.dumps(completion_data))
                            except json.JSONDecodeError as e:
                                print(f"Failed to parse JSON: {e}")
                                continue
            except requests.RequestException as e:
                print(f"Request failed: {e}")

        return generate_sse_stream()

    def invoke_non_streaming(self, messages: List[Dict[str, str]],
                             endpoint: str, params: Dict[str, Any],
                             model_name: str) -> Optional[str]:
        """
        Invokes the non-streaming endpoint of the LLM API.

        :param messages: A list of dictionaries representing the conversation history.
        :param endpoint: The API endpoint URL for the LLM service.
        :param params: Additional parameters to include in the API request.
        :param model_name: The model to pass along to the API.
        :return: The complete response from the LLM or None if an error occurs.
        """
        retries: int = 3  # Set the maximum number of retries
        url: str = endpoint + '/v1/chat/completions'
        data: Dict[str, Any] = {"model": model_name, "stream": False, "messages": messages, **(params or {})}
        for attempt in range(retries):
            try:
                print(f"Non-Streaming flow! Attempt: {attempt + 1}")
                print(data)
                response = self.session.post(url, headers=self.headers, json=data, timeout=14400)
                response.raise_for_status()  # Raises HTTPError for bad responses
                payload = response.json()
                print("response: ", response)
                print("payload: ", payload)
                if 'choices' in payload and payload['choices'][0] and 'message' in payload['choices'][
                    0] and 'content' in payload['choices'][0]['message']:
                    result_text = payload['choices'][0]['message']['content']
                    return result_text
                else:
                    return ''
            except requests.exceptions.RequestException as e:
                print(f"Attempt {attempt + 1} failed with error: {e}")
                if attempt == retries - 1:
                    return None
            except Exception as e:
                print("Unexpected error:", e)
                return None
