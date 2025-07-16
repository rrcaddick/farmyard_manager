import uuid
import uuid as uuid_lib

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db import models
from model_utils.models import TimeStampedModel

from farmyard_manager.utils.uuid_utils import get_unique_ref


class BaseModelMixin(models.Model):
    class Meta:
        abstract = True

    def is_new(self):
        return self.pk is None


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
        self.ref_number = kwargs.pop("ref_number", get_unique_ref(self.uuid))

        retries = kwargs.pop("retries", 5)

        try:
            return super().save(*args, **kwargs)
        except IntegrityError as e:
            # Let retry_ref_number_save handle the constraint check
            return self.retry_ref_number_save(e, *args, retries=retries, **kwargs)

    def _is_ref_constraint(self, error):
        """
        Check if an IntegrityError is due to the ref_number constraint violation.
        """
        duplicate_error_code = 1062

        if not hasattr(error, "__cause__") or not error.__cause__:
            return False

        db_error = error.__cause__

        if not hasattr(db_error, "args") or len(db_error.args) == 0:
            return False

        if db_error.args[0] != duplicate_error_code:
            return False

        error_message = str(db_error)
        return ".ref_number" in error_message

    def retry_ref_number_save(self, error, *args, retries, **kwargs):
        # Check if this is our specific constraint violation
        if not self._is_ref_constraint(error):
            # If it's not our constraint, re-raise the original error
            raise error

        # Check retries count
        if retries <= 0:
            error_message = (
                f"Failed to generate a unique ref number after {retries} retries."
            )
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


class TransitionTextChoices(models.TextChoices):
    @classmethod
    def get_transition_map(cls) -> dict:
        raise NotImplementedError

    @classmethod
    def validate_choice_transition(cls, prev_choice, new_choice):
        prev_val = prev_choice.value if isinstance(prev_choice, cls) else prev_choice
        new_val = new_choice.value if isinstance(new_choice, cls) else new_choice

        allowed = cls.get_transition_map().get(prev_val, [])
        if new_val not in allowed:
            error_message = (
                f"Invalid transition from '{prev_val}' to '{new_val}'. "
                f"Allowed: {allowed or 'none'}"
            )
            raise ValidationError(error_message)

        return True


class CleanBeforeSaveModel(models.Model):
    """
    Base model that enforces full_clean() before saving.

    Pass clean=False to bypass validation, e.g., for trusted backfill operations.
    """

    class Meta:
        abstract = True

    def save(self, *args, clean=True, **kwargs):
        if clean:
            # Call full_clean to validate the model before saving
            self.full_clean()
        return super().save(*args, **kwargs)
