import types
import logging

logger = logging.getLogger(__name__)

def aggregate_generator_input(input_arg):
    """
    Aggregates input if it's a generator type.

    This is a workaround for the WorkflowManager's current limitation where
    it doesn't automatically aggregate generator outputs from intermediate
    workflow steps when the overall workflow stream=True. Modules receiving
    output from such steps need to call this function on their input.

    Args:
        input_arg: The input argument, which might be a string or a generator.

    Returns:
        str: The aggregated string content. Returns the input directly if not a generator,
             or an error string if aggregation fails.
    """
    if isinstance(input_arg, types.GeneratorType):
        logger.debug("Input is a generator, aggregating stream...")
        try:
            # Consume generator and join elements (assuming they are strings)
            aggregated_string = "".join(map(str, list(input_arg)))
            logger.debug("Aggregation complete.")
            return aggregated_string
        except Exception as e:
            logger.error(f"Error aggregating generator stream: {e}", exc_info=True)
            # Return an error string to indicate failure
            return f"[Error aggregating stream: {e}]"
    # If not a generator, assume it's already a string or compatible type
    logger.debug(f"Input type {type(input_arg)} is not a generator, returning as is.")
    return input_arg 