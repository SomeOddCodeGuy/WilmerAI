import json
import os
import traceback
from typing import Generator, Dict, Any, Union, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3 import Retry

from Middleware.models.open_ai_api_presets import OpenAiApiPresets
from Middleware.utilities.config_utils import get_config_property_if_exists, get_openai_preset_path, \
    get_endpoint_config, get_api_type_config
from Middleware.utilities.text_utils import return_brackets_in_string


class KoboldApiGenerateService:
    """
    A service class that provides compatibility with the KoboldCpp API.
    """

    def __init__(self, endpoint: str, presetname: str, api_type_config, max_tokens,
                 stream: bool = False):
        """
        Initializes the KoboldApiGenerateService with the given configuration.

        :param endpoint: The API endpoint URL for the LLM service.
        :param presetname: The name of the preset file containing API parameters.
        :param stream: A boolean indicating whether to use streaming or not.
        :param api_type_config: The config file for the specified apiType in the Endpoint
        :param max_tokens: The max number of tokens to generate from the response
        """
        endpoint_file = get_endpoint_config(endpoint)
        self.stripStartStopLineBreaks = endpoint_file.get("trimBeginningAndEndLineBreaks", False)
        api_type_config = get_api_type_config(
            endpoint_file.get("apiTypeConfigFileName", "apiTypeConfigFileNameNotFoundInEndpoint"))
        type = api_type_config.get("presetType", "")
        preset_file = get_openai_preset_path(presetname, type)
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

        # Set Kobold-specific endpoints
        self.endpoint = f"{self.endpoint_url}/api/v1/generate"
        self.stream_endpoint = f"{self.endpoint_url}/api/extra/generate/stream"

        self.stream: bool = stream
        self._api = KoboldGenerateApi(self.api_key, self.endpoint_url)

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
        full_prompt = full_prompt.strip() + " "
        print("\n************************************************")
        print("Formatted Prompt:", full_prompt)
        print("************************************************")

        try:
            self.is_busy = True
            if self.stream:
                return self._api.invoke_koboldcpp_streaming(prompt=full_prompt, endpoint=self.stream_endpoint,
                                                            stripStartStopLineBreaks=self.stripStartStopLineBreaks,
                                                            params=self._gen_input)
            else:
                result = self._api.invoke_koboldcpp_non_streaming(prompt=full_prompt, endpoint=self.endpoint,
                                                                  stripStartStopLineBreaks=self.stripStartStopLineBreaks,
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


class KoboldGenerateApi:
    """
    A class that encapsulates the functionality to interact with various LLM APIs, including OpenAI and KoboldCpp.
    """

    def __init__(self, api_key: str, endpoint: str) -> None:
        """
        Initializes the KoboldGenerateApi with the base URL and default headers.

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
        print("Initialized KoboldGenerateApi with retries configured.")

    def invoke_koboldcpp_streaming(self, prompt: str, endpoint: str, stripStartStopLineBreaks=False,
                                   params: Optional[Dict[str, Any]] = None) -> Generator[str, None, None]:
        """
        Invokes the streaming endpoint of the KoboldCpp API.

        :param prompt: The prompt to send to the LLM.
        :param endpoint: The API endpoint URL for the LLM service.
        :param stripStartStopLineBreaks: Whether to strip newlines at the start and end of the entire response.
        :param params: Additional parameters to include in the API request.
        :return: A generator yielding chunks of the response.
        """
        data: Dict[str, Any] = {
            "prompt": prompt,
            **(params or {})
        }

        print(f"KoboldCpp Streaming flow!")
        print(f"URL: {endpoint}")
        print(f"Headers: {self.headers}")
        print(f"Sending request with data: {json.dumps(data, indent=2)}")

        def generate_sse_stream():
            def sse_format(data: str) -> str:
                return f"data: {data}\n\n"

            try:
                with requests.post(endpoint, headers=self.headers, json=data, stream=True) as r:
                    print(f"Response status code: {r.status_code}")
                    buffer = ""
                    partial_token = ""  # Buffer to hold a partial token if it's split across chunks
                    is_first_token = True  # Flag to handle stripping newlines only at the start

                    for chunk in r.iter_content(chunk_size=1024, decode_unicode=True):
                        buffer += chunk  # Accumulate the whole chunk without stripping

                        # Process each event/data pair in the buffer
                        while "data:" in buffer:
                            data_pos = buffer.find("data:")
                            end_pos = buffer.find("\n", data_pos)
                            if end_pos == -1:
                                break

                            data_str = buffer[data_pos + 5:end_pos].strip()
                            buffer = buffer[end_pos + 1:]

                            try:
                                chunk_data = json.loads(data_str) if data_str else {}
                                token = chunk_data.get("token", "")
                                finish_reason = chunk_data.get("finish_reason", "")

                                # Combine the partial token with the current token
                                if partial_token:
                                    token = partial_token + token
                                    partial_token = ""

                                # Check if the token is incomplete and save it for the next chunk
                                if not token.endswith((" ", ".", ",", "\n")) and finish_reason == "null":
                                    partial_token = token
                                    continue  # Wait for the next chunk to complete this token

                                # Handle stripping newlines only at the start and end
                                if stripStartStopLineBreaks:
                                    if is_first_token:
                                        # Strip leading newlines from the first token
                                        token = token.lstrip("\n")
                                        is_first_token = False
                                    if finish_reason == "stop":
                                        # Strip trailing newlines from the last token
                                        token = token.rstrip("\n")

                                # Generate the completion data even if the token is empty
                                completion_data = {
                                    "choices": [{
                                        "finish_reason": finish_reason,
                                        "index": 0,
                                        "delta": {"content": token},
                                        "text": token
                                    }],
                                    "created": None,
                                    "id": None,
                                    "model": "Wilmer-AI",
                                    "object": "chat.completion.chunk"
                                }
                                json_completion_data = json.dumps(completion_data)
                                yield sse_format(json_completion_data)

                            except json.JSONDecodeError as e:
                                print(f"Failed to parse JSON: {e}")
                                continue

                    # Handle any remaining partial_token
                    if partial_token:
                        completion_data = {
                            "choices": [{
                                "finish_reason": "null",
                                "index": 0,
                                "delta": {"content": partial_token},
                                "text": partial_token
                            }],
                            "created": None,
                            "id": None,
                            "model": "Wilmer-AI",
                            "object": "chat.completion.chunk"
                        }
                        json_completion_data = json.dumps(completion_data)
                        yield sse_format(json_completion_data)

                    # Flush remaining buffer
                    remaining_buffer = buffer.strip()
                    if remaining_buffer:
                        try:
                            if remaining_buffer.startswith('{') and remaining_buffer.endswith('}'):
                                chunk_data = json.loads(remaining_buffer)
                                token = chunk_data.get("token", "")
                                finish_reason = chunk_data.get("finish_reason", "")

                                if stripStartStopLineBreaks and finish_reason == "stop":
                                    token = token.rstrip("\n")

                                completion_data = {
                                    "choices": [{
                                        "finish_reason": finish_reason,
                                        "index": 0,
                                        "delta": {"content": token},
                                        "text": token
                                    }],
                                    "created": None,
                                    "id": None,
                                    "model": "Wilmer-AI",
                                    "object": "chat.completion.chunk"
                                }
                                json_completion_data = json.dumps(completion_data)
                                yield sse_format(json_completion_data)
                            else:
                                print(f"Remaining buffer does not contain valid JSON: {remaining_buffer}")
                        except json.JSONDecodeError as e:
                            print(f"Failed to parse JSON during buffer flush: {e}")

                # Ensure final JSON with finish_reason "stop" and [DONE] signal are sent
                final_completion_data = {
                    "choices": [{
                        "finish_reason": "stop",
                        "index": 0,
                        "delta": {"content": ""},
                        "text": ""
                    }],
                    "created": None,
                    "id": None,
                    "model": "Wilmer-AI",
                    "object": "chat.completion.chunk"
                }
                json_final_completion_data = json.dumps(final_completion_data)
                yield sse_format(json_final_completion_data)

                print("End of stream reached, sending [DONE] signal.")
                yield sse_format("[DONE]")

            except requests.RequestException as e:
                print(f"Request failed: {e}")
                traceback.print_exc()
                raise

        return generate_sse_stream()

    def invoke_koboldcpp_non_streaming(self, prompt: str, endpoint: str, stripStartStopLineBreaks,
                                       params: Dict[str, Any]) -> Optional[str]:
        """
        Invokes the non-streaming endpoint of the KoboldCpp API.

        :param prompt: The prompt to send to the LLM.
        :param endpoint: The API endpoint URL for the LLM service.
        :param params: Additional parameters to include in the API request.
        :return: The complete response from the LLM or None if an error occurs.
        """
        retries: int = 3
        data: Dict[str, Any] = {
            "prompt": prompt,
            **params
        }

        for attempt in range(retries):
            try:
                print(f"KoboldCpp Non-Streaming flow! Attempt: {attempt + 1}")
                print("Headers: ")
                print(json.dumps(self.headers, indent=2))
                print("Data: ")
                print(json.dumps(data, indent=2))
                response = self.session.post(endpoint, headers=self.headers, json=data, timeout=14400)
                response.raise_for_status()

                payload = response.json()
                print("Response: ", response)
                print("Payload: ", json.dumps(payload, indent=2))

                if 'results' in payload and len(payload['results']) > 0 and 'text' in payload['results'][0]:
                    result_text = payload['results'][0]['text']

                    if stripStartStopLineBreaks:
                        result_text = result_text.strip("\n")

                    return result_text
                else:
                    return ''
            except requests.exceptions.RequestException as e:
                print(f"Attempt {attempt + 1} failed with error: {e}")
                traceback.print_exc()
                if attempt == retries - 1:
                    raise
            except Exception as e:
                print("Unexpected error:", e)
                traceback.print_exc()
                raise
