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
    Tool for processing a large block of text using multiple LLMs in parallel.
    The text is divided into chunks, and each LLM processes a chunk concurrently.
    """

    def __init__(self, config):
        """
        Initializes the ParallelLlmProcessingTool with the given configuration.

        Parameters:
        config (dict): Configuration dictionary containing model and endpoint information.
        """
        self.llm_handlers = None
        self.workflow_config = None
        self.initialize_language_models(config)

    def initialize_language_models(self, config):
        """
        Initializes language model handlers based on the provided configuration.

        Parameters:
        config (dict): Configuration that includes model information.
        """
        self.workflow_config = config
        llm_handler_service = LlmHandlerService()
        logger.debug("config: %s", self.workflow_config)

        self.llm_handlers = []
        for endpoint in config['multiModelList']:
            endpoint_data = get_endpoint_config(endpoint["endpointName"])
            handler = llm_handler_service.initialize_llm_handler(endpoint_data,
                                                                 config['preset'],
                                                                 endpoint['endpointName'],
                                                                 False,
                                                                 endpoint.get("maxContextTokenSize", 4096),
                                                                 config.get("maxResponseSizeInTokens", 400))
            self.llm_handlers.append(handler)

    def process_prompt_chunks(self, chunks, workflow_prompt, workflow_system_prompt, messages, custom_delimiter=""):
        """
        Processes each prompt chunk in parallel using threads.

        Parameters:
        chunks (list): Tokenized chunks of the original prompt.
        workflow_prompt (str): The prompt used in processing.
        workflow_system_prompt (str): The system prompt used in processing.
        custom_delimiter (str): Delimiter for joining the processed chunks. Default is an empty string.

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
        Worker method for processing chunks; intended to run in a thread.

        Parameters:
        handler (LlmHandlerService): A single handler assigned to this worker.
        chunks_queue (Queue): Queue of chunks waiting to be processed.
        workflow_prompt (str): The prompt used in processing.
        workflow_system_prompt (str): The system prompt used in processing.
        results_queue (Queue): Queue where results are placed after processing.
        """
        index = 0
        if chunks_queue.qsize() == 0:
            return results_queue
        while True:
            try:
                chunk, index = chunks_queue.get_nowait()
                logger.info(f"Handler for model {handler.prompt_template_file_name} is processing chunk {index}.")
                self.process_single_chunk(chunk=chunk,
                                          index=index,
                                          llm_handler=handler,
                                          workflow_prompt=workflow_prompt,
                                          workflow_system_prompt=workflow_system_prompt,
                                          results_queue=results_queue,
                                          messages=messages)
                chunks_queue.task_done()
            except Empty:
                logger.info(f"No more chunks to process by handler for model {handler.prompt_template_file_name}.")
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
        Processes a single chunk using the specified LLM handler.

        Parameters:
        chunk (str): The text chunk to be processed.
        index (int): The index of the chunk in the original text.
        llm_handler (LlmHandlerService): The handler for processing the chunk.
        workflow_prompt (str): The prompt used in processing.
        workflow_system_prompt (str): The system prompt used in processing.
        results_queue (Queue): Queue where the result is placed after processing.
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

        if not llm_handler.takes_message_collection:
            result = llm_handler.llm.get_response_from_llm(system_prompt=formatted_system_prompt,
                                                           prompt=formatted_prompt)
        else:
            collection = []
            if formatted_system_prompt:
                collection.append({"role": "system", "content": formatted_system_prompt})
            if formatted_prompt:
                collection.append({"role": "user", "content": formatted_prompt})

            result = llm_handler.llm.get_response_from_llm(collection)

        if result:
            results_queue.put((index, result))

    @staticmethod
    def assemble_results(chunks, results_queue, custom_delimiter=""):
        """
        Assembles the processed chunks into a single result string.

        Parameters:
        chunks (list): The original list of chunks.
        results_queue (Queue): Queue containing the processed results.
        custom_delimiter (str): Delimiter for joining the processed chunks. Default is an empty string.

        Returns:
        str: The assembled result from all processed chunks.
        """
        processed_chunks = [''] * len(chunks)
        while not results_queue.empty():
            index, text = results_queue.get()
            processed_chunks[index] = text if text is not None else "There is no text here"

        return custom_delimiter.join(processed_chunks)
