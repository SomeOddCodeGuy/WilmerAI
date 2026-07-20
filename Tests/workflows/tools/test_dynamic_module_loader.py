# tests/workflows/tools/test_dynamic_module_loader.py

import os
import sys

import pytest

from Middleware.workflows.tools.dynamic_module_loader import (
    run_dynamic_module
)


@pytest.fixture(autouse=True)
def _sys_path_snapshot():
    """
    run_dynamic_module inserts the project root and Middleware/ directory into
    sys.path as a side effect. Snapshot and restore sys.path around every test
    so the loader tests do not permanently pollute the interpreter's path.
    """
    original = list(sys.path)
    yield
    sys.path[:] = original


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


def test_run_dynamic_module_invoke_type_error_returns_setup_issue(tmp_path, mocker):
    """
    Tests that a TypeError raised by 'Invoke' is translated into the
    module-setup-issue error string instead of propagating.
    """
    # Arrange: Create a module whose Invoke raises a TypeError.
    module_content = """
def Invoke(*args, **kwargs):
    raise TypeError("bad arguments")
"""
    module_path = tmp_path / "type_error_module.py"
    module_path.write_text(module_content)
    mock_logger_error = mocker.patch("Middleware.workflows.tools.dynamic_module_loader.logger.error")

    # Act
    result = run_dynamic_module(str(module_path))

    # Assert: The setup-issue string names the module by basename.
    assert result == "Error: Module 'type_error_module.py' setup issue. Please check logs."
    mock_logger_error.assert_called_once()


def test_run_dynamic_module_invoke_file_not_found_is_reraised(tmp_path):
    """
    Tests that a FileNotFoundError raised by 'Invoke' is re-raised (it signals
    a setup issue), not swallowed into an error string.
    """
    # Arrange: Create a module whose Invoke raises FileNotFoundError.
    module_content = """
def Invoke(*args, **kwargs):
    raise FileNotFoundError("missing resource file")
"""
    module_path = tmp_path / "fnf_error_module.py"
    module_path.write_text(module_content)

    # Act & Assert
    with pytest.raises(FileNotFoundError, match="missing resource file"):
        run_dynamic_module(str(module_path))


def test_run_dynamic_module_syntax_error_propagates(tmp_path):
    """
    Tests that a syntactically broken module makes exec_module raise, and that
    the SyntaxError propagates out of the loader (it happens before Invoke's
    error handling is in play).
    """
    # Arrange: Create a module with invalid Python syntax.
    module_path = tmp_path / "broken_syntax_module.py"
    module_path.write_text("def Invoke(:\n    pass")

    # Act & Assert
    with pytest.raises(SyntaxError):
        run_dynamic_module(str(module_path))


def test_run_dynamic_module_error_without_module_name_uses_basename(tmp_path):
    """
    Tests that a DynamicModuleError raised without a module_name falls back to
    the module file's basename in the returned error message.
    """
    # Arrange: Create a module that raises DynamicModuleError with no module_name.
    module_content = """
from Middleware.workflows.tools.dynamic_module_loader import DynamicModuleError

def Invoke(*args, **kwargs):
    raise DynamicModuleError("Missing input")
"""
    module_path = tmp_path / "anonymous_error_module.py"
    module_path.write_text(module_content)

    # Act
    result = run_dynamic_module(str(module_path))

    # Assert: Basename fallback in the user-facing message.
    assert result == "Error processing request in module 'anonymous_error_module.py'. Missing input"


def test_run_dynamic_module_adds_project_root_to_sys_path(tmp_path, mocker):
    """
    Tests that the loader puts the project root on sys.path so a dynamic module can
    import sibling project packages (e.g. Public.workflow_python_scripts._isevendays_mcp_scripts.*). A unique fake root is
    injected via the resolver so the assertion is not confounded by the real repo
    root already being on sys.path under pytest (pythonpath=.).
    """
    # Arrange: Create a minimal valid module (absolute path, so path resolution is
    # a no-op and the only call to the resolver is the sys.path insertion below).
    module_content = "def Invoke(): return 'ok'"
    module_path = tmp_path / "path_test_module.py"
    module_path.write_text(module_content)

    fake_root = str(tmp_path / "fake_project_root")
    mocker.patch(
        "Middleware.workflows.tools.dynamic_module_loader.get_project_root_directory_path",
        return_value=fake_root,
    )

    # Ensure the path is not in sys.path before the test.
    if fake_root in sys.path:
        sys.path.remove(fake_root)
    assert fake_root not in sys.path

    # Act / Assert: running the loader adds the resolved project root to sys.path.
    try:
        run_dynamic_module(str(module_path))
        assert fake_root in sys.path
    finally:
        if fake_root in sys.path:
            sys.path.remove(fake_root)


def test_run_dynamic_module_resolves_relative_path_against_project_root(tmp_path, mocker):
    """
    Tests that a relative module_path that does not exist against the current
    working directory is retried relative to the project root, so the
    repo-relative paths in shipped workflow configs work regardless of the
    directory Wilmer was launched from.
    """
    # Arrange: Place the module under a fake project root, with a relative
    # path that cannot resolve against the test runner's cwd.
    module_dir = tmp_path / "Public" / "modules"
    module_dir.mkdir(parents=True)
    (module_dir / "root_relative_module.py").write_text("def Invoke(): return 'from-root'")
    mocker.patch(
        "Middleware.workflows.tools.dynamic_module_loader.get_project_root_directory_path",
        return_value=str(tmp_path),
    )

    # Act
    result = run_dynamic_module(os.path.join("Public", "modules", "root_relative_module.py"))

    # Assert
    assert result == "from-root"


