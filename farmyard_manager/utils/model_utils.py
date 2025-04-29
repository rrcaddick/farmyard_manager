from django.core.exceptions import ValidationError
from django.db import models


def validate_text_choice(
    value: str,
    choices: type[models.TextChoices],
    error_message: str = "Invalid choice",
) -> None:
    if value not in [choice.value for choice in choices]:
        raise ValidationError(error_message)

    return True
