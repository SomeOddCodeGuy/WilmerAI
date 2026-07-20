# tests/services/test_cancellation_service.py

import pytest
import threading
import time
from Middleware.services.cancellation_service import CancellationService, cancellation_service


class TestCancellationService:
    """Test suite for the CancellationService class."""

    @staticmethod
    def _reset_singleton_state():
        """Clear all cancelled ids and abort callbacks from the process-wide singleton."""
        service = CancellationService()
        for req_id in list(service.get_all_cancelled_requests()):
            service.acknowledge_cancellation(req_id)
        # Callbacks registered for never-cancelled ids are not enumerable through
        # the public API, so clear the registry directly to prevent state leaking
        # into other test files.
        with service._set_lock:
            service._abort_callbacks.clear()

    def setup_method(self):
        """Set up test fixtures before each test method."""
        self._reset_singleton_state()

    def teardown_method(self):
        """Ensure no cancellations or callbacks leak from the singleton after each test."""
        self._reset_singleton_state()

    def test_singleton_pattern(self):
        """Test that CancellationService implements the singleton pattern correctly."""
        service1 = CancellationService()
        service2 = CancellationService()
        assert service1 is service2, "CancellationService should be a singleton"

    def test_global_instance(self):
        """Test that the global cancellation_service instance is the singleton."""
        service = CancellationService()
        assert cancellation_service is service, "Global instance should be the same as singleton"

    def test_request_cancellation(self):
        """Test that request_cancellation correctly adds a request ID to the set."""
        service = CancellationService()
        request_id = "test_request_123"

        service.request_cancellation(request_id)

        assert service.is_cancelled(request_id), "Request should be marked as cancelled"

    def test_request_cancellation_empty_id(self):
        """Test that request_cancellation handles empty request IDs gracefully."""
        service = CancellationService()

        service.request_cancellation("")
        service.request_cancellation(None)

        assert not service.is_cancelled(""), "Empty string should not be marked as cancelled"
        assert not service.is_cancelled(None), "None should not be marked as cancelled"

    def test_request_cancellation_duplicate(self):
        """Test that requesting cancellation for the same ID multiple times is safe."""
        service = CancellationService()
        request_id = "duplicate_request"

        service.request_cancellation(request_id)
        service.request_cancellation(request_id)

        assert service.is_cancelled(request_id), "Request should be marked as cancelled"
        all_cancelled = service.get_all_cancelled_requests()
        # Sets inherently have unique values, so we just verify it's present and set size
        assert request_id in all_cancelled, "Request ID should be in the set"
        assert len(all_cancelled) == 1, "Should have exactly one request in the set"

    def test_is_cancelled_false_for_nonexistent(self):
        """Test that is_cancelled returns False for non-existent request IDs."""
        service = CancellationService()
        request_id = "nonexistent_request"

        assert not service.is_cancelled(request_id), "Non-existent request should not be cancelled"

    def test_is_cancelled_empty_id(self):
        """Test that is_cancelled handles empty request IDs correctly."""
        service = CancellationService()

        assert not service.is_cancelled(""), "Empty string should return False"
        assert not service.is_cancelled(None), "None should return False"

    def test_acknowledge_cancellation(self):
        """Test that acknowledge_cancellation removes a request ID from the set."""
        service = CancellationService()
        request_id = "test_ack_request"

        service.request_cancellation(request_id)
        assert service.is_cancelled(request_id), "Request should be cancelled initially"

        service.acknowledge_cancellation(request_id)
        assert not service.is_cancelled(request_id), "Request should not be cancelled after acknowledgement"

    def test_acknowledge_cancellation_nonexistent(self):
        """Test that acknowledging a non-existent request is safe."""
        service = CancellationService()
        request_id = "nonexistent_ack"

        # Should not raise an exception
        service.acknowledge_cancellation(request_id)

    def test_acknowledge_cancellation_empty_id(self):
        """Test that acknowledge_cancellation handles empty request IDs gracefully."""
        service = CancellationService()

        # Should not raise an exception
        service.acknowledge_cancellation("")
        service.acknowledge_cancellation(None)

    def test_get_all_cancelled_requests(self):
        """Test that get_all_cancelled_requests returns a copy of the set."""
        service = CancellationService()
        request_id1 = "request_1"
        request_id2 = "request_2"

        service.request_cancellation(request_id1)
        service.request_cancellation(request_id2)

        all_cancelled = service.get_all_cancelled_requests()

        assert request_id1 in all_cancelled, "First request should be in the set"
        assert request_id2 in all_cancelled, "Second request should be in the set"
        assert len(all_cancelled) == 2, "Should have exactly 2 cancelled requests"

        # Modify the returned set and verify it doesn't affect the internal state
        all_cancelled.add("request_3")
        assert not service.is_cancelled("request_3"), "Modifying returned set should not affect internal state"

    def test_thread_safety_concurrent_requests(self):
        """Test that the service handles concurrent cancellation requests safely."""
        service = CancellationService()
        num_threads = 10
        requests_per_thread = 50
        threads = []

        def cancel_requests(thread_id):
            for i in range(requests_per_thread):
                request_id = f"thread_{thread_id}_request_{i}"
                service.request_cancellation(request_id)

        # Start multiple threads
        for i in range(num_threads):
            thread = threading.Thread(target=cancel_requests, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Verify all requests were registered
        all_cancelled = service.get_all_cancelled_requests()
        expected_count = num_threads * requests_per_thread
        assert len(all_cancelled) == expected_count, f"Should have {expected_count} cancelled requests"

    def test_thread_safety_concurrent_checks(self):
        """Test that the service handles concurrent is_cancelled checks safely."""
        service = CancellationService()
        request_id = "shared_request"
        service.request_cancellation(request_id)

        results = []

        def check_cancellation():
            for _ in range(100):
                results.append(service.is_cancelled(request_id))

        threads = [threading.Thread(target=check_cancellation) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # All checks should return True
        assert all(results), "All concurrent checks should return True"

    def test_thread_safety_concurrent_acknowledge(self):
        """Test that the service handles concurrent acknowledgements safely."""
        service = CancellationService()
        num_requests = 100

        # Cancel all requests
        for i in range(num_requests):
            service.request_cancellation(f"request_{i}")

        def acknowledge_requests():
            for i in range(num_requests):
                service.acknowledge_cancellation(f"request_{i}")

        # Start multiple threads trying to acknowledge the same requests
        threads = [threading.Thread(target=acknowledge_requests) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # All requests should be acknowledged (no duplicates or missed acknowledgements)
        all_cancelled = service.get_all_cancelled_requests()
        assert len(all_cancelled) == 0, "All requests should be acknowledged"

    def test_thread_safety_mixed_operations(self):
        """Test thread safety with mixed operations."""
        service = CancellationService()
        request_id = "mixed_ops_request"

        def operations():
            for i in range(50):
                service.request_cancellation(f"{request_id}_{i}")
                service.is_cancelled(f"{request_id}_{i}")
                if i % 2 == 0:
                    service.acknowledge_cancellation(f"{request_id}_{i}")

        threads = [threading.Thread(target=operations) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # Deterministic invariants: odd-indexed ids are cancelled by every thread
        # and never acknowledged, so they must all remain cancelled. Even-indexed
        # ids race between cancel and acknowledge across threads, so their final
        # state is unknown, but nothing outside the generated ids may appear.
        all_cancelled = service.get_all_cancelled_requests()
        all_ids = {f"{request_id}_{i}" for i in range(50)}
        odd_ids = {f"{request_id}_{i}" for i in range(50) if i % 2 == 1}
        assert odd_ids.issubset(all_cancelled), "Odd-indexed ids are never acknowledged and must stay cancelled"
        assert all_cancelled.issubset(all_ids), "No unexpected ids should appear in the cancelled set"

    def test_register_abort_callback(self):
        """Test that abort callbacks can be registered."""
        service = CancellationService()
        request_id = "abort_callback_test"
        callback_executed = []

        def abort_callback():
            callback_executed.append(True)

        service.register_abort_callback(request_id, abort_callback)
        service.request_cancellation(request_id)

        assert len(callback_executed) == 1, "Abort callback should be executed once"

    def test_register_multiple_abort_callbacks(self):
        """Test that multiple abort callbacks can be registered for the same request."""
        service = CancellationService()
        request_id = "multi_abort_test"
        callback_count = []

        def callback1():
            callback_count.append(1)

        def callback2():
            callback_count.append(2)

        service.register_abort_callback(request_id, callback1)
        service.register_abort_callback(request_id, callback2)
        service.request_cancellation(request_id)

        assert len(callback_count) == 2, "Both callbacks should be executed"
        assert 1 in callback_count and 2 in callback_count, "Both callbacks should have been called"

    def test_abort_callback_only_called_on_first_cancellation(self):
        """Test that abort callbacks are only called on the first cancellation request."""
        service = CancellationService()
        request_id = "single_abort_test"
        callback_count = []

        def abort_callback():
            callback_count.append(1)

        service.register_abort_callback(request_id, abort_callback)
        service.request_cancellation(request_id)
        service.request_cancellation(request_id)  # Second call should not trigger callback again

        assert len(callback_count) == 1, "Abort callback should only be executed once"

    def test_unregister_abort_callbacks(self):
        """Test that abort callbacks can be unregistered."""
        service = CancellationService()
        request_id = "unregister_test"
        callback_executed = []

        def abort_callback():
            callback_executed.append(True)

        service.register_abort_callback(request_id, abort_callback)
        service.unregister_abort_callbacks(request_id)
        service.request_cancellation(request_id)

        assert len(callback_executed) == 0, "Callback should not be executed after unregistering"

    def test_abort_callback_exception_handling(self):
        """Test that exceptions in abort callbacks are handled gracefully."""
        service = CancellationService()
        request_id = "exception_test"
        callback2_executed = []

        def failing_callback():
            raise RuntimeError("Test exception")

        def callback2():
            callback2_executed.append(True)

        service.register_abort_callback(request_id, failing_callback)
        service.register_abort_callback(request_id, callback2)

        # Should not raise an exception
        service.request_cancellation(request_id)

        assert len(callback2_executed) == 1, "Second callback should execute despite first one failing"

    def test_acknowledge_cancellation_clears_callbacks(self):
        """Test that acknowledging a cancellation clears the abort callbacks."""
        service = CancellationService()
        request_id = "clear_callbacks_test"

        def abort_callback():
            pass

        service.register_abort_callback(request_id, abort_callback)
        service.request_cancellation(request_id)
        service.acknowledge_cancellation(request_id)

        # Verify callbacks are cleared by checking internal state
        # (We can't directly test this without accessing private members, but we can verify behavior)
        # If we register a new callback and cancel again, only the new callback should be called
        callback_count = []

        def new_callback():
            callback_count.append(1)

        service.register_abort_callback(request_id, new_callback)
        service.request_cancellation(request_id)

        assert len(callback_count) == 1, "Only the new callback should be executed"

    def test_abort_callback_empty_request_id(self):
        """Test that registering abort callbacks with empty request IDs is handled gracefully."""
        service = CancellationService()

        def abort_callback():
            pass

        # Should not raise an exception
        service.register_abort_callback("", abort_callback)
        service.register_abort_callback(None, abort_callback)

    def test_register_abort_callback_after_cancellation_fires_immediately_once(self):
        """Test that registering a callback for an already-cancelled request invokes
        it synchronously exactly once, and it is not stored for later invocation."""
        service = CancellationService()
        request_id = "late_registration_test"
        callback_count = []

        def abort_callback():
            callback_count.append(1)

        service.request_cancellation(request_id)
        service.register_abort_callback(request_id, abort_callback)

        assert len(callback_count) == 1, "Callback should fire synchronously exactly once"

        # A repeat cancellation request is a no-op and must not re-fire the callback.
        service.request_cancellation(request_id)
        assert len(callback_count) == 1, "Callback should not fire again"

    def test_register_abort_callback_after_cancellation_exception_not_propagated(self):
        """Test that an exception from an immediately-invoked callback does not propagate."""
        service = CancellationService()
        request_id = "late_registration_exception_test"

        def failing_callback():
            raise RuntimeError("Test exception")

        service.request_cancellation(request_id)
        # Should not raise an exception
        service.register_abort_callback(request_id, failing_callback)

    def test_unregister_abort_callbacks_empty_request_id(self):
        """Test that unregistering with empty request IDs is handled gracefully."""
        service = CancellationService()

        # Should not raise an exception
        service.unregister_abort_callbacks("")
        service.unregister_abort_callbacks(None)

    def test_unregister_abort_callbacks_nonexistent_request_id(self):
        """Test that unregistering for an id with no registered callbacks is safe."""
        service = CancellationService()

        # Should not raise an exception
        service.unregister_abort_callbacks("never_registered")

    def test_request_cancellation_with_no_callbacks_registered(self):
        """Test that cancelling a request with no registered callbacks still marks it cancelled."""
        service = CancellationService()
        request_id = "no_callbacks_test"

        # Should not raise an exception
        service.request_cancellation(request_id)

        assert service.is_cancelled(request_id), "Request should be marked as cancelled"

    def test_thread_safety_abort_callbacks(self):
        """Test thread safety of abort callback registration and execution."""
        service = CancellationService()
        request_id = "thread_safe_abort"
        callback_count = []
        lock = threading.Lock()

        def abort_callback():
            with lock:
                callback_count.append(1)

        def register_callbacks():
            for _ in range(10):
                service.register_abort_callback(request_id, abort_callback)

        # Register callbacks from multiple threads
        threads = [threading.Thread(target=register_callbacks) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # Cancel the request
        service.request_cancellation(request_id)

        # All callbacks should have been executed
        assert len(callback_count) == 50, "All 50 callbacks should have been executed"


class TestCancellationTTLPruning:
    """Entries that are never acknowledged (bogus ids sent to the DELETE
    endpoints, requests that died without teardown) must be pruned after the
    TTL so the registry cannot grow without bound."""

    @staticmethod
    def _reset_singleton_state():
        service = CancellationService()
        for req_id in list(service.get_all_cancelled_requests()):
            service.acknowledge_cancellation(req_id)
        with service._set_lock:
            service._abort_callbacks.clear()

    def setup_method(self):
        self._reset_singleton_state()

    def teardown_method(self):
        self._reset_singleton_state()

    def test_stale_entry_pruned_on_next_cancellation(self):
        from Middleware.services.cancellation_service import CANCELLATION_TTL_SECONDS
        service = CancellationService()

        service.request_cancellation("stale-req")
        # Age the entry past the TTL directly; we cannot wait an hour.
        with service._set_lock:
            service._cancelled_requests["stale-req"] -= (CANCELLATION_TTL_SECONDS + 1)

        service.request_cancellation("fresh-req")

        assert not service.is_cancelled("stale-req"), "Stale entry should have been pruned"
        assert service.is_cancelled("fresh-req")

    def test_stale_entry_prune_also_clears_its_abort_callbacks(self):
        from Middleware.services.cancellation_service import CANCELLATION_TTL_SECONDS
        service = CancellationService()

        service.request_cancellation("stale-req")
        with service._set_lock:
            service._cancelled_requests["stale-req"] -= (CANCELLATION_TTL_SECONDS + 1)
            service._abort_callbacks["stale-req"] = [lambda: None]

        service.request_cancellation("fresh-req")

        with service._set_lock:
            assert "stale-req" not in service._abort_callbacks

    def test_fresh_entries_survive_pruning(self):
        service = CancellationService()

        service.request_cancellation("recent-req")
        service.request_cancellation("another-req")

        assert service.is_cancelled("recent-req")
        assert service.is_cancelled("another-req")
