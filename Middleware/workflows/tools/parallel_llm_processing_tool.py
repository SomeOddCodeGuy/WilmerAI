# Middleware/workflows/tools/parallel_llm_processing_tool.py

import logging
import traceback
from queue import Queue, Empty
from threading import Thread

from Middleware.services.llm_service import LlmHandlerService
from Middleware.utilities.config_utils import get_endpoint_config
from Middleware.utilities.prompt_extraction_utils import remove_discussion_id_tag_from_string
from Middleware.utilities.prompt_template_utils import format_user_turn_with_template, \
    format_system_prompt_with_template
from Middleware.workflows.managers.workflow_variable_manager import WorkflowVariableManager

logger = logging.getLogger(__name__)


class ParallelLlmProcessingTool:
    """
    A tool for parallel text processing using multiple LLMs.

    This class divides a large text block into chunks and processes each
    chunk concurrently using a separate LLM handler in a dedicated thread.
    This is useful for tasks like summarization, translation, or
    sentiment analysis on large documents.
    """

    def __init__(self, config):
        """
        Initializes the ParallelLlmProcessingTool.

        Args:
            config (dict): The configuration dictionary for the tool. This includes
                           details on the LLMs to be used.
        """
        self.llm_handlers = None
        self.workflow_config = None
        self.initialize_language_models(config)

    def initialize_language_models(self, config):
        """
        Initializes the LLM handlers based on the provided configuration.

        The method iterates through a list of endpoints defined in the
        `multiModelList` of the workflow configuration. It retrieves the
        specific endpoint configuration for each and initializes an
        `LlmHandler` for each LLM.

        Args:
            config (dict): The workflow configuration dictionary.
        """
        self.workflow_config = config
        llm_handler_service = LlmHandlerService()
        logger.debug("config: %s", self.workflow_config)

        self.llm_handlers = []
        for endpoint in config['multiModelList']:
            endpoint_data = get_endpoint_config(endpoint["endpointName"])
            # Each call to initialize_llm_handler creates a new, independent handler for an endpoint.
            handler = llm_handler_service.initialize_llm_handler(endpoint_data,
                                                                 config['preset'],
                                                                 endpoint['endpointName'],
                                                                 False,  # stream is always False for this tool
                                                                 endpoint.get("maxContextTokenSize", 4096),
                                                                 config.get("maxResponseSizeInTokens", 400))
            self.llm_handlers.append(handler)

    def process_prompt_chunks(self, chunks, workflow_prompt, workflow_system_prompt, messages, custom_delimiter=""):
        """
        Processes a list of text chunks in parallel using multiple threads.

        Each thread is assigned an LLM handler and a queue of chunks to process.
        The results from each thread are collected and assembled into a
        single output string.

        Args:
            chunks (list): A list of strings, where each string is a chunk of the
                           original text to be processed.
            workflow_prompt (str): The user prompt template to be applied to each chunk.
            workflow_system_prompt (str): The system prompt template to be applied to each chunk.
            messages (List[Dict[str,str]]): A list of dictionaries representing the
                                             conversation history, with 'role' and 'content' keys.
            custom_delimiter (str, optional): The delimiter to use when joining the
                                              processed chunks. Defaults to an empty string.

        Returns:
            str: The assembled result from all processed chunks.
        """
        chunks_queue = Queue()
        results_queue = Queue()

        for index, chunk in enumerate(chunks):
            chunks_queue.put((chunk, index))

        threads = [
            Thread(target=self.chunk_processing_worker,
                   args=(handler, chunks_queue, workflow_prompt, workflow_system_prompt, results_queue, messages))
            for handler in self.llm_handlers]

        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        return self.assemble_results(chunks, results_queue, custom_delimiter)

    def chunk_processing_worker(self, handler, chunks_queue, workflow_prompt, workflow_system_prompt, results_queue,
                                messages):
        """
        A worker function for processing chunks in a dedicated thread.

        This function continuously retrieves chunks from the `chunks_queue`,
        processes them using the assigned `handler`, and places the results
        in the `results_queue`. It terminates when the queue is empty.

        Args:
            handler (LlmHandler): An initialized LLM handler wrapper object assigned to this worker.
            chunks_queue (Queue): The queue containing text chunks to be processed.
            workflow_prompt (str): The prompt template to use for processing.
            workflow_system_prompt (str): The system prompt template to use for processing.
            results_queue (Queue): The queue where processed results are stored.
            messages (List[Dict[str,str]]): A list of dictionaries representing the
                                             conversation history.
        """
        index = 0
        if chunks_queue.qsize() == 0:
            return results_queue
        while True:
            try:
                chunk, index = chunks_queue.get_nowait()
                logger.debug(f"Handler for model {handler.prompt_template_file_name} is processing chunk {index}.")
                self.process_single_chunk(chunk=chunk,
                                          index=index,
                                          llm_handler=handler,
                                          workflow_prompt=workflow_prompt,
                                          workflow_system_prompt=workflow_system_prompt,
                                          results_queue=results_queue,
                                          messages=messages)
                chunks_queue.task_done()
            except Empty:
                logger.debug(f"No more chunks to process by handler for model {handler.prompt_template_file_name}.")
                break  # Exit if no more chunks are available
            except Exception as e:
                logger.error(f"Error processing chunk at index {index} by handler for model "
                             f"{handler.prompt_template_file_name}: {str(e)}")
                traceback.print_exc()  # This prints the stack trace
                raise

    @staticmethod
    def process_single_chunk(chunk, index, llm_handler, workflow_prompt, workflow_system_prompt, results_queue,
                             messages):
        """
        Processes a single text chunk using the specified LLM handler.

        This method formats the prompt and system prompt with variables,
        replaces the '[TextChunk]' placeholder, and sends the request to
        the LLM via the handler. The result is then placed into the
        `results_queue` along with its original index.

        Args:
            chunk (str): The text chunk to be processed.
            index (int): The original index of the chunk in the list.
            llm_handler (LlmHandler): The LLM handler wrapper to use for processing. This object is
                                      expected to have an `.llm` attribute containing an `LlmApiService` instance.
            workflow_prompt (str): The user prompt template.
            workflow_system_prompt (str): The system prompt template.
            results_queue (Queue): The queue to place the result in.
            messages (List[Dict[str,str]]): The conversation history.
        """
        workflow_variable_service = WorkflowVariableManager()
        formatted_prompt = workflow_variable_service.apply_variables(workflow_prompt, llm_handler, messages)
        formatted_system_prompt = workflow_variable_service.apply_variables(workflow_system_prompt, llm_handler,
                                                                              messages)

        formatted_prompt = formatted_prompt.replace('[TextChunk]', chunk)
        formatted_system_prompt = formatted_system_prompt.replace('[TextChunk]', chunk)

        formatted_prompt = format_user_turn_with_template(formatted_prompt, llm_handler.prompt_template_file_name,
                                                          llm_handler.takes_message_collection)
        formatted_system_prompt = format_system_prompt_with_template(formatted_system_prompt,
                                                                     llm_handler.prompt_template_file_name,
                                                                     llm_handler.takes_message_collection)

        formatted_system_prompt = remove_discussion_id_tag_from_string(formatted_system_prompt)
        formatted_prompt = remove_discussion_id_tag_from_string(formatted_prompt)

        # The `llm_handler` object wraps the `LlmApiService` instance, which is accessed via the `.llm` attribute.
        if not llm_handler.takes_message_collection:
            result = llm_handler.llm.get_response_from_llm(system_prompt=formatted_system_prompt,
                                                           prompt=formatted_prompt,
                                                           llm_takes_images=llm_handler.takes_image_collection)
        else:
            collection = []
            if formatted_system_prompt:
                collection.append({"role": "system", "content": formatted_system_prompt})
            if formatted_prompt:
                collection.append({"role": "user", "content": formatted_prompt})

            result = llm_handler.llm.get_response_from_llm(collection,
                                                           llm_takes_images=llm_handler.takes_image_collection)

        if result:
            results_queue.put((index, result))

    @staticmethod
    def assemble_results(chunks, results_queue, custom_delimiter=""):
        """
        Assembles the processed chunks into a single result string.

        This method retrieves all processed chunks from the `results_queue`
        and reconstructs the full text in the correct order, using the
        original chunk indices.

        Args:
            chunks (list): The original list of chunks.
            results_queue (Queue): A queue containing tuples of `(index, result_text)`.
            custom_delimiter (str, optional): The delimiter to use when joining the
                                              processed chunks. Defaults to an empty string.

        Returns:
            str: The assembled result string.
        """
        processed_chunks = [''] * len(chunks)
        while not results_queue.empty():
            index, text = results_queue.get()
            processed_chunks[index] = text if text is not None else "There is no text here"

        return custom_delimiter.join(processed_chunks)