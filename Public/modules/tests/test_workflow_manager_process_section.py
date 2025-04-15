#!/usr/bin/env python

"""
Unit tests for the WorkflowManager._process_section method, specifically focusing on 
dispatching to the correct handler based on the 'type' field in the configuration.
"""

import unittest
import sys
import os
import logging
from unittest.mock import patch, MagicMock, ANY

# Adjust import paths 
# Assuming this script is in WilmerAI/Public/modules/tests
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))) # Go up four levels to root

# Import the class under test and necessary mocks/dependencies
from WilmerAI.Middleware.workflows.managers.workflow_manager import WorkflowManager
from WilmerAI.Middleware.workflows.managers.workflow_variable_manager import WorkflowVariableManager
from WilmerAI.Middleware.workflows.processors.prompt_processor import PromptProcessor
from WilmerAI.Middleware.services.llm_service import LlmHandlerService
from WilmerAI.Middleware.models.llm_handler import LlmHandler

# Basic logging setup for testing visibility
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Simple mock for LlmHandler to avoid complex setup
class MockLlmHandler(LlmHandler):
    def __init__(self):
        # Initialize base class attributes minimally if needed, or override methods
        super().__init__(None, "mock_template", 0, 0, True) 
        self.takes_message_collection = True # Example attribute


