# ruff: noqa: N806, SLF001

import pytest
from django.db import models

from farmyard_manager.core.fields import SnakeCaseFK
from farmyard_manager.utils.string_utils import to_snake_case


@pytest.fixture
def create_snake_case_related_models(fake_model_factory):
    def _create_models(*, create_in_db=False, **kwargs):
        ParentModel, _ = fake_model_factory(
            "ParentModel",
            create_in_db=create_in_db,
        )
        ChildModel, child_name = fake_model_factory(
            "ChildModel",
            fields={
                "related": SnakeCaseFK(
                    ParentModel,
                    on_delete=models.CASCADE,
                    **kwargs,
                ),
            },
            create_in_db=create_in_db,
        )

        prefix = kwargs.get("related_name_prefix", "")
        suffix = kwargs.get("related_name_suffix", "")
        pluralize = kwargs.get("pluralize_related_name", False)

        related_name = to_snake_case(
            child_name,
            prefix=prefix,
            suffix=suffix,
            pluralize=pluralize,
        )

        return ParentModel, ChildModel, related_name

    return _create_models


class TestSnakeCaseFK:
    @pytest.mark.parametrize(
        ("kwargs"),
        [
            ({}),
            ({"related_name_prefix": "foo"}),
            ({"related_name_suffix": "bar"}),
            ({"pluralize_related_name": True}),
            (
                {
                    "related_name_prefix": "pre",
                    "related_name_suffix": "post",
                    "pluralize_related_name": True,
                }
            ),
        ],
        ids=[
            "default",
            "prefix",
            "suffix",
            "pluralize",
            "combined",
        ],
    )
    def test_related_name_variants(
        self,
        create_snake_case_related_models,
        kwargs,
    ):
        _, ChildModel, related_name = create_snake_case_related_models(**kwargs)
        child_related_field = ChildModel._meta.get_field("related")
        assert child_related_field.remote_field.related_name == related_name

    @pytest.mark.django_db(transaction=True)
    def test_snake_case_related_name(self, create_snake_case_related_models):
        ParentModel, ChildModel, related_name = create_snake_case_related_models(
            create_in_db=True,
            pluralize_related_name=True,
        )

        parent_model = ParentModel.objects.create()
        child_model = ChildModel.objects.create(related=parent_model)

        assert getattr(parent_model, related_name).count() == 1
        assert ChildModel.objects.count() == 1
        assert child_model.related == parent_model
