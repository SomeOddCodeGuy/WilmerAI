import json
import os
import traceback
from typing import Any, Dict, Generator, Optional, Union

import requests
from requests.adapters import HTTPAdapter
from urllib3 import Retry

from Middleware.models.open_ai_api_presets import OpenAiApiPresets
from Middleware.utilities.config_utils import get_openai_preset_path, get_endpoint_config, \
    get_is_chat_complete_add_user_assistant, get_is_chat_complete_add_missing_assistant, get_config_property_if_exists
from Middleware.utilities.text_utils import return_brackets_in_string


class OpenAiLlmCompletionsApiService:
    """
    A service class that provides compatibility with OpenAI's API for interacting with LLMs.
    """

    def __init__(self, endpoint: str, presetname: str, api_type_config, max_tokens,
                 stream: bool = False):
        """
        Initializes the OpenAiLlmCompletionsApiService with the given configuration.

        :param endpoint: The API endpoint URL for the LLM service.
        :param presetname: The name of the preset file containing API parameters.
        :param stream: A boolean indicating whether to use streaming or not.
        :param api_type_config: The config file for the specified apiType in the Endpoint
        :param truncate_length: The max context length of the model, if it applies
        :param max_tokens: The max number of tokens to generate from the response
        """
        preset_file = get_openai_preset_path(presetname)
        endpoint_file = get_endpoint_config(endpoint)
        self.api_key = endpoint_file.get("apiKey", "")
        print("Api key found: " + self.api_key)
        self.endpoint_url = endpoint_file["endpoint"]
        self.model_name = endpoint_file["modelNameToSendToAPI"]
        self.is_busy: bool = False
        self.truncate_property_name = get_config_property_if_exists("truncateLengthPropertyName", api_type_config)
        self.stream_property_name = get_config_property_if_exists("streamPropertyName", api_type_config)
        self.max_token_property_name = get_config_property_if_exists("maxNewTokensPropertyName", api_type_config)

        if not os.path.exists(preset_file):
            raise FileNotFoundError(f'The preset file {preset_file} does not exist.')

        with open(preset_file) as file:
            preset = json.load(file)

        self._gen_input_raw = OpenAiApiPresets(**preset)
        self._gen_input = self._gen_input_raw.to_json()
        # Add optional fields if they are not None
        if self.truncate_property_name:
            self._gen_input[self.truncate_property_name] = endpoint_file["maxContextTokenSize"]
        if self.stream_property_name:
            self._gen_input[self.stream_property_name] = stream
        if self.max_token_property_name:
            self._gen_input[self.max_token_property_name] = max_tokens

        self.endpoint: str = endpoint_file["endpoint"]
        self.stream: bool = stream
        self._api = OpenAiCompletionsApi(self.api_key, self.endpoint_url)

    def get_response_from_llm(self, system_prompt: str, prompt: str) -> Union[
        Generator[str, None, None], Dict[str, Any], None]:
        """
        Sends a prompt to the LLM and returns the response.

        :param system_prompt: The system prompt to send to the LLM.
        :param prompt: The prompt to send to the LLM.
        :return: A generator yielding chunks of the response if streaming, otherwise a dictionary with the result.
        """
        full_prompt = system_prompt + prompt
        full_prompt = return_brackets_in_string(full_prompt)
        print("\n************************************************")
        print("Formatted Prompt:", full_prompt)
        print("************************************************")

        try:
            self.is_busy = True
            if self.stream:
                return self._api.invoke_streaming(prompt=full_prompt, endpoint=self.endpoint,
                                                  model_name=self.model_name,
                                                  params=self._gen_input)
            else:
                result = self._api.invoke_non_streaming(prompt=full_prompt, endpoint=self.endpoint,
                                                        model_name=self.model_name,
                                                        params=self._gen_input)
                print("######################################")
                print("Non-streaming output: ", result)
                print("######################################")
                return result
        except Exception as e:
            print("Exception in callApi:", e)
            traceback.print_exc()  # This prints the stack trace
            raise
        finally:
            self.is_busy = False

    def is_busy(self) -> bool:
        """
        Checks if the service is currently busy processing a request.

        :return: True if busy, False otherwise.
        """
        return self.is_busy


