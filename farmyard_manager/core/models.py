import uuid
import uuid as uuid_lib

from django.db import IntegrityError
from django.db import models
from django.utils import timezone
from django_extensions.db.models import TimeStampedModel

from farmyard_manager.utils.uuid_utils import get_unique_ref


class BaseModelMixin(models.Model):
    class Meta:
        abstract = True

    def is_new(self):
        return self.pk is None


class CustomCreatedTimeStampedModel(TimeStampedModel, models.Model):
    created = models.DateTimeField(default=timezone.now)

    class Meta:
        abstract = True


class UUIDModelMixin(BaseModelMixin, TimeStampedModel, models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    class Meta:
        abstract = True


class UUIDRefNumberModelMixin(UUIDModelMixin, models.Model):
    ref_number = models.CharField(max_length=255, unique=True, blank=True)

    class Meta:
        abstract = True

        constraints = [
            models.UniqueConstraint(
                fields=["ref_number"],
                name="ref_number_unique_constraint",
            ),
        ]

    def save(self, *args, **kwargs):
        # Initial assignment of ref_number
        self.ref_number = get_unique_ref(self.uuid)

        try:
            return super().save(*args, **kwargs)
        except IntegrityError as e:
            # Let retry_ref_number_save handle the constraint check
            return self.retry_ref_number_save(5, e, *args, **kwargs)

    def _is_ref_constraint(self, error):
        """
        Check if an IntegrityError is due to the ref_number constraint violation.
        """
        duplicate_error_code = 1062
        ref_constraint_name = "ref_number_unique_constraint"

        if not hasattr(error, "__cause__") or not error.__cause__:
            return False

        db_error = error.__cause__

        if not hasattr(db_error, "args") or len(db_error.args) == 0:
            return False

        if db_error.args[0] != duplicate_error_code:
            return False

        error_message = str(db_error)
        return ref_constraint_name in error_message

    def retry_ref_number_save(self, retries, error, *args, **kwargs):
        # Check if this is our specific constraint violation
        if not self._is_ref_constraint(error):
            # If it's not our constraint, re-raise the original error
            raise error

        # Check retries count
        if retries <= 0:
            error_message = "Failed to generate a unique ref number after 5 retries."
            raise IntegrityError(error_message)

        # Generate new values
        self.uuid = uuid_lib.uuid4()
        self.ref_number = get_unique_ref(self.uuid)

        try:
            return super().save(*args, **kwargs)
        except IntegrityError as e:
            # Recursively try again with one fewer retry
            return self.retry_ref_number_save(
                retries - 1,
                e,
                *args,
                **kwargs,
            )


class RequiredFieldsAbstractModelMixin:
    required_fields = {}  # Format: {field_name: expected_type}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        # Skip validation for abstract models
        if hasattr(cls, "Meta") and getattr(cls.Meta, "abstract", False):
            return

        # Skip validation if no requirements defined
        if not hasattr(cls, "required_fields") or not cls.required_fields:
            return

        # Check for required fields and their types
        missing = []
        type_errors = []

        for field_name, expected_type in cls.required_fields.items():
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

        # Raise appropriate errors
        if missing:
            error_message = (
                f"{cls.__name__} must define class attributes: {', '.join(missing)}"
            )
            raise NotImplementedError(error_message)

        if type_errors:
            error_message = f"{cls.__name__} has type errors: {'; '.join(type_errors)}"
            raise TypeError(error_message)
