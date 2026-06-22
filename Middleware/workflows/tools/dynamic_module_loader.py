# /Middleware/workflows/tools/dynamic_module_loader.py

import importlib.util
import os
import logging
import sys

from Middleware.utilities.config_utils import get_project_root_directory_path

# Base exception for errors occurring within dynamically loaded modules
class DynamicModuleError(Exception):
    """Base class for exceptions raised by dynamically loaded workflow modules."""
    def __init__(self, message, module_name=None, details=None):
        super().__init__(message)
        self.module_name = module_name
        self.details = details # Optional structured details

logger = logging.getLogger(__name__)


def _resolve_module_path(module_path):
    """
    Resolves the on-disk location of a dynamic module path.

    A relative path is honored as-is when it resolves against the current
    working directory — the original behavior, so an existing setup that
    launches Wilmer from a directory where the path already resolves keeps
    working unchanged. Only when that fails is the path retried relative to
    the project root, which makes the repo-relative paths used by shipped
    workflow configs (e.g. ``Public/workflow_python_scripts/_isevendays_mcp_scripts/ensure_system_prompt.py``) work
    no matter which directory Wilmer was launched from.

    Args:
        module_path (str): Absolute or relative path from the node config.

    Returns:
        str: The resolved path, or the original path unchanged when nothing
            matched (the caller's existence check then raises with the path
            the workflow author wrote).
    """
    if os.path.isabs(module_path) or os.path.isfile(module_path):
        return module_path
    root_candidate = os.path.join(get_project_root_directory_path(), module_path)
    if os.path.isfile(root_candidate):
        logger.debug(f"Resolved relative module_path '{module_path}' against the project root: '{root_candidate}'")
        return root_candidate
    return module_path


def run_dynamic_module(module_path, *args, **kwargs):
    """
    Dynamically loads and runs a module from a given file path.

    This function loads a Python module from the specified file path,
    checks for an 'Invoke' function within the module, and executes it
    with the provided arguments.

    Args:
        module_path (str): The file path to the module to load. May be
            absolute, or relative — a relative path that does not exist
            against the current working directory is retried relative to
            the project root (see ``_resolve_module_path``).
        *args: Variable length argument list to pass to the 'Invoke' function.
        **kwargs: Arbitrary keyword arguments to pass to the 'Invoke' function.

    Returns:
        The result of the 'Invoke' function within the loaded module.

    Raises:
        FileNotFoundError: If no file is found at the specified module path.
        AttributeError: If the module does not have an 'Invoke' function.
        TypeError: If 'Invoke' is not callable.
    """
    module_path = _resolve_module_path(module_path)
    if not os.path.isfile(module_path):
        raise FileNotFoundError(f"No file found at {module_path}")

    # Ensure the project root is on sys.path so a dynamic module can import sibling
    # project packages (e.g. `Public.workflow_python_scripts._isevendays_mcp_scripts.*`, `Middleware.*`). Use the canonical
    # resolver rather than counting "..": this file lives three levels below the repo
    # root (Middleware/workflows/tools/), so a two-level climb would wrongly add the
    # Middleware/ package directory instead of its parent.
    project_root = get_project_root_directory_path()
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
        logger.debug(f"Added project root {project_root} to sys.path for dynamic module execution")

    # Backward compat: before this loader put the repo root on sys.path it instead added
    # the Middleware/ directory, so older user scripts may import Middleware sub-packages
    # by short name (e.g. `import utilities.config_utils`). Keep those working alongside
    # the canonical `import Middleware.x` form by also exposing Middleware/.
    middleware_dir = os.path.join(project_root, "Middleware")
    if os.path.isdir(middleware_dir) and middleware_dir not in sys.path:
        sys.path.insert(0, middleware_dir)
        logger.debug(f"Added {middleware_dir} to sys.path for legacy short-name imports")

    spec = importlib.util.spec_from_file_location("dynamic_module", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "Invoke"):
        raise AttributeError(f"The module does not have a function named 'Invoke'")

    func = getattr(module, "Invoke")

    if not callable(func):
        raise TypeError(f"'Invoke' is not callable")

    try:
        response = func(*args, **kwargs)
        return response
    # Handle errors raised by the dynamic module itself
    except DynamicModuleError as dme:
        module_name_str = f" '{dme.module_name or os.path.basename(module_path)}'" if dme.module_name or module_path else ""
        details_str = f". Details: {dme.details}" if dme.details else ""
        error_message = f"Error in dynamic module{module_name_str}: {dme}{details_str}"
        logger.error(error_message)
        return f"Error processing request in module{module_name_str}. {dme}{details_str}"

    # Handle other potential errors during dynamic module execution
    except FileNotFoundError:
        raise # Re-raise FileNotFoundError as it indicates a setup issue
    except (AttributeError, TypeError) as e:
        logger.error(f"Error setting up or calling 'Invoke' in dynamic module '{os.path.basename(module_path)}': {e}")
        return f"Error: Module '{os.path.basename(module_path)}' setup issue. Please check logs."
    except Exception as e:
        logger.exception(f"Unexpected error executing 'Invoke' in dynamic module '{os.path.basename(module_path)}': {e}") # Log full traceback
        return "Error: An unexpected error occurred while processing your request. Please check system logs."