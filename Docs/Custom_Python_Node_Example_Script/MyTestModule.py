"""Minimal PythonModule example without filesystem writes."""


def Invoke(*args, **kwargs):
    """Return the single string argument supplied by a workflow.

    Args:
        *args: Exactly one string to return.
        **kwargs: Optional workflow keyword arguments, unused by this example.

    Returns:
        str: The input string.

    Raises:
        ValueError: If the positional arguments are not exactly one string.
    """
    if len(args) != 1 or not isinstance(args[0], str):
        raise ValueError("Expected a single string argument")
    return args[0]
