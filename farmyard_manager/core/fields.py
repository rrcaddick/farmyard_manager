from django.db import models

from farmyard_manager.utils.string_utils import to_snake_case


class SnakeCaseFK(models.ForeignKey):
    def __init__(
        self,
        *args,
        related_name_prefix: str = "",
        related_name_suffix: str = "",
        pluralize_related_name: bool = False,
        **kwargs,
    ) -> None:
        self.prefix = related_name_prefix
        self.suffix = related_name_suffix
        self.pluralize = pluralize_related_name
        super().__init__(*args, **kwargs)

    # ruff: noqa: FBT001, FBT002
    def contribute_to_class(
        self,
        cls: type[models.Model],
        name: str,
        private_only: bool = False,
    ) -> None:
        related_name = to_snake_case(
            cls.__name__,
            prefix=self.prefix,
            suffix=self.suffix,
            pluralize=self.pluralize,
        )

        self.remote_field.related_name = related_name

        super().contribute_to_class(cls, name, private_only)
