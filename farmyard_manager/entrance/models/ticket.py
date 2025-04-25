from django.core.exceptions import ValidationError
from django.db import models

from farmyard_manager.core.models import CleanBeforeSaveModel
from farmyard_manager.entrance.managers import TicketManager
from farmyard_manager.utils.model_utils import validate_text_choice

from .base import BaseEditHistory
from .base import BaseEntranceRecord
from .base import BaseItem
from .base import BaseStatusHistory
from .enums import TicketStatusChoices
from .re_entry import ReEntry


class TicketItemEditHistory(BaseEditHistory, models.Model):
    ticket_item = models.ForeignKey(
        "entrance.TicketItem",
        on_delete=models.PROTECT,
        related_name="edit_history",
    )

    class Meta:
        db_table = "entrance_ticket_item_edit_history"

    def __str__(self):
        return super().__str__()


class TicketItem(BaseItem, CleanBeforeSaveModel, models.Model):
    edit_history_model = TicketItemEditHistory

    ticket = models.ForeignKey(
        "entrance.Ticket",
        on_delete=models.PROTECT,
        related_name="ticket_items",
    )

    class Meta:
        db_table = "entrance_ticket_items"

    def __str__(self):
        return super().__str__()

    def clean(self):
        # Status rules for creating items
        action = "edit" if self.pk else "add"

        error_message = (
            f"Can't {action} items, ticket is processed"
            if self.ticket.is_processed
            else "Ticket needs to pass security check first"
            if self.ticket.status == TicketStatusChoices.PENDING_SECURITY
            else ""
        )

        if error_message != "":
            raise ValidationError(error_message)

        return True

    def delete(self, *args, **kwargs):
        if self.ticket.is_processed:
            error_message = "Can't delete items on a processed ticket"
            raise ValidationError(error_message)

        return super().delete(*args, **kwargs)


class TicketStatusHistory(BaseStatusHistory, CleanBeforeSaveModel, models.Model):
    StatusChoices = TicketStatusChoices

    ticket = models.ForeignKey(
        "entrance.Ticket",
        on_delete=models.PROTECT,
        related_name="status_history",
    )

    prev_status = models.CharField(
        max_length=50,
        db_index=True,
        blank=True,
        choices=TicketStatusChoices.choices,
    )

    new_status = models.CharField(
        max_length=50,
        db_index=True,
        choices=TicketStatusChoices.choices,
    )

    class Meta:
        db_table = "entrance_ticket_status_history"

    def __str__(self):
        return (
            f"Status {self.prev_status} → {self.new_status} for Ticket {self.ticket.id}"
        )

    def clean(self):
        validate_text_choice(
            self.new_status,
            self.StatusChoices,
            "Invalid ticket status choice",
        )

        self.StatusChoices.validate_choice_transition(self.prev_status, self.new_status)


class Ticket(BaseEntranceRecord, CleanBeforeSaveModel, models.Model):
    StatusChoices = TicketStatusChoices

    item_model = TicketItem

    status_history_model = TicketStatusHistory

    status = models.CharField(
        max_length=255,
        choices=TicketStatusChoices.choices,
    )

    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        on_delete=models.PROTECT,
        related_name="tickets",
    )

    objects = TicketManager()

    class Meta:
        db_table = "entrance_tickets"

    def __str__(self):
        return f"{self.ref_number} - {self.status}"

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
    def is_processed(self):
        return self.status in [
            TicketStatusChoices.PROCESSED,
            TicketStatusChoices.REFUNDED,
        ]

    @property
    def pending_re_entries(self):
        return self.re_entries.filter(status="pending")

    def add_re_entry(self, visitors_left: int):
        if self.status != TicketStatusChoices.PROCESSED:
            error_message = "Only processed tickets can have re-entries"
            raise ValueError(error_message)

        if visitors_left <= 0:
            error_message = "Visitors left must be greater than 0"
            raise ValueError(error_message)

        return ReEntry.objects.create(
            ticket=self,
            status=ReEntry.StatusChoices.PENDING,
            visitors_left=visitors_left,
        )
