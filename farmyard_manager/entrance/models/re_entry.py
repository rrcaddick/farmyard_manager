from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.db import models

from farmyard_manager.core.models import CleanBeforeSaveModel
from farmyard_manager.entrance.managers import ReEntryManager
from farmyard_manager.utils.model_utils import validate_text_choice

from .base import BaseEditHistory
from .base import BaseEntranceRecord
from .base import BaseItem
from .base import BaseStatusHistory
from .enums import ReEntryStatusChoices

if TYPE_CHECKING:
    from farmyard_manager.entrance.models.ticket import Ticket  # noqa: F401
    from farmyard_manager.payments.models import Payment  # noqa: F401
    from farmyard_manager.users.models import User


class ReEntryItemEditHistory(BaseEditHistory, models.Model):
    re_entry_item = models.ForeignKey(
        "entrance.ReEntryItem",
        on_delete=models.PROTECT,
        related_name="edit_history",
    )

    class Meta:
        db_table = "entrance_re_entry_item_edit_history"

    def __str__(self):
        return super().__str__()


class ReEntryItem(BaseItem, CleanBeforeSaveModel, models.Model):
    edit_history_model = ReEntryItemEditHistory

    re_entry = models.ForeignKey["ReEntry", "ReEntry"](
        "entrance.ReEntry",
        on_delete=models.PROTECT,
        related_name="re_entry_items",
    )

    class Meta:
        db_table = "entrance_re_entry_items"

    def __str__(self):
        return super().__str__()

    def clean(self):
        status: str = self.re_entry.status

        # Status rules for creating items
        if status not in [
            ReEntryStatusChoices.PENDING_PAYMENT,
        ]:
            error_message = "Only re entries pending payment can add/edit items"
            raise ValueError(error_message)

        return True

    def delete(self, *args, **kwargs):
        if self.re_entry.is_processed:
            error_message = "Can't delete items on a processed re-entry"
            raise ValidationError(error_message)

        return super().delete(*args, **kwargs)

    @property
    def payment(self):
        return self.re_entry.payment

    @property
    def vehicle(self):
        return self.re_entry.vehicle


class ReEntryStatusHistory(BaseStatusHistory, CleanBeforeSaveModel, models.Model):
    StatusChoices = ReEntryStatusChoices

    re_entry = models.ForeignKey(
        "entrance.ReEntry",
        on_delete=models.PROTECT,
        related_name="status_history",
    )

    prev_status = models.CharField(
        max_length=50,
        db_index=True,
        blank=True,
        choices=ReEntryStatusChoices.choices,
    )

    new_status = models.CharField(
        max_length=50,
        db_index=True,
        choices=ReEntryStatusChoices.choices,
    )

    class Meta:
        db_table = "entrance_re_entry_status_history"

    def __str__(self):
        return (
            f"{self.performed_by}: {self.prev_status} → "
            f"f{self.new_status}: {self.re_entry.ticket.id}"
        )

    def clean(self):
        validate_text_choice(
            self.new_status,
            self.StatusChoices,
            "Invalid re-entry status choice",
        )

        self.StatusChoices.validate_choice_transition(self.prev_status, self.new_status)


class ReEntry(BaseEntranceRecord, CleanBeforeSaveModel, models.Model):
    StatusChoices = ReEntryStatusChoices

    item_model = ReEntryItem

    status_history_model = ReEntryStatusHistory

    re_entry_items: "models.QuerySet[ReEntryItem]"

    ticket = models.ForeignKey["Ticket", "Ticket"](
        "entrance.Ticket",
        on_delete=models.PROTECT,
        related_name="re_entries",
    )

    status = models.CharField(
        max_length=50,
        choices=ReEntryStatusChoices.choices,
        default=ReEntryStatusChoices.PENDING,
        db_index=True,
    )

    visitors_left = models.IntegerField()

    visitors_returned = models.IntegerField(null=True, blank=True)

    completed_time = models.DateTimeField(null=True, blank=True)

    objects: ReEntryManager = ReEntryManager()

    class Meta:
        db_table = "entrance_re_entries"

    def __str__(self):
        return f"Re-Entry {self.ticket.vehicle.plate_number} - {self.status}"

    def clean(self):
        validate_text_choice(
            self.status,
            self.StatusChoices,
            "Invalid ticket status choice",
        )

        if self.pk and self._original_status != self.status:
            self.StatusChoices.validate_choice_transition(
                self._original_status,
                self.status,
            )

    @property
    def additional_visitors(self):
        return max(0, (self.visitors_returned or 0) - self.visitors_left)

    @property
    def payment_required(self):
        # Only count additional visitors if MORE people returned than left
        added_visitor_count = sum(
            item.visitor_count for item in self.re_entry_items.all()
        )
        return self.additional_visitors > added_visitor_count

    @property
    def is_processed(self):
        return self.status in [
            ReEntryStatusChoices.PROCESSED,
            ReEntryStatusChoices.REFUNDED,
        ]

    @property
    def vehicle(self):
        return self.ticket.vehicle

    def process_return(self, visitors_returned: int, performed_by: "User"):
        # Update visitors_returned
        self.visitors_returned = visitors_returned

        # Check if more visitors returned than left
        has_additional = (visitors_returned - self.visitors_left) > 0

        if has_additional:
            # If yes, update status to pending_payment
            self.update_status(self.StatusChoices.PENDING_PAYMENT, performed_by)
        else:
            # If no, update status to processed
            self.update_status(self.StatusChoices.PROCESSED, performed_by)
