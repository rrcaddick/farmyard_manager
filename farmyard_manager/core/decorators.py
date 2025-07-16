from typing import TYPE_CHECKING
from typing import get_origin

from django.core.exceptions import FieldDoesNotExist
from django.db.models import Field
from django.db.models.signals import class_prepared
from django.dispatch import receiver

if TYPE_CHECKING:
    # Allows the decorator to be used without having to add @property decorator as well.
    # Requires a dummy setter if asigning in the base class to avoid mypy errors.
    required_field = property

else:

    def required_field(func):
        """
        Marks a method as a required class-level field for subclasses.
        Always wraps as a @property for proper type checking with Django and mypy.
        """
        # Mark the function as required
        func.is_required_field = True

        # Always wrap as property
        if not isinstance(func, property):
            func = property(func)

        # Preserve the marking on the property
        func.fget.is_required_field = True

        return func


def requires_child_fields(baseclass):
    """Marks a class to require field validation later."""

    def new_init_subclass(subclass, **kwargs):
        super(baseclass, subclass).__init_subclass__(**kwargs)

        if hasattr(subclass, "Meta") and getattr(subclass.Meta, "abstract", False):
            return

        subclass.requires_child_fields_validation = True

    baseclass.__init_subclass__ = classmethod(new_init_subclass)
    return baseclass


def _validate_required_fields_for_subclass(subclass):
    """Validates that required fields are properly implemented."""
    required_fields = _collect_required_fields(subclass)

    if not required_fields:
        return

    missing, type_errors = _check_field_requirements(subclass, required_fields)

    _raise_validation_errors(subclass, missing, type_errors)


def _collect_required_fields(cls):
    """Collects all required fields from parent classes."""
    required_fields = {}

    for base in cls.__mro__[1:]:
        for attr_name in dir(base):
            if attr_name.startswith("__"):
                continue

            attr_descriptor = getattr(base, attr_name, None)

            if isinstance(attr_descriptor, property) and hasattr(
                attr_descriptor.fget,
                "is_required_field",
            ):
                if attr_descriptor.fget.is_required_field:  # type: ignore[union-attr]
                    field_type = attr_descriptor.fget.__annotations__.get(
                        "return",
                        None,
                    )
                    required_fields[attr_name] = field_type

    return required_fields


def _check_field_requirements(cls, required_fields):  # noqa: C901
    """Checks for both Django model fields and regular attributes."""
    missing = []
    type_errors = []

    for field_name, expected_type in required_fields.items():
        if expected_type is None:
            continue

        origin = get_origin(expected_type) or expected_type

        # Handle Type[X] annotations
        if origin is type or origin is type:
            # Extract the actual type from Type[X]
            origin = getattr(expected_type, "__args__", (object,))[0]

        # First check if it's a Django model field
        try:
            field = cls._meta.get_field(field_name)
            # For Django fields, check if it's the right field type
            if hasattr(origin, "__mro__") and issubclass(origin, Field):
                if not isinstance(field, origin):
                    msg = (
                        f"{field_name} must be an instance of {origin.__name__}, "
                        f"got {type(field).__name__}"
                    )
                    type_errors.append(msg)
            # Field exists, validation passed
            continue
        except (FieldDoesNotExist, AttributeError):
            # Not a Django field, check as regular attribute
            pass

        # Check as regular class attribute
        attr = getattr(cls, field_name, None)
        if attr is None:
            missing.append(field_name)
            continue

        # Check if still using the unimplemented @required_field property
        if isinstance(attr, property):
            if hasattr(attr.fget, "is_required_field") and attr.fget.is_required_field:  # type: ignore[union-attr]
                # Still using the abstract property, not implemented
                missing.append(field_name)
                continue

        # Type checking for non-Django fields
        # Check if it's a class type that should be subclass
        if isinstance(origin, type) and isinstance(attr, type):
            if not issubclass(attr, origin):
                msg = (
                    f"{field_name} must be a subclass of {origin.__name__}, "
                    f"got {attr.__name__}"
                )
                type_errors.append(msg)
        # Check instance types
        elif isinstance(origin, type) and not isinstance(attr, origin):
            msg = (
                f"{field_name} must be an instance of {origin.__name__}, "
                f"got {type(attr).__name__} (value: {attr!r})"
            )
            type_errors.append(msg)

    return missing, type_errors


def _raise_validation_errors(cls, missing, type_errors):
    """Raises exceptions if missing fields or type errors."""
    if missing:
        error_message = (
            f"{cls.__name__} must define class attributes: {', '.join(missing)}"
        )
        raise NotImplementedError(error_message)

    if type_errors:
        error_message = f"{cls.__name__} has type errors: {'; '.join(type_errors)}"
        raise TypeError(error_message)


# Allows django fields to be validated as well.
@receiver(class_prepared)
def validate_model(sender, **kwargs):  # noqa: ARG001
    """Runs after a model class is fully constructed."""
    if getattr(sender, "requires_child_fields_validation", False):
        _validate_required_fields_for_subclass(sender)
