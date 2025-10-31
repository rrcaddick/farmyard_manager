from decimal import Decimal
from typing import TYPE_CHECKING
from typing import TypedDict

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import models
from django.db import transaction
from model_utils.managers import SoftDeletableManager
from model_utils.managers import SoftDeletableQuerySet

from farmyard_manager.users.models import User

if TYPE_CHECKING:
    from farmyard_manager.entrance.models.base import BaseEntranceRecord
    from farmyard_manager.entrance.models.re_entry import ReEntry
    from farmyard_manager.entrance.models.re_entry import ReEntryItem
    from farmyard_manager.entrance.models.ticket import Ticket
    from farmyard_manager.entrance.models.ticket import TicketItem
    from farmyard_manager.payments.models import Payment
    from farmyard_manager.payments.models import Refund
    from farmyard_manager.payments.models import RefundTransactionItem
    from farmyard_manager.payments.models import RefundVehicleAllocation
    from farmyard_manager.payments.models import TransactionItem
    from farmyard_manager.users.models import User
    from farmyard_manager.vehicles.models import Vehicle


class PaymentQuerySet(SoftDeletableQuerySet["Payment"], models.QuerySet["Payment"]):
    def completed(self) -> "PaymentQuerySet":
        return self.filter(
            status__in=[
                self.model.PaymentStatusChoices.SETTLED,
                self.model.PaymentStatusChoices.REFUNDED,
            ],
        )


class PaymentManager(SoftDeletableManager["Payment"], models.Manager["Payment"]):
    def get_queryset(self) -> PaymentQuerySet:
        """Return custom QuerySet"""
        return PaymentQuerySet(self.model, using=self._db)

    def completed(self) -> PaymentQuerySet:
        """Return completed payments"""
        return self.get_queryset().completed()

    def initiate_entrance_payment(
        self,
        entrance_record: "BaseEntranceRecord",
        **kwargs,
    ):
        TicketModel: type[Ticket] = apps.get_model("entrance", "Ticket")  # noqa: N806
        ReEntryModel: type[ReEntry] = apps.get_model("entrance", "ReEntry")  # noqa: N806

        if entrance_record.total_due <= 0:
            error_message = "Entrance record has no due amount"
            raise ValidationError(error_message)

        if entrance_record.payment is not None:
            error_message = "Entrance record already has a payment"
            raise ValidationError(error_message)

        # Ticket specific validations
        if isinstance(entrance_record, TicketModel):
            ticket: Ticket = entrance_record

            if ticket.status != TicketModel.StatusChoices.COUNTED:
                error_message = "Ticket not ready for payment"
                raise ValidationError(error_message)

        # ReEntry specific validations
        if isinstance(entrance_record, ReEntryModel):
            re_entry: ReEntry = entrance_record

            if re_entry.status != ReEntryModel.StatusChoices.PENDING_PAYMENT:
                error_message = "ReEntry does not require payment"
                raise ValidationError(error_message)

            if re_entry.additional_visitors <= 0:
                error_message = "ReEntry does not require payment"
                raise ValidationError(error_message)

        with transaction.atomic():
            payment = self.create(**kwargs)
            entrance_record.assign_payment(payment)

            return payment

    def sync_offline_payment(self):
        pass


class TransactionItemQuerySet(
    SoftDeletableQuerySet["TransactionItem"],
    models.QuerySet["TransactionItem"],
):
    def by_payment(self, payment: "Payment") -> "TransactionItemQuerySet":
        return self.filter(payment=payment)


class TransactionItemManager(
    SoftDeletableManager["TransactionItem"],
    models.Manager["TransactionItem"],
):
    def get_queryset(self) -> TransactionItemQuerySet:
        return TransactionItemQuerySet(self.model, using=self._db)

    def by_payment(self, payment: "Payment") -> TransactionItemQuerySet:
        return self.get_queryset().by_payment(payment)

    def create_payment_transaction(
        self,
        payment: "Payment",
        amount: Decimal,
        added_by: "User",
        **kwargs,
    ) -> "TransactionItem":
        """Create a transaction item for a payment"""
        # Ensure that only one user deal with a payments lifecycle at a time
        if added_by != payment.created_by:
            error_message = "Payment managed by another user"
            raise ValidationError(error_message)

        if amount > payment.total_outstanding:
            error_message = "Amount exceeds outstanding balance"
            raise ValueError(error_message)

        shift = added_by.get_active_shift()

        if shift is None:
            error_message = "User must have an active shift to add transactions"
            raise ValueError(error_message)

        return self.create(
            amount=amount,
            shift=shift,
            added_by=added_by,
            payment=payment,
            **kwargs,
        )


