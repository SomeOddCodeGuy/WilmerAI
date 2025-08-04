# Middleware/api/handlers/base/base_api_handler.py
from abc import ABC, abstractmethod
from flask import Flask

class BaseApiHandler(ABC):
    """
    Abstract base class for all API handlers.

    This class defines the fundamental structure for handling API requests
    within the WilmerAI middleware. Concrete implementations of this class
    are responsible for registering specific routes with the Flask application
    and handling the logic for those routes. All API handlers must inherit
    from this class.
    """

    @abstractmethod
    def register_routes(self, app: Flask) -> None:
        """
        Registers all the Flask URL rules for this handler.

        This method must be implemented by all subclasses to define the
        API endpoints and their corresponding view functions.

        Args:
            app (Flask): The Flask application instance to which routes will be registered.
        """
        pass