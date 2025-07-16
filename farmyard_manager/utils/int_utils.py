def is_int(value):
    """
    Check if the given value can be converted to int

    Args:
        value: The value to check.

    Returns:
        bool: True if the value can convert
    """
    try:
        int(value)
    except (TypeError, ValueError):
        return False
    else:
        return True
