from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from django.core.exceptions import ValidationError

from farmyard_manager.entrance.tests.models.factories import ReEntryFactory
from farmyard_manager.entrance.tests.models.factories import TicketFactory
from farmyard_manager.payments.managers import PaymentManager
from farmyard_manager.payments.managers import PaymentQuerySet
from farmyard_manager.payments.managers import RefundManager
from farmyard_manager.payments.managers import RefundQuerySet
from farmyard_manager.payments.managers import RefundTransactionItemManager
from farmyard_manager.payments.managers import RefundTransactionItemQuerySet
from farmyard_manager.payments.managers import RefundVehicleAllocationManager
from farmyard_manager.payments.managers import TransactionItemManager
from farmyard_manager.payments.managers import TransactionItemQuerySet
from farmyard_manager.payments.models import Payment
from farmyard_manager.payments.models import Refund
from farmyard_manager.payments.models import RefundTransactionItem
from farmyard_manager.payments.models import RefundVehicleAllocation
from farmyard_manager.payments.models import TransactionItem
from farmyard_manager.payments.tests.factories import PaymentFactory
from farmyard_manager.payments.tests.factories import RefundFactory
from farmyard_manager.payments.tests.factories import TransactionItemFactory
from farmyard_manager.users.tests.factories import UserFactory
from farmyard_manager.vehicles.tests.factories import VehicleFactory

PRICE_PER_VISITOR = Decimal("100.00")


@pytest.fixture(autouse=True)
def use_pricing(with_pricing):
    with_pricing(price=PRICE_PER_VISITOR)


@pytest.mark.django_db(transaction=True)
class TestPaymentQuerySet:
    """Test suite for the PaymentQuerySet class."""

    def test_queryset_assignment(self):
        """Test that Payment manager uses PaymentQuerySet."""
        assert isinstance(Payment.objects.get_queryset(), PaymentQuerySet)

    def test_completed_filter(self):
        """Test filtering completed payments."""
        # Create payments with different statuses
        completed_payments = [
            PaymentFactory(settled=True),
            PaymentFactory(refunded=True),
        ]

        # Create non-completed payments
        PaymentFactory()
        PaymentFactory(partially_settled=True)
        PaymentFactory(partially_refunded=True)

        result = Payment.objects.completed()

        assert result.count() == 2  # noqa: PLR2004
        for payment in result:
            assert payment.status in [
                Payment.PaymentStatusChoices.SETTLED,
                Payment.PaymentStatusChoices.REFUNDED,
            ]
            assert payment in completed_payments


