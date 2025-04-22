# Payments app models

from django.db import models
from model_utils.models import SoftDeletableModel
from model_utils.models import TimeStampedModel

from farmyard_manager.core.models import UUIDModelMixin
from farmyard_manager.core.models import UUIDRefNumberModelMixin
from farmyard_manager.entrance.models import Ticket
from farmyard_manager.users.models import User


class Payment(
    UUIDRefNumberModelMixin,
    TimeStampedModel,
    SoftDeletableModel,
    models.Model,
):
    """
    Represents a complete payment transaction that can include multiple tickets
    and different payment methods.
    """

    class PaymentStatusChoices(models.TextChoices):
        PAID = ("paid", "Paid")
        REFUNDED = ("refunded", "Refunded")
        PENDING = ("pending", "Pending")

    total_amount = models.DecimalField(max_digits=10, decimal_places=2)

    status = models.CharField(
        max_length=50,
        choices=PaymentStatusChoices.choices,
        default=PaymentStatusChoices.PENDING,
    )

    created_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="payments",
    )

    # TODO: Add a shift field to link payments to shifts when shift model is implemented

    def __str__(self):
        return f"Payment {self.ref_number} - {self.status}"

    def add_ticket(self):
        pass

    def add_transaction(self):
        pass

    def initiate_refund(self):
        # Should this be handled by the Refund Manager?
        pass


class PaymentTicket(UUIDModelMixin, TimeStampedModel, models.Model):
    """
    Links payments to tickets, allowing a single payment to cover multiple tickets.
    """

    payment = models.ForeignKey(
        Payment,
        on_delete=models.PROTECT,
        related_name="payment_tickets",
    )

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.PROTECT,
        related_name="ticket_payments",
    )

    def __str__(self):
        return f"Payment {self.payment.ref_number} → Ticket {self.ticket.ref_number}"


class PaymentTransaction(UUIDModelMixin, TimeStampedModel, models.Model):
    """
    Represents individual payment method transactions (cash/card) within a Payment.
    """

    class PaymentMethodChoices(models.TextChoices):
        CASH = ("cash", "Cash")
        CARD = ("card", "Card")

    payment = models.ForeignKey(
        Payment,
        on_delete=models.PROTECT,
        related_name="transactions",
    )

    method_type = models.CharField(max_length=50, choices=PaymentMethodChoices.choices)

    amount = models.DecimalField(max_digits=10, decimal_places=2)

    amount_tendered = models.DecimalField(max_digits=10, decimal_places=2)

    # AddPay-specific fields for card payments
    # Retrieval Reference Number
    addpay_rrn = models.CharField(
        max_length=255,
        blank=True,
    )

    # AddPay Transaction ID
    addpay_trans_id = models.CharField(
        max_length=255,
        blank=True,
    )

    processed_by = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="processed_transactions",
    )

    # Different to created for offline cash transactions
    processed_at = models.DateTimeField()

    def __str__(self):
        return f"Transaction {self.uuid} ({self.method_type}) - {self.amount}"

    @property
    def change_due(self):
        return self.amount_tendered - self.amount


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

    ticket = models.ForeignKey(Ticket, on_delete=models.PROTECT, related_name="refunds")

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
        User,
        on_delete=models.PROTECT,
        related_name="requested_refunds",
    )

    approved_by = models.ForeignKey(
        User,
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
        PaymentTransaction,
        on_delete=models.PROTECT,
        related_name="refund_references",
    )

    amount = models.DecimalField(max_digits=10, decimal_places=2)

    status = models.CharField(max_length=50, choices=RefundStatusChoices.choices)

    processed_by = models.ForeignKey(
        User,
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
