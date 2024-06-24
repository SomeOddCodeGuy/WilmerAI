import os


# In order for the PythonModule node to work, the entrypoint must be "Invoke(*args, **kwargs).
# And it must return a string.
# Beyond that, do anything you want. If you wanted, you could simply return "" at the end
# if there is nothing to return. This is simply the structure necessary to trigger code.
def Invoke(*args, **kwargs):
    if len(args) != 1:
        raise ValueError("Expected a single string argument")
    input_string = args[0]

    # Ensure the directory exists
    directory = os.path.dirname("D:\\temp\\test.txt")
    os.makedirs(directory, exist_ok=True)

    with open("D:\\temp\\test.txt", "w") as f:
        f.write(input_string)
    return f"Wrote '{input_string}' to test.txt"
