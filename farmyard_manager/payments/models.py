from decimal import Decimal
from typing import TYPE_CHECKING

from django.db import models
from django.forms import ValidationError
from django.utils import timezone
from model_utils.models import SoftDeletableModel
from model_utils.models import TimeStampedModel

from farmyard_manager.core.models import TransitionTextChoices
from farmyard_manager.core.models import UUIDModelMixin
from farmyard_manager.core.models import UUIDRefNumberModelMixin
from farmyard_manager.payments.managers import PaymentManager

if TYPE_CHECKING:
    from django.db.models.query import QuerySet

    from farmyard_manager.entrance.models import ReEntry
    from farmyard_manager.entrance.models import Ticket
    from farmyard_manager.users.models import User


class Payment(
    UUIDRefNumberModelMixin,
    TimeStampedModel,
    SoftDeletableModel,
    models.Model,
):
    class PaymentStatusChoices(TransitionTextChoices):
        PENDING = ("pending", "Pending")
        PARTIALLY_PAID = ("partially_paid", "Partially Paid")
        PAID = ("paid", "Paid")
        REFUNDED = ("refunded", "Refunded")

        @classmethod
        def get_transition_map(cls) -> dict:
            return {
                cls.PENDING: [cls.PARTIALLY_PAID, cls.PAID],
                # TODO: Lock down refund process for partially paid tickets
                cls.PARTIALLY_PAID: [cls.PAID, cls.REFUNDED],
                cls.PAID: [cls.REFUNDED],
                cls.REFUNDED: [],
            }

    tickets: "QuerySet[Ticket]"
    transaction_items: "QuerySet[TransactionItem]"
    re_entries: "QuerySet[ReEntry]"

    status = models.CharField(
        max_length=50,
        choices=PaymentStatusChoices.choices,
        default=PaymentStatusChoices.PENDING,
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    objects: PaymentManager = PaymentManager()

    class Meta:
        db_table = "payments_payments"

    def __str__(self):
        # TODO: Add more details to the string representation
        return f"Payment - {self.status}"

    @property
    def total_due(self):
        ticket_total = sum(ticket.total_due for ticket in self.tickets.all())
        re_entry_total = sum(re_entry.total_due for re_entry in self.re_entries.all())
        return ticket_total + re_entry_total

    @property
    def total_paid(self):
        return sum(transaction.amount for transaction in self.transaction_items.all())

    @property
    def total_outstanding(self):
        return max(self.total_due - self.total_paid, 0)

    def update_status(self, new_status: PaymentStatusChoices | None = None):
        """Automatically update status based on payment amounts"""
        old_status = self.status

        if new_status is None:
            # If no payments have been made, keep status as pending
            if self.total_paid == 0:
                return

            # Partial payment maid
            if self.total_outstanding > 0:
                new_status = self.PaymentStatusChoices.PARTIALLY_PAID
            elif self.total_outstanding == 0:
                new_status = self.PaymentStatusChoices.PAID
                if not self.completed_at:
                    self.completed_at = timezone.now()

        # Validate transition
        self.PaymentStatusChoices.validate_choice_transition(old_status, new_status)
        self.status = str(new_status)
        self.save(update_fields=["status", "completed_at"])

    def add_transaction(  # noqa: PLR0913
        self,
        payment_type: str,
        amount: Decimal,
        created_by: "User",
        shift_id: int,
        cash_tendered: Decimal | None = None,
        addpay_rrn: str = "",
        addpay_transaction_id: str = "",
    ):
        if amount > self.total_outstanding:
            error_message = "Amount exceeds outstanding balance"
            raise ValueError(error_message)

        return TransactionItem.objects.create(
            payment_type=payment_type,
            amount=amount,
            created_by=created_by,
            shift_id=shift_id,
            cash_tendered=cash_tendered,
            addpay_rrn=addpay_rrn,
            addpay_transaction_id=addpay_transaction_id,
            payment=self,
        )

    def add_ticket(self, ticket: "Ticket"):
        ticket.assign_payment(self)
        return ticket

    # TODO: Do we want to allow multiple re-entries per payment?
    def add_re_entry(self, re_entry: "ReEntry"):
        """Add re-entry to this payment"""
        re_entry.assign_payment(self)
        return re_entry

    def can_process(self, employee: "User") -> bool:
        """Check if employee can process this payment"""
        if self.status == self.PaymentStatusChoices.PENDING:
            return True
        if self.status == self.PaymentStatusChoices.PARTIALLY_PAID:
            first_transaction = self.transaction_items.first()
            return (
                first_transaction is not None
                and first_transaction.created_by == employee
            )
        return False

    def initiate_refund(self):
        # Should this be handled by the Refund Manager?
        pass

    def clean(self):
        """Validate payment state"""
        if self.status == self.PaymentStatusChoices.PAID and self.total_outstanding > 0:
            error_message = "Payment still has outstanding balance"
            raise ValidationError(error_message)

        # Payment needs to be attached to at least one source
        if not self.tickets.exists() and not self.re_entries.exists():
            error_message = "Payment must have at least one ticket or re-entry"
            raise ValidationError(error_message)


class TransactionItem(UUIDModelMixin, TimeStampedModel, models.Model):
    class PaymentTypeChoices(models.TextChoices):
        CASH = ("cash", "Cash")
        CARD = ("card", "Card")

    payment = models.ForeignKey(
        Payment,
        on_delete=models.PROTECT,
        related_name="transaction_items",
    )

    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="payments",
    )

    shift = models.ForeignKey(
        "shifts.Shift",
        on_delete=models.PROTECT,
        related_name="payments",
    )

    payment_type = models.CharField(max_length=50, choices=PaymentTypeChoices.choices)

    amount = models.DecimalField(max_digits=10, decimal_places=2)

    cash_tendered = models.DecimalField(max_digits=10, decimal_places=2, null=True)

    addpay_rrn = models.CharField(
        max_length=255,
        blank=True,
    )

    addpay_transaction_id = models.CharField(
        max_length=255,
        blank=True,
    )

    class Meta:
        db_table = "payments_transaction_items"

    def __str__(self):
        return f"{self.payment_type} - R {self.amount}"

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        if self.payment_type not in [
            choice[0] for choice in self.PaymentTypeChoices.choices
        ]:
            error_message = "Invalid payment type"
            raise ValueError(error_message)

        if self.payment_type == self.PaymentTypeChoices.CASH:
            if self.cash_tendered is None:
                error_message = "Cash tendered is required for cash payments"
                raise ValueError(error_message)
            if self.cash_tendered < self.amount:
                error_message = (
                    "Cash tendered must be greater than or equal to the amount"
                )
                raise ValueError(error_message)

        if self.payment_type == self.PaymentTypeChoices.CARD and (
            self.addpay_rrn == "" or self.addpay_transaction_id == ""
        ):
            error_message = (
                "AddPay RRN and transaction ID are required for card payments"
            )
            raise ValueError(error_message)

    @property
    def change_due(self):
        if self.payment_type == self.PaymentTypeChoices.CARD:
            error_message = "Change not possible on card payments"
            raise ValueError(error_message)

        if self.cash_tendered is None:
            error_message = "Cash tendered is required to calculate change"
            raise ValueError(error_message)

        return self.cash_tendered - self.amount


