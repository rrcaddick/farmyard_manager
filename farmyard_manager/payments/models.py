from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from model_utils.models import SoftDeletableModel
from model_utils.models import TimeStampedModel

from farmyard_manager.core.models import CleanBeforeSaveModel
from farmyard_manager.core.models import TransitionTextChoices
from farmyard_manager.core.models import UUIDModelMixin
from farmyard_manager.core.models import UUIDRefNumberModelMixin
from farmyard_manager.payments.managers import PaymentManager
from farmyard_manager.payments.managers import RefundManager
from farmyard_manager.payments.managers import RefundTransactionItemManager
from farmyard_manager.payments.managers import RefundVehicleAllocationManager
from farmyard_manager.payments.managers import TransactionItemManager

if TYPE_CHECKING:
    from django.db.models.query import QuerySet

    from farmyard_manager.entrance.models import ReEntry
    from farmyard_manager.entrance.models import Ticket
    from farmyard_manager.entrance.models.base import BaseEntranceRecord
    from farmyard_manager.entrance.models.re_entry import ReEntryItem
    from farmyard_manager.entrance.models.ticket import TicketItem
    from farmyard_manager.users.models import User
    from farmyard_manager.vehicles.models import Vehicle


class Payment(
    UUIDRefNumberModelMixin,
    CleanBeforeSaveModel,
    TimeStampedModel,
    SoftDeletableModel,
    models.Model,
):
    """Payment model that holds all transactions"""

    # TODO: Add role based permissions for user actions
    #         * add_transaction
    #         * initiate_refund
    #         * add/remove tickets and re-entries
    #         * update_status

    class PaymentStatusChoices(TransitionTextChoices):
        PENDING_SETTLEMENT = ("pending_settlement", "Pending Settlement")
        PARTIALLY_SETTLED = ("partially_settled", "Partially Settled")
        SETTLED = ("settled", "Settled")
        PARTIALLY_REFUNDED = ("partially_refunded", "Partially Refunded")
        REFUNDED = ("refunded", "Refunded")

        @classmethod
        def get_transition_map(cls) -> dict:
            return {
                cls.PENDING_SETTLEMENT: [cls.PARTIALLY_SETTLED, cls.SETTLED],
                cls.PARTIALLY_SETTLED: [cls.SETTLED],
                cls.SETTLED: [cls.REFUNDED, cls.PARTIALLY_REFUNDED],
                cls.PARTIALLY_REFUNDED: [cls.REFUNDED],
                cls.REFUNDED: [],
            }

    tickets: "QuerySet[Ticket]"
    re_entries: "QuerySet[ReEntry]"

    transaction_items: "QuerySet[TransactionItem]"

    refunds: "QuerySet[Refund]"

    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="payments",
    )

    status = models.CharField(
        max_length=50,
        db_index=True,
        choices=PaymentStatusChoices.choices,
        default=PaymentStatusChoices.PENDING_SETTLEMENT,
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    objects: PaymentManager = PaymentManager()

    class Meta:
        db_table = "payments_payments"

    def __str__(self):
        return f"Payment {self.ref_number} - {self.status}"

    @property
    def total_due(self):
        """
        Total amount due for this payment including tickets and re-entries
        """
        ticket_total = sum(ticket.total_due for ticket in self.tickets.all())
        re_entry_total = sum(re_entry.total_due for re_entry in self.re_entries.all())
        return ticket_total + re_entry_total

    @property
    def total_due_count(self):
        """
        Total visitor count for this payment including tickets and re-entries
        """
        return sum(ticket.total_due_visitors for ticket in self.tickets.all()) + sum(
            re_entry.total_due_visitors for re_entry in self.re_entries.all()
        )

    @property
    def total_paid(self):
        """Total of processed transactions"""
        return sum(
            transaction.amount
            for transaction in self.transaction_items.all()
            if transaction.status == TransactionItem.StatusChoices.PROCESSED
        )

    @property
    def total_paid_count(self):
        """Visitor count covered by processed transactions"""
        return sum(
            transaction.visitor_count
            for transaction in self.transaction_items.all()
            if transaction.status == TransactionItem.StatusChoices.PROCESSED
        )

    @property
    def total_outstanding(self):
        """Unpaid balance"""
        return max(self.total_due - self.total_paid, 0)

    @property
    def total_outstanding_count(self):
        """Unpaid balance"""
        return max(self.total_due_count - self.total_paid_count, 0)

    @property
    def refund_deadline(self):
        """Calculate refund deadline based on payment completion"""
        if not self.completed_at:
            return None
        hours = getattr(settings, "REFUND_TIME_LIMIT_HOURS", 1)
        return self.completed_at + timedelta(hours=hours)

    @property
    def is_refundable(self):
        """
        Check if payment is still within refund time window and status allows refund
        """
        return (
            self.status
            in [
                self.PaymentStatusChoices.SETTLED,
                self.PaymentStatusChoices.PARTIALLY_REFUNDED,
            ]
            and timezone.now() <= self.refund_deadline
            if self.refund_deadline
            else False
        )

    @property
    def total_processed_refunds(self):
        """Total amount refunded across all processed refunds"""
        return sum(
            refund.proccessed_refund_amount
            for refund in self.refunds.filter(status=Refund.StatusChoices.SETTLED)
        )

    @property
    def total_pending_refunds(self):
        """Total amount refunded across all processed refunds"""
        return sum(
            refund.pending_refund_amount
            for refund in self.refunds.filter(
                status__in=[
                    Refund.StatusChoices.PENDING_ALLOCATIONS,
                    Refund.StatusChoices.PENDING_TRANSACTIONS,
                    Refund.StatusChoices.PENDING_SETTLEMENT,
                ],
            )
        )

    @property
    def remaining_refundable_amount(self):
        """Remaining amount that can still be refunded"""
        return max(
            self.total_paid - self.total_processed_refunds - self.total_pending_refunds,
            0,
        )

    @property
    def remaining_refundable_count(self):
        """Remaining visitor count that can still be refunded"""
        return max(
            self.total_paid - self.total_processed_refunds - self.total_pending_refunds,
            0,
        )

    def add_entrance_record(self, item: "BaseEntranceRecord"):
        """Associate a ticket or re-entry with this payment"""
        TicketModel: type[Ticket] = apps.get_model("entrance", "Ticket")  # noqa: N806

        item_type = "Ticket" if isinstance(item, TicketModel) else "Re entry"

        if item.payment is not None:
            error_message = (
                f"{item_type} {item.ref_number} already has a payment assigned"
            )
            raise ValidationError(error_message)

        item.assign_payment(self)

        return item

    def remove_entrance_record(self, item: "BaseEntranceRecord"):
        """Remove a ticket or re-entry with this payment"""
        TicketModel: type[Ticket] = apps.get_model("entrance", "Ticket")  # noqa: N806

        item_type = "Ticket" if isinstance(item, TicketModel) else "Re entry"

        if item.payment != self:
            error_message = (
                f"{item_type} {item.ref_number} is not assigned to this payment"
            )
            raise ValidationError(error_message)

        if self.status != self.PaymentStatusChoices.PENDING_SETTLEMENT:
            error_message = f"Cannot remove {item_type.lower()} from processed payment"
            raise ValidationError(error_message)

        item.remove_pending_payment()

        return item

    def add_transaction(self, amount: Decimal, added_by: "User", **kwargs):
        """Adds a successful transaction item to this payment and updates status"""
        transaction = TransactionItem.objects.create_payment_transaction(
            self,
            amount,
            added_by,
            **kwargs,
        )

        # Ensure payment instance adding transaction is up to date so update
        # status evaluates all items
        self.refresh_from_db()

        # Update status to paid or partially paid depending on self.total_outstanding
        self.update_status()

        return transaction

    def update_status(self, new_status: PaymentStatusChoices | None = None):
        """
        Automatically update status based on payment
        amounts and set completed_at if fully paid
        """
        old_status = self.status

        if new_status is None:
            # If no payments have been made, keep status as pending
            if self.total_paid == 0:
                return

            # Partial payment made
            if self.total_outstanding > 0:
                new_status = self.PaymentStatusChoices.PARTIALLY_SETTLED
            elif self.total_outstanding == 0:
                new_status = self.PaymentStatusChoices.SETTLED
                if not self.completed_at:
                    self.completed_at = timezone.now()

        # Validate transition
        self.PaymentStatusChoices.validate_choice_transition(old_status, new_status)
        self.status = str(new_status)
        self.save(update_fields=["status", "completed_at"])

    def initiate_refund(
        self,
        requested_by: "User",
        vehicle: "Vehicle",
        reason: str,
        **kwargs,
    ) -> "Refund":
        """
        Starts a refund process for this payment. Returns a empty refund object for
        allocation and transaction items to attach to. Vehicle model requirements,
        ensures presence of vehile as vehicle is retrieved from scan data in serializer
        """
        return Refund.objects.initiate_refund(
            self,
            requested_by,
            vehicle,
            reason,
            **kwargs,
        )

    def clean(self):
        """Validate payment state"""
        if (
            self.status == self.PaymentStatusChoices.SETTLED
            and self.total_outstanding > 0
        ):
            error_message = "Payment still has outstanding balance"
            raise ValidationError(error_message)

        # Payment needs to be attached to at least one source
        if not self.tickets.exists() and not self.re_entries.exists():
            error_message = "Payment must have at least one ticket or re-entry"
            raise ValidationError(error_message)

        # Prevent negative total amounts
        if self.total_due < 0:
            error_message = "Payment total cannot be negative"
            raise ValidationError(error_message)

        # Prevent overpayment beyond total due
        if self.total_paid > self.total_due:
            error_message = (
                f"Payment amount (R{self.total_paid}) exceeds "
                f"total due (R{self.total_due})"
            )
            raise ValidationError(error_message)


class TransactionItem(
    UUIDModelMixin,
    CleanBeforeSaveModel,
    TimeStampedModel,
    SoftDeletableModel,
    models.Model,
):
    class PaymentTypeChoices(models.TextChoices):
        CASH = ("cash", "Cash")
        CARD = ("card", "Card")

    class StatusChoices(TransitionTextChoices):
        PROCESSED = ("processed", "Processed")
        PARTIALLY_REFUNDED = ("partially_refunded", "Partially Refunded")
        REFUNDED = ("refunded", "Refunded")

        @classmethod
        def get_transition_map(cls) -> dict:
            return {
                cls.PROCESSED: [cls.PARTIALLY_REFUNDED, cls.REFUNDED],
                cls.PARTIALLY_REFUNDED: [cls.REFUNDED],
                cls.REFUNDED: [],
            }

    refund_transaction_items: "QuerySet[RefundTransactionItem]"

    payment = models.ForeignKey(
        Payment,
        on_delete=models.PROTECT,
        related_name="transaction_items",
    )

    added_by = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="payment_transactions",
    )

    shift = models.ForeignKey(
        "shifts.Shift",
        on_delete=models.PROTECT,
        related_name="payments",
    )

    payment_type = models.CharField(
        max_length=50,
        choices=PaymentTypeChoices.choices,
        db_index=True,
    )

    status = models.CharField(
        max_length=50,
        choices=StatusChoices.choices,
        db_index=True,
    )

    visitor_count = models.IntegerField()

    amount = models.DecimalField(max_digits=10, decimal_places=2)

    cash_tendered = models.DecimalField(max_digits=10, decimal_places=2, null=True)

    addpay_rrn = models.CharField(max_length=255, blank=True)

    addpay_transaction_id = models.CharField(max_length=255, blank=True)

    addpay_card_number = models.CharField(max_length=255, blank=True)

    addpay_cardholder_name = models.CharField(max_length=255, blank=True)

    addpay_response_data = models.JSONField(null=True, blank=True)

    objects: TransactionItemManager = TransactionItemManager()

    class Meta:
        db_table = "payments_transaction_items"

    def __str__(self):
        return f"{self.payment_type} - R {self.amount}"

    @property
    def is_cash_transaction(self):
        return self.payment_type == self.PaymentTypeChoices.CASH

    @property
    def change_due(self):
        if self.is_card_transaction:
            error_message = "Change not possible on card payments"
            raise ValueError(error_message)

        if self.cash_tendered is None:
            error_message = "Cash tendered is required to calculate change"
            raise ValueError(error_message)

        return self.cash_tendered - self.amount

    @property
    def is_card_transaction(self):
        return self.payment_type == self.PaymentTypeChoices.CARD

    @property
    def is_missing_addpay_data(self):
        return self.is_card_transaction and any(
            not field
            for field in [
                self.addpay_rrn,
                self.addpay_transaction_id,
                self.addpay_card_number,
                self.addpay_cardholder_name,
            ]
        )

    @property
    def total_processed_refund_amount(self):
        """Total amount refunded from this transaction item"""
        return sum(
            refund_transaction.processed_amount
            for refund_transaction in self.refund_transaction_items.filter(
                status=RefundTransactionItem.StatusChoices.PROCESSED,
            )
        )

    @property
    def total_processed_refund_count(self):
        """Total visitor count refunded from this transaction item"""
        return sum(
            refund_transaction.visitor_count
            for refund_transaction in self.refund_transaction_items.filter(
                status=RefundTransactionItem.StatusChoices.PROCESSED,
            )
        )

    @property
    def total_pending_refund_amount(self):
        """Total amount refunded from this transaction item"""
        return sum(
            refund_transaction.requested_amount
            for refund_transaction in self.refund_transaction_items.filter(
                refund__status=RefundTransactionItem.StatusChoices.PENDING,
            )
        )

    @property
    def total_pending_refund_count(self):
        """Total amount refunded from this transaction item"""
        return sum(
            refund_transaction.visitor_count
            for refund_transaction in self.refund_transaction_items.filter(
                refund__status=RefundTransactionItem.StatusChoices.PENDING,
            )
        )

    @property
    def remaining_refundable_amount(self):
        """Amount that can still be refunded from this transaction"""
        return max(
            self.amount
            - (self.total_processed_refund_amount + self.total_pending_refund_amount),
            0,
        )

    @property
    def remaining_refundable_count(self):
        """Amount that can still be refunded from this transaction"""
        return max(
            self.visitor_count
            - (self.total_processed_refund_count + self.total_pending_refund_count),
            0,
        )

    def clean(self):
        if self.is_cash_transaction:
            if self.cash_tendered is None:
                error_message = "Cash tendered is required for cash payments"
                raise ValueError(error_message)
            if self.cash_tendered < self.amount:
                error_message = (
                    "Cash tendered must be greater than or equal to the amount"
                )
                raise ValueError(error_message)

        if self.is_card_transaction and self.is_missing_addpay_data:
            error_message = "Cannot save card transaction without AddPay data"
            raise ValueError(error_message)

    def delete(self, *args, **kwargs):  # noqa: ARG002
        """Prevent deletion of transaction items on processed payments"""
        error_message = "Can't delete processed transaction items"
        raise ValidationError(error_message)


