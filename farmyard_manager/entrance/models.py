from django.db import models
from django.db import transaction
from model_utils.models import SoftDeletableModel
from model_utils.models import TimeStampedModel

from farmyard_manager.core.models import UUIDModelMixin
from farmyard_manager.entrance.managers import ReEntryManager
from farmyard_manager.entrance.managers import TicketManager
from farmyard_manager.users.models import User
from farmyard_manager.utils.time_utils import get_unix_timestamp


class TicketTypeChoices(models.TextChoices):
    PUBLIC = ("public", "Public")
    GROUP = ("group", "Group")
    SCHOOL = ("school", "School")
    ONLINE = ("online", "Online")


class TicketStatusChoices(models.TextChoices):
    PENDING_SECURITY = ("pending_security", "Pending Security")
    PASSED_SECURITY = ("passed_security", "Passed Security")
    COUNTED = ("counted", "Visitors Counted")
    PAID = ("paid", "Payment Processed")
    GROUP_ENTRY_PROCESSED = ("group_entry_processed", "Group Entry Processed")
    ONLINE_ENTRY_PROCESSED = ("online_entry_processed", "Online Entry Processed")
    SCHOOL_ENTRY_PROCESSED = ("school_entry_processed", "School Entry Processed")
    REFUNDED = ("refunded", "Ticket Refunded")


class Ticket(UUIDModelMixin, TimeStampedModel, SoftDeletableModel, models.Model):
    TypeChoices = TicketTypeChoices

    StatusChoices = TicketStatusChoices

    type = models.CharField(
        max_length=255,
        choices=TicketTypeChoices.choices,
        blank=True,
    )

    status = models.CharField(
        max_length=255,
        choices=TicketStatusChoices.choices,
    )

    ticket_number = models.BigIntegerField(default=get_unix_timestamp, unique=True)

    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        on_delete=models.PROTECT,
        related_name="tickets",
    )

    visitor_count = models.IntegerField(null=True)

    applied_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
    )

    payment = models.ForeignKey(
        "payments.Payment",
        on_delete=models.SET_NULL,
        null=True,
        related_name="tickets",
    )

    objects = TicketManager()

    def __str__(self):
        return f"{self.ticket_number} - {self.status}"

    def _get_price(self, ticket_type):
        # TODO: Implement price retrieval logic
        return 100.0

    def add_initial_status(self, status, performed_by):
        """Update ticket status after security check."""
        with transaction.atomic():
            self.status = status
            self.save(update_fields=["status"])

            StatusHistory.objects.create(
                ticket=self,
                prev_status="",
                new_status=self.status,
                performed_by=performed_by,
            )

    def add_security_check(self, performed_by):
        """Update ticket status after security check."""
        with transaction.atomic():
            prev_status = self.status
            self.status = TicketStatusChoices.PASSED_SECURITY
            self.save(update_fields=["status"])

            StatusHistory.objects.create(
                ticket=self,
                prev_status=prev_status,
                new_status=self.status,
                performed_by=performed_by,
            )

    def add_visitor_details(self, ticket_type, visitor_count, performed_by):
        """Add innitial visitor details"""
        if self.status != TicketStatusChoices.PASSED_SECURITY:
            error_message = (
                "Ticket must pass security check before adding visitor details"
            )
            raise ValueError(error_message)

        with transaction.atomic():
            prev_status = self.status

            # Update fields
            self.type = ticket_type
            self.visitor_count = visitor_count
            self.applied_price = self._get_price(ticket_type)
            self.status = TicketStatusChoices.COUNTED

            # TODO: Check if modified is updated here
            self.save(
                update_fields=["type", "visitor_count", "applied_price", "status"],
            )

            # Only create status history, not edit history since this is initial data
            StatusHistory.objects.create(
                ticket=self,
                prev_status=prev_status,
                new_status=self.status,
                performed_by=performed_by,
            )

    def edit_visitor_details(
        self,
        performed_by,
        ticket_type: str | None = None,
        visitor_count: int | None = None,
    ):
        """Edit visitor details after initial setup - tracked as an edit."""
        if self.status not in [TicketStatusChoices.COUNTED]:
            error_message = "Only counted tickets can be editted"
            raise ValueError(error_message)

        with transaction.atomic():
            # Track edits
            edit_history_entries = []

            if ticket_type and self.type != ticket_type:
                if ticket_type not in [
                    choice[0] for choice in TicketTypeChoices.choices
                ]:
                    error_message = "Ticket type must be one of the available choices"
                    raise ValueError(error_message)

                edit_history_entries.append(
                    EditHistory(
                        ticket=self,
                        field="type",
                        prev_value=self.type,
                        new_value=ticket_type,
                        performed_by=performed_by,
                    ),
                )
                self.type = ticket_type

            if visitor_count and self.visitor_count != visitor_count:
                edit_history_entries.append(
                    EditHistory(
                        ticket=self,
                        field="visitor_count",
                        prev_value=str(self.visitor_count),
                        new_value=str(visitor_count),
                        performed_by=performed_by,
                    ),
                )
                self.visitor_count = visitor_count

            # Save if changes were made
            if edit_history_entries:
                self.save(update_fields=["type", "visitor_count"])
                EditHistory.objects.bulk_create(edit_history_entries)

    def process_payment(self):
        # TODO: Decide if this method should be here or in the Payment model
        pass

    def refund(self):
        # TODO: Decide if this method should be here or in the Payment model
        pass


