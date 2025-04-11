#!/usr/bin/env python3
import unittest
import sys
import os

# Adjust import paths
# Assuming the script is run from the 'tests' directory
# Go up four levels to reach the project root ('Wilmer')
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
sys.path.insert(0, project_root)

# Ensure the modules directory itself is in the path if needed
# sys.path.insert(0, os.path.abspath(os.path.dirname(__file__))) # Uncomment if tests need to import directly from modules siblings

# Import test modules
from test_mcp_tool_executor import TestMcpToolExecutor
from test_mcp_workflow_integration import TestMcpWorkflowIntegration
from test_workflow_history_integration import TestWorkflowHistoryIntegration

if __name__ == '__main__':
    # Discover all tests in the current directory (where this script resides)
    # It looks for files matching the pattern 'test*.py'
    loader = unittest.TestLoader()
    # Use '.' to discover in the current directory
    test_suite = loader.discover('.')

    # Create a test runner with verbosity
    runner = unittest.TextTestRunner(verbosity=2)

    # Run the test suite
    result = runner.run(test_suite)

    # Exit with 1 if any test failed, 0 otherwise
    sys.exit(not result.wasSuccessful()) 