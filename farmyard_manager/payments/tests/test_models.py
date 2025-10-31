# ruff: noqa: PLR2004, FBT003, F401
from datetime import timedelta
from decimal import Decimal
from itertools import count
from typing import Literal
from unittest.mock import MagicMock
from unittest.mock import PropertyMock
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from farmyard_manager.entrance.models.ticket import TicketItem
from farmyard_manager.entrance.tests.models.factories import ReEntryFactory
from farmyard_manager.entrance.tests.models.factories import ReEntryItemFactory
from farmyard_manager.entrance.tests.models.factories import TicketFactory
from farmyard_manager.entrance.tests.models.factories import TicketItemFactory
from farmyard_manager.payments.enums import RefundVehicleAllocationStatusChoices
from farmyard_manager.payments.models import Payment
from farmyard_manager.payments.models import Refund
from farmyard_manager.payments.models import RefundTransactionItem
from farmyard_manager.payments.models import RefundVehicleAllocation
from farmyard_manager.payments.models import TransactionItem
from farmyard_manager.payments.tests.factories import PaymentFactory
from farmyard_manager.payments.tests.factories import RefundFactory
from farmyard_manager.payments.tests.factories import RefundTransactionItemFactory
from farmyard_manager.payments.tests.factories import RefundVehicleAllocationFactory
from farmyard_manager.payments.tests.factories import TransactionItemFactory
from farmyard_manager.users.tests.factories import UserFactory
from farmyard_manager.vehicles.tests.factories import VehicleFactory

PRICE_PER_VISITOR = Decimal("100.00")


@pytest.fixture(autouse=True)
def use_pricing(with_pricing):
    with_pricing(price=PRICE_PER_VISITOR)