class TestWorkflowManagerProcessSectionDispatch(unittest.TestCase):

    def setUp(self):
        """Set up mocks and the WorkflowManager instance for each test."""
        logger.debug("Setting up test: %s", self._testMethodName)

        # Mock dependencies needed by WorkflowManager.__init__ or _process_section
        self.mock_llm_handler_service = MagicMock(spec=LlmHandlerService)
        self.mock_llm_handler = MockLlmHandler()
        self.mock_llm_handler_service.load_model_from_config.return_value = self.mock_llm_handler
        
        # Mock WorkflowVariableManager
        self.mock_variable_manager = MagicMock(spec=WorkflowVariableManager)
        
        # Patch LlmHandlerService globally or where needed. Here, patching where WorkflowManager is defined.
        # Patch PromptProcessor creation as well
        self.llm_service_patcher = patch('WilmerAI.Middleware.workflows.managers.workflow_manager.LlmHandlerService', return_value=self.mock_llm_handler_service)
        self.prompt_processor_patcher = patch('WilmerAI.Middleware.workflows.managers.workflow_manager.PromptProcessor')
        
        self.mock_llm_service = self.llm_service_patcher.start()
        self.addCleanup(self.llm_service_patcher.stop)
        self.mock_prompt_processor_constructor = self.prompt_processor_patcher.start()
        self.addCleanup(self.prompt_processor_patcher.stop)
        
        self.mock_prompt_processor_instance = MagicMock(spec=PromptProcessor)
        self.mock_prompt_processor_constructor.return_value = self.mock_prompt_processor_instance

        # --- Mock all _handle_..._step methods ON THE CLASS before instantiation ---
        # Store mocks in a dictionary for easy access in tests
        self.handler_mocks = {}
        handler_methods_to_mock = [
            '_handle_standard_step', '_handle_conversation_memory_step', 
            '_handle_full_chat_summary_step', '_handle_recent_memory_step',
            '_handle_conversational_keyword_search_step', '_handle_memory_keyword_search_step',
            '_handle_recent_memory_summarizer_step', '_handle_chat_summary_gathering_step',
            '_handle_get_current_summary_step', '_handle_chat_summary_summarizer_step',
            '_handle_get_current_memory_step', '_handle_write_summary_step',
            '_handle_slow_rag_step', '_handle_quality_memory_step',
            '_handle_python_module_step', '_handle_wiki_full_article_step',
            '_handle_wiki_best_article_step', '_handle_wiki_topn_articles_step',
            '_handle_wiki_partial_article_step', '_handle_workflow_lock_step',
            '_handle_custom_workflow_step', '_handle_conditional_workflow_step',
            '_handle_get_custom_file_step', '_handle_image_processor_step'
        ]
        
        for method_name in handler_methods_to_mock:
             # Patch the method on the CLASS
             # Use create=True in case a method doesn't exist? Safer to assume they do.
             patcher = patch.object(WorkflowManager, method_name, return_value=f"Mock result for {method_name}", spec_set=True) 
             self.handler_mocks[method_name] = patcher.start()
             self.addCleanup(patcher.stop) # Ensure patch stops even if test fails

        # Instantiate the WorkflowManager AFTER patching the class methods
        # Pass the mock variable manager via kwargs if it's used in __init__
        self.manager = WorkflowManager(workflow_config_name="test_workflow", 
                                       workflow_variable_service=self.mock_variable_manager) 
        # Ensure the manager uses our mock LLM handler if needed within _process_section
        # This should be handled by the LlmHandlerService mock now
        # self.manager.llm_handler = self.mock_llm_handler # Maybe not needed if service mock works

        # --- Common arguments for _process_section ---
        self.common_args = {
            "request_id": "test_req_id",
            "workflow_id": "test_wf_id",
            "discussion_id": "test_disc_id",
            "messages": [{"role": "user", "content": "hello"}],
            "agent_outputs": {},
            "stream": False,
            "addGenerationPrompt": None
        }
        
        logger.debug("Setup complete for: %s", self._testMethodName)


    def tearDown(self):
        """Stop patchers."""
        logger.debug("Tearing down test: %s", self._testMethodName)
        # Patches started with self.addCleanup in setUp will be stopped automatically
        # self.llm_service_patcher.stop() # Now stopped by addCleanup
        # self.prompt_processor_patcher.stop() # Now stopped by addCleanup
        logger.debug("Teardown complete for: %s", self._testMethodName)


    def _run_test_for_type(self, step_type, expected_handler_method_name):
        """Helper method to run the dispatch test for a given type."""
        logger.info(f"Testing dispatch for type: {step_type} -> {expected_handler_method_name}")
        
        config = {
            "title": f"Test Step {step_type}", 
            "type": step_type,
            # Add 'endpointName' if needed for LLM handler loading logic within _process_section
            "endpointName": "MockEndpoint" 
        }

        # Call the method under test
        result = self.manager._process_section(config=config, **self.common_args)

        # Assert the expected handler was called
        if expected_handler_method_name in self.handler_mocks:
            mock_handler = self.handler_mocks[expected_handler_method_name]
            try:
                 mock_handler.assert_called_once()
                 # Optionally check arguments passed to the handler
                 # mock_handler.assert_called_once_with(config=config, messages=self.common_args['messages'], ...) 
            except AssertionError as e:
                 logger.error(f"Assertion failed for type '{step_type}': {e}")
                 # Log which mocks *were* called, if any
                 for name, mock_obj in self.handler_mocks.items():
                      if mock_obj.called:
                           logger.error(f"Mock {name} was called unexpectedly.")
                 raise e

            # Assert other handlers were *not* called
            for name, mock_obj in self.handler_mocks.items():
                if name != expected_handler_method_name:
                    mock_obj.assert_not_called()
                    
            # Check the result matches the mock handler's return value
            self.assertEqual(result, f"Mock result for {expected_handler_method_name}", 
                             f"Result mismatch for type '{step_type}'")
        else:
             self.fail(f"Mock for handler method '{expected_handler_method_name}' not found in setup.")


    # --- Individual tests for each type ---

    def test_dispatch_standard(self):
        self._run_test_for_type("Standard", "_handle_standard_step")

    def test_dispatch_conversation_memory(self):
        self._run_test_for_type("ConversationMemory", "_handle_conversation_memory_step")

    def test_dispatch_full_chat_summary(self):
        self._run_test_for_type("FullChatSummary", "_handle_full_chat_summary_step")

    def test_dispatch_recent_memory(self):
        self._run_test_for_type("RecentMemory", "_handle_recent_memory_step")

    def test_dispatch_conversational_keyword_search(self):
        self._run_test_for_type("ConversationalKeywordSearchPerformerTool", "_handle_conversational_keyword_search_step")

    def test_dispatch_memory_keyword_search(self):
        self._run_test_for_type("MemoryKeywordSearchPerformerTool", "_handle_memory_keyword_search_step")

    def test_dispatch_recent_memory_summarizer(self):
        self._run_test_for_type("RecentMemorySummarizerTool", "_handle_recent_memory_summarizer_step")

    def test_dispatch_chat_summary_gathering(self):
        self._run_test_for_type("ChatSummaryMemoryGatheringTool", "_handle_chat_summary_gathering_step")

    def test_dispatch_get_current_summary(self):
        self._run_test_for_type("GetCurrentSummaryFromFile", "_handle_get_current_summary_step")
        
    def test_dispatch_get_current_memory(self):
        # This type aliases to the summary handler
        self._run_test_for_type("GetCurrentMemoryFromFile", "_handle_get_current_memory_step") 

    def test_dispatch_chat_summary_summarizer(self):
        self._run_test_for_type("chatSummarySummarizer", "_handle_chat_summary_summarizer_step")

    def test_dispatch_write_summary(self):
        self._run_test_for_type("WriteCurrentSummaryToFileAndReturnIt", "_handle_write_summary_step")

    def test_dispatch_slow_rag(self):
        self._run_test_for_type("SlowButQualityRAG", "_handle_slow_rag_step")

    def test_dispatch_quality_memory(self):
        self._run_test_for_type("QualityMemory", "_handle_quality_memory_step")

    def test_dispatch_python_module(self):
        self._run_test_for_type("PythonModule", "_handle_python_module_step")

    def test_dispatch_wiki_full_article(self):
        self._run_test_for_type("OfflineWikiApiFullArticle", "_handle_wiki_full_article_step")

    def test_dispatch_wiki_best_article(self):
        self._run_test_for_type("OfflineWikiApiBestFullArticle", "_handle_wiki_best_article_step")
        
    def test_dispatch_wiki_topn_articles(self):
        self._run_test_for_type("OfflineWikiApiTopNFullArticles", "_handle_wiki_topn_articles_step")

    def test_dispatch_wiki_partial_article(self):
        self._run_test_for_type("OfflineWikiApiPartialArticle", "_handle_wiki_partial_article_step")

    def test_dispatch_workflow_lock(self):
        self._run_test_for_type("WorkflowLock", "_handle_workflow_lock_step")

    def test_dispatch_custom_workflow(self):
        self._run_test_for_type("CustomWorkflow", "_handle_custom_workflow_step")

    def test_dispatch_conditional_workflow(self):
        self._run_test_for_type("ConditionalCustomWorkflow", "_handle_conditional_workflow_step")

    def test_dispatch_get_custom_file(self):
        self._run_test_for_type("GetCustomFile", "_handle_get_custom_file_step")
        
    def test_dispatch_image_processor(self):
        self._run_test_for_type("ImageProcessor", "_handle_image_processor_step")

    def test_dispatch_unknown_type(self):
        """Test that an unknown type is handled gracefully (returns None, logs warning)."""
        unknown_type = "ThisTypeDoesNotExist"
        logger.info(f"Testing dispatch for unknown type: {unknown_type}")
        
        config = {"title": "Test Unknown Step", "type": unknown_type, "endpointName": "MockEndpoint"}

        # Call the method under test
        # Capture log messages maybe? For now, check return and lack of handler calls.
        with self.assertLogs(logger='WilmerAI.Middleware.workflows.managers.workflow_manager', level='WARNING') as cm:
            result = self.manager._process_section(config=config, **self.common_args)
        
        # Assert the return value is None for unknown types
        self.assertIsNone(result, "Expected None return value for unknown step type.")

        # Assert that NO known handler was called
        for name, mock_obj in self.handler_mocks.items():
            mock_obj.assert_not_called()
            
        # Check log message (optional but good)
        self.assertTrue(any(f"Unknown step type '{unknown_type}'" in message for message in cm.output))

    def test_dispatch_no_type(self):
        """Test that a step with no 'type' key defaults to 'Standard'."""
        logger.info("Testing dispatch for step with missing 'type' key")
        
        config = {
            "title": "Test Step No Type", 
            # "type": is missing
            "endpointName": "MockEndpoint" 
        }

        # Call the method under test
        result = self.manager._process_section(config=config, **self.common_args)

        # Assert the Standard handler was called
        expected_handler_method_name = "_handle_standard_step"
        if expected_handler_method_name in self.handler_mocks:
             mock_handler = self.handler_mocks[expected_handler_method_name]
             try:
                  mock_handler.assert_called_once()
             except AssertionError as e:
                  logger.error(f"Assertion failed for missing type (defaulting to Standard): {e}")
                  raise e
             self.assertEqual(result, f"Mock result for {expected_handler_method_name}", 
                              "Result mismatch for missing type default")

             # Assert other handlers were *not* called
             for name, mock_obj in self.handler_mocks.items():
                 if name != expected_handler_method_name:
                     mock_obj.assert_not_called()
        else:
             self.fail("Mock for default handler '_handle_standard_step' not found.")


if __name__ == '__main__':
    unittest.main() 