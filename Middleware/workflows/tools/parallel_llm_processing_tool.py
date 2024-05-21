from queue import Queue, Empty
from threading import Thread

from Middleware.services.llm_service import LlmHandlerService
from Middleware.utilities.config_utils import load_config, get_model_config_path
from Middleware.utilities.prompt_template_utils import format_user_turn_with_template


class ParallelLlmProcessingTool:
    """
    Tool for using N number of LLMs to chew through a large block of text
    by breaking it into chunks and having each LLM process the chunk in parallel
    """

    def __init__(self, config):
        self.llm_handlers = None
        self.workflow_config = None
        self.initialize_language_models(config)
        pass

    def initialize_language_models(self, config):
        """
        Initializes language model handlers based on the provided configuration.

        Parameters:
        config (dict): Configuration that includes model information.

        Returns:
        list: A list of initialized language model handlers.
        """
        self.workflow_config = config
        llm_handler_service = LlmHandlerService()
        print("config: ", self.workflow_config)

        self.llm_handlers = []
        for endpoint in config['multiModelList']:
            config_file = get_model_config_path(endpoint['endpointName'])
            config_data = load_config(config_file)
            handler = llm_handler_service.initialize_llm_handler(config_data,
                                                                 config['preset'],
                                                                 endpoint['endpointName'],
                                                                 config["maxNewTokens"],
                                                                 config["minNewTokens"],
                                                                 False)
            self.llm_handlers.append(handler)

    def get_smallest_truncate_length(self):
        """
        Determines the smallest truncate length among the provided language model handlers.

        Parameters:
        llm_handlers (list): A list of language model handlers.

        Returns:
        int: The smallest truncate length.
        """
        return min(self.llm_handlers, key=lambda x: x.truncate_length).truncate_length

    def process_prompt_chunks(self, chunks, workflow_prompt, custom_delimiter=""):
        """
        Processes each prompt chunk in parallel using threads.

        Parameters:
        chunks (list): Tokenized chunks of the original prompt.
        llm_handlers (list): Handlers for the language models.
        workflow_prompt (str): The prompt template_name used in processing.

        Returns:
        str: The assembled result from all processed chunks.
        """
        chunks_queue = Queue()
        results_queue = Queue()

        for index, chunk in enumerate(chunks):
            chunks_queue.put((chunk, index))

        threads = [
            Thread(target=self.chunk_processing_worker, args=(handler, chunks_queue, workflow_prompt, results_queue))
            for handler in self.llm_handlers]

        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        return self.assemble_results(chunks, results_queue, custom_delimiter)

    def chunk_processing_worker(self, handler, chunks_queue, workflow_prompt, results_queue):
        """
        Worker method for processing chunks; intended to run in a thread.

        Parameters:
        handler (LlmHandlerService): A single handler assigned to this worker.
        chunks_queue (Queue): Queue of chunks waiting to be processed.
        workflow_prompt (str): The prompt template_name used in processing.
        results_queue (Queue): Queue where results are placed after processing.
        """
        index = 0
        while True:
            try:
                chunk, index = chunks_queue.get_nowait()
                print(f"Handler for model {handler.prompt_template_file_name} is processing chunk {index}.")
                self.process_single_chunk(chunk, index, handler, workflow_prompt, results_queue)
                chunks_queue.task_done()
            except Empty:
                print(f"No more chunks to process by handler for model {handler.prompt_template_file_name}.")
                break  # Exit if no more chunks are available
            except Exception as e:
                print(
                    f"Error processing chunk at index {index} by handler for model "
                    f"{handler.prompt_template_file_name}: {str(e)}")

    @staticmethod
    def process_single_chunk(chunk, index, llm_handler, workflow_prompt, results_queue):
        formatted_prompt = workflow_prompt.replace('[TextChunk]', chunk)

        formatted_prompt = format_user_turn_with_template(formatted_prompt, llm_handler.prompt_template_file_name)

        result = llm_handler.llm.get_response_from_llm(formatted_prompt)
        if result:
            results_queue.put((index, result))

    @staticmethod
    def assemble_results(chunks, results_queue, custom_delimiter=""):
        processed_chunks = [''] * len(chunks)
        while not results_queue.empty():
            index, text = results_queue.get()
            processed_chunks[index] = text if text is not None else "There is no text here"

        return custom_delimiter.join(processed_chunks)
