from __future__ import annotations

import re
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db import transaction
from model_utils.models import SoftDeletableModel
from model_utils.models import TimeStampedModel

from farmyard_manager.core.decorators import required_field
from farmyard_manager.core.decorators import requires_fields
from farmyard_manager.core.fields import SnakeCaseForeignKey
from farmyard_manager.core.models import CustomCreatedTimeStampedModel
from farmyard_manager.core.models import UUIDModelMixin
from farmyard_manager.core.models import UUIDRefNumberModelMixin
from farmyard_manager.entrance.managers import ReEntryManager
from farmyard_manager.entrance.managers import TicketManager

if TYPE_CHECKING:
    from django.db.models.query import QuerySet

    from farmyard_manager.users.models import User


class ItemTypeChoices(models.TextChoices):
    PUBLIC = ("public", "Public")
    GROUP = ("group", "Group")
    SCHOOL = ("school", "School")
    ONLINE = ("online", "Online")
    VOIDED = ("voided", "VOIDED")


class TicketStatusChoices(models.TextChoices):
    PENDING_SECURITY = ("pending_security", "Pending Security")
    PASSED_SECURITY = ("passed_security", "Passed Security")
    COUNTED = ("counted", "Visitors Counted")
    PROCESSED = ("processed", "Processed")
    REFUNDED = ("refunded", "Ticket Refunded")


class ReEntryStatusChoices(models.TextChoices):
    PENDING = ("pending", "Pending")
    PENDING_PAYMENT = ("pending_payment", "Pending Payment")
    PROCESSED = ("processed", "Processed")


class BaseStatusHistory(
    UUIDModelMixin,
    CustomCreatedTimeStampedModel,
    models.Model,
):
    performed_by = SnakeCaseForeignKey(
        "users.User",
        on_delete=models.PROTECT,
    )

    class Meta:
        abstract = True


class BaseEditHistory(UUIDModelMixin, CustomCreatedTimeStampedModel, models.Model):
    ItemTypeChoices = ItemTypeChoices

    class FieldChoices(models.TextChoices):
        ITEM_TYPE = ("item_type", "Item Type")
        VISITOR_COUNT = ("visitor_count", "Visitor Count")

    field = models.CharField(
        max_length=50,
        choices=FieldChoices.choices,
        db_index=True,
    )

    prev_value = models.CharField(
        max_length=255,
    )

    new_value = models.CharField(max_length=255)

    performed_by = SnakeCaseForeignKey(
        "users.User",
        on_delete=models.PROTECT,
    )

    class Meta:
        abstract = True

    def __str__(self):
        return f"{self.field} edit by {self.performed_by}"


class TicketItemEditHistory(BaseEditHistory, models.Model):
    ticket_item = models.ForeignKey(
        "entrance.TicketItem",
        on_delete=models.PROTECT,
        related_name="edit_history",
    )

    class Meta:
        db_table = "entrance_ticket_item_edit_history"


class ReEntryItemEditHistory(BaseEditHistory, models.Model):
    re_entry_item = models.ForeignKey(
        "entrance.ReEntryItem",
        on_delete=models.PROTECT,
        related_name="edit_history",
    )

    class Meta:
        db_table = "entrance_re_entry_item_edit_history"