@pytest.mark.django_db(transaction=True)
class TestPayment:
    """Test suite for the Payment model."""

    def test_str_representation(self):
        """Test string representation of payment."""
        payment = PaymentFactory()
        expected = f"Payment {payment.ref_number} - {payment.status}"
        assert str(payment) == expected

    def test_model_defaults(self):
        """Test payment creation with default values."""
        payment = PaymentFactory()
        assert payment.status == Payment.PaymentStatusChoices.PENDING_SETTLEMENT
        assert payment.completed_at is None
        assert payment.uuid is not None
        assert payment.ref_number is not None
        assert payment.created is not None

    @pytest.mark.parametrize(
        ("visitor_count", "paid_count", "expected_status"),
        [
            (2, 1, Payment.PaymentStatusChoices.PARTIALLY_SETTLED),
            (2, 2, Payment.PaymentStatusChoices.SETTLED),
        ],
        ids=["partially_settled", "settled"],
    )
    def test_update_status(
        self,
        visitor_count,
        paid_count,
        expected_status,
    ):
        """Test status update with partial payment."""
        payment = PaymentFactory(
            for_entrance_records=[
                TicketFactory(
                    counted=True,
                    with_items=True,
                    with_items__visitor_count=visitor_count,
                ),
            ],
        )

        # No settled transactions yet
        assert payment.status == Payment.PaymentStatusChoices.PENDING_SETTLEMENT

        # Add partial transaction and update status
        TransactionItemFactory.create(
            payment=payment,
            amount=paid_count * PRICE_PER_VISITOR,
            visitor_count=paid_count,
            as_card_transaction=True,
        )

        # Update payment status
        payment.update_status()

        # Payment status correctly changed
        assert payment.status == expected_status

    def test_total_due_calculation(self):
        """Test total_due calculation with tickets and re-entries."""

        ticket_count = 2
        visitors_left = 1
        re_entry_add_count = 3

        payment = PaymentFactory(
            for_entrance_records=[
                TicketFactory(
                    counted=True,
                    with_items=True,
                    with_items__visitor_count=ticket_count,
                ),
                ReEntryFactory(
                    visitors_left=visitors_left,
                    visitors_returned=re_entry_add_count + visitors_left,
                    pending_payment=True,
                    with_items=True,
                    with_items__visitor_count=re_entry_add_count,
                ),
            ],
        )

        # Check counts match
        expected_count = ticket_count + re_entry_add_count
        assert payment.total_due_count == expected_count

        # Check total due matches
        expected_total = expected_count * PRICE_PER_VISITOR
        assert payment.total_due == expected_total

    def test_total_paid_calculation(self):
        """Test total_paid calculation with multiple transactions."""
        visitor_count1 = 1
        visitor_count2 = 2

        payment = PaymentFactory(
            settled=True,
            with_transactions=[
                {"visitor_count": visitor_count1},
                {"visitor_count": visitor_count2},
            ],
        )

        expected_count = visitor_count1 + visitor_count2
        expected_total = (visitor_count1 + visitor_count2) * PRICE_PER_VISITOR

        assert payment.total_paid == expected_total
        assert payment.total_paid_count == expected_count

    def test_total_outstanding_calculation(self):
        """Test total_outstanding calculation."""
        payment = PaymentFactory(
            partially_settled=True,
            for_entrance_records=[
                TicketFactory(
                    counted=True,
                    with_items=True,
                    with_items__visitor_count=2,
                ),
            ],
            with_transactions=True,
            with_transactions__visitor_count=1,
            with_transactions__amount=PRICE_PER_VISITOR,
        )

        assert payment.total_outstanding_count == 1
        assert payment.total_outstanding == PRICE_PER_VISITOR

    @patch("django.conf.settings.REFUND_TIME_LIMIT_HOURS", 1)
    def test_refund_deadline_calculation(self):
        """Test refund deadline calculation."""
        completed_at = timezone.now()
        payment = PaymentFactory.build(settled=True, completed_at=completed_at)

        expected_deadline = completed_at + timedelta(hours=1)
        assert payment.refund_deadline == expected_deadline

    def test_refund_deadline_no_completion(self):
        """Test refund deadline when payment not completed."""
        payment = PaymentFactory.build(completed_at=None)
        assert payment.refund_deadline is None

    @patch("django.conf.settings.REFUND_TIME_LIMIT_HOURS", 1)
    @pytest.mark.parametrize(
        ("factory_kwargs", "settled_duration", "expected_is_refundable"),
        [
            ({"settled": True}, timedelta(minutes=59), True),
            ({"settled": True}, timedelta(hours=2), False),
            ({"partially_settled": True}, timedelta(minutes=59), True),
            ({"partially_settled": True}, timedelta(hours=2), False),
            ({"pending_settlement": True}, None, False),
            ({"refunded": True}, timedelta(minutes=59), False),
            ({"refunded": True}, timedelta(hours=2), False),
        ],
        ids=[
            "settled_within_refundable_deadline",
            "settled_outside_refundable_deadline",
            "partially_settled_within_refundable_deadline",
            "partially_settled_outside_refundable_deadline",
            "pending_payment_not_refundable",
            "refunded_settled_within_refundable_deadline",
            "refunded_settled_outside_refundable_deadline",
        ],
    )
    def test_is_refundable(
        self,
        factory_kwargs,
        settled_duration,
        expected_is_refundable,
    ):
        """Test is_refundable property"""
        completed_at = timezone.now() - settled_duration if settled_duration else None
        payment = PaymentFactory.build(**factory_kwargs, completed_at=completed_at)

        assert payment.is_refundable is expected_is_refundable

    def test_add_entrance_record_ticket(self):
        """Test adding ticket to payment."""
        payment = PaymentFactory()
        ticket = TicketFactory(counted=True)

        result = payment.add_entrance_record(ticket)

        assert result == ticket
        assert ticket.payment == payment

    def test_add_entrance_record_already_assigned(self):
        """Test error when adding already assigned entrance record."""
        ticket = TicketFactory(counted=True)
        PaymentFactory(for_entrance_records=[ticket])

        payment = PaymentFactory()

        with pytest.raises(ValidationError, match="already has a payment assigned"):
            payment.add_entrance_record(ticket)

    def test_remove_entrance_record_success(self):
        """Test successfully removing entrance record."""
        ticket = TicketFactory(counted=True)
        payment = PaymentFactory(for_entrance_records=[ticket])

        result = payment.remove_entrance_record(ticket)

        assert result == ticket
        assert ticket.payment is None

    def test_remove_entrance_record_wrong_payment(self):
        """Test error when removing record from wrong payment."""
        ticket = TicketFactory(counted=True)
        PaymentFactory(for_entrance_records=[ticket])

        payment = PaymentFactory()

        with pytest.raises(ValidationError, match="not assigned to this payment"):
            payment.remove_entrance_record(ticket)

    def test_remove_entrance_record_processed_payment(self):
        """Test error when removing record from processed payment."""
        ticket = TicketFactory(counted=True)
        payment = PaymentFactory(settled=True, for_entrance_records=[ticket])

        with pytest.raises(
            ValidationError,
            match="Cannot remove.*from processed payment",
        ):
            payment.remove_entrance_record(ticket)

    def test_add_transaction_success(self):
        """Test that add_transaction creates transaction and updates payment status."""
        created_by = UserFactory(with_active_shift=True)

        payment = PaymentFactory(
            created_by=created_by,
            pending_settlement=True,
            for_entrance_records=[
                TicketFactory(
                    counted=True,
                    with_items=True,
                    with_items__visitor_count=2,
                ),
            ],
        )

        transaction = payment.add_transaction(
            amount=Decimal("100.00"),
            visitor_count=1,
            added_by=created_by,
            payment_type="card",
            addpay_rrn="12345",
            addpay_transaction_id="67890",
            addpay_card_number="1234",
            addpay_cardholder_name="John Doe",
            addpay_response_data={},
        )

        # Assert transaction was actually created
        assert transaction.id is not None

        # Assert payment status updated correctly
        assert payment.status == "partially_settled"

        assert payment.transaction_items.count() == 1

        # Add another transaction to complete it
        payment.add_transaction(
            amount=Decimal("100.00"),
            visitor_count=1,
            added_by=created_by,
            payment_type="card",
            addpay_rrn="12345",
            addpay_transaction_id="67890",
            addpay_card_number="1234",
            addpay_cardholder_name="John Doe",
            addpay_response_data={},
        )

        assert payment.status == "settled"

    def test_add_transaction_overpayment(self):
        """Test validation error with overpayment."""
        created_by = UserFactory()
        payment = PaymentFactory(created_by=created_by, settled=True)

        with pytest.raises(ValueError, match="Amount exceeds outstanding balance"):
            payment.add_transaction(
                amount=Decimal("100.00"),
                added_by=created_by,
                visitor_count=1,
                payment_type="card",
                addpay_rrn="12345",
                addpay_transaction_id="67890",
                addpay_card_number="1234",
                addpay_cardholder_name="John Doe",
                addpay_response_data={},
            )

    def test_add_transaction_different_user(self):
        """Test validation error with overpayment."""
        payment = PaymentFactory(settled=True)

        with pytest.raises(ValidationError, match="Payment managed by another user"):
            payment.add_transaction(
                amount=Decimal("100.00"),
                added_by=UserFactory(),
                visitor_count=1,
                payment_type="card",
                addpay_rrn="12345",
                addpay_transaction_id="67890",
                addpay_card_number="1234",
                addpay_cardholder_name="John Doe",
                addpay_response_data={},
            )

    def test_initiate_refund_success(self):
        """Test successful refund initiation."""
        requested_by = UserFactory()
        vehicle = VehicleFactory()
        payment = PaymentFactory(
            settled=True,
            for_entrance_records=[
                TicketFactory(vehicle=vehicle, processed=True, with_items=True),
            ],
            with_transactions=True,
        )

        refund_reason = "Testing refund"

        refund = payment.initiate_refund(
            requested_by=requested_by,
            vehicle=vehicle,
            reason=refund_reason,
        )

        assert refund.id is not None
        assert refund.payment == payment
        assert refund.status == Refund.StatusChoices.PENDING_ALLOCATIONS
        assert refund.reason == refund_reason
        assert refund.requested_by == requested_by
        assert refund.vehicle_allocations.count() == 1
        assert refund.refund_transaction_items.count() == 0

    @pytest.mark.parametrize(
        (
            "completed_duration",
            "existing_refund",
            "different_vehicle",
            "reason",
            "error_message",
        ),
        [
            # Not refundable (outside time window)
            (
                timedelta(hours=2),
                False,
                False,
                "Testing refund",
                "Payment is outside refund time window or not completed",
            ),
            # Existing refund
            (
                timedelta(),
                True,
                False,
                "Testing refund",
                "Payment already has an active refund in progress",
            ),
            # Vehicle not linked
            (
                timedelta(),
                False,
                True,
                "Testing refund",
                "Vehicle does not belong to payment",
            ),
            # Empty reason
            (
                timedelta(),
                False,
                False,
                "",
                "Reason for refund is required",
            ),
        ],
        ids=[
            "not_refundable",
            "existing_refund",
            "vehicle_not_linked",
            "empty_reason",
        ],
    )
    def test_initiate_refund_failure(
        self,
        completed_duration,
        existing_refund,
        different_vehicle,
        reason,
        error_message,
    ):
        requested_by = UserFactory()
        vehicle = VehicleFactory()

        completed_at = timezone.now() - completed_duration

        payment = PaymentFactory(
            settled=True,
            for_entrance_records=[
                TicketFactory(vehicle=vehicle, processed=True, with_items=True),
            ],
            with_transactions=True,
            completed_at=completed_at,
        )

        if existing_refund:
            RefundFactory(payment=payment)

        # Use different vehicle if specified
        test_vehicle = VehicleFactory() if different_vehicle else vehicle

        with pytest.raises(ValidationError, match=error_message):
            payment.initiate_refund(
                requested_by=requested_by,
                vehicle=test_vehicle,
                reason=reason,
            )

    def test_clean_validation_settled_with_outstanding(self):
        """Test validation error when settled but has outstanding balance."""
        payment = PaymentFactory(
            partially_settled=True,
            for_entrance_records=[
                TicketFactory(
                    counted=True,
                    with_items=True,
                ),
            ],
            with_transactions=True,
        )

        payment.status = Payment.PaymentStatusChoices.SETTLED
        with pytest.raises(ValidationError, match="still has outstanding balance"):
            payment.save()

    def test_clean_validation_no_entrance_records(self):
        """Test validation error when no tickets or re-entries."""
        payment = PaymentFactory(for_entrance_records=[])

        with pytest.raises(
            ValidationError,
            match="must have at least one ticket or re-entry",
        ):
            payment.save()


