# ruff: noqa: ERA001

from django.db import models
from model_utils.models import TimeStampedModel

from farmyard_manager.core.models import CleanBeforeSaveModel
from farmyard_manager.core.models import UUIDModelMixin
from farmyard_manager.entrance.managers import PricingManager


class Pricing(UUIDModelMixin, TimeStampedModel, CleanBeforeSaveModel, models.Model):
    class PricingTypes(models.TextChoices):
        PEAK_DAY = ("peak_day", "Peak Day")
        PUBLIC_HOLIDAY = ("public_holiday", "Public Holiday")
        SCHOOL_HOLIDAY = ("school_holiday", "School Holiday")
        WEEKEND = ("weekend", "Weekend")
        WEEKDAY = ("weekday", "Weekday")

    price_type = models.CharField(max_length=20, choices=PricingTypes.choices)
    start_date = models.DateField()
    end_date = models.DateField()
    price = models.DecimalField(max_digits=10, decimal_places=2)

    objects: PricingManager = PricingManager()

    class Meta:
        db_table = "entrance_pricing"
        indexes = [
            models.Index(fields=["start_date", "end_date", "price_type"]),
        ]

    def __str__(self):
        return f"{self.price_type}): {self.price}"
