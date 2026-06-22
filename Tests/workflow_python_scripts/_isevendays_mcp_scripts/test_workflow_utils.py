# Tests/workflow_python_scripts/_isevendays_mcp_scripts/test_workflow_utils.py

from Public.workflow_python_scripts._isevendays_mcp_scripts.workflow_utils import aggregate_generator_input


def test_aggregate_generator_input_joins_generator_chunks():
    """
    Tests that a generator of string chunks is consumed and joined
    into a single aggregated string.
    """
    # Arrange: Create a generator yielding string chunks.
    def chunk_generator():
        yield "Hello"
        yield ", "
        yield "world"

    # Act: Aggregate the generator.
    result = aggregate_generator_input(chunk_generator())

    # Assert: The chunks are joined in order.
    assert result == "Hello, world"


def test_aggregate_generator_input_coerces_non_string_chunks():
    """
    Tests that non-string elements yielded by a generator are coerced
    to strings during aggregation.
    """
    # Arrange: Generator yielding mixed types.
    def mixed_generator():
        yield 1
        yield "-"
        yield 2

    # Act
    result = aggregate_generator_input(mixed_generator())

    # Assert
    assert result == "1-2"


def test_aggregate_generator_input_passes_through_strings():
    """
    Tests that a plain string input is returned unchanged.
    """
    assert aggregate_generator_input("already a string") == "already a string"


def test_aggregate_generator_input_passes_through_non_generator_types():
    """
    Tests that non-generator, non-string inputs are returned as-is.
    """
    assert aggregate_generator_input(None) is None
    assert aggregate_generator_input(42) == 42
    assert aggregate_generator_input(["a", "b"]) == ["a", "b"]


def test_aggregate_generator_input_returns_error_string_on_failure():
    """
    Tests that an error raised while consuming the generator results in
    an error string rather than an exception propagating.
    """
    # Arrange: Generator that raises mid-stream.
    def failing_generator():
        yield "ok"
        raise ValueError("boom")

    # Act
    result = aggregate_generator_input(failing_generator())

    # Assert: An error indicator string is returned instead of raising.
    assert result.startswith("[Error aggregating stream:")
    assert "boom" in result
