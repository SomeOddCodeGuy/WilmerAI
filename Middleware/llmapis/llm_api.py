# /Middleware/llmapis/llm_api.py

import ipaddress
import json
import logging
import os
import socket
import traceback
from copy import deepcopy
from typing import Any, Dict, Generator, List, Optional, Set, Union
from urllib.parse import urlsplit

from Middleware.common import instance_global_variables
from Middleware.llmapis.handlers.base.base_llm_api_handler import LlmApiHandler
from Middleware.llmapis.handlers.impl.claude_api_handler import ClaudeApiHandler
from Middleware.llmapis.handlers.impl.koboldcpp_api_handler import KoboldCppApiHandler
from Middleware.llmapis.handlers.impl.litellm_api_handler import LiteLLMApiHandler
from Middleware.llmapis.handlers.impl.ollama_chat_api_handler import OllamaChatHandler
from Middleware.llmapis.handlers.impl.ollama_generate_api_handler import OllamaGenerateApiHandler
from Middleware.llmapis.handlers.impl.openai_api_handler import OpenAiApiHandler
from Middleware.llmapis.handlers.impl.openai_completions_api_handler import OpenAiCompletionsApiHandler
from Middleware.llmapis.sampler_translation import deep_merge, translate
from Middleware.utilities.config_utils import (
    get_openai_preset_path,
    get_endpoint_config,
    try_get_endpoint_config,
    get_api_type_config,
)
from Middleware.utilities.sensitive_logging_utils import sensitive_log

logger = logging.getLogger(__name__)


def _acquire_endpoint_gate() -> bool:
    """Acquire the per-instance LLM-call semaphore when CONCURRENCY_LEVEL == 'endpoint'.

    Returns:
        bool: True if the gate was acquired (and must be released by the caller), False if no
            gate applies (level != 'endpoint' or no semaphore configured).

    Raises:
        TimeoutError: If the semaphore could not be acquired within CONCURRENCY_TIMEOUT.
    """
    if instance_global_variables.CONCURRENCY_LEVEL != "endpoint":
        return False
    sem = instance_global_variables.get_request_semaphore()
    if sem is None:
        return False
    timeout = instance_global_variables.CONCURRENCY_TIMEOUT
    if not sem.acquire(timeout=timeout):
        raise TimeoutError(
            f"Timed out after {timeout}s waiting for an LLM call slot "
            f"(concurrency-level=endpoint, limit={instance_global_variables.CONCURRENCY_LIMIT})"
        )
    return True


def _release_endpoint_gate(acquired: bool) -> None:
    """Release the per-instance LLM-call semaphore if it was acquired by us.

    Args:
        acquired (bool): Whether _acquire_endpoint_gate acquired the gate; release is a no-op
            when False.
    """
    if not acquired:
        return
    sem = instance_global_variables.get_request_semaphore()
    if sem is not None:
        sem.release()


def _ip_is_local(ip) -> bool:
    """Report whether an IP is on the machine or local network.

    Treats loopback / RFC1918-private / link-local addresses as local. IPv4-mapped IPv6 is
    unwrapped first so the v4 rules apply.

    Args:
        ip (ipaddress.IPv4Address | ipaddress.IPv6Address): The address to classify.

    Returns:
        bool: True if the address is loopback, private, or link-local.
    """
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return ip.is_loopback or ip.is_private or ip.is_link_local


def _classify_backup_host(url: str) -> str:
    """Classifies a backup endpoint URL's host for the failover egress guard.

    Failover forwards the full conversation/prompt to the backup, so a backup whose
    host is off the machine/LAN is a data-egress decision. This classifies where the
    backup is:

    - 'local'   : loopback / RFC1918-private / link-local, or localhost; or a hostname
                  that resolves entirely to such addresses. Failing over here keeps the
                  prompt on the machine or local network.
    - 'remote'  : a public IP literal, or a hostname that resolves to any public
                  address. Off-machine, so it is gated by allowRemoteBackup.
    - 'unknown' : a hostname that cannot be resolved (e.g. a transient DNS failure).
                  Allowed, but the caller logs it, so a DNS hiccup cannot block a
                  legitimate failover.

    Args:
        url (str): The backup endpoint URL whose host is classified; a scheme is assumed if
            missing.

    Returns:
        str: One of 'local', 'remote', or 'unknown' as described above.
    """
    try:
        split = urlsplit(url if "//" in url else "//" + url)
        host = split.hostname
    except ValueError:
        return "unknown"
    if not host:
        return "unknown"
    host_lower = host.lower()
    if host_lower == "localhost" or host_lower.endswith(".localhost"):
        return "local"
    try:
        return "local" if _ip_is_local(ipaddress.ip_address(host)) else "remote"
    except ValueError:
        pass
    # Not an IP literal: resolve so a public hostname (e.g. a cloud API) is gated by
    # allowRemoteBackup too, not waved through. Conservative on a mixed result -- any
    # public address makes it 'remote', since failover would ship the prompt there.
    try:
        resolved = {
            ipaddress.ip_address(info[4][0].split("%")[0])
            for info in socket.getaddrinfo(host, None)
        }
    except (socket.gaierror, OSError, ValueError, UnicodeError):
        return "unknown"
    if not resolved:
        return "unknown"
    return "local" if all(_ip_is_local(ip) for ip in resolved) else "remote"


