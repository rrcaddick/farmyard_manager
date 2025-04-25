from django.core.exceptions import ValidationError
from django.db import models
from model_utils.models import TimeStampedModel

from farmyard_manager.core.models import CleanBeforeSaveModel
from farmyard_manager.core.models import UUIDModelMixin

from .enums import ItemTypeChoices


class Pricing(UUIDModelMixin, TimeStampedModel, CleanBeforeSaveModel, models.Model):
    ItemTypeChoices = ItemTypeChoices

    ticket_item_type = models.CharField(
        max_length=50,
        choices=ItemTypeChoices.choices,
        db_index=True,
    )

    price = models.DecimalField(max_digits=10, decimal_places=2)

    price_start = models.DateTimeField()

    price_end = models.DateTimeField()

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "entrance_pricing"
        constraints = [
            models.UniqueConstraint(
                fields=["ticket_item_type", "is_active"],
                condition=models.Q(is_active=True),
                name="unique_active_pricing_per_type",
            ),
        ]

    def __str__(self):
        return f"{self.ticket_item_type} - {self.price}"

    def clean(self):
        # Check for overlapping date ranges
        overlaps = Pricing.objects.filter(
            ticket_item_type=self.ticket_item_type,
            price_start__lt=self.price_end,
            price_end__gt=self.price_start,
        ).exclude(pk=self.pk)

        if overlaps.exists():
            error_message = (
                f"Date range overlaps with existing pricing for {self.ticket_item_type}"
            )
            raise ValidationError(error_message)

        # Ensure applies_to is after applies_from
        if self.price_end <= self.price_start:
            error_message = "End date must be after start date"
            raise ValidationError(error_message)

    @staticmethod
    def get_price(ticket_item_type: str, date_time=None):
        # Base query parameters
        query_params = {
            "ticket_item_type": ticket_item_type,
            "is_active": True,
        }

        # Add date filters if date_time is provided
        if date_time is not None:
            query_params.update(
                {
                    "price_start__lte": date_time,
                    "price_end__gte": date_time,
                },
            )

        try:
            pricing = Pricing.objects.get(**query_params)
        except Pricing.DoesNotExist as err:
            error_message = f"No pricing found for {ticket_item_type} on {date_time}"
            raise ValueError(error_message) from err

        return pricing.price