@pytest.mark.django_db(transaction=True)
class TestTransactionItem:
    """Test suite for the TransactionItem model."""

    def test_str_representation(self):
        """Test string representation of transaction item."""
        transaction = TransactionItemFactory(
            amount=Decimal("100.00"),
            visitor_count=1,
            as_card_transaction=True,
        )
        expected = "card - R 100.00"
        assert str(transaction) == expected

    @pytest.mark.parametrize(
        ("transaction_item_kwargs", "expected_is_card", "expected_is_cash"),
        [
            ({"as_card_transaction": True}, True, False),
            ({"as_cash_transaction": True}, False, True),
        ],
        ids=["card_transaction", "cash_transaction"],
    )
    def test_transaction_type(
        self,
        transaction_item_kwargs,
        expected_is_card,
        expected_is_cash,
    ):
        """Test is_card_transaction property."""
        transaction = TransactionItemFactory(
            amount=Decimal("100.00"),
            visitor_count=1,
            **transaction_item_kwargs,
        )

        assert transaction.is_card_transaction is expected_is_card
        assert transaction.is_cash_transaction is expected_is_cash

    def test_change_due_calculation(self):
        """Test change calculation for cash transactions."""
        transaction = TransactionItemFactory.create(
            amount=Decimal("100.00"),
            visitor_count=1,
            cash_tendered=Decimal("120.00"),
            as_cash_transaction=True,
        )

        assert transaction.change_due == Decimal("20.00")

    @pytest.mark.parametrize(
        ("transaction_item_kwargs", "reset_tendered", "error_message"),
        [
            (
                {"as_card_transaction": True},
                False,
                "Change not possible on card payments",
            ),
            (
                {"cash_tendered": Decimal("120.00"), "as_cash_transaction": True},
                True,
                "Cash tendered is required",
            ),
        ],
        ids=["card_transaction", "cash_transaction_no_tendered"],
    )
    def test_change_due_error(
        self,
        transaction_item_kwargs,
        reset_tendered,
        error_message,
    ):
        """Test error when calculating change without cash tendered."""
        transaction = TransactionItemFactory.create(
            amount=Decimal("100.00"),
            visitor_count=1,
            **transaction_item_kwargs,
        )

        if reset_tendered:
            transaction.cash_tendered = None

        with pytest.raises(ValueError, match=error_message):
            test = transaction.change_due  # noqa: F841

    @pytest.mark.parametrize(
        ("add_pay_kwargs", "should_raise"),
        [
            (
                {
                    "addpay_rrn": "12345",
                    "addpay_transaction_id": "67890",
                    "addpay_card_number": "1234",
                    "addpay_cardholder_name": "John Doe",
                    "addpay_response_data": {},
                },
                False,
            ),
            (
                {
                    "addpay_transaction_id": "67890",
                    "addpay_card_number": "1234",
                    "addpay_cardholder_name": "John Doe",
                    "addpay_response_data": {},
                },
                True,
            ),
            (
                {
                    "addpay_rrn": "12345",
                    "addpay_card_number": "1234",
                    "addpay_cardholder_name": "John Doe",
                    "addpay_response_data": {},
                },
                True,
            ),
            (
                {
                    "addpay_rrn": "12345",
                    "addpay_transaction_id": "67890",
                    "addpay_cardholder_name": "John Doe",
                    "addpay_response_data": {},
                },
                True,
            ),
            (
                {
                    "addpay_rrn": "12345",
                    "addpay_transaction_id": "67890",
                    "addpay_card_number": "1234",
                    "addpay_response_data": {},
                },
                True,
            ),
            ({}, True),
        ],
        ids=[
            "all_present_not_missing",
            "missing_rrn",
            "missing_transaction_id",
            "missing_card_number",
            "missing_cardholder_name",
            "all_missing",
        ],
    )
    def test_is_missing_addpay_data(
        self,
        add_pay_kwargs,
        should_raise,
    ):
        """Test detection of missing AddPay data for card transactions."""
        shared_kwargs = {"visitor_count": 1, "amount": Decimal("100.00")}

        if should_raise:
            with pytest.raises(
                ValueError,
                match="Cannot save card transaction without AddPay data",
            ):
                TransactionItemFactory(
                    payment_type=TransactionItem.PaymentTypeChoices.CARD,
                    **add_pay_kwargs,
                    **shared_kwargs,
                )
        else:
            transaction = TransactionItemFactory(
                **add_pay_kwargs,
                **shared_kwargs,
                as_card_transaction=True,
            )
            assert transaction.is_missing_addpay_data is should_raise

    def test_refund_amount_calculations(self):
        """Test refund amount calculations."""
        vehicle = VehicleFactory()

        ticket = TicketFactory(
            vehicle=vehicle,
            processed=True,
        )

        ticket_item = TicketItemFactory(ticket=ticket, visitor_count=2, skip_clean=True)

        payment = PaymentFactory(
            settled=True,
            for_entrance_records=[ticket],
            with_transactions=False,
        )

        transaction_item = TransactionItemFactory(
            payment=payment,
            visitor_count=2,
            amount=2 * PRICE_PER_VISITOR,
            as_card_transaction=True,
        )

        refund = RefundFactory.create(payment=payment)

        RefundVehicleAllocationFactory.create(
            refund=refund,
            ticket_item=ticket_item,
            visitor_count=1,
            settled=True,
        )

        # Create refund transaction items
        RefundTransactionItemFactory.create(
            refund=refund,
            transaction_item=transaction_item,
            amount=PRICE_PER_VISITOR,
            visitor_count=1,
            processed=True,
        )

        assert transaction_item.total_processed_refund_amount == PRICE_PER_VISITOR
        assert transaction_item.total_processed_refund_count == 1
        assert transaction_item.remaining_refundable_amount == PRICE_PER_VISITOR
        assert transaction_item.remaining_refundable_count == 1

    @pytest.mark.parametrize(
        ("transaction_kwargs", "error_message"),
        [
            (
                {"payment_type": TransactionItem.PaymentTypeChoices.CASH},
                "Cash tendered is required for cash payments",
            ),
            (
                {
                    "payment_type": TransactionItem.PaymentTypeChoices.CASH,
                    "cash_tendered": Decimal("100.00"),
                },
                "Cash tendered must be greater than or equal to the amount",
            ),
            (
                {"payment_type": TransactionItem.PaymentTypeChoices.CARD},
                "Cannot save card transaction without AddPay data",
            ),
        ],
        ids=[
            "cash_transaction_no_tendered",
            "cash_transaction_less_tendered",
            "card_transaction_missing_addpay_data",
        ],
    )
    def test_clean_validation(self, transaction_kwargs, error_message):
        """Test validation error for cash transaction without tendered amount."""
        with pytest.raises(
            ValueError,
            match=error_message,
        ):
            TransactionItemFactory(
                visitor_count=2,
                amount=Decimal("200.00"),
                **transaction_kwargs,
            )

    def test_delete_prevention(self):
        """Test that transaction items cannot be deleted."""
        transaction = TransactionItemFactory(
            visitor_count=2,
            amount=Decimal("200.00"),
            as_card_transaction=True,
        )

        with pytest.raises(
            ValidationError,
            match="Can't delete processed transaction items",
        ):
            transaction.delete()


