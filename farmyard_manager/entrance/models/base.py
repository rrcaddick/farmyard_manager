from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db import transaction
from model_utils.models import SoftDeletableModel
from model_utils.models import TimeStampedModel

from farmyard_manager.core.decorators import required_field
from farmyard_manager.core.decorators import requires_child_fields
from farmyard_manager.core.fields import SnakeCaseFK
from farmyard_manager.core.models import CleanBeforeSaveModel
from farmyard_manager.core.models import UUIDModelMixin
from farmyard_manager.core.models import UUIDRefNumberModelMixin
from farmyard_manager.payments.models import Payment
from farmyard_manager.payments.models import RefundVehicleAllocation
from farmyard_manager.utils.int_utils import is_int
from farmyard_manager.utils.model_utils import validate_text_choice
from farmyard_manager.utils.string_utils import to_snake_case

from .enums import ItemTypeChoices
from .pricing import Pricing

if TYPE_CHECKING:
    from django.db.models.query import QuerySet

    from farmyard_manager.users.models import User


class BaseStatusHistory(UUIDModelMixin, TimeStampedModel, models.Model):
    if TYPE_CHECKING:
        objects: models.Manager

    performed_by = SnakeCaseFK(
        "users.User",
        on_delete=models.PROTECT,
    )

    class Meta:
        abstract = True

    def delete(self, *args, **kwargs):  # noqa: ARG002
        error_message = "Status change entries cannot be deleted"
        raise ValidationError(error_message)


class BaseEditHistory(
    UUIDModelMixin,
    TimeStampedModel,
    CleanBeforeSaveModel,
    models.Model,
):
    if TYPE_CHECKING:
        objects: models.Manager

    ItemTypeChoices = ItemTypeChoices

    class FieldChoices(models.TextChoices):
        ITEM_TYPE = ("item_type", "Item Type")
        VISITOR_COUNT = ("visitor_count", "Visitor Count")

    field = models.CharField(
        max_length=50,
        choices=FieldChoices.choices,
        db_index=True,
    )

    prev_value = models.CharField(max_length=255)

    new_value = models.CharField(max_length=255)

    performed_by = SnakeCaseFK(
        "users.User",
        on_delete=models.PROTECT,
    )

    class Meta:
        abstract = True

    def __str__(self):
        return f"{self.field} edited by {self.performed_by}"

    def clean(self):
        # Checks if the field is editable
        validate_text_choice(
            self.field,
            self.FieldChoices,
            f"{self.field} is not editable",
        )

        # Checks if the new value is a valid item type
        if self.field == self.FieldChoices.ITEM_TYPE:
            validate_text_choice(
                self.new_value,
                self.ItemTypeChoices,
                f"{self.new_value} is a valid item type",
            )

        # Checks if the new value is a valid visitor count
        if self.field == self.FieldChoices.VISITOR_COUNT:
            if is_int(self.new_value):
                new_visitor_count = int(self.new_value)
            else:
                error_message = "Visitor count must be a valid integer"
                raise ValidationError(error_message)

            if new_visitor_count < 1:
                error_message = "Visitor count must be greater than 0"
                raise ValidationError(error_message)

    def delete(self, *args, **kwargs):  # noqa: ARG002
        error_message = "Edit history entries cannot be deleted"
        raise ValidationError(error_message)


@requires_child_fields
class BaseItem(
    UUIDModelMixin,
    TimeStampedModel,
    SoftDeletableModel,
    CleanBeforeSaveModel,
    models.Model,
):
    ItemTypeChoices = ItemTypeChoices

    refund_allocations: "QuerySet[RefundVehicleAllocation]"

    created_by = SnakeCaseFK(
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
        null=True,
        blank=True,
    )

    class Meta:
        abstract = True

    def __str__(self):
        return f"{self.visitor_count} {self.item_type} visitors at {self.applied_price}"

    def clean(self):
        validate_text_choice(
            self.item_type,
            self.ItemTypeChoices,
            f"{self.item_type} is not a valid item type",
        )

    @required_field
    def edit_history_model(self) -> type[BaseEditHistory]:
        raise NotImplementedError

    @property
    def amount_due(self):
        """
        Total amount due for this item. None public items have
        different settlements paths
        """
        return self.visitor_count * (self.applied_price or 0)

    @property
    def snake_case_model_name(self):
        return to_snake_case(self.__class__.__name__)

    @property
    def processed_refund_visitor_count(self):
        return sum(
            allocation.visitor_count
            for allocation in self.refund_allocations.filter(
                status=RefundVehicleAllocation.RefundVehicleAllocationStatusChoices.SETTLED,
            )
        )

    @property
    def pending_refund_visitor_count(self):
        return sum(
            allocation.visitor_count
            for allocation in self.refund_allocations.filter(
                status__in=[
                    RefundVehicleAllocation.RefundVehicleAllocationStatusChoices.PENDING_COUNT,
                    RefundVehicleAllocation.RefundVehicleAllocationStatusChoices.COUNTED,
                ],
            )
        )

    @property
    def remaining_refundable_visitor_count(self):
        return (
            self.visitor_count
            - self.processed_refund_visitor_count
            - self.pending_refund_visitor_count
        )

    # TODO: This is no longer needed. Remove once tests pass
    def get_price(self):
        if self.item_type is None:
            error_message = "Set item type befor getting price"
            raise ValueError(error_message)

        return Pricing.objects.get_price()

    def edit(
        self,
        performed_by: "User",
        item_type: str | None = None,
        visitor_count: int | None = None,
    ):
        with transaction.atomic():
            edit_history_entries: list[BaseEditHistory] = []
            update_fields = []

            # Item type changed
            if item_type and self.item_type != item_type:
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

                for entry in edit_history_entries:
                    entry.full_clean()

                self.edit_history_model.objects.bulk_create(edit_history_entries)

            return self