class RefundQuerySet(SoftDeletableQuerySet["Refund"], models.QuerySet["Refund"]):
    def settled(self) -> "RefundQuerySet":
        return self.filter(
            status__in=[
                self.model.StatusChoices.SETTLED,
            ],
        )


class RefundManager(SoftDeletableManager["Refund"], models.Manager["Refund"]):
    def get_queryset(self) -> RefundQuerySet:
        return RefundQuerySet(self.model, using=self._db)

    def settled(self) -> RefundQuerySet:
        return self.get_queryset().settled()

    def initiate_refund(
        self,
        payment: "Payment",
        requested_by: "User",
        vehicle: "Vehicle",
        reason: str,
        **kwargs,
    ) -> "Refund":
        """
        Starts a refund process for this payment. Returns a empty refund object for
        allocation and transaction items to attach to. Vehicle model requirement,
        ensures presence of vehile as vehicle is retrieved from scan data in serializer
        """
        if not payment.is_refundable:
            error_message = "Payment is outside refund time window or not completed"
            raise ValidationError(error_message)

        if payment.refund_in_progress:
            error_message = "Payment already has an active refund in progress"
            raise ValidationError(error_message)

        if payment.remaining_refundable_amount <= 0:
            error_message = "No refundable amount remaining"
            raise ValidationError(error_message)

        if vehicle.linked_to_payment(payment) is False:
            error_message = "Vehicle does not belong to payment"
            raise ValidationError(error_message)

        if reason == "":
            error_message = "Reason for refund is required"
            raise ValidationError(error_message)

        with transaction.atomic():
            refund = self.create(
                payment=payment,
                requested_by=requested_by,
                reason=reason,
                **kwargs,
            )

            refund.add_allocation(vehicle=vehicle, processed_by=requested_by)

            return refund


class RefundVehicleAllocationQuerySet(
    SoftDeletableQuerySet["RefundVehicleAllocation"],
    models.QuerySet["RefundVehicleAllocation"],
):
    def refund_pending_count(
        self,
        refund: "Refund",
    ) -> "RefundVehicleAllocationQuerySet":
        return self.filter(
            refund=refund,
            status__in=[
                self.model.RefundVehicleAllocationStatusChoices.PENDING_COUNT,
            ],
        )


class RefundVehicleAllocationManager(
    SoftDeletableManager["RefundVehicleAllocation"],
    models.Manager["RefundVehicleAllocation"],
):
    def get_queryset(self) -> RefundVehicleAllocationQuerySet:
        return RefundVehicleAllocationQuerySet(self.model, using=self._db)

    def add_refund_allocation(
        self,
        refund: "Refund",
        vehicle: "Vehicle",
        processed_by: "User",
        **kwargs,
    ) -> "RefundVehicleAllocation":
        # Ensure the entrance item is a TicketItem or ReEntryItem
        TicketItemModel: type[TicketItem] = apps.get_model("entrance", "TicketItem")  # noqa: N806
        ReEntryItemModel: type[ReEntryItem] = apps.get_model("entrance", "ReEntryItem")  # noqa: N806

        entrance_item = vehicle.get_public_item(refund.payment)

        if not isinstance(entrance_item, (TicketItemModel, ReEntryItemModel)):
            error_message = "Entrance item must be a Ticket item or ReEntry item"
            raise TypeError(error_message)

        # Ensure entrance item part of refunded in payment
        if entrance_item.payment != refund.payment:
            error_message = (
                "Vehicle belongs to a different payment. Finish processing "
                "current refund first"
            )
            raise ValidationError(error_message)

        # Get the correct field name for the entrance item
        item_type_name = (
            "ticket_item"
            if isinstance(entrance_item, TicketItemModel)
            else "re_entry_item"
        )

        data = {
            "refund": refund,
            "processed_by": processed_by,
            item_type_name: entrance_item,
            **kwargs,
        }

        return self.create(**data)