@pytest.mark.django_db(transaction=True)
class TestPaymentManager:
    """Test suite for the PaymentManager class."""

    def test_manager_assignment(self):
        """Test that Payment model uses PaymentManager."""
        assert isinstance(Payment.objects, PaymentManager)

    def test_initiate_entrance_payment_ticket_success(self):
        """Test successful payment initiation for ticket."""
        ticket = TicketFactory(
            counted=True,
            with_items=True,
        )
        user = UserFactory()

        payment = Payment.objects.initiate_entrance_payment(
            ticket,
            created_by=user,
        )

        assert payment.tickets.count() == 1
        assert payment.created_by == user
        assert ticket.payment == payment

    def test_initiate_entrance_payment_re_entry_success(self):
        """Test successful payment initiation for re-entry."""
        re_entry = ReEntryFactory(
            pending_payment=True,
            visitors_left=1,
            visitors_returned=2,
            with_items=True,
            with_items__visitor_count=1,
        )

        user = UserFactory()

        payment = Payment.objects.initiate_entrance_payment(
            re_entry,
            created_by=user,
        )

        assert payment.re_entries.count() == 1
        assert payment.created_by == user
        assert re_entry.payment == payment

    def test_initiate_entrance_payment_no_amount_due(self):
        """Test error when entrance record has no amount due."""
        with (
            pytest.raises(ValidationError, match="no due amount"),
        ):
            Payment.objects.initiate_entrance_payment(
                entrance_record=TicketFactory(counted=True, with_items=False),
                created_by=UserFactory(),
            )

    def test_initiate_entrance_payment_already_has_payment(self):
        """Test error when entrance record already has payment."""
        paid_ticket = TicketFactory(with_items=True, with_payment=True)

        with (
            pytest.raises(ValidationError, match="already has a payment"),
        ):
            Payment.objects.initiate_entrance_payment(
                entrance_record=paid_ticket,
                created_by=UserFactory(),
            )

    def test_initiate_entrance_payment_ticket_wrong_status(self):
        """Test error when ticket has wrong status."""

        with (
            pytest.raises(ValidationError, match="not ready for payment"),
        ):
            Payment.objects.initiate_entrance_payment(
                entrance_record=TicketFactory(passed_security=True, with_items=True),
                created_by=UserFactory(),
            )

    def test_initiate_entrance_payment_re_entry_no_additional_visitors(self):
        """Test error when re-entry has no additional visitors."""
        with (
            pytest.raises(
                ValueError,
                match="no additional visitors are returning",
            ),
        ):
            Payment.objects.initiate_entrance_payment(
                entrance_record=ReEntryFactory(
                    visitors_left=1,
                    visitors_returned=1,
                    with_items=True,
                ),
                created_by=UserFactory(),
            )


@pytest.mark.django_db(transaction=True)
class TestTransactionItemQuerySet:
    """Test suite for the TransactionItemQuerySet class."""

    def test_queryset_assignment(self):
        """Test that TransactionItem manager uses TransactionItemQuerySet."""
        assert isinstance(
            TransactionItem.objects.get_queryset(),
            TransactionItemQuerySet,
        )

    def test_by_payment_filter(self):
        """Test filtering transaction items by payment."""
        tx1_count = 5
        tx2_count = 2
        tx3_count = 3
        total_paid_visitors = tx1_count + tx2_count + tx3_count

        payment_transactions = [
            {"visitor_count": tx1_count, "amount": tx1_count * PRICE_PER_VISITOR},
            {"visitor_count": tx2_count, "amount": tx2_count * PRICE_PER_VISITOR},
            {"visitor_count": tx3_count, "amount": tx3_count * PRICE_PER_VISITOR},
        ]

        payment = PaymentFactory(
            for_entrance_records=[
                TicketFactory(
                    counted=True,
                    with_items=True,
                    with_items__visitor_count=total_paid_visitors,
                ),
            ],
            with_transactions=payment_transactions,
        )

        # Create random payments with transactions
        for _ in range(3):
            PaymentFactory(
                for_entrance_records=[
                    TicketFactory(
                        counted=True,
                        with_items=True,
                    ),
                ],
                with_transactions=True,
            )

        transactions_items = TransactionItem.objects.by_payment(payment)

        assert (
            transactions_items.count()
            == len(payment_transactions)
            == payment.transaction_items.count()
        )
        for transaction in transactions_items:
            assert transaction.payment == payment
            assert transaction in payment.transaction_items.all()


