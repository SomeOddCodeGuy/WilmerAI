import threading
import uuid

import pytest

from Middleware.common import instance_global_variables

# NOTE: The old TestUsersGlobal class was removed. It only asserted that a
# module-level attribute holds whatever value was just assigned to it, which is
# a Python language guarantee rather than project behavior. The USERS global's
# actual behavior (single- vs multi-user routing and request rejection) is
# covered in Tests/api/test_api_helpers.py (TestMultiUserModelParsing and
# TestRequireIdentifiedUser).


class TestRequestUser:
    """Tests for per-request user get/set/clear functions."""

    def test_get_request_user_default(self):
        """Returns None when no request user has been set."""
        instance_global_variables.clear_request_user()
        assert instance_global_variables.get_request_user() is None

    def test_set_and_get_request_user(self):
        """set_request_user stores a value retrievable by get_request_user."""
        instance_global_variables.set_request_user('user-one')
        try:
            assert instance_global_variables.get_request_user() == 'user-one'
        finally:
            instance_global_variables.clear_request_user()

    def test_clear_request_user(self):
        """clear_request_user resets the value to None."""
        instance_global_variables.set_request_user('user-one')
        instance_global_variables.clear_request_user()
        assert instance_global_variables.get_request_user() is None

    def test_request_user_independent_of_workflow_override(self):
        """Request user and workflow override are independent."""
        instance_global_variables.set_request_user('user-one')
        instance_global_variables.set_workflow_override('my-workflow')
        try:
            assert instance_global_variables.get_request_user() == 'user-one'
            assert instance_global_variables.get_workflow_override() == 'my-workflow'

            instance_global_variables.clear_request_user()
            assert instance_global_variables.get_request_user() is None
            assert instance_global_variables.get_workflow_override() == 'my-workflow'
        finally:
            instance_global_variables.clear_request_user()
            instance_global_variables.clear_workflow_override()


class TestThreadIsolation:
    """Tests that request-scoped state is thread-local (the module's core design claim)."""

    def test_request_state_is_not_visible_to_other_threads(self):
        """Values set on the main thread must not leak into a spawned thread."""
        instance_global_variables.set_request_user('main-user')
        instance_global_variables.set_workflow_override('main-workflow')

        child_seen = {}

        def child():
            child_seen['request_user'] = instance_global_variables.get_request_user()
            child_seen['workflow_override'] = instance_global_variables.get_workflow_override()
            # A write on the child thread must not clobber the main thread's value.
            instance_global_variables.set_request_user('child-user')

        try:
            worker = threading.Thread(target=child)
            worker.start()
            worker.join()

            assert child_seen['request_user'] is None
            assert child_seen['workflow_override'] is None
            assert instance_global_variables.get_request_user() == 'main-user'
            assert instance_global_variables.get_workflow_override() == 'main-workflow'
        finally:
            instance_global_variables.clear_request_user()
            instance_global_variables.clear_workflow_override()


class TestApiType:
    """Tests for per-request API type get/set/clear functions."""

    @pytest.fixture(autouse=True)
    def reset_api_type(self):
        yield
        instance_global_variables.clear_api_type()

    def test_get_api_type_defaults_to_openai(self):
        """A thread that never set an API type sees the 'openai' default even
        while another thread has a non-default value set (request scoping)."""
        instance_global_variables.set_api_type('ollamagenerate')
        seen = {}

        def child():
            seen['api_type'] = instance_global_variables.get_api_type()

        worker = threading.Thread(target=child)
        worker.start()
        worker.join()

        assert seen['api_type'] == 'openai'
        # The main thread's value is untouched by the child's read.
        assert instance_global_variables.get_api_type() == 'ollamagenerate'

    def test_set_and_get_api_type(self):
        """set_api_type stores a value retrievable by get_api_type."""
        instance_global_variables.set_api_type('ollamaapichat')
        assert instance_global_variables.get_api_type() == 'ollamaapichat'

    def test_clear_api_type_resets_to_default(self):
        """clear_api_type resets the value to the 'openai' default."""
        instance_global_variables.set_api_type('ollamagenerate')
        instance_global_variables.clear_api_type()
        assert instance_global_variables.get_api_type() == 'openai'


class TestWorkflowOverride:
    """Tests for per-request workflow override get/set/clear functions."""

    def test_clear_workflow_override_resets_to_none(self):
        """clear_workflow_override actually clears the stored value (the
        independence test above only asserts the value persists)."""
        instance_global_variables.set_workflow_override('my-workflow')
        instance_global_variables.clear_workflow_override()
        assert instance_global_variables.get_workflow_override() is None

    def test_get_workflow_override_default(self):
        """Returns None when no override has ever been set on this thread."""
        seen = {}

        def child():
            seen['override'] = instance_global_variables.get_workflow_override()

        worker = threading.Thread(target=child)
        worker.start()
        worker.join()

        assert seen['override'] is None


class TestInstanceId:
    """Tests for the process-lifetime instance identity."""

    def test_instance_id_is_a_valid_uuid_string(self):
        """INSTANCE_ID must be a parseable UUID string. LockingService uses it
        to distinguish this process's locks from stale ones during startup
        cleanup; an empty or constant value would break that identity."""
        assert isinstance(instance_global_variables.INSTANCE_ID, str)
        assert uuid.UUID(instance_global_variables.INSTANCE_ID)


class TestRequestSemaphore:
    """Tests for the startup concurrency semaphore initialization."""

    @pytest.fixture(autouse=True)
    def reset_semaphore(self):
        """Save and restore the process-wide semaphore around each test."""
        original = instance_global_variables._request_semaphore
        instance_global_variables._request_semaphore = None
        yield
        instance_global_variables._request_semaphore = original

    def test_zero_leaves_semaphore_disabled(self):
        """initialize_request_semaphore(0) leaves concurrency limiting off."""
        instance_global_variables.initialize_request_semaphore(0)
        assert instance_global_variables.get_request_semaphore() is None

    def test_positive_creates_bounded_semaphore(self):
        """initialize_request_semaphore(n > 0) creates a BoundedSemaphore of size n."""
        instance_global_variables.initialize_request_semaphore(2)
        semaphore = instance_global_variables.get_request_semaphore()

        assert isinstance(semaphore, threading.BoundedSemaphore)
        # Exactly two slots are available.
        assert semaphore.acquire(blocking=False) is True
        assert semaphore.acquire(blocking=False) is True
        assert semaphore.acquire(blocking=False) is False
        semaphore.release()
        semaphore.release()
