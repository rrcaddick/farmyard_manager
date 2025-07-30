from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from model_utils.models import TimeStampedModel

from farmyard_manager.core.models import CleanBeforeSaveModel
from farmyard_manager.core.models import UUIDModelMixin
from farmyard_manager.users.models import User


class Shift(UUIDModelMixin, TimeStampedModel, CleanBeforeSaveModel, models.Model):
    class StatusChoices(models.TextChoices):
        ACTIVE = ("active", "Active")
        CLOSED = ("closed", "Closed")
        SUSPENDED = ("suspended", "Suspended")

    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="shifts",
    )

    # TODO: Add role that the shift is. Either a ForeignKey to a Role model or a choice

    start_time = models.DateTimeField()

    end_time = models.DateTimeField(null=True, blank=True)

    status = models.CharField(
        max_length=50,
        choices=StatusChoices.choices,
        default=StatusChoices.ACTIVE,
    )

    float_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Starting cash amount for the shift",
    )

    expected_cash_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Expected cash at end of shift",
    )

    actual_cash_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Actual cash counted at end of shift",
    )

    discrepancy_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Difference between expected and actual cash",
    )

    discrepancy_notes = models.TextField(blank=True)

    adjusted_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="adjusted_shifts",
        null=True,
        blank=True,
        help_text="Manager who made adjustments to this shift",
    )

    adjusted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "shifts_shift"
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(status="active"),
                name="one_active_shift_per_user",
            ),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.status})"

    def clean(self):
        """Validate shift data"""
        super().clean()

        # Validate end_time is after start_time
        if self.end_time and self.end_time <= self.start_time:
            error_message = "End time must be after start time"
            raise ValidationError(error_message)

        # TODO: Validate status transitions

    @property
    def is_active(self):
        """Check if shift is currently active"""
        return self.status == self.StatusChoices.ACTIVE

    @property
    def duration(self):
        """Calculate shift duration"""
        if not self.end_time:
            return timezone.now() - self.start_time
        return self.end_time - self.start_time

    @property
    def total_cash_collected(self):
        """Calculate total cash collected during shift"""
        from farmyard_manager.payments.models import TransactionItem

        return TransactionItem.objects.filter(
            payment__shift=self,
            payment_type=TransactionItem.PaymentTypeChoices.CASH,
        ).aggregate(
            total=models.Sum("amount"),
        )["total"] or Decimal("0.00")

    @property
    def total_card_collected(self):
        """Calculate total card payments during shift"""
        from farmyard_manager.payments.models import TransactionItem

        return TransactionItem.objects.filter(
            payment__shift=self,
            payment_type=TransactionItem.PaymentTypeChoices.CARD,
        ).aggregate(
            total=models.Sum("amount"),
        )["total"] or Decimal("0.00")

    @property
    def expected_till_balance(self):
        """Calculate expected till balance at end of shift"""
        return self.float_amount + self.total_cash_collected

    def close_shift(self, actual_cash_amount, performed_by):
        """Close the shift and calculate discrepancies"""
        if self.status != self.StatusChoices.ACTIVE:
            error_message = "Only active shifts can be closed"
            raise ValidationError(error_message)

        self.end_time = timezone.now()
        self.status = self.StatusChoices.CLOSED
        self.actual_cash_amount = actual_cash_amount
        self.expected_cash_amount = self.expected_till_balance
        self.discrepancy_amount = actual_cash_amount - self.expected_cash_amount

        if performed_by != self.user:
            self.adjusted_by = performed_by
            self.adjusted_at = timezone.now()

        self.save()

    def can_create_tickets(self):
        """Check if this shift type can create tickets"""
        # TODO: This is likely attached to the user rather than the shift

    def suspend_shift(self, reason=""):
        """Suspend an active shift"""
        if self.status != self.StatusChoices.ACTIVE:
            error_message = "Only active shifts can be suspended"
            raise ValidationError(error_message)

        self.status = self.StatusChoices.SUSPENDED
        if reason:
            self.discrepancy_notes = f"Suspended: {reason}"
        self.save()

    def resume_shift(self):
        """Resume a suspended shift"""
        if self.status != self.StatusChoices.SUSPENDED:
            error_message = "Only suspended shifts can be resumed"
            raise ValidationError(error_message)

        self.status = self.StatusChoices.ACTIVE
        self.save()