@pytest.mark.django_db(transaction=True)
class TestRefundVehicleAllocation:
    """Test suite for the RefundVehicleAllocation model."""

    @pytest.fixture
    def get_allocation(self):
        def _get_allocation(
            visitor_count: int,
            entrance_type: Literal["Ticket", "ReEntry"] = "Ticket",
            allocation_count: int | None = None,
        ):
            if allocation_count is None:
                allocation_count = visitor_count

            vehicle = VehicleFactory(plate_number="ABC123GP")

            ticket = TicketFactory(
                vehicle=vehicle,
                processed=True,
                with_items=[{"visitor_count": visitor_count}],
            )

            re_entry = None

            if entrance_type == "ReEntry":
                re_entry = ReEntryFactory(
                    ticket=ticket,
                    processed=True,
                    visitors_left=1,
                    visitors_returned=1 + visitor_count,
                    with_items=[{"visitor_count": visitor_count}],
                )

            payment = PaymentFactory(
                settled=True,
                for_entrance_records=[
                    ticket if entrance_type == "Ticket" else re_entry,
                ],
            )

            refund = RefundFactory(
                payment=payment,
            )

            if entrance_type == "Ticket":
                entrance_item = payment.tickets.first().ticket_items.first()
                allocation_kwargs = {
                    "ticket_item": entrance_item,
                }
            elif entrance_type == "ReEntry":
                entrance_item = payment.re_entries.first().re_entry_items.first()
                allocation_kwargs = {
                    "re_entry_item": entrance_item,
                }

            allocation = RefundVehicleAllocationFactory(
                refund=refund,
                visitor_count=allocation_count,
                **allocation_kwargs,
            )

            return allocation, vehicle, entrance_item, refund, payment

        return _get_allocation

    def test_str_representation(self, get_allocation):
        """Test string representation of refund allocation."""
        visitor_count = 3
        allocation, vehicle, *_ = get_allocation(visitor_count=visitor_count)

        expected = f"Vehicle {vehicle.plate_number} - {visitor_count} visitors"
        assert str(allocation) == expected

    @pytest.mark.parametrize(
        ("entrance_type"),
        [("Ticket"), ("ReEntry")],
        ids=["ticket_item_linked", "re_entry_item_linked"],
    )
    def test_entrance_item_property(self, get_allocation, entrance_type):
        """Test entrance_item property returns re-entry item."""
        allocation, _, entrance_item, *_ = get_allocation(
            visitor_count=3,
            entrance_type=entrance_type,
        )

        assert allocation.entrance_item == entrance_item

    def test_vehicle_property(self, get_allocation):
        """Test vehicle property."""
        allocation, vehicle, *_ = get_allocation(
            visitor_count=3,
        )

        assert allocation.vehicle == vehicle

    def test_clean_validation_both_items(self, get_allocation):
        """Test validation error when both entrance items are set."""
        allocation, *_ = get_allocation(
            visitor_count=3,
        )

        allocation.re_entry_item = ReEntryItemFactory()

        with pytest.raises(ValidationError, match="linked to a single entrance item"):
            allocation.save()

    def test_clean_validation_no_items(self, get_allocation):
        """Test validation error when no entrance items are set."""
        allocation, *_ = get_allocation(
            visitor_count=3,
        )

        allocation.ticket_item = None

        with pytest.raises(
            ValidationError,
            match="linked to a single entrance item",
        ):
            allocation.clean()

    def test_clean_validation_payment_vehicle_mismatch(self):
        """Test validation error when vehicle doesn't match payment."""
        with pytest.raises(
            ValidationError,
            match="Cannot allocate a vehicle from a different payment",
        ):
            RefundVehicleAllocationFactory(
                refund=RefundFactory(),
                ticket_item=TicketItemFactory(),
            )

    def test_clean_validation_zero_visitors(self, get_allocation):
        """Test validation error with zero visitor count."""
        with pytest.raises(ValidationError, match="must be greater than 0"):
            get_allocation(visitor_count=0)

    def test_clean_validation_exceeds_refundable(self, get_allocation):
        """Test validation error when count exceeds refundable limit."""
        visitor_count = 2
        allocation, *_ = get_allocation(
            visitor_count=visitor_count,
        )

        allocation.visitor_count = visitor_count + 2

        with (
            pytest.raises(
                ValidationError,
                match="Count exceeds remaining refundable visitors",
            ),
        ):
            allocation.save()

    @pytest.mark.parametrize(
        ("update_count", "error_message"),
        [
            (4, None),
            (0, "Count cannot be 0 or negative"),
            (-1, "Count cannot be 0 or negative"),
            (5, "Count exceeds remaining refundable amount"),
        ],
        ids=[
            "succesful_update",
            "failed_zero_count",
            "failed_negative_count",
            "failed_exceeds_limit",
        ],
    )
    def test_update_visitor(
        self,
        get_allocation,
        update_count,
        error_message,
    ):
        """Test successful visitor count update."""
        visitor_count = 4
        allocation_count = 2

        allocation, *_ = get_allocation(
            visitor_count=visitor_count,
            allocation_count=allocation_count,
        )

        if error_message:
            with pytest.raises(ValueError, match=error_message):
                allocation.update_visitor_count(count=update_count)
            return

        allocation.update_visitor_count(count=4)

        assert allocation.visitor_count == 4
        assert allocation.status == RefundVehicleAllocationStatusChoices.COUNTED

    def test_update_visitor_count_invalid_status(self, get_allocation):
        """Test error when updating count on completed allocation."""
        visitor_count = 4
        allocation_count = 2

        allocation, *_ = get_allocation(
            visitor_count=visitor_count,
            allocation_count=allocation_count,
        )

        allocation.status = RefundVehicleAllocationStatusChoices.SETTLED

        with pytest.raises(
            ValueError,
            match="Can't update count on completed allocations",
        ):
            allocation.update_visitor_count(3)


