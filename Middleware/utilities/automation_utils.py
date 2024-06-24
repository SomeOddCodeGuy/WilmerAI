import importlib.util
import os


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

    # Load the module dynamically
    spec = importlib.util.spec_from_file_location("dynamic_module", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Check if the module has the Invoke function
    if not hasattr(module, "Invoke"):
        raise AttributeError(f"The module does not have a function named 'Invoke'")

    func = getattr(module, "Invoke")

    if not callable(func):
        raise TypeError(f"'Invoke' is not callable")

    # Call the function and return the result
    response = func(*args, **kwargs)
    return response