class RefundVehicleAllocation(
    UUIDModelMixin,
    CleanBeforeSaveModel,
    TimeStampedModel,
    SoftDeletableModel,
    models.Model,
):
    class RefundVehicleAllocationStatusChoices(TransitionTextChoices):
        PENDING_COUNT = ("pending_count", "Pending Count")
        COUNTED = ("counted", "Counted")
        SETTLED = ("settled", "Settled")
        DENIED = ("denied", "Denied")
        CANCELED = ("canceled", "Canceled")

        @classmethod
        def get_transition_map(cls) -> dict:
            return {
                cls.PENDING_COUNT: [cls.COUNTED, cls.CANCELED],
                cls.COUNTED: [cls.SETTLED, cls.DENIED, cls.CANCELED],
                cls.SETTLED: [],
                cls.DENIED: [],
                cls.CANCELED: [],
            }

    refund = models.ForeignKey["Refund", "Refund"](
        "payments.Refund",
        on_delete=models.CASCADE,
        related_name="vehicle_allocations",
    )

    ticket_item = models.ForeignKey["TicketItem | None", "TicketItem | None"](
        "entrance.TicketItem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="refund_allocations",
    )

    re_entry_item = models.ForeignKey["ReEntryItem | None", "ReEntryItem | None"](
        "entrance.ReEntryItem",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="refund_allocations",
    )

    visitor_count = models.PositiveIntegerField(null=True, blank=True)

    status = models.CharField(
        max_length=20,
        choices=RefundVehicleAllocationStatusChoices.choices,
        default=RefundVehicleAllocationStatusChoices.PENDING_COUNT,
    )

    processed_by = models.ForeignKey["User | None", "User | None"](
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="allocated_refunds",
    )

    objects: RefundVehicleAllocationManager = RefundVehicleAllocationManager()

    class Meta:
        verbose_name = _("Refund Allocation")
        verbose_name_plural = _("Refund Allocations")
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(ticket_item__isnull=False, re_entry_item__isnull=True)
                    | models.Q(ticket_item__isnull=True, re_entry_item__isnull=False)
                ),
                name="exactly_one_entrance_item",
            ),
        ]
        indexes = [
            models.Index(fields=["refund", "status"]),
        ]

    def __str__(self):
        return f"Vehicle {self.vehicle.plate_number} - {self.visitor_count} visitors"

    @property
    def entrance_item(self) -> "TicketItem | ReEntryItem":
        item = self.ticket_item or self.re_entry_item
        assert item is not None, (
            "Exactly one entrance item must be set (invariant violated)"
        )
        return item

    @property
    def vehicle(self) -> "Vehicle":
        return self.entrance_item.vehicle

    def clean(self):
        # Ensures exactly one entrance item set
        if (self.ticket_item and self.re_entry_item) or not self.entrance_item:
            raise ValidationError(
                _("Allocation needs to be linked to a single entrance item"),
            )

        # Ensures that refund payment matches entrance item payment
        if self.entrance_item.payment != self.refund.payment:
            raise ValidationError(
                _("Cannot allocated a vehicle from a different payment"),
            )

        # Prevents 0 visitor count
        if self.visitor_count is not None and self.visitor_count <= 0:
            raise ValidationError(_("Visitor count must be greater than 0."))

        # Ensures allocation count stays within refundable limit
        if self.visitor_count > self.entrance_item.remaining_refundable_visitor_count:
            raise ValidationError(_("Count exceeds remaining refundable visitors."))

    def update_visitor_count(self, count: int):
        """
        Updates the allocation visitor count. Ensure the count does not
        exceed remaining refundable count
        """
        if self.status not in [
            self.RefundVehicleAllocationStatusChoices.PENDING_COUNT,
            self.RefundVehicleAllocationStatusChoices.COUNTED,
        ]:
            error_message = "Can't update count on completed allocations'"
            raise ValueError(error_message)

        if count <= 0:
            error_message = "Count cannot be 0 or negative"
            raise ValueError(error_message)

        if count > self.entrance_item.remaining_refundable_visitor_count:
            error_message = "Count exceeds remaining refundable amount"
            raise ValueError(error_message)

        self.visitor_count = count
        self.status = self.RefundVehicleAllocationStatusChoices.COUNTED