@pytest.mark.django_db(transaction=True)
class TestTransactionItemManager:
    """Test suite for the TransactionItemManager class."""

    def test_manager_assignment(self):
        """Test that TransactionItem model uses TransactionItemManager."""
        assert isinstance(TransactionItem.objects, TransactionItemManager)

    def test_create_payment_transaction_success(self):
        """Test successful payment transaction creation."""
        visitor_count = 3
        transaction_count = 2
        transaction_amount = transaction_count * PRICE_PER_VISITOR

        user = UserFactory(with_active_shift=True)

        payment = PaymentFactory(
            created_by=user,
            for_entrance_records=[
                TicketFactory(
                    counted=True,
                    with_items=True,
                    with_items__visitor_count=visitor_count,
                ),
            ],
        )

        assert payment.total_due_count == visitor_count
        assert payment.total_due == visitor_count * PRICE_PER_VISITOR

        assert payment.total_outstanding_count == visitor_count
        assert payment.total_outstanding == visitor_count * PRICE_PER_VISITOR

        assert payment.total_paid_count == 0
        assert payment.total_paid == 0

        transaction = TransactionItem.objects.create_payment_transaction(
            payment=payment,
            visitor_count=transaction_count,
            amount=transaction_amount,
            cash_tendered=transaction_amount,
            added_by=user,
            payment_type=TransactionItem.PaymentTypeChoices.CASH,
        )

        assert transaction.payment == payment
        assert transaction.added_by == user
        assert transaction.amount == transaction_amount
        assert transaction.shift == user.get_active_shift()

    def test_create_payment_transaction_wrong_user(self):
        """Test error when different user tries to manage payment."""
        payment = PaymentFactory()

        with pytest.raises(ValidationError, match="Payment managed by another user"):
            TransactionItem.objects.create_payment_transaction(
                payment=payment,
                amount=PRICE_PER_VISITOR,
                added_by=UserFactory(),
            )

    def test_create_payment_transaction_exceeds_outstanding(self):
        """Test error when amount exceeds outstanding balance."""
        visitor_count = 3
        transaction_count = visitor_count * 2  # Deliberately exceed
        transaction_amount = transaction_count * PRICE_PER_VISITOR

        user = UserFactory(with_active_shift=True)

        payment = PaymentFactory(
            created_by=user,
            for_entrance_records=[
                TicketFactory(
                    counted=True,
                    with_items=True,
                    with_items__visitor_count=visitor_count,
                ),
            ],
        )

        with (
            pytest.raises(ValueError, match="Amount exceeds outstanding balance"),
        ):
            TransactionItem.objects.create_payment_transaction(
                payment=payment,
                amount=transaction_amount,
                visitor_count=transaction_count,
                added_by=user,
            )

    def test_create_payment_transaction_no_active_shift(self):
        """Test error when user has no active shift."""
        user = UserFactory(with_active_shift=False)

        payment = PaymentFactory(
            created_by=user,
            for_entrance_records=[
                TicketFactory(
                    counted=True,
                    with_items=True,
                ),
            ],
        )

        with (
            pytest.raises(ValueError, match="must have an active shift"),
        ):
            TransactionItem.objects.create_payment_transaction(
                payment=payment,
                amount=PRICE_PER_VISITOR,
                visitor_count=1,
                added_by=user,
            )


@pytest.mark.django_db(transaction=True)
class TestRefundQuerySet:
    """Test suite for the RefundQuerySet class."""

    def test_queryset_assignment(self):
        """Test that Refund manager uses RefundQuerySet."""
        assert isinstance(Refund.objects.get_queryset(), RefundQuerySet)

    def test_settled_filter(self):
        """Test filtering settled refunds."""
        settled_refund_count = 2

        # Create settled refunds
        settled_refunds = RefundFactory.create_batch(
            settled_refund_count,
            settled=True,
        )

        # Create non-settled refunds
        RefundFactory.create_batch(3)
        RefundFactory(denied=True)

        result = Refund.objects.settled()

        assert result.count() == settled_refund_count
        for refund in result:
            assert refund.status == Refund.StatusChoices.SETTLED
            assert refund in settled_refunds


