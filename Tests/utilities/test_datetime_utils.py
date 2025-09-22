# Tests/utilities/test_datetime_utils.py

from datetime import datetime, timedelta

import pytest

# Import the functions to be tested (including new/updated ones)
from Middleware.utilities.datetime_utils import (
    _calculate_relative_time,
    format_relative_time_string,
    current_timestamp,
    add_seconds_to_timestamp,
    subtract_minutes_from_timestamp,
    format_relative_time_ago,
    parse_timestamp_string,
    format_datetime_to_ts
)

# A fixed point in time to make tests predictable
MOCK_NOW = datetime(2025, 9, 20, 18, 31, 21)


@pytest.fixture
def mock_datetime_now(mocker):
    """Fixture to mock datetime.now() to a fixed value."""

    # A robust way to mock datetime.now() while keeping others intact:
    class MockDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return MOCK_NOW

    # Ensure strptime/strftime are available on the mock class
    MockDateTime.strptime = datetime.strptime
    mocker.patch('Middleware.utilities.datetime_utils.datetime', MockDateTime)
    return MockDateTime


# New Tests for helper functions
def test_parse_timestamp_string_valid():
    """Tests the internal parsing helper."""
    ts_str = "(Saturday, 2025-09-20 18:31:21)"
    dt_obj = datetime(2025, 9, 20, 18, 31, 21)
    assert parse_timestamp_string(ts_str) == dt_obj


@pytest.mark.parametrize("invalid_input", [
    None,
    "",
    12345,
    "Not a timestamp",
    "(2025-09-20 18:31:21)",  # Missing day
])
def test_parse_timestamp_string_invalid(invalid_input):
    assert parse_timestamp_string(invalid_input) is None


def test_parse_timestamp_strips_padding():
    """Ensures parsing works regardless of surrounding parentheses or spaces."""
    ts_str_padded = " (Saturday, 2025-09-20 18:31:21) "
    ts_str_no_paren = "Saturday, 2025-09-20 18:31:21"
    dt_obj = datetime(2025, 9, 20, 18, 31, 21)
    assert parse_timestamp_string(ts_str_padded) == dt_obj
    assert parse_timestamp_string(ts_str_no_paren) == dt_obj


def test_format_datetime_to_ts():
    """Tests the centralized formatter."""
    dt_obj = datetime(2025, 9, 20, 18, 31, 21)
    expected_str = "(Saturday, 2025-09-20 18:31:21)"
    assert format_datetime_to_ts(dt_obj) == expected_str


def test_calculate_relative_time_internal(mock_datetime_now):
    base_time = MOCK_NOW - timedelta(days=2, hours=3, minutes=15)
    days, hours, minutes = _calculate_relative_time(base_time)

    assert days == 2
    assert hours == 3
    assert minutes == 15


@pytest.mark.parametrize("time_delta, expected_string", [
    (timedelta(seconds=30), "less than a minute"),
    (timedelta(minutes=1), "1 minute"),
    (timedelta(minutes=45), "45 minutes"),
    (timedelta(hours=1, minutes=1), "1 hour, 1 minute"),
    (timedelta(days=3, hours=8, minutes=30), "3 days, 8 hours, 30 minutes"),
])
def test_format_relative_time_string(mock_datetime_now, time_delta, expected_string):
    base_time = MOCK_NOW - time_delta
    result = format_relative_time_string(base_time)
    assert result == expected_string


def test_current_timestamp(mock_datetime_now):
    expected_timestamp = "(Saturday, 2025-09-20 18:31:21)"
    assert current_timestamp() == expected_timestamp


def test_add_seconds_to_timestamp():
    initial_ts = "(Saturday, 2025-09-20 18:31:21)"
    expected_ts = "(Saturday, 2025-09-20 18:32:20)"
    result = add_seconds_to_timestamp(initial_ts, 59)
    assert result == expected_ts


def test_add_seconds_to_timestamp_negative():
    """Tests subtracting seconds."""
    initial_ts = "(Saturday, 2025-09-20 18:31:21)"
    expected_ts = "(Saturday, 2025-09-20 18:31:20)"
    result = add_seconds_to_timestamp(initial_ts, -1)
    assert result == expected_ts


def test_add_seconds_to_timestamp_invalid():
    """Tests that invalid input returns the original string."""
    initial_ts = "Invalid"
    result = add_seconds_to_timestamp(initial_ts, 10)
    assert result == initial_ts


def test_subtract_minutes_from_timestamp(mock_datetime_now):
    expected_ts = "(Saturday, 2025-09-20 18:16:21)"
    result = subtract_minutes_from_timestamp(minutes=15)
    assert result == expected_ts


@pytest.mark.parametrize("input_timestamp, expected_output", [
    (
            "(Saturday, 2025-09-20 16:31:21)",
            "[Sent 2 hours ago]"
    ),
    (
            "(Saturday, 2025-09-20 18:30:51)",
            "[Sent less than a minute ago]"
    ),
])
def test_format_relative_time_ago_valid_inputs(mock_datetime_now, input_timestamp, expected_output):
    result = format_relative_time_ago(input_timestamp)
    assert result == expected_output


@pytest.mark.parametrize("invalid_input", [
    "", None, "Not a timestamp",
])
def test_format_relative_time_ago_invalid_inputs(invalid_input):
    result = format_relative_time_ago(invalid_input)
    assert result == ""
