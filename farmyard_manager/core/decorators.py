def required_field(field):
    """
    Decorator to mark a field as required.
    The type will be determined from type annotations.

    Usage:
        @required_field
        item_model: BaseItem
    """
    field.is_required_field = True  # Using a public attribute instead of _private
    return field


def requires_fields(cls):
    """
    Class decorator that validates required fields in subclasses.

    Usage:
        @validate_required_fields
        class BaseModel(models.Model):
            @required_field
            item_model: BaseItem
    """

    def new_init_subclass(subclass, **kwargs):
        # Safely call the original __init_subclass__, if it exists
        super(cls, cls).__init_subclass__(**kwargs)

        # Skip validation for abstract models
        if hasattr(subclass, "Meta") and getattr(subclass.Meta, "abstract", False):
            return

        # Breaking up complexity into smaller functions
        _validate_required_fields_for_subclass(subclass)

    # Replace the __init_subclass__ method
    cls.__init_subclass__ = new_init_subclass
    return cls


def _validate_required_fields_for_subclass(subclass):
    """Handles the validation of required fields for a subclass."""
    # Collect required fields from annotations and decorators
    required_fields = _collect_required_fields(subclass)

    # Skip if no requirements
    if not required_fields:
        return

    # Validate fields
    missing, type_errors = _check_field_requirements(subclass, required_fields)

    # Raise appropriate errors
    _raise_validation_errors(subclass, missing, type_errors)


def _collect_required_fields(cls):
    """Collects required fields and their expected types from a class."""
    required_fields = {}

    # Check class attributes for the marker
    for attr_name, attr_value in cls.__dict__.items():
        if hasattr(attr_value, "is_required_field"):
            # Get type from annotations
            field_type = None
            if hasattr(cls, "__annotations__"):
                field_type = cls.__annotations__.get(attr_name)
            required_fields[attr_name] = field_type

    return required_fields


def _check_field_requirements(cls, required_fields):
    """Checks for missing fields and type errors."""
    missing = []
    type_errors = []

    for field_name, expected_type in required_fields.items():
        # Check if field exists
        if not hasattr(cls, field_name):
            missing.append(field_name)
            continue

        # Check field type
        field_value = getattr(cls, field_name)
        if field_value is not None and isinstance(expected_type, type):
            if not issubclass(field_value, expected_type):
                type_errors.append(
                    f"{field_name} must be a subclass of {expected_type.__name__}, "
                    f"got {field_value.__name__}",
                )

    return missing, type_errors


def _raise_validation_errors(cls, missing, type_errors):
    """Raises appropriate exceptions for validation errors."""
    if missing:
        error_message = (
            f"{cls.__name__} must define class attributes: {', '.join(missing)}"
        )
        raise NotImplementedError(error_message)

    if type_errors:
        error_message = f"{cls.__name__} has type errors: {'; '.join(type_errors)}"
        raise TypeError(error_message)
