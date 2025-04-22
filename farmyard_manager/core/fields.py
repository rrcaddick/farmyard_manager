import re
from typing import Any

from django.db import models
from django.db.models import Model


class SnakeCaseForeignKey(models.ForeignKey):
    def __init__(
        self,
        *args: Any,
        related_name_prefix: str | None = None,
        related_name_suffix: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.prefix = related_name_prefix
        self.suffix = related_name_suffix
        super().__init__(*args, **kwargs)

    # ruff: noqa: FBT001, FBT002
    def contribute_to_class(
        self,
        cls: type[Model],
        name: str,
        private_only: bool = False,
    ) -> None:
        if self.prefix is not None or self.suffix is not None:
            snake_case = re.sub(r"(?<!^)(?=[A-Z])", "_", cls.__name__).lower()
            related_name = (
                f"{self.prefix}_{snake_case}_{self.suffix}"
                if self.prefix is not None and self.suffix is not None
                else f"{self.prefix}_{snake_case}"
                if self.prefix is not None
                else f"{snake_case}_{self.suffix}"
                if self.suffix is not None
                else None
            )
            if related_name:
                self.remote_field.related_name = related_name

        super().contribute_to_class(cls, name, private_only)