@pytest.mark.django_db(transaction=True)
class TestRefundManager:
    """Test suite for the RefundManager class."""

    def test_manager_assignment(self):
        """Test that Refund model uses RefundManager."""
        assert isinstance(Refund.objects, RefundManager)

    def test_initiate_refund_success(self):
        """Test successful refund initiation."""
        vehicle = VehicleFactory()
        payment = PaymentFactory(
            for_entrance_records=[
                TicketFactory(vehicle=vehicle, processed=True, with_items=True),
            ],
            with_transactions=True,
            settled=True,
        )

        user = UserFactory(with_active_shift=True)
        reason = "Customer request"

        refund = Refund.objects.initiate_refund(
            payment=payment,
            requested_by=user,
            vehicle=vehicle,
            reason=reason,
        )

        assert refund.payment == payment
        assert refund.requested_by == user
        assert refund.reason == reason
        assert refund.status == Refund.StatusChoices.PENDING_ALLOCATIONS

    def test_initiate_refund_not_refundable(self):
        """Test error when payment is not refundable."""
        payment = PaymentFactory(
            for_entrance_records=True,
            with_transactions=True,
            non_refundable=True,
        )

        with (
            pytest.raises(ValidationError, match="outside refund time window"),
        ):
            Refund.objects.initiate_refund(
                payment=payment,
                requested_by=UserFactory(with_active_shift=True),
                vehicle=payment.tickets.first().vehicle,
                reason="Testing",
            )

    def test_initiate_refund_no_refundable_amount(self):
        """Test error when no refundable amount remaining."""
        # Create fully refunded payment
        refund = RefundFactory(
            for_payment=True,
            settled=True,
            with_allocations=True,
            with_refund_transactions=True,
            with_refund_transactions__processed=True,
        )

        with (
            pytest.raises(ValidationError, match="No refundable amount remaining"),
        ):
            # Attempt another refund on same payment
            Refund.objects.initiate_refund(
                payment=refund.payment,
                requested_by=refund.requested_by,
                vehicle=refund.payment.tickets.first().vehicle,
                reason="Testing",
            )

    def test_initiate_refund_vehicle_not_linked(self):
        """Test error when vehicle not linked to payment."""
        refund = RefundFactory(
            for_payment=True,
            settled=True,
            with_allocations=True,
        )

        with (
            pytest.raises(
                ValidationError,
                match="Vehicle does not belong to payment",
            ),
        ):
            Refund.objects.initiate_refund(
                payment=refund.payment,
                requested_by=refund.requested_by,
                vehicle=VehicleFactory(),  # Different vehicle
                reason="Testing",
            )

    def test_initiate_refund_empty_reason(self):
        """Test error when reason is empty."""
        refund = RefundFactory(
            for_payment=True,
            settled=True,
            with_allocations=True,
        )

        with (
            pytest.raises(ValidationError, match="Reason for refund is required"),
        ):
            Refund.objects.initiate_refund(
                payment=refund.payment,
                requested_by=refund.requested_by,
                vehicle=refund.payment.tickets.first().vehicle,
                reason="",
            )

    def test_settled_delegate(self):
        """Test settled method delegation."""
        result = Refund.objects.settled()
        assert isinstance(result, RefundQuerySet)


@pytest.mark.django_db(transaction=True)
class TestRefundVehicleAllocationManager:
    """Test suite for the RefundVehicleAllocationManager class."""

    def test_manager_assignment(self):
        """Test that RefundVehicleAllocation model uses correct manager."""
        assert isinstance(
            RefundVehicleAllocation.objects,
            RefundVehicleAllocationManager,
        )

    def test_add_refund_allocation_ticket_item(
        self,
    ):
        """Test adding refund allocation for ticket item."""
        refund = RefundFactory(for_payment=True, with_allocations=False)
        vehicle = refund.payment.tickets.first().vehicle
        user = refund.requested_by
        ticket_item = refund.payment.tickets.first().ticket_items.first()

        allocation = RefundVehicleAllocation.objects.add_refund_allocation(
            refund=refund,
            vehicle=vehicle,
            processed_by=user,
        )

        assert allocation.refund == refund
        assert allocation.processed_by == user
        assert allocation.ticket_item == ticket_item
        assert allocation.re_entry_item is None

    def test_add_refund_allocation_payment_mismatch(self):
        """Test error when entrance item payment doesn't match refund payment."""
        refund = RefundFactory(for_payment=True, with_allocations=False)

        different_payment = PaymentFactory(
            for_entrance_records=True,
            with_transactions=True,
            settled=True,
        )

        vehicle = different_payment.tickets.first().vehicle
        user = refund.requested_by

        with (
            pytest.raises(
                ValueError,
                match="Vehicle likely belongs to another payment",
            ),
        ):
            RefundVehicleAllocation.objects.add_refund_allocation(
                refund=refund,
                vehicle=vehicle,
                processed_by=user,
            )

    def test_add_refund_allocation_invalid_entrance_item_type(self):
        """Test error when entrance item is not TicketItem or ReEntryItem."""
        refund = RefundFactory(for_payment=True, with_allocations=False)
        vehicle = refund.payment.tickets.first().vehicle
        user = refund.requested_by

        vehicle.get_public_item = MagicMock(return_value=3)

        with (
            pytest.raises(
                TypeError,
                match="must be a Ticket item or ReEntry item",
            ),
        ):
            RefundVehicleAllocation.objects.add_refund_allocation(
                refund=refund,
                vehicle=vehicle,
                processed_by=user,
            )


