import re

import inflect

_inflector = inflect.engine()


def to_snake_case(
    string: str,
    *,
    prefix: str = "",
    suffix: str = "",
    pluralize: bool = False,
) -> str:
    prefix = "" if prefix is None else prefix
    suffix = "" if suffix is None else suffix
    pluralize = False if pluralize is None else pluralize

    # Add underscore before uppercase letters (except the first one)
    snake_case_string = re.sub(r"(?<!^)(?=[A-Z])", "_", string.strip()).lower()

    # Replace special characters and spaces with underscores
    snake_case_string = re.sub(r"[^a-zA-Z0-9]+", "_", snake_case_string)

    snake_case = (
        f"{prefix}_{snake_case_string}_{suffix}"
        if prefix != "" and suffix != ""
        else f"{prefix}_{snake_case_string}"
        if prefix != "" and suffix == ""
        else f"{snake_case_string}_{suffix}"
        if suffix != "" and prefix == ""
        else snake_case_string
    )

    if pluralize:
        return _inflector.plural(snake_case)

    return snake_case