class OpenAiCompletionsApi:
    """
    A class that encapsulates the functionality to interact with the OpenAI API.
    """

    def __init__(self, api_key: str, endpoint: str) -> None:
        """
        Initializes the OpenAiCompletionsApi with the base URL and default headers.

        :param api_key: The API key for authorization.
        :param endpoint: The API endpoint URL.
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
        print("Initialized OpenAiCompletionsApi with retries configured.")

    def invoke_streaming(self, prompt: str, endpoint: str, model_name: str,
                         params: Optional[Dict[str, Any]] = None) -> Generator[str, None, None]:
        """
        Invokes the streaming endpoint of the LLM API.

        :param prompt: The prompt to send to the LLM.
        :param endpoint: The API endpoint URL for the LLM service.
        :param model_name: The name of the model to use.
        :param params: Additional parameters to include in the API request.
        :return: A generator yielding chunks of the response.
        """
        url: str = endpoint + '/v1/completions'
        data: Dict[str, Any] = {
            "prompt": prompt,
            "stream": True,
            "model": model_name,
            **(params or {})
        }

        add_user_assistant = get_is_chat_complete_add_user_assistant()
        add_missing_assistant = get_is_chat_complete_add_missing_assistant()

        print(f"Streaming flow!")
        print(f"URL: {url}")
        print(f"Headers: {self.headers}")
        print(f"Sending request with data: {json.dumps(data, indent=2)}")

        def generate_sse_stream():
            def sse_format(data: str) -> str:
                return f"data: {data}\n\n"

            try:
                with requests.post(url, headers=self.headers, json=data, stream=True) as r:
                    print(f"Response status code: {r.status_code}")
                    buffer = ""
                    first_chunk_buffer = ""
                    first_chunk_processed = False
                    max_buffer_length = 100

                    for chunk in r.iter_content(chunk_size=1024, decode_unicode=True):
                        buffer += chunk

                        while "data:" in buffer:
                            data_pos = buffer.find("data:")
                            end_pos = buffer.find("\n", data_pos)
                            if end_pos == -1:
                                break

                            data_str = buffer[data_pos + 5:end_pos].strip()
                            buffer = buffer[end_pos + 1:]

                            if data_str == "[DONE]" or data_str == "data: [DONE]":
                                print("Stream done signal received.")
                                yield sse_format("[DONE]")
                                return

                            try:
                                chunk_data = json.loads(data_str)
                                if 'choices' in chunk_data:
                                    for choice in chunk_data.get("choices", []):
                                        if "text" in choice:
                                            content = choice["text"]

                                            if add_user_assistant and add_missing_assistant and not first_chunk_processed:
                                                first_chunk_buffer += content
                                                if "Assistant:" in first_chunk_buffer:
                                                    if first_chunk_buffer.startswith("Assistant:"):
                                                        first_chunk_buffer = first_chunk_buffer[
                                                                             len("Assistant:"):].lstrip()
                                                    first_chunk_processed = True
                                                    content = first_chunk_buffer
                                                elif len(first_chunk_buffer) > max_buffer_length:
                                                    first_chunk_processed = True
                                                    content = first_chunk_buffer
                                                else:
                                                    continue

                                            completion_data = {
                                                "choices": [{
                                                    "finish_reason": choice.get("finish_reason"),
                                                    "index": choice.get("index"),
                                                    "delta": {"content": content},
                                                    "text": content
                                                }],
                                                "created": chunk_data.get("created"),
                                                "id": chunk_data.get("id"),
                                                "model": "Wilmer-AI",
                                                "object": "chat.completion.chunk"
                                            }
                                            yield sse_format(json.dumps(completion_data))
                                elif 'choices' in chunk_data.get("response", {}):
                                    for choice in chunk_data["response"].get("choices", []):
                                        if "text" in choice:
                                            content = choice["text"]

                                            if add_user_assistant and add_missing_assistant and not first_chunk_processed:
                                                first_chunk_buffer += content
                                                if "Assistant:" in first_chunk_buffer:
                                                    if first_chunk_buffer.startswith("Assistant:"):
                                                        first_chunk_buffer = first_chunk_buffer[
                                                                             len("Assistant:"):].lstrip()
                                                    first_chunk_processed = True
                                                    content = first_chunk_buffer
                                                elif len(first_chunk_buffer) > max_buffer_length:
                                                    first_chunk_processed = True
                                                    content = first_chunk_buffer
                                                else:
                                                    continue

                                            completion_data = {
                                                "choices": [{
                                                    "finish_reason": choice.get("finish_reason"),
                                                    "index": choice.get("index"),
                                                    "delta": {"content": content},
                                                    "text": content
                                                }],
                                                "created": chunk_data.get("created"),
                                                "id": chunk_data.get("id"),
                                                "model": "Wilmer-AI",
                                                "object": "chat.completion.chunk"
                                            }
                                            yield sse_format(json.dumps(completion_data))
                                elif 'content' in chunk_data:
                                    content = chunk_data["content"]

                                    if add_user_assistant and add_missing_assistant and not first_chunk_processed:
                                        first_chunk_buffer += content
                                        if "Assistant:" in first_chunk_buffer:
                                            if first_chunk_buffer.startswith("Assistant:"):
                                                first_chunk_buffer = first_chunk_buffer[len("Assistant:"):].lstrip()
                                            first_chunk_processed = True
                                            content = first_chunk_buffer
                                        elif len(first_chunk_buffer) > max_buffer_length:
                                            first_chunk_processed = True
                                            content = first_chunk_buffer
                                        else:
                                            continue

                                    completion_data = {
                                        "choices": [{
                                            "finish_reason": None,
                                            "index": 0,
                                            "delta": {"content": content},
                                            "text": content
                                        }],
                                        "created": None,
                                        "id": None,
                                        "model": "Wilmer-AI",
                                        "object": "chat.completion.chunk"
                                    }
                                    yield sse_format(json.dumps(completion_data))
                            except json.JSONDecodeError as e:
                                print(f"Failed to parse JSON: {e}")
                                traceback.print_exc()  # This prints the stack trace
                                continue

                    # Flush remaining buffer
                    if buffer.strip():
                        data_str = buffer.strip()
                        if data_str == "data: [DONE]" or data_str == "[DONE]":
                            print("Stream done signal received in buffer flush.")
                            yield sse_format("[DONE]")
                        else:
                            try:
                                chunk_data = json.loads(data_str)
                                if 'choices' in chunk_data:
                                    for choice in chunk_data.get("choices", []):
                                        if "text" in choice:
                                            content = choice["text"]
                                            completion_data = {
                                                "choices": [{
                                                    "finish_reason": choice.get("finish_reason"),
                                                    "index": choice.get("index"),
                                                    "delta": {"content": content},
                                                    "text": content
                                                }],
                                                "created": chunk_data.get("created"),
                                                "id": chunk_data.get("id"),
                                                "model": "Wilmer-AI",
                                                "object": "chat.completion.chunk"
                                            }
                                            yield sse_format(json.dumps(completion_data))
                            except json.JSONDecodeError as e:
                                print(f"Failed to parse JSON: {e}")
                                traceback.print_exc()  # This prints the stack trace

            except requests.RequestException as e:
                print(f"Request failed: {e}")
                traceback.print_exc()  # This prints the stack trace
                raise

        return generate_sse_stream()

    def invoke_non_streaming(self, prompt: str, endpoint: str, model_name: str,
                             params: Dict[str, Any]) -> Optional[str]:
        """
        Invokes the non-streaming endpoint of the LLM API.

        :param prompt: The prompt to send to the LLM.
        :param endpoint: The API endpoint URL for the LLM service.
        :param model_name: The name of the model to use.
        :param params: Additional parameters to include in the API request.
        :return: The complete response from the LLM or None if an error occurs.
        """
        retries: int = 3  # Set the maximum number of retries
        url: str = endpoint + '/v1/completions'
        data: Dict[str, Any] = {
            "prompt": prompt,
            "model": model_name,
            **params
        }

        for attempt in range(retries):
            try:
                print(f"Non-Streaming flow! Attempt: {attempt + 1}")
                print("Headers: ")
                print(json.dumps(self.headers, indent=2))
                print("Data: ")
                print(json.dumps(data, indent=2))
                response = self.session.post(url, headers=self.headers, json=data, timeout=14400)
                response.raise_for_status()  # Raises HTTPError for bad responses

                payload = response.json()
                print("Response: ", response)
                print("Payload: ", json.dumps(payload, indent=2))

                # Check for your original format first
                if 'choices' in payload and payload['choices'][0] and 'text' in payload['choices'][0]:
                    result_text = payload['choices'][0]['text']
                    return result_text
                # Check for specified format in the API specification
                elif 'choices' in payload and payload['choices'][0]:
                    result_text = payload['choices'][0]['text']
                    return result_text
                elif 'content' in payload:
                    result_text = payload['content']  # llama.cpp server
                    return result_text
                else:
                    return ''
            except requests.exceptions.RequestException as e:
                print(f"Attempt {attempt + 1} failed with error: {e}")
                traceback.print_exc()  # This prints the stack trace
                if attempt == retries - 1:
                    raise
            except Exception as e:
                print("Unexpected error:", e)
                traceback.print_exc()  # This prints the stack trace
                raise