def test_run_dynamic_module_cwd_relative_path_wins_over_project_root(tmp_path, mocker, monkeypatch):
    """
    Tests that a relative path which resolves against the current working
    directory keeps being used as-is (the original behavior), even when a
    same-named file also exists under the project root.
    """
    # Arrange: Same relative filename in both a cwd dir and a fake project root.
    cwd_dir = tmp_path / "launch_dir"
    cwd_dir.mkdir()
    (cwd_dir / "dual_module.py").write_text("def Invoke(): return 'from-cwd'")
    root_dir = tmp_path / "install_root"
    root_dir.mkdir()
    (root_dir / "dual_module.py").write_text("def Invoke(): return 'from-root'")
    mocker.patch(
        "Middleware.workflows.tools.dynamic_module_loader.get_project_root_directory_path",
        return_value=str(root_dir),
    )
    monkeypatch.chdir(cwd_dir)

    # Act
    result = run_dynamic_module("dual_module.py")

    # Assert
    assert result == "from-cwd"


def test_run_dynamic_module_relative_path_missing_everywhere_raises(tmp_path, mocker):
    """
    Tests that a relative path that resolves neither against the cwd nor the
    project root still raises FileNotFoundError naming the path the workflow
    author wrote.
    """
    mocker.patch(
        "Middleware.workflows.tools.dynamic_module_loader.get_project_root_directory_path",
        return_value=str(tmp_path),
    )

    with pytest.raises(FileNotFoundError, match="No file found at missing/nowhere.py"):
        run_dynamic_module("missing/nowhere.py")


def test_run_dynamic_module_does_not_duplicate_sys_path(tmp_path, mocker):
    """
    Tests that the project root is not added to sys.path again if already present.
    """
    # Arrange: Create a minimal valid module.
    module_content = "def Invoke(): return 'ok'"
    module_path = tmp_path / "path_test_module_2.py"
    module_path.write_text(module_content)

    fake_root = str(tmp_path / "fake_project_root_2")
    mocker.patch(
        "Middleware.workflows.tools.dynamic_module_loader.get_project_root_directory_path",
        return_value=fake_root,
    )

    # Ensure the path is already in sys.path.
    if fake_root not in sys.path:
        sys.path.insert(0, fake_root)
    original_path = list(sys.path)  # Make a copy for comparison.

    # Act / Assert: an already-present root is not inserted a second time.
    try:
        run_dynamic_module(str(module_path))
        assert sys.path == original_path
    finally:
        if fake_root in sys.path and sys.path[0] == fake_root:
            sys.path.pop(0)


def test_run_dynamic_module_reloads_fresh_code_each_call(tmp_path):
    """
    Tests the PythonModule node's reload-per-call semantics: the script is
    re-executed from disk on every invocation, so an edit to the script file
    takes effect on the next workflow call without restarting Wilmer.
    """
    # Arrange: Write an initial version of the module and run it.
    module_path = tmp_path / "reload_module.py"
    module_path.write_text("def Invoke():\n    return 'first version'\n")
    assert run_dynamic_module(str(module_path)) == "first version"

    # Act: Rewrite the module with different code (different length too, so
    # any bytecode cache keyed on mtime+size cannot serve the stale version).
    module_path.write_text("def Invoke():\n    return 'second version rewritten'\n")

    # Assert: The next call picks up the new code.
    assert run_dynamic_module(str(module_path)) == "second version rewritten"


def test_run_dynamic_module_adds_middleware_dir_for_legacy_imports(tmp_path, mocker):
    """
    Tests that the loader also inserts <project_root>/Middleware onto sys.path
    (when that directory exists) so older user scripts using legacy short-name
    imports (e.g. `import utilities.config_utils`) keep working alongside the
    canonical `import Middleware.x` form.
    """
    # Arrange: A fake project root that contains a Middleware/ directory.
    module_path = tmp_path / "legacy_path_module.py"
    module_path.write_text("def Invoke(): return 'ok'")

    fake_root = tmp_path / "fake_root_with_mw"
    middleware_dir = fake_root / "Middleware"
    middleware_dir.mkdir(parents=True)
    mocker.patch(
        "Middleware.workflows.tools.dynamic_module_loader.get_project_root_directory_path",
        return_value=str(fake_root),
    )
    assert str(middleware_dir) not in sys.path

    # Act
    run_dynamic_module(str(module_path))

    # Assert: Both the root and its Middleware/ dir are importable.
    # (sys.path is restored by the autouse _sys_path_snapshot fixture.)
    assert str(fake_root) in sys.path
    assert str(middleware_dir) in sys.path


def test_run_dynamic_module_expands_home_directory(tmp_path, monkeypatch):
    """
    A module_path with a leading ~ must expand to the home directory, matching
    how every other file-path field in workflow configs behaves. Regression
    test for ~-based paths (e.g. a user-wide {python_scripts_dir} of
    "~/Shared/Public/...") failing with FileNotFoundError on the literal ~.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    module_path = tmp_path / "home_module.py"
    module_path.write_text("def Invoke():\n    return 'from home'\n")

    result = run_dynamic_module("~/home_module.py")

    assert result == "from home"
