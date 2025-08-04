# Middleware/exceptions/early_termination_exception.py

class EarlyTerminationException(Exception):
    def __init__(self, message):
        super().__init__(message)