class StatusHistory(UUIDModelMixin, TimeStampedModel):
    StatusChoices = TicketStatusChoices

    ticket = models.ForeignKey(
        "entrance.Ticket",
        on_delete=models.PROTECT,
        related_name="status_history",
        db_index=True,
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

    performed_by = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="status_changes",
        db_index=True,
    )

    class Meta:
        db_table = "entrance_status_history"

    def __str__(self):
        return (
            f"Status {self.prev_status} → {self.new_status} for Ticket {self.ticket.id}"
        )


class EditHistory(UUIDModelMixin, TimeStampedModel):
    class Fields(models.TextChoices):
        TYPE = ("type", "Ticket Type")
        VISITOR_COUNT = ("visitor_count", "Visitor Count")

    TypeChoices = TicketTypeChoices

    ticket = models.ForeignKey(
        "entrance.Ticket",
        on_delete=models.PROTECT,
        related_name="edit_history",
        db_index=True,
    )

    field = models.CharField(max_length=50, choices=Fields.choices, db_index=True)

    prev_value = models.CharField(
        max_length=255,
    )

    new_value = models.CharField(max_length=255)

    performed_by = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        db_index=True,
        related_name="ticket_edits",
    )

    class Meta:
        db_table = "entrance_edit_history"

    def __str__(self):
        return f"Edit {self.field} on Ticket {self.ticket.id} by {self.performed_by}"


class Pricing(UUIDModelMixin, TimeStampedModel):
    TicketTypeChoices = TicketTypeChoices

    ticket_type = models.CharField(
        max_length=50,
        choices=TicketTypeChoices.choices,
        db_index=True,
    )

    price = models.DecimalField(max_digits=10, decimal_places=2)

    applies_from = models.DateTimeField()

    applies_to = models.DateTimeField()

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "entrance_pricing"

    def __str__(self):
        return f"{self.ticket_type} - {self.price}"


class ReEntry(UUIDModelMixin, TimeStampedModel):
    class StatusChoices(models.TextChoices):
        PENDING = ("pending", "Pending")
        COMPLETED = ("completed", "Completed")

    ticket = models.ForeignKey(
        "entrance.Ticket",
        on_delete=models.PROTECT,
        related_name="re_entries",
        db_index=True,
    )

    status = models.CharField(
        max_length=50,
        choices=StatusChoices.choices,
        default=StatusChoices.PENDING,
        db_index=True,
    )

    visitors_left = models.IntegerField()

    visitors_returned = models.IntegerField(null=True)

    completed_time = models.DateTimeField(null=True)

    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="created_re_entries",
    )

    completed_by = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        null=True,
        related_name="completed_re_entries",
    )

    objects = ReEntryManager()

    class Meta:
        db_table = "entrance_re_entries"

    def __str__(self):
        return f"Re-Entry {self.ticket.vehicle.plate_number} - {self.status}"

    def complete_re_entry(self, visitors_returned: int, completed_by: User):
        if self.status != self.StatusChoices.PENDING:
            error_message = "Only pending re-entries can be completed"
            raise ValueError(error_message)

        with transaction.atomic():
            self.status = self.StatusChoices.COMPLETED
            self.visitors_returned = visitors_returned
            self.completed_by = completed_by
            self.completed_time = get_unix_timestamp()
            self.save(
                update_fields=[
                    "status",
                    "visitors_returned",
                    "completed_by",
                    "completed_time",
                    "modified",
                ],
            )

            if visitors_returned > self.visitors_left:
                # Create ReEntryAddition with the extra visitors
                visitor_count = self.visitors_returned - self.visitors_left

                assert self.ticket.applied_price is not None, (
                    "Processed ticket must have a price"
                )

                ReEntryAddition.objects.create(
                    re_entry=self,
                    visitor_count=visitor_count,
                    ticket=self.ticket,
                    status=ReEntryAddition.StatusChoices.PENDING,
                    applied_price=self.ticket.applied_price,
                )


class ReEntryAddition(UUIDModelMixin, TimeStampedModel):
    class StatusChoices(models.TextChoices):
        PENDING = ("pending", "Pending")
        PAID = ("paid", "Paid")

    re_entry = models.ForeignKey(
        "entrance.ReEntry",
        on_delete=models.PROTECT,
        related_name="additional_visitors",
        db_index=True,
    )

    ticket = models.ForeignKey(
        "entrance.Ticket",
        on_delete=models.PROTECT,
        related_name="re_entry_additions",
        db_index=True,
    )

    status = models.CharField(
        max_length=50,
        choices=StatusChoices.choices,
        db_index=True,
    )

    visitor_count = models.IntegerField()

    applied_price = models.DecimalField(max_digits=10, decimal_places=2)

    payment = models.OneToOneField(
        "payments.Payment",
        on_delete=models.PROTECT,
        null=True,
        related_name="re_entry_payments",
    )

    class Meta:
        db_table = "entrance_re_entry_additions"

    def __str__(self):
        return f"Re-Entry Addition {self.uuid} - {self.status}"

    def process_payment(self):
        # TODO: Decide if this method should be here or in the Payment model
        # Likely both
        pass
