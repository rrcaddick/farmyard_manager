import pytest
from django.db import models

from farmyard_manager.core.decorators import required_field
from farmyard_manager.core.decorators import requires_child_fields


class TestRequiresChildFields:
    @pytest.mark.parametrize(
        ("base_fields", "child_fields", "expected_exception", "expected_value"),
        [
            (
                {
                    "required_field": {
                        "expected_type": str,
                        "decorators": [required_field],
                    },
                },
                {
                    "required_field": "test",
                },
                None,
                "test",
            ),
            (
                {
                    "required_field": {
                        "expected_type": models.IntegerField,
                        "decorators": [required_field],
                    },
                },
                {
                    "required_field": models.IntegerField(),
                },
                None,
                models.IntegerField(),
            ),
            (
                {
                    "required_field": {
                        "expected_type": str,
                        "decorators": [required_field],
                    },
                },
                {},
                NotImplementedError,
                None,
            ),
            (
                {
                    "required_field": {
                        "expected_type": str,
                        "decorators": [required_field],
                    },
                },
                {
                    "required_field": 123,
                },
                TypeError,
                None,
            ),
        ],
        ids=[
            "valid_str_field",
            "valid_model_field",
            "missing_required_field",
            "wrong_type_for_field",
        ],
    )
    def test_required_fields_validation(
        self,
        fake_model_factory,
        base_fields,
        child_fields,
        expected_exception,
        expected_value,
    ):
        base_model, _ = fake_model_factory(
            base_name="AbstractBase",
            fields=base_fields,
            create_in_db=False,
            class_decorators=[requires_child_fields],
        )

        if expected_exception:
            with pytest.raises(expected_exception):
                fake_model_factory(
                    base_name="ChildModel",
                    fields=child_fields,
                    base_class=base_model,
                    create_in_db=False,
                )
        else:
            child_model, _ = fake_model_factory(
                base_name="ChildModel",
                fields=child_fields,
                base_class=base_model,
                create_in_db=False,
            )

            if "required_field" in [f.name for f in child_model._meta.get_fields()]:  # noqa: SLF001
                field = child_model._meta.get_field("required_field")  # noqa: SLF001
                assert isinstance(field, type(expected_value))
            else:
                instance = child_model()
                assert instance.required_field == expected_value

    def test_required_field_marker(self):
        @required_field  # type: ignore[misc]
        def some_property():
            return "value"

        # During type checking required_field is an alisas for @property so it can be
        # used on it's own, so is_required_field is not yet defined
        assert hasattr(some_property.fget, "is_required_field")  # type: ignore[attr-defined]
        assert some_property.fget.is_required_field is True  #  type: ignore[attr-defined]
