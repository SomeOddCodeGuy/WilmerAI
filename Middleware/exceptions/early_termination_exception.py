# Middleware/exceptions/early_termination_exception.py

class EarlyTerminationException(Exception):
    """
    Raised to signal an intentional, non-error early exit from a workflow.

    This is used by nodes such as WorkflowLock to stop execution cleanly when
    a condition is met (e.g., an active lock is detected). It is caught at the
    workflow-processor level and results in an empty response rather than an
    error being propagated to the client.
    """

    def __init__(self, message):
        super().__init__(message)