class RefundTransactionItem(
    UUIDModelMixin,
    CleanBeforeSaveModel,
    TimeStampedModel,
    SoftDeletableModel,
    models.Model,
):
    """
    Represents individual transaction items being refunded.
    Links back to original TransactionItem to maintain payment method constraints.
    """

    class StatusChoices(TransitionTextChoices):
        PENDING = ("pending", "Pending")
        PROCESSED = ("processed", "Processed")
        CANCELED = ("canceled", "Canceled")

        @classmethod
        def get_transition_map(cls) -> dict:
            return {
                cls.PENDING: [cls.PROCESSED, cls.CANCELED],
                cls.PROCESSED: [],
                cls.CANCELED: [],
            }

    refund = models.ForeignKey["Refund", "Refund"](
        "payments.Refund",
        on_delete=models.PROTECT,
        related_name="refund_transaction_items",
    )

    transaction_item = models.ForeignKey["TransactionItem", "TransactionItem"](
        "payments.TransactionItem",
        on_delete=models.PROTECT,
        related_name="refund_transaction_items",
    )

    status = models.CharField(
        max_length=50,
        choices=StatusChoices.choices,
        default=StatusChoices.PENDING,
    )

    visitor_count = models.IntegerField()

    requested_amount = models.DecimalField(max_digits=10, decimal_places=2)

    processed_amount = models.DecimalField(max_digits=10, decimal_places=2)

    added_by = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="added_refund_transactions",
    )

    processed_by = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="processed_refund_transactions",
        null=True,
        blank=True,
    )

    processed_at = models.DateTimeField(null=True, blank=True)

    objects: RefundTransactionItemManager = RefundTransactionItemManager()

    class Meta:
        db_table = "payments_refund_transaction_items"

    def __str__(self):
        return f"RefundTransaction {self.id} - {self.status} - R{self.processed_amount}"

    def clean(self):
        """Validate refund transaction constraints"""
        # Ensure visitor count is positive
        if self.visitor_count <= 0:
            error_message = "Visitor count must be greater than 0"
            raise ValidationError(error_message)

        # Ensure that transaction is within vehicle allocation limits
        if self.visitor_count > self.refund.remaining_refundable_count:
            error_message = "Requested refund count more than added allocated count"
            raise ValidationError(error_message)

        # Ensure amount doesn't exceed what's available from original transaction
        if self.visitor_count > self.transaction_item.remaining_refundable_count:
            error_message = (
                "Requested refund count more than remaining refundable count"
            )
            raise ValidationError(error_message)

    def mark_processed(
        self,
        processed_by: "User",
        processed_amount: Decimal,
    ):
        """
        Marks pending refund transaction as processed. Called from the addpay
        wehook for card payemnts
        """

        if self.status != self.StatusChoices.PENDING:
            error_message = "Only pending refund transactions can be processed"
            raise ValidationError(error_message)

        self.status = self.StatusChoices.PROCESSED
        self.processed_amount = processed_amount
        self.processed_by = processed_by
        self.processed_at = timezone.now()

        self.save(
            update_fields=[
                "status",
                "processed_by",
                "processed_amount",
                "processed_at",
            ],
        )