@requires_fields
class BaseItem(
    UUIDModelMixin,
    CustomCreatedTimeStampedModel,
    SoftDeletableModel,
    models.Model,
):
    class ItemTypeChoices(models.TextChoices):
        PUBLIC = ("public", "Public")
        GROUP = ("group", "Group")
        SCHOOL = ("school", "School")
        ONLINE = ("online", "Online")
        VOIDED = ("voided", "VOIDED")

    created_by = SnakeCaseForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name_prefix="created",
        related_name_suffix="s",
    )

    item_type = models.CharField(
        max_length=50,
        choices=ItemTypeChoices.choices,
    )

    visitor_count = models.IntegerField(validators=[MinValueValidator(1)])

    applied_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
    )

    class Meta:
        abstract = True

    def __str__(self):
        return f"{self.visitor_count} {self.item_type} visitors at {self.applied_price}"

    @property
    @required_field
    def edit_history_model(self):
        return BaseEditHistory

    @property
    def amount_due(self):
        return self.visitor_count * self.applied_price

    @property
    def snake_case_model_name(self):
        return re.sub(r"(?<!^)(?=[A-Z])", "_", self.__class__.__name__).lower()

    def get_price(self):
        if self.item_type is None:
            error_message = "Set item type befor getting price"
            raise ValueError(error_message)

        return Pricing.get_price(self.item_type)

    def edit(
        self,
        performed_by: User,
        item_type: str | None = None,
        visitor_count: int | None = None,
    ):
        with transaction.atomic():
            edit_history_entries = []
            update_fields = []

            # Item type changed
            if item_type and self.item_type != item_type:
                if item_type not in [
                    choice[0] for choice in self.ItemTypeChoices.choices
                ]:
                    error_message = "Invalid ticket item type"
                    raise ValueError(error_message)

                edit_history_kwargs = {
                    self.snake_case_model_name: self,
                    "field": "item_type",
                    "prev_value": self.item_type,
                    "new_value": item_type,
                    "performed_by": performed_by,
                }
                edit_history_entries.append(
                    self.edit_history_model(**edit_history_kwargs),
                )
                self.item_type = item_type
                self.applied_price = self.get_price()
                update_fields.extend(["item_type", "applied_price"])

            # Visitor count edit
            if visitor_count is not None and self.visitor_count != visitor_count:
                if visitor_count < 1:
                    error_message = "Visitor count must be greater than 0"
                    raise ValueError(error_message)

                edit_history_kwargs = {
                    self.snake_case_model_name: self,
                    "field": "visitor_count",
                    "prev_value": str(self.visitor_count),
                    "new_value": str(visitor_count),
                    "performed_by": performed_by,
                }

                edit_history_entries.append(
                    self.edit_history_model(**edit_history_kwargs),
                )
                self.visitor_count = visitor_count
                update_fields.append("visitor_count")

            # Save if changes were made
            if update_fields:
                self.save(update_fields=update_fields)
                self.edit_history_model.objects.bulk_create(edit_history_entries)

            return self


@requires_fields
class BaseEntranceRecord(
    UUIDRefNumberModelMixin,
    CustomCreatedTimeStampedModel,
    SoftDeletableModel,
    models.Model,
):
    payment = SnakeCaseForeignKey(
        "payments.Payment",
        on_delete=models.PROTECT,
        null=True,
        related_name_suffix="payments",
    )  # type: ignore[misc]

    class Meta:
        abstract = True

    def __str__(self):
        return f"{self.ref_number} - {self.status}"

    status: models.CharField

    @property
    @required_field
    def item_model(self):
        return BaseItem

    @property
    @required_field
    def status_history_model(self):
        return BaseStatusHistory

    @property
    def snake_case_model_name(self):
        return re.sub(r"(?<!^)(?=[A-Z])", "_", self.__class__.__name__).lower()

    @property
    def item_relation(self):
        model_name = re.sub(
            r"(?<!^)(?=[A-Z])",
            "_",
            self.item_model.__name__,
        ).lower()

        return f"{model_name}s"

    @property
    def items(self):
        items: QuerySet[BaseItem] = getattr(self, self.item_relation).all()
        return items

    @property
    def total_due(self):
        return sum(item.amount_due for item in self.items)

    @property
    def total_visitors(self):
        return sum(item.visitor_count for item in self.items)

    @property
    def voided_items(self):
        return self.item_model.objects.all_with_deleted().filter(
            **{self.snake_case_model_name: self},
            is_removed=True,
        )

    def validate_status(self):
        raise NotImplementedError

    def add_create_status(self, performed_by: User):
        kwargs = {
            self.snake_case_model_name: self,
            "prev_status": "",
            "new_status": self.status,
            "performed_by": performed_by,
        }
        self.status_history_model.objects.create(**kwargs)

    def update_status(self, new_status: str, performed_by: User):
        prev_status = self.status

        self.status = new_status

        with transaction.atomic():
            kwargs = {
                self.snake_case_model_name: self,
                "prev_status": prev_status,
                "new_status": new_status,
                "performed_by": performed_by,
            }
            self.status_history_model.objects.create(**kwargs)
            self.save(update_fields=["status"])

        return self

    def add_item(
        self,
        item_type: str,
        visitor_count: int,
        created_by: User,
        applied_price=None,
    ):
        # Check if the child status is in a valid state
        self.validate_status()

        # Validate ticket type
        if item_type not in [choice[0] for choice in ItemTypeChoices.choices]:
            error_message = "Invalid item type"
            raise ValueError(error_message)

        # Validate visitor count
        if visitor_count < 1:
            error_message = "Visitor count must be greater than 0"
            raise ValueError(error_message)

        # Get price for this type
        applied_price = (
            Pricing.get_price(item_type) if applied_price is None else applied_price
        )

        # Create the item using the dynamic relationship
        kwargs = {
            self.snake_case_model_name: self,
            "created_by": created_by,
            "item_type": item_type,
            "visitor_count": visitor_count,
            "applied_price": applied_price,
        }
        return self.item_model.objects.create(**kwargs)

    def remove_item(self, item_id: int, performed_by: User):
        # Check if the status allows removing items
        self.validate_status()

        try:
            # Use the correct relation property name
            item = getattr(self, self.item_relation).get(id=item_id)
        except self.item_model.DoesNotExist as err:
            error_message = f"{self.item_model.__name__} {item_id} not found"
            raise ValueError(error_message) from err

        item.delete()
        return True