@pytest.mark.django_db(transaction=True)
class TestRefundTransactionItem:
    """Test suite for the RefundTransactionItem model."""

    def test_str_representation(self):
        """Test string representation of refund transaction item."""
        visitor_count = 1
        amount = Decimal("100.00")

        refund_transaction = RefundTransactionItemFactory(
            visitor_count=visitor_count,
            amount=amount,
            processed=True,
        )

        expected = f"RefundTransaction {refund_transaction.id} - processed - R{amount}"
        assert str(refund_transaction) == expected

    def test_process_transaction_success(self):
        """Test successfully marking refund transaction as processed."""
        visitor_count = 1
        amount = Decimal("100.00")

        refund_transaction = RefundTransactionItemFactory(
            visitor_count=visitor_count,
            amount=amount,
        )

        processed_by = UserFactory()

        refund_transaction.process_transaction(processed_by=processed_by)

        assert (
            refund_transaction.status == RefundTransactionItem.StatusChoices.PROCESSED
        )

        assert refund_transaction.processed_by == processed_by
        assert refund_transaction.processed_at is not None

    def test_process_transaction_wrong_status(self):
        """Test error when marking non-pending transaction as processed."""
        visitor_count = 1
        amount = Decimal("100.00")

        refund_transaction = RefundTransactionItemFactory(
            visitor_count=visitor_count,
            amount=amount,
            processed=True,
        )
        with pytest.raises(
            ValidationError,
            match="Only pending refund transactions can be processed",
        ):
            refund_transaction.process_transaction(processed_by=UserFactory())

    def test_clean_validation_zero_visitors(self):
        """Test validation error with zero visitor count."""
        visitor_count = 0
        amount = Decimal("0.00")

        with pytest.raises(
            ValidationError,
            match="Visitor count must be greater than 0",
        ):
            RefundTransactionItemFactory(
                visitor_count=visitor_count,
                amount=amount,
                processed=True,
            )

    def test_clean_validation_exceeds_allocation(self):
        """Test validation error when exceeds allocation limit."""
        visitor_count = 2
        amount = Decimal("200.00")

        refund_transaction = RefundTransactionItemFactory(
            visitor_count=visitor_count,
            amount=amount,
            processed=True,
        )

        # Set to exceed allocation
        refund_transaction.visitor_count = visitor_count + 2

        with pytest.raises(
            ValidationError,
            match="Requested refund count more than added allocated count",
        ):
            refund_transaction.clean()

    def test_clean_validation_exceeds_transaction_limit(self):
        """Test validation error when exceeds transaction limit."""
        visitor_count = 2
        amount = Decimal("200.00")

        refund_transaction = RefundTransactionItemFactory(
            visitor_count=visitor_count,
            amount=amount,
            processed=True,
        )

        # Set to exceed transcation limit
        exceeded_count = visitor_count + 2
        refund_transaction.visitor_count = exceeded_count

        # Mock the property return to simulate exceeding limit
        with (
            patch.object(
                type(refund_transaction.refund),
                "remaining_refundable_count",
                new_callable=PropertyMock,
                return_value=exceeded_count,
            ),
            pytest.raises(
                ValidationError,
                match="Requested refund count more than remaining refundable count",
            ),
        ):
            refund_transaction.clean()