class RefundTransactionItemQuerySet(
    SoftDeletableQuerySet["RefundTransactionItem"],
    models.QuerySet["RefundTransactionItem"],
):
    def by_refund(self, refund: "Refund") -> "RefundTransactionItemQuerySet":
        return self.filter(refund=refund)


class RefundTransactionItemManager(
    SoftDeletableManager["RefundTransactionItem"],
    models.Manager["RefundTransactionItem"],
):
    def get_queryset(self):
        return RefundTransactionItemQuerySet(self.model, using=self._db)

    def by_refund(self, refund: "Refund") -> RefundTransactionItemQuerySet:
        return self.get_queryset().by_refund(refund)

    def add_refund_transaction(
        self,
        refund: "Refund",
        transaction_item: "TransactionItem",
        added_by: "User",
        visitor_count: int,
        amount: Decimal,
        **kwargs,
    ) -> "RefundTransactionItem":
        """Adds a pending refund transaction item to refund"""
        if refund.status in [
            refund.StatusChoices.SETTLED,
            refund.StatusChoices.DENIED,
        ]:
            error_message = "Cannot add refund transactions to approved or denied"
            raise ValidationError(error_message)

        if added_by != refund.requested_by:
            error_message = "Refund managed by another user"
            raise ValidationError(error_message)

        if transaction_item.payment != refund.payment:
            error_message = (
                "Cannot refund a transaction belonging to a different payment"
            )
            raise ValidationError(error_message)

        if visitor_count <= 0:
            error_message = "Visitor count must be greater than 0"
            raise ValidationError(error_message)

        if visitor_count > transaction_item.remaining_refundable_count:
            error_message = "Visitor count exceeds remaining refundable count"
            raise ValidationError(error_message)

        if amount > transaction_item.remaining_refundable_amount:
            error_message = "Amount exceeds remaining refundable amount"
            raise ValidationError(error_message)

        return self.create(
            refund=refund,
            transaction_item=transaction_item,
            added_by=added_by,
            visitor_count=visitor_count,
            amount=amount,
            **kwargs,
        )

    class RefundTransactionInput(TypedDict):
        """Input structure for bulk refund transactions

        Args:
            transaction_item: TransactionItem - The TransactionItem being refunded
            visitor_count: int - Number of visitors being refunded
            amount: Decimal - Refund amount
            kwargs: dict - Optional fields to pass to RefundTransactionItem creation
        """

        transaction_item: "TransactionItem"
        visitor_count: int
        amount: Decimal
        kwargs: dict

    def add_multiple_refund_transactions(
        self,
        refund: "Refund",
        added_by: "User",
        transaction_data: list[RefundTransactionInput],
        **shared_kwargs,
    ) -> list["RefundTransactionItem"]:
        """Bulk create multiple refund transaction items"""

        # Validate once upfront
        if refund.status in [
            refund.StatusChoices.SETTLED,
            refund.StatusChoices.DENIED,
        ]:
            error_message = (
                "Cannot add refund transactions to approved or denied refunds"
            )
            raise ValidationError(
                error_message,
            )

        if added_by != refund.requested_by:
            error_message = "Refund managed by another user"
            raise ValidationError(error_message)

        items_to_create = []

        for data in transaction_data:
            transaction_item = data["transaction_item"]
            visitor_count = data["visitor_count"]
            amount = data["amount"]
            kwargs = data.get("kwargs", {})

            # Individual validations
            if transaction_item.payment != refund.payment:
                error_message = (
                    "Cannot refund a transaction belonging to a different payment"
                )
                raise ValidationError(error_message)

            if (
                visitor_count <= 0
                or visitor_count > transaction_item.remaining_refundable_count
            ):
                error_message = (
                    f"Invalid visitor count for transaction {transaction_item.id}"
                )
                raise ValidationError(error_message)

            if amount > transaction_item.remaining_refundable_amount:
                error_message = (
                    "Amount exceeds remaining refundable amount for "
                    f"transaction {transaction_item.id}"
                )
                raise ValidationError(error_message)

            items_to_create.append(
                self.model(
                    refund=refund,
                    transaction_item=transaction_item,
                    added_by=added_by,
                    visitor_count=visitor_count,
                    amount=amount,
                    **kwargs,
                    **shared_kwargs,
                ),
            )

        with transaction.atomic():
            return self.bulk_create(items_to_create)
