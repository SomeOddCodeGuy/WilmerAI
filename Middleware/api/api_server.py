# Middleware/api/api_server.py

import importlib
import inspect
import logging
import os

from Middleware.api.app import app
from Middleware.api.handlers.base.base_api_handler import BaseApiHandler
from Middleware.utilities.config_utils import get_application_port

logger = logging.getLogger(__name__)


class ApiServer:
    """
    Discovers API handlers, registers their routes, and runs the Flask server.

    This class initializes the Flask application, dynamically discovers all API
    handlers in the 'handlers' directory, and registers the routes defined by
    each handler. It then starts the Flask web server to listen for incoming requests.
    """

    def __init__(self):
        self.app = app
        self._discover_and_register_handlers()

    def _discover_and_register_handlers(self):
        """
        Dynamically imports all handlers from the 'handlers' directory and its subdirectories,
        and registers their routes.

        This method traverses the `handlers/` directory, identifies all Python files that
        are not base classes, and dynamically imports them. It then inspects each
        imported module to find concrete classes that inherit from `BaseApiHandler`.
        For each discovered handler, it instantiates the class and calls its
        `register_routes` method, making the server extensible and modular.

        Raises:
            ImportError: If a handler module cannot be imported, often due to a
                         circular import or a missing `__init__.py` file.
            Exception: For any other errors that occur during the loading or
                       registration of a handler.
        """
        handlers_root_dir = os.path.join(os.path.dirname(__file__), 'handlers')
        logger.info(f"Discovering API handlers in: {handlers_root_dir}")

        for root, _, files in os.walk(handlers_root_dir):
            for filename in files:
                if filename.endswith('.py') and not filename.startswith('__') and not filename.startswith('base_'):

                    # Construct the full, importable module path from the file path.
                    relative_path = os.path.relpath(os.path.join(root, filename), handlers_root_dir)
                    sub_module_path = relative_path.replace(os.sep, '.')[:-3]
                    module_name = f"Middleware.api.handlers.{sub_module_path}"

                    if module_name.endswith("."):
                        module_name = module_name[:-1]

                    try:
                        logger.debug(f"Attempting to import and register handler: {module_name}")
                        module = importlib.import_module(module_name)
                        for name, obj in inspect.getmembers(module, inspect.isclass):
                            if issubclass(obj, BaseApiHandler) and not inspect.isabstract(obj):
                                handler_instance = obj()
                                handler_instance.register_routes(self.app)
                                logger.info(f"Successfully registered routes from {name} in {module_name}")
                    except ImportError as e:
                        # This error often points to specific structural issues in the project.
                        logger.error(
                            f"Failed to import handler from {module_name}: {e}. Check for circular imports or missing __init__.py files.")
                    except Exception as e:
                        logger.error(f"Failed to load or register handler from {module_name}: {e}")

    def run(self, debug: bool = False):
        """
        Starts the Flask web server.

        This method retrieves the application port from the User Config and
        starts the Flask server, making it accessible on the local network.

        Args:
            debug (bool): A boolean flag to enable or disable Flask's debug mode.
                          Defaults to False.
        """
        port = get_application_port()
        logger.info(f"Starting Flask server on host 0.0.0.0, port {port}")
        self.app.run(host='0.0.0.0', port=port, debug=debug)