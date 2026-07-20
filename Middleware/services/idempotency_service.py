# Middleware/services/idempotency_service.py

import logging
import threading
import time
from collections import OrderedDict
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Upper bound on how many logical requests can be tracked in flight at once.
# The map normally shrinks as requests finish (release() removes their entry),
# so this cap only bites under an abnormal flood of distinct keys: a hostile
# or buggy client that never lets requests complete. When the cap is exceeded
# the oldest entry is evicted (LRU); losing an entry only means a later
# duplicate of that one request would not be cancelled promptly, degrading to
# the streaming layer's own disconnect detection.
MAX_IN_FLIGHT_KEYS = 1024

# Backstop TTL for in-flight entries whose release() never fired (a bug or a
# hard process fault between admission and teardown). A well-behaved request
# removes its own entry when its response completes or errors out, so this only
# prunes leaked entries. It is set well above any realistic single-generation
# wall-clock time so a legitimately long-running request is never pruned out
# from under a duplicate that could arrive while it is still generating.
IN_FLIGHT_TTL_SECONDS = 900

class IdempotencyService:
    """
    A thread-safe singleton that tracks in-flight logical requests by their
    client-supplied idempotency key.

    The chat client sends the same ``X-Idempotency-Key`` value across every
    retry of one logical request, and only ever retries after an attempt failed
    before its response began. This service lets Wilmer detect that a newly
    arrived request carries the key of an attempt that is still running
    downstream, so the caller can cancel the orphaned original and serve the
    new arrival fresh instead of double-generating on a single-slot backend.

    The registry maps ``key -> request_id`` (with a reverse ``request_id -> key``
    index for cleanup) and is bounded in both size (LRU cap) and age (TTL
    backstop). Keys are meaningful only within one process; nothing is persisted
    and there are no cross-restart semantics.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """
        Ensures only one instance of IdempotencyService exists (singleton pattern).
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(IdempotencyService, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """
        Initializes the registry and its guarding lock.
        """
        if self._initialized:
            return

        # key -> (request_id, monotonic_registration_time). OrderedDict so the
        # oldest entry can be evicted in O(1) when the size cap is exceeded.
        self._in_flight: "OrderedDict[str, Tuple[str, float]]" = OrderedDict()
        # request_id -> key, so a finishing request can find and clear its own
        # entry without scanning the forward map.
        self._by_request_id: Dict[str, str] = {}
        self._set_lock = threading.Lock()
        self._initialized = True
        logger.info("IdempotencyService initialized")

    def _prune_stale_locked(self) -> None:
        """
        Removes in-flight entries older than IN_FLIGHT_TTL_SECONDS.

        Must be called while holding self._set_lock. This is a leak backstop for
        entries whose release() never ran; healthy requests remove themselves.
        """
        cutoff = time.monotonic() - IN_FLIGHT_TTL_SECONDS
        stale = [key for key, (_, registered_at) in self._in_flight.items()
                 if registered_at < cutoff]
        for key in stale:
            request_id, _ = self._in_flight.pop(key)
            if self._by_request_id.get(request_id) == key:
                del self._by_request_id[request_id]
        if stale:
            logger.info(f"Pruned {len(stale)} stale idempotency entries older than "
                        f"{IN_FLIGHT_TTL_SECONDS}s")

    def _evict_oldest_locked(self) -> None:
        """
        Evicts least-recently-registered entries until the size cap is met.

        Must be called while holding self._set_lock. Eviction only drops
        tracking; it never cancels the evicted request.
        """
        while len(self._in_flight) > MAX_IN_FLIGHT_KEYS:
            key, (request_id, _) = self._in_flight.popitem(last=False)
            if self._by_request_id.get(request_id) == key:
                del self._by_request_id[request_id]
            logger.warning(
                f"Idempotency registry exceeded {MAX_IN_FLIGHT_KEYS} in-flight keys; "
                f"evicted oldest entry for request_id {request_id}")

    def register(self, key: str, request_id: str) -> Optional[str]:
        """
        Registers a request under an idempotency key, returning any displaced
        in-flight request that the caller should cancel.

        If the key is already bound to a different, still-in-flight request, that
        original's client has (by the client contract) already disconnected, so
        its request_id is returned as the "displaced" one and the key is rebound
        to the new request. The caller is responsible for cancelling the
        displaced request via the CancellationService; this service intentionally
        does not reach into cancellation itself, keeping the two concerns
        independent and separately testable.

        Args:
            key (str): The client-supplied idempotency key. A falsy key is
                ignored (returns None) so callers can pass through unconditionally.
            request_id (str): The unique identifier for the newly arrived request.

        Returns:
            Optional[str]: The request_id of a displaced in-flight original that
            should be cancelled, or None when the key was previously unseen (or
            was falsy).
        """
        if not key or not request_id:
            return None

        with self._set_lock:
            self._prune_stale_locked()

            displaced: Optional[str] = None
            existing = self._in_flight.get(key)
            if existing is not None:
                existing_request_id = existing[0]
                if existing_request_id != request_id:
                    displaced = existing_request_id
                    # Drop the displaced request's reverse index now so its own
                    # later release() is a clean no-op and cannot remove the new
                    # binding we are about to write.
                    if self._by_request_id.get(existing_request_id) == key:
                        del self._by_request_id[existing_request_id]

            self._in_flight[key] = (request_id, time.monotonic())
            self._in_flight.move_to_end(key)
            self._by_request_id[request_id] = key
            self._evict_oldest_locked()

        if displaced:
            logger.info(f"Idempotency key already in flight; displacing request_id {displaced} "
                        f"in favor of {request_id}")
        return displaced

    def release(self, request_id: str) -> None:
        """
        Releases the in-flight entry owned by a finishing request.

        The release is guarded: the forward ``key -> request_id`` binding is only
        removed when it still points at this request. This is what makes a
        displaced original's late teardown harmless: by then the key has been
        rebound to the newer request, so this call clears only the stale reverse
        index and leaves the live binding intact. Safe to call more than once and
        safe to call for a request that was never registered (a no-op).

        Args:
            request_id (str): The unique identifier of the finishing request.
        """
        if not request_id:
            return

        with self._set_lock:
            key = self._by_request_id.pop(request_id, None)
            if key is None:
                return
            existing = self._in_flight.get(key)
            if existing is not None and existing[0] == request_id:
                del self._in_flight[key]

    def get_request_id_for_key(self, key: str) -> Optional[str]:
        """
        Returns the request_id currently bound to a key, if any.

        Provided for inspection and testing; the normal admission path uses
        register() instead.

        Args:
            key (str): The idempotency key to look up.

        Returns:
            Optional[str]: The bound request_id, or None when the key is unknown.
        """
        if not key:
            return None
        with self._set_lock:
            existing = self._in_flight.get(key)
            return existing[0] if existing is not None else None

    def clear(self) -> None:
        """
        Removes all tracked entries. Intended for test isolation.
        """
        with self._set_lock:
            self._in_flight.clear()
            self._by_request_id.clear()


# Global singleton instance
idempotency_service = IdempotencyService()
