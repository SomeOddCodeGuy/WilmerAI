# Middleware/services/cancellation_service.py

import logging
import threading
from typing import Set, Dict, Callable, List

logger = logging.getLogger(__name__)


class CancellationService:
    """
    A thread-safe singleton service that manages request cancellations.

    This service maintains a central registry of request IDs that have been
    marked for cancellation. It provides methods to request cancellation,
    check cancellation status, and acknowledge processed cancellations.

    Additionally, it supports abort callbacks that are invoked when a request
    is cancelled, allowing active operations (like HTTP requests) to be
    interrupted immediately.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """
        Ensures only one instance of CancellationService exists (singleton pattern).
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(CancellationService, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """
        Initializes the cancellation service with a thread-safe set and abort callbacks.
        """
        if self._initialized:
            return

        self._cancelled_requests: Set[str] = set()
        self._abort_callbacks: Dict[str, List[Callable[[], None]]] = {}
        self._set_lock = threading.Lock()
        self._initialized = True
        logger.info("CancellationService initialized")

    def request_cancellation(self, request_id: str) -> None:
        """
        Marks a request for cancellation and invokes all registered abort callbacks.

        Args:
            request_id (str): The unique identifier of the request to cancel.
        """
        if not request_id:
            logger.warning("Attempted to cancel a request with empty request_id")
            return

        callbacks_to_call = []
        with self._set_lock:
            # Ensure we only process the cancellation registration once.
            if request_id in self._cancelled_requests:
                logger.debug(f"Request {request_id} already marked for cancellation. Skipping registration.")
                return

            self._cancelled_requests.add(request_id)
            logger.info(f"Cancellation registered for request_id: {request_id}")

            # Get callbacks to invoke (copy the list to avoid holding the lock during callback execution)
            if request_id in self._abort_callbacks:
                callbacks_to_call = self._abort_callbacks[request_id].copy()
                logger.debug(f"Found {len(callbacks_to_call)} abort callback(s) for {request_id}. Preparing to invoke.")
            else:
                logger.debug(f"Cancellation requested for {request_id}, but no abort callbacks registered yet. They will be invoked upon registration.")

        # Call abort callbacks outside the lock to prevent deadlocks
        for callback in callbacks_to_call:
            try:
                logger.debug(f"Invoking abort callback for request_id: {request_id}")
                callback()
                logger.debug(f"Abort callback finished for request_id: {request_id}")
            except Exception as e:
                logger.error(f"Error executing abort callback for request_id {request_id}: {e}")

    def is_cancelled(self, request_id: str) -> bool:
        """
        Checks if a request has been marked for cancellation.

        Args:
            request_id (str): The unique identifier of the request to check.

        Returns:
            bool: True if the request has been marked for cancellation, False otherwise.
        """
        if not request_id:
            return False

        with self._set_lock:
            return request_id in self._cancelled_requests

    def acknowledge_cancellation(self, request_id: str) -> None:
        """
        Removes a request from the cancellation registry after it has been processed.
        Also cleans up any registered abort callbacks for this request.

        Args:
            request_id (str): The unique identifier of the request to acknowledge.
        """
        if not request_id:
            return

        with self._set_lock:
            if request_id in self._cancelled_requests:
                self._cancelled_requests.remove(request_id)
                logger.info(f"Cancellation acknowledged and cleared for request_id: {request_id}")
            else:
                logger.debug(f"Attempted to acknowledge non-existent cancellation for request_id: {request_id}")

            # Clean up abort callbacks
            if request_id in self._abort_callbacks:
                del self._abort_callbacks[request_id]
                logger.debug(f"Cleared abort callbacks for request_id: {request_id}")

    def register_abort_callback(self, request_id: str, callback: Callable[[], None]) -> None:
        """
        Registers an abort callback. If the request is already cancelled, invokes the callback immediately.

        This allows active operations (like HTTP requests) to be interrupted immediately
        when cancellation is requested. The callback should handle any cleanup needed
        to abort the operation (e.g., closing a response stream).

        Args:
            request_id (str): The unique identifier of the request.
            callback (Callable[[], None]): A function to call when the request is cancelled.
        """
        if not request_id:
            logger.warning("Attempted to register abort callback with empty request_id")
            return

        invoke_immediately = False
        with self._set_lock:
            # Check if the request is already cancelled (Handles the race condition)
            if request_id in self._cancelled_requests:
                logger.warning(f"Registering abort callback for already cancelled request {request_id}. Invoking immediately.")
                invoke_immediately = True
            else:
                # Normal registration
                if request_id not in self._abort_callbacks:
                    self._abort_callbacks[request_id] = []
                self._abort_callbacks[request_id].append(callback)
                logger.debug(f"Registered abort callback for request_id: {request_id}")

        # Invoke the callback outside the lock if necessary
        if invoke_immediately:
            try:
                logger.info(f"Invoking immediate abort callback for request_id: {request_id}")
                callback()
            except Exception as e:
                logger.error(f"Error executing immediate abort callback for request_id {request_id}: {e}")

    def unregister_abort_callbacks(self, request_id: str) -> None:
        """
        Removes all abort callbacks for a request.

        This should be called when an operation completes normally (not due to cancellation)
        to clean up the callback registry.

        Args:
            request_id (str): The unique identifier of the request.
        """
        if not request_id:
            return

        with self._set_lock:
            if request_id in self._abort_callbacks:
                del self._abort_callbacks[request_id]
                logger.debug(f"Unregistered abort callbacks for request_id: {request_id}")

    def get_all_cancelled_requests(self) -> Set[str]:
        """
        Returns a copy of all currently cancelled request IDs.

        Returns:
            Set[str]: A set containing all request IDs marked for cancellation.
        """
        with self._set_lock:
            return self._cancelled_requests.copy()


# Global singleton instance
cancellation_service = CancellationService()
