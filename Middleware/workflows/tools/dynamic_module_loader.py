# /Middleware/workflows/tools/dynamic_module_loader.py

import importlib.util
import os
import logging
import sys

# Base exception for errors occurring within dynamically loaded modules
class DynamicModuleError(Exception):
    """Base class for exceptions raised by dynamically loaded workflow modules."""
    def __init__(self, message, module_name=None, details=None):
        super().__init__(message)
        self.module_name = module_name
        self.details = details # Optional structured details

logger = logging.getLogger(__name__)

def run_dynamic_module(module_path, *args, **kwargs):
    """
    Dynamically loads and runs a module from a given file path.

    This function loads a Python module from the specified file path,
    checks for an 'Invoke' function within the module, and executes it
    with the provided arguments.

    Args:
        module_path (str): The file path to the module to load.
        *args: Variable length argument list to pass to the 'Invoke' function.
        **kwargs: Arbitrary keyword arguments to pass to the 'Invoke' function.

    Returns:
        The result of the 'Invoke' function within the loaded module.

    Raises:
        FileNotFoundError: If no file is found at the specified module path.
        AttributeError: If the module does not have an 'Invoke' function.
        TypeError: If 'Invoke' is not callable.
    """
    if not os.path.isfile(module_path):
        raise FileNotFoundError(f"No file found at {module_path}")

    # Ensure the project root is in sys.path for the dynamic module
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
        logger.debug(f"Added project root {project_root} to sys.path for dynamic module execution")

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