@pytest.mark.django_db(transaction=True)
class TestRefundTransactionItemQuerySet:
    """Test suite for the RefundTransactionItemQuerySet class."""

    def test_queryset_assignment(self):
        """
        Test that RefundTransactionItem manager uses RefundTransactionItemQuerySet.
        """
        assert isinstance(
            RefundTransactionItem.objects.get_queryset(),
            RefundTransactionItemQuerySet,
        )

    def test_by_refund_filter(self):
        """Test filtering refund transaction items by refund."""
        tx1_count = 5
        tx2_count = 2
        tx3_count = 3
        total_paid_visitors = tx1_count + tx2_count + tx3_count

        transactions_items = [
            {"visitor_count": tx1_count, "amount": tx1_count * PRICE_PER_VISITOR},
            {"visitor_count": tx2_count, "amount": tx2_count * PRICE_PER_VISITOR},
            {"visitor_count": tx3_count, "amount": tx3_count * PRICE_PER_VISITOR},
        ]

        refund = RefundFactory(
            for_payment={
                "for_entrance_records": [
                    TicketFactory(
                        counted=True,
                        with_items=True,
                        with_items__visitor_count=total_paid_visitors,
                    ),
                ],
                "with_transactions": transactions_items,
            },
            with_allocations=True,
            with_refund_transactions=transactions_items,  # Refund all transactions
        )

        refund_transaction_items = RefundTransactionItem.objects.by_refund(refund)

        assert refund_transaction_items.count() == len(transactions_items)
        for refund_transaction_item in refund_transaction_items:
            assert refund_transaction_item.refund == refund
            assert refund_transaction_item in refund_transaction_items


