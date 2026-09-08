## Custom Python Node Example Script

Wilmer has a [workflow](../User_Documentation/Setup/Workflow_Details/Workflows.md) node that allows the [running of
custom python scripts](../User_Documentation/Setup/Workflow_Details/Nodes/PythonModule.md). Inside this folder, you
can find an example of the structure of that Python script. `MyTestModule.Invoke` accepts one string and returns it
unchanged. Replace the return expression with the processing your
workflow needs; the entry point must still return a string.
