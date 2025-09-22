# tests/workflows/tools/test_dynamic_module_loader.py

import os
import sys

import pytest

from Middleware.workflows.tools.dynamic_module_loader import (
    run_dynamic_module
)


def test_run_dynamic_module_success(tmp_path):
    """
    Tests that a valid Python module with an 'Invoke' function is executed correctly
    and that its return value, along with args and kwargs, are passed through.
    """
    # Arrange: Create a temporary valid python module file.
    module_content = """
def Invoke(*args, **kwargs):
    return "Success", args, kwargs
"""
    module_path = tmp_path / "test_module.py"
    module_path.write_text(module_content)

    # Act: Run the dynamic module loader with test arguments.
    result = run_dynamic_module(str(module_path), 1, "test", key="value")

    # Assert: The result should match what the 'Invoke' function returned.
    assert result == ("Success", (1, "test"), {"key": "value"})


def test_run_dynamic_module_file_not_found(mocker):
    """
    Tests that a FileNotFoundError is raised if the module path does not exist.
    This test mocks os.path.isfile to avoid actual file system checks.
    """
    # Arrange: Define a path that doesn't exist and mock the file system check.
    non_existent_path = "/path/to/non/existent/module.py"
    mocker.patch('os.path.isfile', return_value=False)

    # Act & Assert: The function should raise a FileNotFoundError.
    with pytest.raises(FileNotFoundError, match=f"No file found at {non_existent_path}"):
        run_dynamic_module(non_existent_path)


def test_run_dynamic_module_invoke_missing(tmp_path):
    """
    Tests that an AttributeError is raised if the loaded module
    does not contain a function named 'Invoke'.
    """
    # Arrange: Create a module without an 'Invoke' function.
    module_content = "def not_the_right_function(): pass"
    module_path = tmp_path / "no_invoke.py"
    module_path.write_text(module_content)

    # Act & Assert: The function should raise an AttributeError.
    with pytest.raises(AttributeError, match="The module does not have a function named 'Invoke'"):
        run_dynamic_module(str(module_path))


def test_run_dynamic_module_invoke_not_callable(tmp_path):
    """
    Tests that a TypeError is raised if the loaded module has an attribute
    named 'Invoke' but it is not a callable function.
    """
    # Arrange: Create a module where 'Invoke' is a variable, not a function.
    module_content = "Invoke = {'a': 1}"
    module_path = tmp_path / "not_callable.py"
    module_path.write_text(module_content)

    # Act & Assert: The function should raise a TypeError.
    with pytest.raises(TypeError, match="'Invoke' is not callable"):
        run_dynamic_module(str(module_path))


def test_run_dynamic_module_handles_dynamic_module_error(tmp_path, mocker):
    """
    Tests that a custom DynamicModuleError raised from within the 'Invoke'
    function is caught and handled correctly, returning a formatted error string.
    """
    # Arrange: Create a module that raises a DynamicModuleError.
    module_content = """
from Middleware.workflows.tools.dynamic_module_loader import DynamicModuleError

def Invoke(*args, **kwargs):
    raise DynamicModuleError("Controlled failure", module_name="MyTool", details={"code": 400})
"""
    module_path = tmp_path / "error_module.py"
    module_path.write_text(module_content)
    mock_logger_error = mocker.patch("Middleware.workflows.tools.dynamic_module_loader.logger.error")

    # Act: Run the module that is expected to fail.
    result = run_dynamic_module(str(module_path))

    # Assert: Check that the returned error message is correctly formatted.
    expected_msg = "Error processing request in module 'MyTool'. Controlled failure. Details: {'code': 400}"
    assert result == expected_msg
    # Assert that the error was logged with the correct details.
    log_msg = "Error in dynamic module 'MyTool': Controlled failure. Details: {'code': 400}"
    mock_logger_error.assert_called_once_with(log_msg)


def test_run_dynamic_module_handles_generic_exception(tmp_path, mocker):
    """
    Tests that a generic, unexpected exception raised from within the 'Invoke'
    function is caught and returns a generic, user-safe error message.
    """
    # Arrange: Create a module that raises a standard Python exception.
    module_content = """
def Invoke(*args, **kwargs):
    raise IndexError("Something unexpected happened")
"""
    module_path = tmp_path / "generic_error_module.py"
    module_path.write_text(module_content)
    mock_logger_exception = mocker.patch("Middleware.workflows.tools.dynamic_module_loader.logger.exception")

    # Act: Run the module.
    result = run_dynamic_module(str(module_path))

    # Assert: The result should be the generic error message.
    assert result == "Error: An unexpected error occurred while processing your request. Please check system logs."
    # Assert that the full exception was logged for debugging.
    mock_logger_exception.assert_called_once()
    call_args, _ = mock_logger_exception.call_args
    assert "Unexpected error executing 'Invoke'" in call_args[0]
    assert "generic_error_module.py" in call_args[0]
    assert "Something unexpected happened" in call_args[0]


def test_run_dynamic_module_adds_project_root_to_sys_path(tmp_path):
    """
    Tests that the project root directory is correctly added to sys.path
    to allow dynamic modules to import other project files.
    """
    # Arrange: Create a minimal valid module.
    module_content = "def Invoke(): return 'ok'"
    module_path = tmp_path / "path_test_module.py"
    module_path.write_text(module_content)

    # Determine the expected project root path relative to the loader's location.
    import Middleware.workflows.tools.dynamic_module_loader as dml
    expected_root = os.path.abspath(os.path.join(os.path.dirname(dml.__file__), '..', '..'))

    # Ensure the path is not in sys.path before the test.
    if expected_root in sys.path:
        sys.path.remove(expected_root)
    assert expected_root not in sys.path

    # Act: Run the dynamic module loader.
    run_dynamic_module(str(module_path))

    # Assert: The project root should now be in sys.path.
    assert expected_root in sys.path

    # Teardown: Clean up sys.path for test isolation.
    if expected_root in sys.path:
        sys.path.remove(expected_root)


def test_run_dynamic_module_does_not_duplicate_sys_path(tmp_path):
    """
    Tests that the project root is not added to sys.path if it is already present.
    """
    # Arrange: Create a minimal valid module.
    module_content = "def Invoke(): return 'ok'"
    module_path = tmp_path / "path_test_module_2.py"
    module_path.write_text(module_content)

    import Middleware.workflows.tools.dynamic_module_loader as dml
    expected_root = os.path.abspath(os.path.join(os.path.dirname(dml.__file__), '..', '..'))

    # Ensure the path is already in sys.path.
    if expected_root not in sys.path:
        sys.path.insert(0, expected_root)
    original_path = list(sys.path)  # Make a copy for comparison.

    # Act: Run the module loader.
    run_dynamic_module(str(module_path))

    # Assert: sys.path should not have been modified.
    assert sys.path == original_path

    # Teardown: Clean up sys.path.
    if expected_root in sys.path and sys.path[0] == expected_root:
        sys.path.pop(0)