@pytest.mark.django_db(transaction=True)
class TestRefundTransactionItemManager:
    """Test suite for the RefundTransactionItemManager class."""

    def test_manager_assignment(self):
        """Test that RefundTransactionItem model uses RefundTransactionItemManager."""
        assert isinstance(RefundTransactionItem.objects, RefundTransactionItemManager)

    def test_add_refund_transaction_success(self):
        """Test successful refund transaction creation."""
        refund = RefundFactory(
            for_payment=True,
            pending_transactions=True,
            with_allocations=True,
        )

        transaction_item = refund.payment.transaction_items.first()
        user = refund.requested_by
        visitor_count = 2
        amount = 2 * PRICE_PER_VISITOR

        refund_transaction = RefundTransactionItem.objects.add_refund_transaction(
            refund=refund,
            transaction_item=transaction_item,
            added_by=user,
            visitor_count=visitor_count,
            amount=amount,
        )

        assert refund_transaction == refund.refund_transaction_items.first()
        assert refund_transaction.refund == refund
        assert refund_transaction.transaction_item == transaction_item
        assert refund_transaction.added_by == user
        assert refund_transaction.visitor_count == visitor_count
        assert refund_transaction.amount == amount
        assert refund_transaction.status == RefundTransactionItem.StatusChoices.PENDING

    def test_add_refund_transaction_completed_refund(self):
        """Test error when adding transaction to completed refund."""
        refund = RefundFactory(
            for_payment=True,
            settled=True,
            with_allocations=True,
        )

        transaction_item = refund.payment.transaction_items.first()
        user = refund.requested_by
        visitor_count = 2
        amount = visitor_count * PRICE_PER_VISITOR

        with pytest.raises(
            ValidationError,
            match="Cannot add refund transactions to approved",
        ):
            RefundTransactionItem.objects.add_refund_transaction(
                refund=refund,
                transaction_item=transaction_item,
                added_by=user,
                visitor_count=visitor_count,
                amount=amount,
            )

    def test_add_refund_transaction_wrong_user(self):
        """Test error when different user tries to manage refund."""
        refund = RefundFactory(
            for_payment=True,
            pending_transactions=True,
            with_allocations=True,
        )

        transaction_item = refund.payment.transaction_items.first()
        visitor_count = 2
        amount = visitor_count * PRICE_PER_VISITOR

        with pytest.raises(ValidationError, match="Refund managed by another user"):
            RefundTransactionItem.objects.add_refund_transaction(
                refund=refund,
                transaction_item=transaction_item,
                added_by=UserFactory(),  # Different user
                visitor_count=visitor_count,
                amount=amount,
            )

    def test_add_refund_transaction_different_payment(self):
        """Test error when transaction belongs to different payment."""
        refund = RefundFactory(
            for_payment=True,
            pending_transactions=True,
            with_allocations=True,
        )

        different_transaction = TransactionItemFactory(
            visitor_count=1,
            amount=PRICE_PER_VISITOR,
            as_card_transaction=True,
        )
        visitor_count = 2
        amount = visitor_count * PRICE_PER_VISITOR
        user = refund.requested_by

        with pytest.raises(
            ValidationError,
            match="Cannot refund a transaction belonging to a different payment",
        ):
            RefundTransactionItem.objects.add_refund_transaction(
                refund=refund,
                transaction_item=different_transaction,  # Different payment
                added_by=user,
                visitor_count=visitor_count,
                amount=amount,
            )

    def test_add_refund_transaction_zero_visitors(self):
        """Test error when visitor count is zero."""
        refund = RefundFactory(
            for_payment=True,
            pending_transactions=True,
            with_allocations=True,
        )

        transaction_item = refund.payment.transaction_items.first()
        user = refund.requested_by
        visitor_count = 0
        amount = visitor_count * PRICE_PER_VISITOR

        with pytest.raises(
            ValidationError,
            match="Visitor count must be greater than 0",
        ):
            RefundTransactionItem.objects.add_refund_transaction(
                refund=refund,
                transaction_item=transaction_item,
                added_by=user,
                visitor_count=visitor_count,
                amount=amount,
            )

    @pytest.mark.parametrize(
        ("visitor_count_multiplier", "amount_multiplier", "error_message"),
        [
            (2, 1, "Visitor count exceeds remaining refundable count"),
            (1, 2, "Amount exceeds remaining refundable amount"),
        ],
        ids=["exceeds_refundable_count", "exceeds_refundable_amount"],
    )
    def test_add_refund_transaction_exceeds_refundable_count_or_amount(
        self,
        visitor_count_multiplier,
        amount_multiplier,
        error_message,
    ):
        """Test error when visitor count exceeds refundable limit."""
        paid_visitor_count = 3

        refund = RefundFactory(
            for_payment={
                "for_entrance_records": [
                    TicketFactory(
                        processed=True,
                        with_items=True,
                        with_items__visitor_count=paid_visitor_count,
                    ),
                ],
                "with_transactions": True,
                "settled": True,
            },
            pending_settlement=True,
            with_allocations=True,
        )

        transaction_item = refund.payment.transaction_items.first()
        user = refund.requested_by
        refund_visitor_count = paid_visitor_count * visitor_count_multiplier
        double_amount = (refund_visitor_count * PRICE_PER_VISITOR) * amount_multiplier

        with (
            pytest.raises(
                ValidationError,
                match=error_message,
            ),
        ):
            RefundTransactionItem.objects.add_refund_transaction(
                refund=refund,
                transaction_item=transaction_item,
                added_by=user,
                visitor_count=refund_visitor_count,
                amount=double_amount,
            )

    def test_add_multiple_refund_transactions_success(self):
        """Test successful bulk creation of refund transaction items."""
        paid_visitor_count = 10
        refund = RefundFactory(
            for_payment={
                "for_entrance_records": [
                    TicketFactory(
                        processed=True,
                        with_items=True,
                        with_items__visitor_count=paid_visitor_count,
                    ),
                ],
                "with_transactions": [
                    {"visitor_count": 5, "amount": 5 * PRICE_PER_VISITOR},
                    {"visitor_count": 5, "amount": 5 * PRICE_PER_VISITOR},
                ],
                "settled": True,
            },
            pending_settlement=True,
            with_allocations=True,
        )

        user = refund.requested_by

        # Create transaction items
        transaction1 = refund.payment.transaction_items.first()
        transaction2 = refund.payment.transaction_items.last()

        transaction_data: list[RefundTransactionItemManager.RefundTransactionInput] = [
            {
                "transaction_item": transaction1,
                "visitor_count": transaction1.visitor_count,
                "amount": transaction1.amount,
                "kwargs": {},
            },
            {
                "transaction_item": transaction2,
                "visitor_count": transaction2.visitor_count,
                "amount": transaction2.amount,
                "kwargs": {},
            },
        ]

        refund_transactions = (
            RefundTransactionItem.objects.add_multiple_refund_transactions(
                refund=refund,
                added_by=user,
                transaction_data=transaction_data,
            )
        )

        assert len(refund_transactions) == len(transaction_data)
        assert all(item.refund == refund for item in refund_transactions)
        assert all(item.added_by == user for item in refund_transactions)

    def test_add_multiple_refund_transactions_validation_error(self):
        """Test error in bulk creation when validation fails."""
        paid_visitor_count = 10
        refund = RefundFactory(
            for_payment={
                "for_entrance_records": [
                    TicketFactory(
                        processed=True,
                        with_items=True,
                        with_items__visitor_count=paid_visitor_count,
                    ),
                ],
                "with_transactions": [
                    {"visitor_count": 5, "amount": 5 * PRICE_PER_VISITOR},
                    {"visitor_count": 5, "amount": 5 * PRICE_PER_VISITOR},
                ],
                "settled": True,
            },
            pending_settlement=True,
            with_allocations=True,
            settled=True,
        )

        user = refund.requested_by

        # Create transaction items
        transaction1 = refund.payment.transaction_items.first()
        transaction2 = refund.payment.transaction_items.last()

        transaction_data: list[RefundTransactionItemManager.RefundTransactionInput] = [
            {
                "transaction_item": transaction1,
                "visitor_count": transaction1.visitor_count,
                "amount": transaction1.amount,
                "kwargs": {},
            },
            {
                "transaction_item": transaction2,
                "visitor_count": transaction2.visitor_count,
                "amount": transaction2.amount,
                "kwargs": {},
            },
        ]

        with pytest.raises(
            ValidationError,
            match="Cannot add refund transactions to approved",
        ):
            RefundTransactionItem.objects.add_multiple_refund_transactions(
                refund=refund,
                added_by=user,
                transaction_data=transaction_data,
            )

    def test_by_refund_delegate(self):
        """Test by_refund method delegation."""
        refund = RefundFactory()
        result = RefundTransactionItem.objects.by_refund(refund)
        assert isinstance(result, RefundTransactionItemQuerySet)
