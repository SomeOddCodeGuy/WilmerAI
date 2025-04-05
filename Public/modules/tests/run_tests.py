#!/usr/bin/env python3
import unittest
import sys
import os

# Adjust import paths
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../..")))

# Import test modules
from test_mcp_tool_executor import TestMcpToolExecutor
from test_mcp_workflow_integration import TestMcpWorkflowIntegration

if __name__ == '__main__':
    # Create test loader
    loader = unittest.TestLoader()
    
    # Create test suite
    test_suite = unittest.TestSuite()
    
    # Add test cases using TestLoader
    test_suite.addTests(loader.loadTestsFromTestCase(TestMcpToolExecutor))
    test_suite.addTests(loader.loadTestsFromTestCase(TestMcpWorkflowIntegration))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)
    
    # Exit with non-zero code if tests failed
    sys.exit(not result.wasSuccessful()) 