from contextlib import suppress
from typing import get_origin

from django.core.exceptions import FieldDoesNotExist
from django.db.models.signals import class_prepared
from django.dispatch import receiver


def required_field(func):
    """
    Marks a method as a required class-level field for subclasses.
    Automatically wraps it as a @classmethod if it's not already.
    """
    if not isinstance(func, classmethod):
        func = classmethod(func)

    real_func = getattr(func, "__func__", func)
    real_func.is_required_field = True
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

            attr_descriptor = getattr(base.__class__, attr_name, None) or getattr(
                base,
                attr_name,
                None,
            )

            func = None
            if isinstance(attr_descriptor, property):
                func = attr_descriptor.fget
            elif isinstance(attr_descriptor, classmethod):
                func = attr_descriptor.__func__
            elif callable(attr_descriptor):
                func = attr_descriptor

            if func and getattr(func, "is_required_field", False):
                field_type = func.__annotations__.get("return", None)
                required_fields[attr_name] = field_type

    return required_fields


def _check_field_requirements(cls, required_fields):
    """Simplified checks for classmethod-based required fields."""
    missing = []
    type_errors = []

    for field_name, expected_type in required_fields.items():
        origin = get_origin(expected_type) or expected_type

        with suppress(FieldDoesNotExist, AttributeError):
            field = cls._meta.get_field(field_name)
            if not isinstance(field, origin):
                msg = (
                    f"{field_name} must be an instance of {origin.__name__}, "
                    f"got {type(field).__name__}"
                )
                type_errors.append(msg)
            continue

        attr = getattr(cls, field_name, None)
        if attr is None:
            missing.append(field_name)
            continue

        # Check if still using the unimplemented @required_field
        origin_func = getattr(attr, "__func__", attr)
        if getattr(origin_func, "is_required_field", False):
            missing.append(field_name)
            continue

        if isinstance(attr, type):
            if not issubclass(attr, origin):
                msg = (
                    f"{field_name} must be a subclass of {origin.__name__}, "
                    f"got {attr.__name__}"
                )
                type_errors.append(msg)
        elif not isinstance(attr, origin):
            msg = (
                f"{field_name} must be an instance of {origin.__name__}, "
                f"got {type(attr).__name__}"
            )
            type_errors.append(msg)

    return missing, type_errors


def _raise_validation_errors(cls, missing, type_errors):
    """Raises exceptions if missing fields or type errors."""
    if missing:
        error_message = (
            f"{cls.__name__} must define class attributes: {', '.join(missing)}",
        )
        raise NotImplementedError(error_message)

    if type_errors:
        error_message = f"{cls.__name__} has type errors: {'; '.join(type_errors)}"
        raise TypeError(error_message)


# Allows django fields to be validated as well.
@receiver(class_prepared)
def validate_model(sender, **kwargs):
    """Runs after a model class is fully constructed."""
    if getattr(sender, "requires_child_fields_validation", False):
        _validate_required_fields_for_subclass(sender)