@pytest.mark.django_db(transaction=True)
class TestRefund:
    """Test suite for the Refund model."""

    def test_str_representation(self):
        """Test string representation of refund."""
        refund = RefundFactory(for_payment=True)

        expected = (
            f"Refund {refund.ref_number} - {Refund.StatusChoices.PENDING_ALLOCATIONS} "
            f"- R0"
        )
        assert str(refund) == expected

    @pytest.mark.parametrize(
        ("initial_status", "new_status", "should_raise"),
        [
            # Valid transitions
            (
                Refund.StatusChoices.PENDING_ALLOCATIONS,
                Refund.StatusChoices.PENDING_TRANSACTIONS,
                False,
            ),
            (
                Refund.StatusChoices.PENDING_TRANSACTIONS,
                Refund.StatusChoices.PENDING_SETTLEMENT,
                False,
            ),
            (
                Refund.StatusChoices.PENDING_SETTLEMENT,
                Refund.StatusChoices.SETTLED,
                False,
            ),
            (
                Refund.StatusChoices.PENDING_SETTLEMENT,
                Refund.StatusChoices.DENIED,
                False,
            ),
            # Invalid transitions
            (
                Refund.StatusChoices.PENDING_TRANSACTIONS,
                Refund.StatusChoices.PENDING_ALLOCATIONS,
                True,
            ),
            (
                Refund.StatusChoices.SETTLED,
                Refund.StatusChoices.PENDING_SETTLEMENT,
                True,
            ),
            (
                Refund.StatusChoices.DENIED,
                Refund.StatusChoices.SETTLED,
                True,
            ),
        ],
        ids=[
            "valid_allocations_to_transactions",
            "valid_transactions_to_settlement",
            "valid_settlement_to_settled",
            "valid_settlement_to_denied",
            "invalid_transactions_to_allocations",
            "invalid_settled_to_settlement",
            "invalid_denied_to_settled",
        ],
    )
    def test_update_status(self, initial_status, new_status, should_raise):
        """Test refund status transition validation."""
        refund = RefundFactory(
            for_payment={
                "for_entrance_records": [
                    TicketFactory(processed=True, with_items=[{"visitor_count": 3}]),
                    ReEntryFactory(
                        processed=True,
                        visitors_left=1,
                        visitors_returned=3,
                        with_items=[{"visitor_count": 2}],
                    ),
                ],
                "with_transactions": True,
            },
            with_allocations=True,
            with_refund_transactions=True,
            status=initial_status,
        )

        if should_raise:
            with pytest.raises(ValidationError, match="Invalid transition"):
                refund.update_status(new_status)
            return

        refund.update_status(new_status)
        assert refund.status == new_status

    def test_allocation_count_properties(self):
        """Test allocation count calculation properties."""
        ticket_visitors = 3
        add_re_entry_visitors = 2

        ticket_vehicle_allocation = 2
        re_entry_vehicle_allocation = 2

        refund = RefundFactory(
            partially_settled=True,
            for_payment={
                "status": "partially_refunded",
                "for_entrance_records": [
                    TicketFactory(
                        processed=True,
                        with_items=[{"visitor_count": ticket_visitors}],
                    ),
                    ReEntryFactory(
                        processed=True,
                        visitors_left=1,
                        visitors_returned=add_re_entry_visitors + 1,
                        with_items=[{"visitor_count": add_re_entry_visitors}],
                    ),
                ],
                "with_transactions": True,
            },
            with_allocations=[
                {"visitor_count": ticket_vehicle_allocation},
                {"visitor_count": re_entry_vehicle_allocation},
            ],
        )

        assert (
            refund.total_allocation_count
            == ticket_vehicle_allocation + re_entry_vehicle_allocation
        )

    def test_refund_count_properties(self):
        """Test refund count calculation properties."""
        ticket_visitors = 3
        add_reentry_visitors = 2

        processed_refund_count = 2
        pending_refund_count = 1

        refund = RefundFactory(
            partially_settled=True,
            for_payment={
                "status": "partially_refunded",
                "for_entrance_records": [
                    TicketFactory(
                        processed=True,
                        with_items=[{"visitor_count": ticket_visitors}],
                    ),
                    ReEntryFactory(
                        processed=True,
                        visitors_left=1,
                        visitors_returned=add_reentry_visitors + 1,
                        with_items=[{"visitor_count": add_reentry_visitors}],
                    ),
                ],
                "with_transactions": [
                    {
                        "visitor_count": ticket_visitors,
                        "amount": PRICE_PER_VISITOR * ticket_visitors,
                        "payment_type": "card",
                    },
                    {
                        "visitor_count": add_reentry_visitors,
                        "amount": PRICE_PER_VISITOR * add_reentry_visitors,
                        "payment_type": "card",
                    },
                ],
            },
            with_allocations=True,
            with_refund_transactions=[
                {
                    "visitor_count": processed_refund_count,
                    "amount": PRICE_PER_VISITOR * processed_refund_count,
                    "processed": True,
                },
                {
                    "visitor_count": pending_refund_count,
                    "amount": PRICE_PER_VISITOR * pending_refund_count,
                },
            ],
        )

        assert refund.processed_refund_count == processed_refund_count
        assert refund.pending_refund_count == pending_refund_count

        total_paid_visitors = ticket_visitors + add_reentry_visitors

        assert (
            refund.remaining_refundable_count
            == total_paid_visitors - processed_refund_count - pending_refund_count
        )

    def test_refund_amount_properties(self):
        """Test refund amount calculation properties."""
        ticket_visitors = 3
        add_reentry_visitors = 2

        processed_refund_count = 2
        pending_refund_count = 1

        refund = RefundFactory(
            partially_settled=True,
            for_payment={
                "status": "partially_refunded",
                "for_entrance_records": [
                    TicketFactory(
                        processed=True,
                        with_items=[{"visitor_count": ticket_visitors}],
                    ),
                    ReEntryFactory(
                        processed=True,
                        visitors_left=1,
                        visitors_returned=add_reentry_visitors + 1,
                        with_items=[{"visitor_count": add_reentry_visitors}],
                    ),
                ],
                "with_transactions": [
                    {
                        "visitor_count": ticket_visitors,
                        "amount": PRICE_PER_VISITOR * ticket_visitors,
                        "payment_type": "card",
                    },
                    {
                        "visitor_count": add_reentry_visitors,
                        "amount": PRICE_PER_VISITOR * add_reentry_visitors,
                        "payment_type": "card",
                    },
                ],
            },
            with_allocations=True,
            with_refund_transactions=[
                {
                    "visitor_count": processed_refund_count,
                    "amount": PRICE_PER_VISITOR * processed_refund_count,
                    "processed": True,
                },
                {
                    "visitor_count": pending_refund_count,
                    "amount": PRICE_PER_VISITOR * pending_refund_count,
                },
            ],
        )

        assert (
            refund.processed_refund_amount == processed_refund_count * PRICE_PER_VISITOR
        )
        assert refund.pending_refund_amount == pending_refund_count * PRICE_PER_VISITOR

    def test_allocations_count_complete(self):
        """Test allocations count completion status."""
        ticket_visitors = 3
        add_re_entry_visitors = 2

        ticket_vehicle_allocation = ticket_visitors
        re_entry_vehicle_allocation = add_re_entry_visitors

        refund = RefundFactory(
            partially_settled=True,
            for_payment={
                "status": "partially_refunded",
                "for_entrance_records": [
                    TicketFactory(
                        processed=True,
                        with_items=[{"visitor_count": ticket_visitors}],
                    ),
                    ReEntryFactory(
                        processed=True,
                        visitors_left=1,
                        visitors_returned=add_re_entry_visitors + 1,
                        with_items=[{"visitor_count": add_re_entry_visitors}],
                    ),
                ],
                "with_transactions": True,
            },
        )

        ticket_item = refund.payment.tickets.first().ticket_items.first()
        re_entry_item = refund.payment.re_entries.first().re_entry_items.first()

        ticket_allocation = RefundVehicleAllocationFactory(
            refund=refund,
            ticket_item=ticket_item,
        )

        assert refund.allocations_count_complete is False

        ticket_allocation.update_visitor_count(
            count=ticket_vehicle_allocation,
            save=True,
        )

        RefundVehicleAllocationFactory(
            refund=refund,
            re_entry_item=re_entry_item,
            counted=True,
            visitor_count=re_entry_vehicle_allocation,
        )

        assert refund.allocations_count_complete is True

    def test_all_transactions_processed(self):
        """Test all transactions processed status."""
        ticket_visitors = 3
        add_reentry_visitors = 2
        total_visitors = ticket_visitors + add_reentry_visitors

        refund = RefundFactory(
            partially_settled=True,
            for_payment={
                "status": "partially_refunded",
                "for_entrance_records": [
                    TicketFactory(
                        processed=True,
                        with_items=[{"visitor_count": ticket_visitors}],
                    ),
                    ReEntryFactory(
                        processed=True,
                        visitors_left=1,
                        visitors_returned=add_reentry_visitors + 1,
                        with_items=[{"visitor_count": add_reentry_visitors}],
                    ),
                ],
                "with_transactions": True,
            },
            with_allocations=True,
        )

        assert refund.all_transactions_processed is False

        transaction_item = refund.payment.transaction_items.first()
        RefundTransactionItemFactory(
            refund=refund,
            transaction_item=transaction_item,
            processed=True,
            visitor_count=total_visitors,
            amount=total_visitors * PRICE_PER_VISITOR,
        )

        assert refund.all_transactions_processed is True

    def test_complete_refund_success(self):
        """Test successful refund completion."""
        user = UserFactory.create()

        refund = RefundFactory(
            partially_settled=True,
            for_payment=True,
            with_allocations=True,
            with_refund_transactions=True,
            with_refund_transactions__processed=True,
        )

        assert refund.status == Refund.StatusChoices.PARTIALLY_SETTLED
        assert refund.completed_by is None
        assert refund.completed_at is None

        refund.complete_refund(user)

        assert refund.status == Refund.StatusChoices.SETTLED
        assert refund.completed_by == user
        assert refund.completed_at is not None

    def test_complete_refund_with_pending_transactions(self):
        """Test error when completing refund with pending transactions."""
        refund = RefundFactory(
            partially_settled=True,
            for_payment=True,
            with_allocations=True,
            with_refund_transactions=True,
        )

        assert refund.status == Refund.StatusChoices.PARTIALLY_SETTLED
        assert refund.completed_by is None
        assert refund.completed_at is None

        with (
            pytest.raises(
                ValidationError,
                match="Cannot complete refund with pending transactions",
            ),
        ):
            refund.complete_refund(completed_by=UserFactory())

    def test_complete_refund_already_completed(self):
        """Test error when completing already completed refund."""
        refund = RefundFactory(
            settled=True,
            for_payment=True,
            with_allocations=True,
            with_refund_transactions=True,
            with_refund_transactions__processed=True,
        )

        assert refund.completed_by is not None
        assert refund.completed_at is not None

        with (
            pytest.raises(
                ValidationError,
                match="Cannot complete already approved",
            ),
        ):
            refund.complete_refund(completed_by=UserFactory())

    def test_deny_refund(self):
        """Test refund denial."""
        refund = RefundFactory(
            pending_settlement=True,
            for_payment=True,
        )

        user = UserFactory()
        reason = "Invalid request"

        refund.deny_refund(user, reason)

        assert refund.status == Refund.StatusChoices.DENIED
        assert refund.completed_by == user
        assert reason in refund.reason

    def test_add_allocation(self):
        """Test adding vehicle allocation."""
        ticket_visitors = 3
        add_re_entry_visitors = 2

        ticket_vehicle_allocation = 2
        re_entry_vehicle_allocation = 2

        refund = RefundFactory(
            partially_settled=True,
            for_payment={
                "for_entrance_records": [
                    TicketFactory(
                        processed=True,
                        with_items=[{"visitor_count": ticket_visitors}],
                    ),
                    ReEntryFactory(
                        processed=True,
                        visitors_left=1,
                        visitors_returned=add_re_entry_visitors + 1,
                        with_items=[{"visitor_count": add_re_entry_visitors}],
                    ),
                ],
                "with_transactions": True,
            },
            with_allocations=[
                {"visitor_count": ticket_vehicle_allocation},
            ],
        )

        re_entry_vehicle = refund.payment.re_entries.first().vehicle

        refund.add_allocation(
            vehicle=re_entry_vehicle,
            processed_by=UserFactory(),
            visitor_count=re_entry_vehicle_allocation,
        )

        assert (
            refund.total_allocation_count
            == ticket_vehicle_allocation + re_entry_vehicle_allocation
        )

    def test_add_refund_transaction(self):
        """Test adding refund transaction."""
        ticket_visitors = 3
        add_re_entry_visitors = 2
        total_paid_visitors = ticket_visitors + add_re_entry_visitors
        refund_user = UserFactory()

        refund = RefundFactory(
            partially_settled=True,
            requested_by=refund_user,
            for_payment={
                "for_entrance_records": [
                    TicketFactory(
                        processed=True,
                        with_items=[{"visitor_count": ticket_visitors}],
                    ),
                    ReEntryFactory(
                        processed=True,
                        visitors_left=1,
                        visitors_returned=add_re_entry_visitors + 1,
                        with_items=[{"visitor_count": add_re_entry_visitors}],
                    ),
                ],
                "with_transactions": True,
            },
            with_allocations=True,
            with_refund_transactions=[],
        )

        assert refund.refund_transaction_items.count() == 0

        transaction_item = refund.payment.transaction_items.first()

        refund_transaction_item = refund.add_refund_transaction(
            transaction_item=transaction_item,
            added_by=refund_user,
            visitor_count=total_paid_visitors,
            amount=total_paid_visitors * PRICE_PER_VISITOR,
        )

        assert refund.refund_transaction_items.count() == 1
        assert refund.remaining_refundable_count == 0
        assert (
            refund_transaction_item.status
            == RefundTransactionItem.StatusChoices.PENDING
        )
        assert refund_transaction_item.visitor_count == total_paid_visitors
        assert refund_transaction_item.amount == total_paid_visitors * PRICE_PER_VISITOR

    @pytest.mark.parametrize(
        ("refund_kwargs", "error_message"),
        [
            ({"payment__status": "pending_settlement"}, "Can only refund settled"),
            (
                {
                    "partially_settled": True,
                    "for_payment": True,
                    "with_allocations": True,
                    "with_refund_transactions": [
                        {
                            "visitor_count": 999,
                            "amount": 999 * PRICE_PER_VISITOR,
                            "skip_clean": True,
                        },
                    ],
                },
                "Refund exceeds maximum allocation count",
            ),
        ],
        ids=["invalid_payment_status", "exceeds_allocation_count"],
    )
    def test_clean_validation(self, refund_kwargs, error_message):
        """Test validation error for wrong payment status."""
        refund = RefundFactory(
            **refund_kwargs,
        )

        with pytest.raises(ValidationError, match=error_message):
            refund.clean()

    def test_clean_validation_manual_status_transition(self):
        """Test validation of status transitions during clean."""
        refund = RefundFactory(for_payment=True)

        assert refund._original_status == Refund.StatusChoices.PENDING_ALLOCATIONS  # noqa: SLF001
        assert refund.status == Refund.StatusChoices.PENDING_ALLOCATIONS

        # Attempt manual invalid status transition
        refund.status = Refund.StatusChoices.SETTLED

        with pytest.raises(ValidationError, match="Invalid transition"):
            refund.save()