class LlmApiService:
    """
    Orchestrates interactions with various LLM API backends.

    This service loads endpoint and preset configurations to instantiate a specific
    API handler, which is then used to send requests and receive responses.

    Supports per-endpoint failover via the optional `backupEndpointName` field in
    the endpoint configuration. When the primary endpoint raises any exception,
    the service instantiates a new LlmApiService for the backup endpoint and
    delegates the call. Backups can chain arbitrarily deep; a visited-set guards
    against cycles. Streaming failover is only possible before the first token is
    emitted to the caller.
    """

    def __init__(self, endpoint: str, presetname: str, max_tokens: int, stream: bool = False,
                 _visited_endpoints: Optional[Set[str]] = None):
        """
        Initializes the LlmApiService instance.

        Loads configurations, sets up connection parameters, and instantiates the
        appropriate API handler based on the endpoint configuration.

        Args:
            endpoint (str): The name of the endpoint configuration to use.
            presetname (str): The name of the generation preset to apply.
            max_tokens (int): The maximum number of tokens to generate.
            stream (bool): A flag indicating whether to use streaming responses.
            _visited_endpoints (Optional[Set[str]]): Internal failover chain tracker.
                Callers should leave this as None; it is populated automatically
                when a backup service is instantiated during failover.
        """
        self.max_tokens = max_tokens
        self.endpoint_file = get_endpoint_config(endpoint)
        self.api_type_config = get_api_type_config(self.endpoint_file.get("apiTypeConfigFileName", ""))
        llm_type = self.api_type_config["type"]
        preset_type = self.api_type_config.get("presetType", "")
        logger.debug(f"API type: {llm_type}, Preset type: {preset_type}, Preset name: {presetname}")
        preset = self._resolve_gen_input(presetname, preset_type)

        self.api_key = self.endpoint_file.get("apiKey", "")
        self.endpoint_url = self.endpoint_file["endpoint"]
        self.model_name = self.endpoint_file.get("modelNameToSendToAPI", "")
        self.dont_include_model = self.endpoint_file.get("dontIncludeModel", False)
        self.is_busy_flag: bool = False

        self._gen_input = preset

        self.stream = stream
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self.api_key
        }
        self.llm_type = llm_type

        self._endpoint_name = endpoint
        self._presetname = presetname
        self._visited_endpoints: Set[str] = set(_visited_endpoints) if _visited_endpoints else set()
        self._visited_endpoints.add(endpoint)
        backup_name = self.endpoint_file.get("backupEndpointName") or None
        self._backup_endpoint_name: Optional[str] = backup_name
        self._has_backup: bool = bool(backup_name)
        # Optional override for the preset the backup should load. When unset the
        # backup inherits the originating request's preset name (see
        # _build_backup_service); set this when the backup's API type has no preset
        # of that name in its own Presets/<type>/ directory.
        self._backup_preset_name: Optional[str] = self.endpoint_file.get("backupPresetName") or None

        self._api_handler = self.create_api_handler()

    def _load_preset_file(self, presetname: str, preset_type: str) -> Dict[str, Any]:
        """
        Loads a preset JSON from the Presets/<type>/ folder.

        Tries the user-subdirectory path first, then falls back to the type root,
        then raises. This is the unchanged legacy preset-loading behavior, now also
        reused to load an `appendPresetName` override file (which respects the same
        configurable preset subdirectory).

        Args:
            presetname (str): The preset file name (without `.json`).
            preset_type (str): The Presets subfolder (the ApiType's presetType).

        Returns:
            Dict[str, Any]: The loaded preset parameters.

        Raises:
            FileNotFoundError: If the preset file is found in neither location.
        """
        preset_file = get_openai_preset_path(presetname, preset_type, True)
        logger.info("Loading preset at {}".format(preset_file))
        if not os.path.exists(preset_file):
            logger.warning(f"No preset file found at {preset_file}. Trying fallback without user subdirectory.")
            preset_file = get_openai_preset_path(presetname, preset_type)
            logger.debug(f"Fallback preset path: {preset_file}")
            if not os.path.exists(preset_file):
                raise FileNotFoundError(f"The preset file {preset_file} does not exist.")
        with open(preset_file) as file:
            return json.load(file)

    def _resolve_gen_input(self, presetname: str, preset_type: str) -> Dict[str, Any]:
        """
        Resolves the generation parameters for this request.

        Resolution order for a node referencing endpoint E and preset name P:

          1. If an endpoint named P exists and carries a `presetSamplers` block,
             translate that canonical block to E's ApiType and use it. P is only
             the value donor; E (``self.api_type_config``) decides the translation
             target, so an endpoint can borrow another endpoint's samplers even
             across API types.
          2. Otherwise fall back to the existing Presets/<type>/ folder file,
             byte-for-byte unchanged from legacy behavior.

        An optional `appendPresetName` file named by E is then deep-merged on top
        as the highest-precedence override layer. It is loaded in the target
        ApiType's native field names and is not translated.

        Args:
            presetname (str): The preset name P requested by the node.
            preset_type (str): The Presets subfolder for E's ApiType.

        Returns:
            Dict[str, Any]: The assembled (pre-injection) generation parameters.
        """
        donor = try_get_endpoint_config(presetname)
        if donor and donor.get("presetSamplers"):
            logger.info("Resolving preset '%s' from an endpoint-embedded presetSamplers block.", presetname)
            gen_input = translate(donor["presetSamplers"], self.api_type_config)
        else:
            gen_input = self._load_preset_file(presetname, preset_type)

        append_name = self.endpoint_file.get("appendPresetName")
        if append_name:
            logger.info("Appending native preset overrides from '%s'.", append_name)
            gen_input = deep_merge(gen_input, self._load_preset_file(append_name, preset_type))

        return gen_input

    def create_api_handler(self) -> LlmApiHandler:
        """
        Creates and returns the appropriate API handler based on the configuration.

        This method acts as a factory, selecting the correct handler class based
        on the 'llm_type' specified in the API type configuration file.

        Returns:
            LlmApiHandler: An instance of a concrete handler for the specified LLM type.
        """
        common_args = {
            "base_url": self.endpoint_url,
            "api_key": self.api_key,
            "gen_input": self._gen_input,
            "model_name": self.model_name,
            "headers": self.headers,
            "stream": self.stream,
            "api_type_config": self.api_type_config,
            "endpoint_config": self.endpoint_file,
            "max_tokens": self.max_tokens,
            "suppress_retries": self._has_backup,
        }

        # Note: ImageSpecific types are deprecated. The regular handlers now support images
        # when passed via the ImageProcessor node. These mappings are kept for backwards
        # compatibility with existing configurations.
        if self.llm_type in ("openAIChatCompletion", "openAIApiChatImageSpecific"):
            return OpenAiApiHandler(**common_args, dont_include_model=self.dont_include_model)
        elif self.llm_type == "claudeMessages":
            return ClaudeApiHandler(**common_args, dont_include_model=self.dont_include_model)
        elif self.llm_type in ("koboldCppGenerate", "koboldCppGenerateImageSpecific"):
            return KoboldCppApiHandler(**common_args)
        elif self.llm_type == "openAIV1Completion":
            return OpenAiCompletionsApiHandler(**common_args)
        elif self.llm_type in ("ollamaApiChat", "ollamaApiChatImageSpecific"):
            return OllamaChatHandler(**common_args)
        elif self.llm_type == "ollamaApiGenerate":
            return OllamaGenerateApiHandler(**common_args)
        elif self.llm_type == "litellmChatCompletion":
            return LiteLLMApiHandler(**common_args, dont_include_model=self.dont_include_model)
        else:
            raise ValueError(f"Unsupported LLM type: {self.llm_type}")

    def _build_backup_service(self) -> "LlmApiService":
        """
        Constructs an LlmApiService for the configured backup endpoint.

        Guards against failover cycles by checking the backup name against the
        visited set before instantiating. Propagates the visited set so downstream
        failovers can detect further cycles.

        The backup loads the preset named by the originating endpoint's optional
        `backupPresetName`, falling back to the originating request's own preset
        name. The fallback matters because the backup may use a different API type,
        whose `Presets/<type>/` directory must contain a preset of that name;
        `backupPresetName` lets a heterogeneous backup point at a preset it actually
        ships instead of failing construction with a bare FileNotFoundError.

        Returns:
            LlmApiService: An initialized service targeting the backup endpoint.

        Raises:
            RuntimeError: If the backup endpoint is already present in the visited
                chain, indicating a misconfigured loop.
        """
        if self._backup_endpoint_name in self._visited_endpoints:
            # _visited_endpoints is an unordered set, so don't print it as a "A -> B"
            # path (that order would be arbitrary). Name the offending backup and list
            # the already-visited endpoints deterministically (sorted) instead.
            visited = ", ".join(sorted(self._visited_endpoints))
            raise RuntimeError(
                f"Failover cycle detected: backup '{self._backup_endpoint_name}' is already in "
                f"the failover chain (visited endpoints: {visited}). "
                f"Check the backupEndpointName settings on each endpoint."
            )

        # Egress guard (safe-by-default). Failover ships the whole conversation/prompt
        # to the backup's host. A backup at a public IP is certainly off-machine, so it
        # is blocked unless the backup endpoint opts in with allowRemoteBackup; a backup
        # at a hostname can't be classified without DNS, so it is allowed but logged.
        backup_config = get_endpoint_config(self._backup_endpoint_name)
        backup_url = backup_config.get("endpoint", "")
        host_class = _classify_backup_host(backup_url)
        if host_class == "remote" and not backup_config.get("allowRemoteBackup", False):
            raise RuntimeError(
                f"Failover to backup '{self._backup_endpoint_name}' is blocked: its host "
                f"({backup_url}) is a public address, so failing over would send the prompt and "
                f"conversation off-machine. If that is intended, set \"allowRemoteBackup\": true "
                f"on endpoint '{self._backup_endpoint_name}'."
            )
        if host_class != "local":
            logger.warning(
                "Failover egress: backup '%s' (%s) may be off-machine; the prompt and conversation "
                "will be sent there.",
                self._backup_endpoint_name, backup_url,
            )

        return LlmApiService(
            endpoint=self._backup_endpoint_name,
            presetname=self._backup_preset_name or self._presetname,
            max_tokens=self.max_tokens,
            stream=self.stream,
            _visited_endpoints=self._visited_endpoints,
        )

    def get_response_from_llm(
            self,
            conversation: Optional[List[Dict[str, str]]] = None,
            system_prompt: Optional[str] = None,
            prompt: Optional[str] = None,
            llm_takes_images: bool = False,
            request_id: Optional[str] = None,
            tools: Optional[List[Dict[str, Any]]] = None,
            tool_choice: Optional[Any] = None,
    ) -> Union[Generator[Dict[str, Any], None, None], str, Dict[str, Any]]:
        """
        Sends a prompt or conversation to the LLM and returns the raw response.

        If the endpoint defines `backupEndpointName` and the primary call raises any
        exception, the call is transparently retried against the backup endpoint.
        For streaming calls, failover is only possible before the first token has
        been yielded to the caller; once any token has been emitted, the original
        exception is re-raised.

        Args:
            conversation (Optional[List[Dict[str, str]]]): The conversation history.
            system_prompt (Optional[str]): The system prompt.
            prompt (Optional[str]): The user prompt.
            llm_takes_images (bool): Flag indicating if the LLM can process images.
            request_id (Optional[str]): The request ID for cancellation tracking.
            tools (Optional[List[Dict[str, Any]]]): Tool definitions in OpenAI format.
            tool_choice (Optional[Any]): Tool selection policy.

        Returns:
            Union[Generator[Dict[str, Any], None, None], str, Dict[str, Any]]: A generator
            yielding raw data dictionaries if streaming, the complete raw response string
            for text-only responses, or a dictionary with 'content', 'tool_calls', and
            'finish_reason' keys when the response includes tool calls.
        """
        self.is_busy_flag = True
        try:
            conversation_copy = deepcopy(conversation) if conversation else None
            system_prompt_to_pass = system_prompt
            prompt_to_pass = prompt

            add_start_system = self.endpoint_file.get("addTextToStartOfSystem", False)
            text_start_system = self.endpoint_file.get("textToAddToStartOfSystem", "")
            add_start_prompt = self.endpoint_file.get("addTextToStartOfPrompt", False)
            text_start_prompt = self.endpoint_file.get("textToAddToStartOfPrompt", "")

            if add_start_system and text_start_system:
                system_prompt_to_pass = text_start_system + (system_prompt_to_pass or "")
            if add_start_prompt and text_start_prompt:
                prompt_to_pass = text_start_prompt + (prompt_to_pass or "")

            logger.debug("llm_api - Stream is: %s", self.stream)
            sensitive_log(logger, logging.DEBUG, "llm_api - System prompt: %s", system_prompt_to_pass)
            sensitive_log(logger, logging.DEBUG, "llm_api - Prompt: %s", prompt_to_pass)

            if not llm_takes_images:
                logger.debug("llm_api does not take images. Stripping images key from messages.")
                if conversation_copy:
                    conversation_copy = [{k: v for k, v in msg.items() if k != "images"} for msg in conversation_copy]
            else:
                logger.debug("llm_api takes images. Leaving images in place.")

            call_kwargs = dict(
                conversation=conversation_copy,
                system_prompt=system_prompt_to_pass,
                prompt=prompt_to_pass,
                request_id=request_id,
                tools=tools,
                tool_choice=tool_choice,
            )
            delegate_kwargs = dict(
                conversation=conversation,
                system_prompt=system_prompt,
                prompt=prompt,
                llm_takes_images=llm_takes_images,
                request_id=request_id,
                tools=tools,
                tool_choice=tool_choice,
            )

            if self.stream:
                def stream_wrapper() -> Generator[Dict[str, Any], None, None]:
                    first_token_yielded = False
                    gate_held = False
                    try:
                        gate_held = _acquire_endpoint_gate()
                        try:
                            for chunk in self._api_handler.handle_streaming(**call_kwargs):
                                first_token_yielded = True
                                yield chunk
                        except Exception as e:
                            if not first_token_yielded and self._has_backup:
                                # Release before delegating so the backup's own
                                # acquire doesn't deadlock against us at limit=1.
                                if gate_held:
                                    _release_endpoint_gate(True)
                                    gate_held = False
                                logger.warning(
                                    "Failover: '%s' failed before emitting any tokens (%s: %s). "
                                    "Switching to backup '%s'.",
                                    self._endpoint_name, type(e).__name__, e, self._backup_endpoint_name,
                                )
                                backup_service = self._build_backup_service()
                                yield from backup_service.get_response_from_llm(**delegate_kwargs)
                                return
                            if first_token_yielded and self._has_backup:
                                logger.error(
                                    "Stream failed after tokens were emitted; cannot fail over to '%s': %s",
                                    self._backup_endpoint_name, e,
                                )
                            raise
                    finally:
                        if gate_held:
                            _release_endpoint_gate(True)
                        self.is_busy_flag = False
                        self.close()

                return stream_wrapper()
            else:
                gate_held = False
                try:
                    gate_held = _acquire_endpoint_gate()
                    try:
                        response = self._api_handler.handle_non_streaming(**call_kwargs)
                        return response
                    except Exception as e:
                        if self._has_backup:
                            # Release before delegating so the backup's own
                            # acquire doesn't deadlock against us at limit=1.
                            if gate_held:
                                _release_endpoint_gate(True)
                                gate_held = False
                            logger.warning(
                                "Failover: '%s' failed (%s: %s). Switching to backup '%s'.",
                                self._endpoint_name, type(e).__name__, e, self._backup_endpoint_name,
                            )
                            self.is_busy_flag = False
                            self.close()
                            backup_service = self._build_backup_service()
                            return backup_service.get_response_from_llm(**delegate_kwargs)
                        raise
                finally:
                    # close() lives in the OUTER finally so it also runs when the gate
                    # acquire above raises TimeoutError (before the inner try is entered);
                    # otherwise the handler's requests.Session would leak on a
                    # concurrency-slot timeout. The release and close() are both no-ops
                    # once the failover branch has already handled them.
                    if gate_held:
                        _release_endpoint_gate(True)
                    if self.is_busy_flag:
                        self.is_busy_flag = False
                        self.close()
        except Exception as e:
            self.is_busy_flag = False
            logger.error("Exception in get_response_from_llm: %s", e)
            traceback.print_exc()
            raise

    def close(self):
        """Closes the underlying API handler's HTTP session."""
        if self._api_handler:
            self._api_handler.close()

    def is_busy(self) -> bool:
        """
        Checks if the service is currently processing a request.

        Returns:
            bool: True if a request is in progress, otherwise False.
        """
        return self.is_busy_flag
