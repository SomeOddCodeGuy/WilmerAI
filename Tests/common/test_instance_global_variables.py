from Middleware.common import instance_global_variables


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


class TestUsersGlobal:
    """Tests for the USERS global list."""

    def test_users_default_none(self):
        """USERS defaults to None."""
        original = instance_global_variables.USERS
        try:
            instance_global_variables.USERS = None
            assert instance_global_variables.USERS is None
        finally:
            instance_global_variables.USERS = original

    def test_users_set_list(self):
        """USERS can be set to a list of usernames."""
        original = instance_global_variables.USERS
        try:
            instance_global_variables.USERS = ['user-one', 'user-two']
            assert instance_global_variables.USERS == ['user-one', 'user-two']
        finally:
            instance_global_variables.USERS = original
