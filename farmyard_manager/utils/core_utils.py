def coalesce(*args):
    """
    Returns the first non-None value from the provided arguments.
    If all arguments are None, returns None.

    Similar to SQL's COALESCE function.

    Example:
        coalesce(None, 0, 10) # returns 0
        coalesce(None, None, 'hello', 'world') # returns 'hello'
        coalesce(None, None, None) # returns None
    """
    for arg in args:
        if arg is not None:
            return arg
    return None
