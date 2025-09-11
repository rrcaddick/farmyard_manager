from collections.abc import Callable
from typing import Any
from typing import TypeVar
from typing import overload

from django.db import models
from django.db.models import Q
from django.db.models.deletion import Collector

# TypeVars matching django-stubs conventions
_ST_contra = TypeVar("_ST_contra", contravariant=True)
_GT_co = TypeVar("_GT_co", covariant=True)

class SnakeCaseFK(models.ForeignKey[_ST_contra, _GT_co]):
    @overload
    def __init__(
        self,
        to: type[models.Model],
        *,
        on_delete: Callable[
            [Collector, models.Field[Any, Any], models.QuerySet[Any, Any], str],
            None,
        ],
        related_name_prefix: str = ...,
        related_name_suffix: str = ...,
        pluralize_related_name: bool = ...,
        related_name: str | None = ...,
        related_query_name: str | None = ...,
        limit_choices_to: Q | dict[str, Any] | None = ...,
        parent_link: bool = ...,
        to_field: str | None = ...,
        db_constraint: bool = ...,
        null: bool = ...,
        blank: bool = ...,
        **kwargs: Any,
    ) -> None: ...
    @overload
    def __init__(
        self,
        to: str,
        *,
        on_delete: Callable[
            [Collector, models.Field[Any, Any], models.QuerySet[Any, Any], str],
            None,
        ],
        related_name_prefix: str = ...,
        related_name_suffix: str = ...,
        pluralize_related_name: bool = ...,
        related_name: str | None = ...,
        related_query_name: str | None = ...,
        limit_choices_to: Q | dict[str, Any] | None = ...,
        parent_link: bool = ...,
        to_field: str | None = ...,
        db_constraint: bool = ...,
        null: bool = ...,
        blank: bool = ...,
        **kwargs: Any,
    ) -> None: ...
    def __class_getitem__(cls, params: Any) -> type[SnakeCaseFK[Any, Any]]: ...