class RefundStatusChoices(models.TextChoices):
    PENDING = ("pending", "Pending")
    APPROVED = ("approved", "Approved")
    PROCESSED = ("processed", "Processed")
    DENIED = ("denied", "Denied")


class Refund(UUIDModelMixin, TimeStampedModel, models.Model):
    """
    Represents a refund request for a ticket and payment.
    """

    StatusChoices = RefundStatusChoices

    ticket = models.ForeignKey(
        "entrance.Ticket",
        on_delete=models.PROTECT,
        related_name="refunds",
    )

    payment = models.ForeignKey(
        Payment,
        on_delete=models.PROTECT,
        related_name="refunds",
    )

    total_amount = models.DecimalField(max_digits=10, decimal_places=2)

    reason = models.TextField()

    status = models.CharField(
        max_length=50,
        choices=RefundStatusChoices.choices,
        default=RefundStatusChoices.PENDING,
    )

    requested_by = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="requested_refunds",
    )

    approved_by = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="approved_refunds",
        null=True,
        blank=True,
    )

    processed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Refund {self.uuid} - {self.status}"

    def approve_refund(self):
        pass

    def process_refund(self):
        pass

    def add_refund_transaction(self):
        pass


class RefundTransaction(TimeStampedModel, models.Model):
    """
    Represents individual transactions related to a refund.
    """

    StatusChoices = RefundStatusChoices

    refund = models.ForeignKey(
        Refund,
        on_delete=models.PROTECT,
        related_name="refund_transactions",
    )

    transaction = models.ForeignKey(
        TransactionItem,
        on_delete=models.PROTECT,
        related_name="refund_references",
    )

    amount = models.DecimalField(max_digits=10, decimal_places=2)

    status = models.CharField(max_length=50, choices=RefundStatusChoices.choices)

    processed_by = models.ForeignKey(
        "users.User",
        on_delete=models.PROTECT,
        related_name="processed_refunds",
    )

    processed_at = models.DateTimeField()

    def __str__(self):
        return f"RefundTransaction {self.id} - {self.status}"

    def process_cash_refund(self):
        pass

    def process_card_refund(self):
        pass