class TicketItem(BaseItem, models.Model):
    edit_history_model = TicketItemEditHistory

    ticket = models.ForeignKey(
        "entrance.Ticket",
        on_delete=models.PROTECT,
        related_name="ticket_items",
    )

    class Meta:
        db_table = "entrance_ticket_items"


class TicketStatusHistory(BaseStatusHistory, models.Model):
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


class Ticket(BaseEntranceRecord, models.Model):
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

    def __str__(self):
        return f"{self.ref_number} - {self.status}"

    @property
    def pending_re_entries(self):
        return self.re_entries.filter(status="pending")

    def validate_status(self):
        if self.status not in [
            TicketStatusChoices.PASSED_SECURITY,
            TicketStatusChoices.COUNTED,
        ]:
            error_message = "Ticket not in correct state"
            raise ValueError(error_message)

        return True

    def add_re_entry(self, visitors_left: int, created_by: User):
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


class Pricing(UUIDModelMixin, TimeStampedModel, models.Model):
    TicketTypeChoices = ItemTypeChoices

    ticket_item_type = models.CharField(
        max_length=50,
        choices=TicketTypeChoices.choices,
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

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

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


class ReEntryItem(BaseItem, models.Model):
    edit_history_model = ReEntryItemEditHistory

    re_entry = models.ForeignKey(
        "entrance.ReEntry",
        on_delete=models.PROTECT,
        related_name="re_entry_items",
    )

    class Meta:
        db_table = "entrance_re_entry_items"


class ReEntryStatusHistory(BaseStatusHistory, models.Model):
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
            f"Status {self.prev_status} → {self.new_status} "
            f"for Ticket {self.re_entry.id}"
        )


class ReEntry(BaseEntranceRecord, models.Model):
    StatusChoices = ReEntryStatusChoices

    item_model = ReEntryItem

    status_history_model = ReEntryStatusHistory

    ticket = models.ForeignKey(
        "entrance.Ticket",
        on_delete=models.PROTECT,
        related_name="re_entries",
        db_index=True,
    )

    status = models.CharField(
        max_length=50,
        choices=ReEntryStatusChoices.choices,
        default=ReEntryStatusChoices.PENDING,
        db_index=True,
    )

    visitors_left = models.IntegerField()

    visitors_returned = models.IntegerField(null=True)

    completed_time = models.DateTimeField(null=True)

    objects = ReEntryManager()

    class Meta:
        db_table = "entrance_re_entries"

    def __str__(self):
        return f"Re-Entry {self.ticket.vehicle.plate_number} - {self.status}"

    @property
    def items_completed(self):
        additional_visitors = self.visitors_left - (self.visitors_returned or 0)
        added_items = sum(item.visitor_count for item in self.re_entry_items.all())
        return additional_visitors - added_items == 0

    def validate_status(self):
        if self.status not in [
            ReEntryStatusChoices.PENDING_PAYMENT,
        ]:
            error_message = "Only re entries in pending payment state can add items"
            raise ValueError(error_message)

        return True

    def process_return(self, visitors_returned: int, performed_by: User):
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
