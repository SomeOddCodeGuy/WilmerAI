# tests/services/test_idempotency_service.py

import time

import pytest

from Middleware.services import idempotency_service as idem_module
from Middleware.services.idempotency_service import IdempotencyService, idempotency_service


class TestIdempotencyService:
    """Test suite for the IdempotencyService class."""

    def setup_method(self):
        """Reset the process-wide singleton before each test."""
        idempotency_service.clear()

    def teardown_method(self):
        """Ensure no entries leak from the singleton after each test."""
        idempotency_service.clear()

    def test_singleton_pattern(self):
        """Two constructions return the same instance."""
        assert IdempotencyService() is IdempotencyService()

    def test_global_instance(self):
        """The module-level instance is the singleton."""
        assert idempotency_service is IdempotencyService()

    def test_register_new_key_returns_none(self):
        """A previously unseen key displaces nothing."""
        assert idempotency_service.register("key-a", "req-1") is None
        assert idempotency_service.get_request_id_for_key("key-a") == "req-1"

    def test_get_request_id_for_unknown_or_empty_key(self):
        """Looking up an unknown or falsy key yields None."""
        assert idempotency_service.get_request_id_for_key("nope") is None
        assert idempotency_service.get_request_id_for_key("") is None
        assert idempotency_service.get_request_id_for_key(None) is None

    def test_register_duplicate_key_displaces_original(self):
        """A second registration of the same key returns the original request_id
        and rebinds the key to the new request."""
        assert idempotency_service.register("key-a", "req-1") is None
        displaced = idempotency_service.register("key-a", "req-2")
        assert displaced == "req-1"
        assert idempotency_service.get_request_id_for_key("key-a") == "req-2"

    def test_register_same_request_id_twice_is_noop(self):
        """Re-registering the identical (key, request_id) never displaces itself."""
        assert idempotency_service.register("key-a", "req-1") is None
        assert idempotency_service.register("key-a", "req-1") is None
        assert idempotency_service.get_request_id_for_key("key-a") == "req-1"

    def test_register_ignores_falsy_inputs(self):
        """Empty key or request_id is ignored so callers can pass through blindly."""
        assert idempotency_service.register("", "req-1") is None
        assert idempotency_service.register(None, "req-1") is None
        assert idempotency_service.register("key-a", "") is None
        assert idempotency_service.register("key-a", None) is None
        assert idempotency_service.get_request_id_for_key("key-a") is None

    def test_release_clears_binding(self):
        """Releasing a request removes its key binding."""
        idempotency_service.register("key-a", "req-1")
        idempotency_service.release("req-1")
        assert idempotency_service.get_request_id_for_key("key-a") is None

    def test_release_unknown_request_is_noop(self):
        """Releasing a never-registered request does nothing and does not raise."""
        idempotency_service.release("never-seen")
        idempotency_service.release("")
        idempotency_service.release(None)

    def test_release_is_idempotent(self):
        """Releasing the same request twice is safe."""
        idempotency_service.register("key-a", "req-1")
        idempotency_service.release("req-1")
        idempotency_service.release("req-1")
        assert idempotency_service.get_request_id_for_key("key-a") is None

    def test_displaced_original_release_preserves_new_binding(self):
        """The core guarded-release invariant: when a displaced original tears
        down after the key was rebound, it must NOT remove the live binding."""
        idempotency_service.register("key-a", "req-1")
        idempotency_service.register("key-a", "req-2")  # displaces req-1

        # req-1 (the orphan) finishes its teardown late.
        idempotency_service.release("req-1")

        # The live binding to req-2 must survive.
        assert idempotency_service.get_request_id_for_key("key-a") == "req-2"

        # And req-2 can still release itself cleanly.
        idempotency_service.release("req-2")
        assert idempotency_service.get_request_id_for_key("key-a") is None

    def test_distinct_keys_are_independent(self):
        """Different keys track different requests without interference."""
        idempotency_service.register("key-a", "req-1")
        idempotency_service.register("key-b", "req-2")
        assert idempotency_service.get_request_id_for_key("key-a") == "req-1"
        assert idempotency_service.get_request_id_for_key("key-b") == "req-2"
        idempotency_service.release("req-1")
        assert idempotency_service.get_request_id_for_key("key-a") is None
        assert idempotency_service.get_request_id_for_key("key-b") == "req-2"

    def test_completed_key_registers_fresh(self):
        """After a key completes (released), the same key registers fresh with
        no displacement; this mirrors the chat-ui 'recently completed' case."""
        idempotency_service.register("key-a", "req-1")
        idempotency_service.release("req-1")
        assert idempotency_service.register("key-a", "req-2") is None
        assert idempotency_service.get_request_id_for_key("key-a") == "req-2"

    def test_size_cap_evicts_oldest(self, monkeypatch):
        """Exceeding the cap evicts the least-recently-registered entry."""
        monkeypatch.setattr(idem_module, "MAX_IN_FLIGHT_KEYS", 3)
        for i in range(3):
            idempotency_service.register(f"key-{i}", f"req-{i}")
        # All three present.
        assert idempotency_service.get_request_id_for_key("key-0") == "req-0"

        # One more over the cap evicts the oldest (key-0).
        idempotency_service.register("key-3", "req-3")
        assert idempotency_service.get_request_id_for_key("key-0") is None
        assert idempotency_service.get_request_id_for_key("key-3") == "req-3"

    def test_register_refreshes_lru_position(self, monkeypatch):
        """Re-registering a key moves it to the most-recent position, so it is
        not the next one evicted."""
        monkeypatch.setattr(idem_module, "MAX_IN_FLIGHT_KEYS", 3)
        idempotency_service.register("key-0", "req-0")
        idempotency_service.register("key-1", "req-1")
        idempotency_service.register("key-2", "req-2")

        # Touch key-0 by rebinding it; it becomes most-recent.
        idempotency_service.register("key-0", "req-0b")

        # Adding a 4th evicts key-1 (now oldest), not key-0.
        idempotency_service.register("key-3", "req-3")
        assert idempotency_service.get_request_id_for_key("key-1") is None
        assert idempotency_service.get_request_id_for_key("key-0") == "req-0b"

    def test_ttl_prunes_leaked_entries(self, monkeypatch):
        """An entry whose release never fired is pruned once it ages past the
        TTL; pruning happens lazily on the next register()."""
        monkeypatch.setattr(idem_module, "IN_FLIGHT_TTL_SECONDS", 0)
        idempotency_service.register("key-a", "req-1")
        # With a zero TTL the entry is already stale; the next register prunes it.
        time.sleep(0.01)
        idempotency_service.register("key-b", "req-2")
        assert idempotency_service.get_request_id_for_key("key-a") is None
        assert idempotency_service.get_request_id_for_key("key-b") == "req-2"

    def test_ttl_pruned_key_reregisters_without_displacement(self, monkeypatch):
        """A key whose stale entry aged out re-registers with NO displacement:
        the long-dead original must not be reported for (spurious) cancellation."""
        monkeypatch.setattr(idem_module, "IN_FLIGHT_TTL_SECONDS", 0)
        idempotency_service.register("key-a", "req-1")
        time.sleep(0.01)

        # The same logical request retries long after the orphan aged out.
        assert idempotency_service.register("key-a", "req-2") is None
        assert idempotency_service.get_request_id_for_key("key-a") == "req-2"

    def test_thread_safety_register_release_storm(self):
        """Concurrent register/lookup/release across threads must stay consistent
        (each thread always sees its own binding) and leave the registry empty.
        Guards the _set_lock coverage of every mutation path."""
        import threading

        errors = []

        def worker(thread_id):
            try:
                for i in range(100):
                    key = f"k-{thread_id}-{i}"
                    request_id = f"r-{thread_id}-{i}"
                    assert idempotency_service.register(key, request_id) is None
                    assert idempotency_service.get_request_id_for_key(key) == request_id
                    idempotency_service.release(request_id)
                    assert idempotency_service.get_request_id_for_key(key) is None
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert not errors
        with idempotency_service._set_lock:
            assert idempotency_service._in_flight == {}
            assert idempotency_service._by_request_id == {}

    def test_thread_safety_contended_same_key(self):
        """Concurrent registers of the SAME key (the core displacement race)
        must resolve to exactly one surviving binding, with every other request
        id reported as displaced exactly once (the displacement chain must not
        drop or duplicate an id, or a duplicate's orphan would never be
        cancelled)."""
        import threading

        displaced_results = []
        errors = []
        barrier = threading.Barrier(8)

        def worker(thread_id):
            try:
                barrier.wait()
                displaced = idempotency_service.register("key-hot", f"r-{thread_id}")
                displaced_results.append(displaced)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert not errors
        all_ids = {f"r-{t}" for t in range(8)}
        survivor = idempotency_service.get_request_id_for_key("key-hot")
        assert survivor in all_ids
        displaced = [d for d in displaced_results if d is not None]
        assert sorted(displaced) == sorted(all_ids - {survivor})
        with idempotency_service._set_lock:
            assert idempotency_service._by_request_id == {survivor: "key-hot"}

    def test_eviction_cleans_reverse_map_and_release_is_noop(self, monkeypatch):
        """LRU eviction must drop the evicted request's reverse entry (else the
        reverse map leaks), and the evicted request's own late release must be a
        clean no-op that does not disturb the surviving bindings."""
        monkeypatch.setattr(idem_module, "MAX_IN_FLIGHT_KEYS", 2)
        idempotency_service.register("key-0", "req-0")
        idempotency_service.register("key-1", "req-1")
        idempotency_service.register("key-2", "req-2")  # evicts key-0

        with idempotency_service._set_lock:
            assert "req-0" not in idempotency_service._by_request_id

        # The evicted original's teardown eventually fires; it must be a no-op.
        idempotency_service.release("req-0")
        assert idempotency_service.get_request_id_for_key("key-1") == "req-1"
        assert idempotency_service.get_request_id_for_key("key-2") == "req-2"