class Refund(
    UUIDRefNumberModelMixin,
    CleanBeforeSaveModel,
    TimeStampedModel,
    SoftDeletableModel,
    models.Model,
):
    """
    Represents a refund request for a payment.
    Each refund is tied to one specific payment.
    """

    # TODO: Add role based permissions for user actions
    # TODO: Complete the refund denial and cancellation processes

    class StatusChoices(TransitionTextChoices):
        PENDING_ALLOCATIONS = ("pending_allocations", "Pending Allocations")
        PENDING_TRANSACTIONS = ("pending_transactions", "Pending Transactions")
        PENDING_SETTLEMENT = ("pending_settlement", "Pending Settlement")
        SETTLED = ("settled", "Settled")
        DENIED = ("denied", "Denied")
        CANCELED = ("canceled", "Canceled")

        @classmethod
        def get_transition_map(cls) -> dict:
            return {
                cls.PENDING_ALLOCATIONS: [cls.PENDING_TRANSACTIONS, cls.CANCELED],
                cls.PENDING_TRANSACTIONS: [cls.PENDING_SETTLEMENT, cls.CANCELED],
                cls.PENDING_SETTLEMENT: [cls.SETTLED, cls.DENIED, cls.CANCELED],
                cls.SETTLED: [],
                cls.DENIED: [],
                cls.CANCELED: [],
            }

    vehicle_allocations: "QuerySet[RefundVehicleAllocation]"

    refund_transaction_items: "QuerySet[RefundTransactionItem]"

    payment = models.ForeignKey["Payment", "Payment"](
        Payment,
        on_delete=models.PROTECT,
        related_name="refunds",
    )

    reason = models.TextField(blank=False)

    status = models.CharField(
        max_length=50,
        choices=StatusChoices.choices,
        default=StatusChoices.PENDING_ALLOCATIONS,
        db_index=True,
    )

    requested_by = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="requested_refunds",
    )

    completed_by = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="approved_refunds",
        null=True,
        blank=True,
    )

    completed_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects: RefundManager = RefundManager()

    class Meta:
        db_table = "payments_refunds"

    def __str__(self):
        return (
            f"Refund {self.ref_number} - {self.status} - "
            f"R{self.proccessed_refund_amount}"
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_status = self.status if self.pk else None

    @property
    def total_allocation_count(self):
        """Max visitors that can be refunded , based off added vehicle allocations"""
        return sum(
            allocation.visitor_count for allocation in self.vehicle_allocations.all()
        )

    @property
    def processed_refund_count(self):
        """Total visitor count already refunded"""
        return sum(
            refund_item.visitor_count
            for refund_item in self.refund_transaction_items.filter(
                status=RefundTransactionItem.StatusChoices.PROCESSED,
            )
        )

    @property
    def pending_refund_count(self):
        """Total visitor count pending refund"""
        return sum(
            refund_item.visitor_count
            for refund_item in self.refund_transaction_items.filter(
                status=RefundTransactionItem.StatusChoices.PENDING,
            )
        )

    @property
    def proccessed_refund_amount(self):
        """Total visitor count being refunded"""
        return sum(
            item.processed_amount
            for item in self.refund_transaction_items.filter(
                status=RefundTransactionItem.StatusChoices.PROCESSED,
            )
        )

    @property
    def pending_refund_amount(self):
        """Total visitor count being refunded"""
        return sum(
            item.processed_amount
            for item in self.refund_transaction_items.filter(
                status=RefundTransactionItem.StatusChoices.PENDING,
            )
        )

    @property
    def remaining_refundable_count(self):
        return max(
            self.total_allocation_count
            - (self.processed_refund_count + self.pending_refund_count),
            0,
        )

    @property
    def allocations_count_complete(self) -> bool:
        qs = self.vehicle_allocations
        return (
            qs.exists()
            and not qs.filter(
                status=RefundVehicleAllocation.RefundVehicleAllocationStatusChoices.PENDING_COUNT,
            ).exists()
        )

    @property
    def all_transactions_processed(self) -> bool:
        return self.processed_refund_count == self.total_allocation_count

    @transaction.atomic
    def complete_refund(self, completed_by: "User"):
        """
        Mark refund as settled, update status, completed_at and by and payment status
        """
        if not self.all_transactions_processed:
            error_message = "Cannot complete refund with pending transactions"
            raise ValidationError(error_message)

        if self.status in [self.StatusChoices.SETTLED, self.StatusChoices.DENIED]:
            error_message = "Cannot complete already approved or denied refunds"
            raise ValidationError(error_message)

        if self.processed_refund_count != self.total_allocation_count:
            error_message = "Refund still contains unprocessed allocations"
            raise ValidationError(error_message)

        # Update completion fields
        self.completed_by = completed_by
        self.completed_at = timezone.now()

        # Validate and udpate status transition
        self.StatusChoices.validate_choice_transition(
            self.status,
            self.StatusChoices.SETTLED,
        )
        self.status = self.StatusChoices.SETTLED

        self.save(update_fields=["completed_by", "completed_at", "status"])

        # Settle all allocations
        self.vehicle_allocations.update(
            status=RefundVehicleAllocation.RefundVehicleAllocationStatusChoices.SETTLED,
        )

        # Update payment status
        payment_status = (
            Payment.PaymentStatusChoices.REFUNDED
            if self.payment.total_paid == self.proccessed_refund_amount
            else Payment.PaymentStatusChoices.PARTIALLY_REFUNDED
        )

        self.payment.update_status(payment_status)

    def deny_refund(self, denied_by: "User", reason: str = ""):
        """Deny a refund request"""
        if self.status in [self.StatusChoices.SETTLED, self.StatusChoices.DENIED]:
            error_message = "Cannot deny already approved or denied refunds"
            raise ValidationError(error_message)

        if reason:
            self.reason += f"Denied: {reason}"

        self.status = self.StatusChoices.DENIED
        self.completed_by = denied_by
        self.save(update_fields=["status", "approved_by", "reason"])

    def update_status(self, new_status: "Refund.StatusChoices"):
        """Validate status transition and update refund status"""
        prev_status = self.status

        self.StatusChoices.validate_choice_transition(prev_status, new_status)

        self.status = new_status.value

        self.save(update_fields=["status"])

    def add_allocation(
        self,
        vehicle: "Vehicle",
        processed_by: "User",
        **kwargs,
    ) -> "RefundVehicleAllocation":
        """Tracks per vehicle counts being refunded"""
        return RefundVehicleAllocation.objects.add_refund_allocation(
            self,
            vehicle,
            processed_by,
            **kwargs,
        )

    @transaction.atomic
    def update_allocation_counts(
        self,
        allocation_counts: dict[RefundVehicleAllocation, int],
    ):
        """
        Updates the counts for each added vehicle allocation
        """
        allocations_to_update = []
        for allocation, count in allocation_counts.items():
            if allocation.refund != self:
                error_message = "Invalid allocation provided"
                raise ValueError(error_message)

            allocation.update_visitor_count(count)
            allocations_to_update.append(allocation)

        allocations = RefundVehicleAllocation.objects.bulk_update(
            allocations_to_update,
            ["visitor_count", "status"],
        )

        if self.allocations_count_complete:
            self.update_status(self.StatusChoices.PENDING_TRANSACTIONS)

        return allocations

    def add_refund_transaction(
        self,
        transaction_item: TransactionItem,
        added_by: "User",
        visitor_count: int,
        requested_amount: Decimal,
        **kwargs,
    ):
        """Add a transaction item to this refund"""
        return RefundTransactionItem.objects.add_refund_transaction(
            self,
            transaction_item,
            added_by,
            visitor_count,
            requested_amount,
            **kwargs,
        )

    def process_refund_transaction(
        self,
        refund_transaction_item: "RefundTransactionItem",
        processed_by: "User",
        processed_amount: Decimal,
    ):
        """Marks a pending refund transaction as processed"""

        # Ensure that only manager are able to process refunds
        if processed_by.is_manager is False:
            error_message = "Only manager can process process refunds"
            raise ValidationError(error_message)

        with transaction.atomic():
            transaction_item = refund_transaction_item.mark_processed(
                processed_by=processed_by,
                processed_amount=processed_amount,
            )

            if self.all_transactions_processed:
                self.complete_refund(completed_by=processed_by)

            return transaction_item

    def clean(self):
        """Validate refund business rules"""
        if self.payment.status not in [
            Payment.PaymentStatusChoices.SETTLED,
            Payment.PaymentStatusChoices.PARTIALLY_REFUNDED,
        ]:
            error_message = "Can only refund settled or partially refunded payments"
            raise ValidationError(error_message)

        # Check refund amount doesn't exceed payment limits
        if self.pending_refund_amount > self.total_allocation_count:
            error_message = (
                f"Requested refund for {self.pending_refund_amount} visitors"
                f"exceed max refundable count of {self.total_allocation_count}"
            )
            raise ValidationError(error_message)

        # Validate status transitions
        if self.pk and hasattr(self, "_original_status"):
            self.StatusChoices.validate_choice_transition(
                self._original_status,
                self.status,
            )