@requires_child_fields
class BaseEntranceRecord(
    UUIDRefNumberModelMixin,
    TimeStampedModel,
    SoftDeletableModel,
    models.Model,
):
    class Meta:
        abstract = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if hasattr(self, "status"):
            self._original_status = self.status

    def __str__(self):
        return f"{self.ref_number} - {self.status}"

    payment = SnakeCaseFK["Payment | None", "Payment | None"](
        "payments.Payment",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        pluralize_related_name=True,
    )

    @required_field
    def status(self) -> models.CharField:
        raise NotImplementedError

    @status.setter
    def status(self):
        raise NotImplementedError

    @required_field
    def item_model(self) -> type[BaseItem]:
        raise NotImplementedError

    @required_field
    def status_history_model(self) -> type[BaseStatusHistory]:
        raise NotImplementedError

    @property
    def snake_case_model_name(self):
        return to_snake_case(self.__class__.__name__)

    @property
    def items_name(self):
        return to_snake_case(self.item_model.__name__, pluralize=True)

    @property
    def items(self):
        items: QuerySet[BaseItem] = getattr(self, self.items_name).all()
        return items

    @property
    def total_due(self):
        return sum(item.amount_due for item in self.items)

    @property
    def total_visitors(self):
        return sum(item.visitor_count for item in self.items)

    @property
    def total_due_visitors(self):
        return sum(
            item.visitor_count
            for item in self.items
            if item.item_type == ItemTypeChoices.PUBLIC
        )

    @property
    def voided_items(self):
        return self.item_model.all_objects.all().filter(
            **{self.snake_case_model_name: self},
            is_removed=True,
        )

    @property
    def public_ticket_item(self):
        """
        The public entrance item, if it exists. Contains the visitor count
        for paid visitors. Used in refund vehicle allocations.
        """
        return self.items.filter(item_type=ItemTypeChoices.PUBLIC)

    def update_status(self, new_status: str, performed_by: "User"):
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
        created_by: "User",
        applied_price=None,
    ):
        # Get price for this type
        if applied_price is None:
            applied_price = (
                None if item_type != "public" else Pricing.objects.get_price()
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

    # TODO: Refactor to work with item instance - Must be moved to inheriting class
    def remove_item(self, item_id: int, performed_by: "User"):  # noqa: ARG002
        try:
            # Use the correct relation property name
            item = self.items.get(id=item_id)
        except self.item_model.DoesNotExist as err:
            error_message = f"{self.item_model.__name__} {item_id} not found"
            raise ValueError(error_message) from err

        item.delete()
        return True

    def initiate_payment(self):
        """Creates a payment for this entrance record"""
        return Payment.objects.initiate_entrance_payment(self)

    def assign_payment(self, payment: "Payment"):
        """
        Assigns this entrance records to an existing payment.
        Used on multi ticket payments
        """
        if self.payment:
            error_message = "Record is already assigned to a payment"
            raise ValueError(error_message)
        self.payment = payment
        self.save(update_fields=["payment"])

    def remove_pending_payment(self):
        if not self.payment:
            error_message = "No payment assigned to remove"
            raise ValueError(error_message)

        if self.payment.status != Payment.PaymentStatusChoices.PENDING_SETTLEMENT:
            error_message = "Can only remove pending payments"
            raise ValueError(error_message)

        self.payment = None
        self.save(update_fields=["payment"])
