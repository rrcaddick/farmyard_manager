import pytest
from django.core.exceptions import ValidationError
from django.db import models

from farmyard_manager.utils.model_utils import validate_text_choice


class TestValidateTextChoice:
    class SampleChoices(models.TextChoices):
        CHOICE_ONE = "one", "Choice One"
        CHOICE_TWO = "two", "Choice Two"
        CHOICE_THREE = "three", "Choice Three"

    @pytest.mark.parametrize(
        ("value", "error"),
        [
            ("one", None),
            (SampleChoices.CHOICE_TWO, None),
            ("invalid", ValidationError),
            (("three", "Choice Three"), ValidationError),
            ({"four": "Choice Four "}, ValidationError),
        ],
        ids=[
            "valid_text_choice",
            "valid_enum_choice",
            "invalid_text_choice",
            "invalid_tuple_choice",
            "invalid_dict_choice",
        ],
    )
    def test_text_choice(self, value, error):
        if error:
            with pytest.raises(error):
                validate_text_choice(value, self.SampleChoices)
        else:
            result = validate_text_choice(value, self.SampleChoices)
            assert result is True
