# ruff: noqa: ERA001, F401, I001, PLR2004

from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.db import transaction
from django.utils import timezone
from datetime import datetime, UTC

from farmyard_manager.entrance.managers import ReEntryManager
from farmyard_manager.entrance.managers import ReEntryQuerySet
from farmyard_manager.entrance.managers import TicketManager
from farmyard_manager.entrance.managers import TicketQuerySet
from farmyard_manager.entrance.models import ReEntry
from farmyard_manager.entrance.models import Ticket
from farmyard_manager.entrance.models.enums import ReEntryStatusChoices
from farmyard_manager.entrance.models.enums import TicketStatusChoices
from farmyard_manager.entrance.tests.models.factories import PricingFactory
from farmyard_manager.entrance.tests.models.factories import ReEntryFactory
from farmyard_manager.entrance.tests.models.factories import TicketFactory
from farmyard_manager.users.tests.factories import UserFactory
from farmyard_manager.vehicles.tests.factories import VehicleFactory


@pytest.mark.django_db(transaction=True)
class TestTicketQuerySet:
    """Test suite for the TicketQuerySet class."""

    @pytest.fixture
    def tickets_by_status(self):
        """Create tickets with different statuses for testing."""
        return {
            "pending_security": TicketFactory.create_batch(
                2,
                status=TicketStatusChoices.PENDING_SECURITY,
            ),
            "passed_security": TicketFactory.create_batch(
                3,
                status=TicketStatusChoices.PASSED_SECURITY,
            ),
            "counted": TicketFactory.create_batch(
                1,
                status=TicketStatusChoices.COUNTED,
            ),
            "processed": TicketFactory.create_batch(
                2,
                status=TicketStatusChoices.PROCESSED,
            ),
            "refunded": TicketFactory.create_batch(
                1,
                status=TicketStatusChoices.REFUNDED,
            ),
        }

    def test_queryset_assignment(self):
        """Test that Ticket manager uses TicketQuerySet."""
        assert isinstance(Ticket.objects.get_queryset(), TicketQuerySet)

    @pytest.mark.parametrize(
        ("method_name", "status", "expected_count"),
        [
            ("pending_security", TicketStatusChoices.PENDING_SECURITY, 2),
            ("passed_security", TicketStatusChoices.PASSED_SECURITY, 3),
            ("counted", TicketStatusChoices.COUNTED, 1),
            ("processed", TicketStatusChoices.PROCESSED, 2),
            ("refunded", TicketStatusChoices.REFUNDED, 1),
        ],
        ids=[
            "pending_security_filter",
            "passed_security_filter",
            "counted_filter",
            "processed_filter",
            "refunded_filter",
        ],
    )
    def test_status_filters(
        self,
        tickets_by_status,
        method_name,
        status,
        expected_count,
    ):
        """Test individual status filter methods."""
        queryset_method = getattr(Ticket.objects, method_name)
        result = queryset_method()

        assert result.count() == expected_count
        for ticket in result:
            assert ticket.status == status
            assert ticket in tickets_by_status[method_name]

    def test_by_status_custom(self, tickets_by_status):
        """Test by_status method with custom status."""
        result = Ticket.objects.by_status(TicketStatusChoices.PROCESSED)

        assert result.count() == 2
        for ticket in result:
            assert ticket.status == TicketStatusChoices.PROCESSED
            assert ticket in tickets_by_status["processed"]

    def test_for_vehicle(self):
        """Test filtering tickets by vehicle."""
        target_vehicle = VehicleFactory()
        other_vehicle = VehicleFactory()

        # Create tickets for target vehicle
        target_tickets = TicketFactory.create_batch(3, vehicle=target_vehicle)

        # Create tickets for other vehicle
        TicketFactory.create_batch(2, vehicle=other_vehicle)

        result = Ticket.objects.for_vehicle(target_vehicle)

        assert result.count() == 3
        for ticket in result:
            assert ticket.vehicle == target_vehicle
            assert ticket in target_tickets

    def test_for_vehicle_ordering(self):
        """Test that for_vehicle orders by creation date descending."""
        vehicle = VehicleFactory()

        # Create tickets at different times
        old_ticket = TicketFactory(
            vehicle=vehicle,
            created=timezone.now() - timedelta(days=10),
        )
        recent_ticket = TicketFactory(
            vehicle=vehicle,
            created=timezone.now() - timedelta(days=1),
        )
        middle_ticket = TicketFactory(
            vehicle=vehicle,
            created=timezone.now() - timedelta(days=5),
        )

        result = list(Ticket.objects.for_vehicle(vehicle))

        assert len(result) == 3
        # Should be ordered by created date descending
        assert result[0] == recent_ticket
        assert result[1] == middle_ticket
        assert result[2] == old_ticket

    def test_for_today(self):
        """Test filtering tickets created today."""
        # Don't manipulate dates - just use the default factory behavior
        today_tickets = TicketFactory.create_batch(
            2,
        )  # These will be created "now" = today

        # Create ticket for yesterday - ensure it's definitely yesterday
        yesterday_time = timezone.now() - timedelta(days=1)
        TicketFactory(created=yesterday_time)

        # Create ticket for tomorrow - ensure it's definitely tomorrow
        tomorrow_time = timezone.now() + timedelta(days=1)
        TicketFactory(created=tomorrow_time)

        result = Ticket.objects.for_today()

        assert result.count() == 2
        # Verify all returned tickets were created today
        today_date = timezone.now().date()
        for ticket in result:
            assert ticket.created.date() == today_date
            assert ticket in today_tickets

    # def test_with_payment(self):
    #     """Test filtering tickets with payment."""
    #     from farmyard_manager.payments.tests.factories import PaymentFactory

    #     # Create tickets with and without payment
    #     payment = PaymentFactory()
    #     tickets_with_payment = TicketFactory.create_batch(2, payment=payment)
    #     TicketFactory.create_batch(3, payment=None)

    #     result = Ticket.objects.with_payment()

    #     assert result.count() == 2
    #     for ticket in result:
    #         assert ticket.payment is not None
    #         assert ticket in tickets_with_payment

    # def test_without_payment(self):
    #     """Test filtering tickets without payment."""
    #     from farmyard_manager.payments.tests.factories import PaymentFactory

    #     # Create tickets with and without payment
    #     payment = PaymentFactory()
    #     TicketFactory.create_batch(2, payment=payment)
    #     tickets_without_payment = TicketFactory.create_batch(3, payment=None)

    #     result = Ticket.objects.without_payment()

    #     assert result.count() == 3
    #     for ticket in result:
    #         assert ticket.payment is None
    #         assert ticket in tickets_without_payment

    @pytest.mark.parametrize(
        ("search_term", "plate_numbers", "expected_count"),
        [
            ("ABC", ["ABC123GP", "XYZ789GP", "ABC456GP"], 2),
            ("123", ["ABC123GP", "XYZ789GP", "DEF123GP"], 2),
            ("ZZZ", ["ABC123GP", "XYZ789GP"], 0),
        ],
        ids=[
            "search_abc_prefix",
            "search_123_suffix",
            "search_no_matches",
        ],
    )
    def test_by_plate_number(self, search_term, plate_numbers, expected_count):
        """Test searching tickets by vehicle plate number."""
        # Create vehicles with different plate numbers and tickets
        for plate in plate_numbers:
            vehicle = VehicleFactory(plate_number=plate)
            TicketFactory(vehicle=vehicle)

        result = Ticket.objects.by_plate_number(search_term)

        assert result.count() == expected_count
        for ticket in result:
            assert search_term.upper() in ticket.vehicle.plate_number.upper()

    def test_with_re_entries(self):
        """Test filtering tickets that have re-entries."""
        # Create tickets with and without re-entries
        tickets_with_re_entries = TicketFactory.create_batch(
            2,
            status=TicketStatusChoices.PROCESSED,
        )
        tickets_without_re_entries = TicketFactory.create_batch(  # noqa: F841
            3,
            status=TicketStatusChoices.PROCESSED,
        )

        # Add re-entries to some tickets
        for ticket in tickets_with_re_entries:
            ReEntryFactory(ticket=ticket)

        result = Ticket.objects.with_re_entries()

        assert result.count() == 2
        for ticket in result:
            assert ticket.re_entries.exists()
            assert ticket in tickets_with_re_entries

    def test_by_date_range(self):
        """Test filtering tickets by date range."""
        now = timezone.now()
        base_date = now.date()
        start_date = base_date - timedelta(days=2)
        end_date = base_date + timedelta(days=2)

        # Create tickets within range
        in_range_tickets: list[Ticket] = []
        for days_offset in [-1, 0, 1]:  # Yesterday, today, tomorrow
            ticket_time = now + timedelta(days=days_offset)
            ticket: Ticket = TicketFactory(created=ticket_time)
            in_range_tickets.append(ticket)

        # Create tickets outside range
        TicketFactory(created=now - timedelta(days=5))
        TicketFactory(created=now + timedelta(days=5))

        result = Ticket.objects.by_date_range(start_date, end_date)

        assert result.count() == 3
        for ticket in result:
            assert start_date <= ticket.created.date() <= end_date
            assert ticket in in_range_tickets

    def test_queryset_chaining(self):
        """Test that QuerySet methods can be chained."""
        vehicle = VehicleFactory()
        now = timezone.now()

        # Create target ticket
        target_ticket = TicketFactory(
            vehicle=vehicle,
            status=TicketStatusChoices.PROCESSED,
            created=now.replace(hour=10, minute=0, second=0, microsecond=0),
        )

        # Create tickets that don't match all criteria
        TicketFactory(
            vehicle=vehicle,
            status=TicketStatusChoices.PENDING_SECURITY,
            created=now.replace(hour=10, minute=0, second=0, microsecond=0),
        )  # Wrong status
        TicketFactory(
            status=TicketStatusChoices.PROCESSED,
            created=now.replace(hour=10, minute=0, second=0, microsecond=0),
        )  # Wrong vehicle

        # Chain multiple filters
        result = Ticket.objects.processed().for_vehicle(vehicle).for_today()

        assert result.count() == 1
        assert result.first() == target_ticket


@pytest.mark.django_db(transaction=True)
class TestTicketManager:
    """Test suite for the TicketManager class."""

    def test_manager_assignment(self):
        """Test that Ticket model uses TicketManager."""
        assert isinstance(Ticket.objects, TicketManager)

    def test_create_ticket_basic(self):
        """Test basic ticket creation with pending security status."""
        vehicle = VehicleFactory()
        user = UserFactory()

        ticket = Ticket.objects.create_ticket(
            status=TicketStatusChoices.PENDING_SECURITY,
            vehicle=vehicle,
            performed_by=user,
        )

        assert ticket.status == TicketStatusChoices.PENDING_SECURITY
        assert ticket.vehicle == vehicle
        assert ticket.ref_number is not None

        # Verify status history was created
        status_history = ticket.status_history.get()
        assert status_history.prev_status == ""
        assert status_history.new_status == TicketStatusChoices.PENDING_SECURITY
        assert status_history.performed_by == user

    def test_create_ticket_with_status_transitions(self):
        """Test ticket creation and status transitions."""
        vehicle = VehicleFactory()
        user = UserFactory()

        # Create with initial valid status
        ticket = Ticket.objects.create_ticket(
            status=TicketStatusChoices.PENDING_SECURITY,
            vehicle=vehicle,
            performed_by=user,
        )

        assert ticket.status == TicketStatusChoices.PENDING_SECURITY
        assert ticket.vehicle == vehicle

    def test_create_ticket_with_custom_ref_number(self):
        """Test ticket creation with custom ref number."""
        vehicle = VehicleFactory()
        user = UserFactory()
        custom_ref = "CUSTOM-12345"

        ticket = Ticket.objects.create_ticket(
            status=TicketStatusChoices.PENDING_SECURITY,
            vehicle=vehicle,
            performed_by=user,
            ref_number=custom_ref,
        )

        assert ticket.ref_number == custom_ref

    def test_create_ticket_without_performed_by_fails(self):
        """Test that ticket creation fails without performed_by."""
        vehicle = VehicleFactory()

        with pytest.raises(
            ValueError,
            match="performed_by is required for new tickets",
        ):
            Ticket.objects.create_ticket(
                status=TicketStatusChoices.PENDING_SECURITY,
                vehicle=vehicle,
                performed_by=None,  # type: ignore[arg-type]
            )

    def test_create_ticket_with_additional_kwargs(self):
        """Test ticket creation with additional kwargs."""
        vehicle = VehicleFactory()
        user = UserFactory()

        ticket = Ticket.objects.create_ticket(
            status=TicketStatusChoices.PENDING_SECURITY,
            vehicle=vehicle,
            performed_by=user,
        )

        assert ticket.status == TicketStatusChoices.PENDING_SECURITY
        assert ticket.vehicle == vehicle

    def test_create_ticket_transaction_atomicity(self):
        """Test that ticket creation is atomic (rollback on failure)."""
        vehicle = VehicleFactory()
        user = UserFactory()

        # Mock the status history creation to fail
        with (
            patch.object(
                Ticket.status_history_model.objects,
                "create",
                side_effect=Exception("Status history creation failed"),
            ),
            pytest.raises(Exception, match="Status history creation failed"),
        ):
            Ticket.objects.create_ticket(
                status=TicketStatusChoices.PENDING_SECURITY,
                vehicle=vehicle,
                performed_by=user,
            )

        # Verify no ticket was created due to rollback
        assert Ticket.objects.count() == 0

    def test_price_validation_method_exists(self):
        """Test that _validate_price method exists and can be called."""
        result = Ticket.objects._validate_price("public")  # noqa: SLF001
        assert result is True

    # Test all delegate methods for IntelliSense support
    @pytest.mark.parametrize(
        "method_name",
        [
            "pending_security",
            "passed_security",
            "counted",
            "processed",
            "refunded",
            "for_today",
            "with_payment",
            "without_payment",
            "with_re_entries",
        ],
        ids=[
            "pending_security_delegate",
            "passed_security_delegate",
            "counted_delegate",
            "processed_delegate",
            "refunded_delegate",
            "for_today_delegate",
            "with_payment_delegate",
            "without_payment_delegate",
            "with_re_entries_delegate",
        ],
    )
    def test_manager_delegate_methods(self, method_name):
        """Test that manager delegate methods exist and return QuerySets."""
        method = getattr(Ticket.objects, method_name)
        assert callable(method)

        result = method()
        assert isinstance(result, TicketQuerySet)

    def test_manager_delegate_methods_with_params(self):
        """Test manager delegate methods that require parameters."""
        vehicle = VehicleFactory()
        start_date = timezone.now().date()
        end_date = start_date + timedelta(days=1)

        # Test methods that take parameters
        result = Ticket.objects.by_status(TicketStatusChoices.PENDING_SECURITY)
        assert isinstance(result, TicketQuerySet)

        result = Ticket.objects.for_vehicle(vehicle)
        assert isinstance(result, TicketQuerySet)

        result = Ticket.objects.by_plate_number("ABC")
        assert isinstance(result, TicketQuerySet)

        result = Ticket.objects.by_date_range(start_date, end_date)
        assert isinstance(result, TicketQuerySet)

    # Placeholder tests for sync methods
    def test_sync_offline_queue_ticket_placeholder(self):
        """Test sync_offline_queue_ticket method exists."""
        assert hasattr(Ticket.objects, "sync_offline_queue_ticket")
        assert callable(Ticket.objects.sync_offline_queue_ticket)

        # Test it doesn't crash when called
        vehicle = VehicleFactory()
        user = UserFactory()
        Ticket.objects.sync_offline_queue_ticket(vehicle=vehicle, performed_by=user)

    def test_sync_offline_security_check_placeholder(self):
        """Test sync_offline_security_check method exists."""
        assert hasattr(Ticket.objects, "sync_offline_security_check")
        assert callable(Ticket.objects.sync_offline_security_check)

        user = UserFactory()
        Ticket.objects.sync_offline_security_check(
            ticket_data={},
            performed_by=user,
        )

    def test_sync_offline_visitor_ticket_placeholder(self):
        """Test sync_offline_visitor_ticket method exists."""
        assert hasattr(Ticket.objects, "sync_offline_visitor_ticket")
        assert callable(Ticket.objects.sync_offline_visitor_ticket)

        user = UserFactory()
        Ticket.objects.sync_offline_visitor_ticket(
            ticket_data={},
            performed_by=user,
        )

    def test_sync_offline_cash_payment_placeholder(self):
        """Test sync_offline_cash_payment method exists."""
        assert hasattr(Ticket.objects, "sync_offline_cash_payment")
        assert callable(Ticket.objects.sync_offline_cash_payment)

        user = UserFactory()
        Ticket.objects.sync_offline_cash_payment(
            payment_data={},
            performed_by=user,
        )


@pytest.mark.django_db(transaction=True)
class TestReEntryQuerySet:
    """Test suite for the ReEntryQuerySet class."""

    @pytest.fixture
    def re_entries_by_status(self):
        """Create re-entries with different statuses for testing."""
        processed_tickets = TicketFactory.create_batch(
            4,
            status=TicketStatusChoices.PROCESSED,
        )

        return {
            "pending": ReEntryFactory.create_batch(
                2,
                status=ReEntryStatusChoices.PENDING,
                ticket=processed_tickets[0],
            ),
            "pending_payment": ReEntryFactory.create_batch(
                3,
                status=ReEntryStatusChoices.PENDING_PAYMENT,
                ticket=processed_tickets[1],
            ),
            "processed": ReEntryFactory.create_batch(
                1,
                status=ReEntryStatusChoices.PROCESSED,
                ticket=processed_tickets[2],
            ),
            "refunded": ReEntryFactory.create_batch(
                1,
                status=ReEntryStatusChoices.REFUNDED,
                ticket=processed_tickets[3],
            ),
        }

    def test_queryset_assignment(self):
        """Test that ReEntry manager uses ReEntryQuerySet."""
        assert isinstance(ReEntry.objects.get_queryset(), ReEntryQuerySet)

    @pytest.mark.parametrize(
        ("method_name", "status", "expected_count"),
        [
            ("pending", ReEntryStatusChoices.PENDING, 2),
            ("pending_payment", ReEntryStatusChoices.PENDING_PAYMENT, 3),
            ("processed", ReEntryStatusChoices.PROCESSED, 1),
            ("refunded", ReEntryStatusChoices.REFUNDED, 1),
        ],
        ids=[
            "pending_filter",
            "pending_payment_filter",
            "processed_filter",
            "refunded_filter",
        ],
    )
    def test_status_filters(
        self,
        re_entries_by_status,
        method_name,
        status,
        expected_count,
    ):
        """Test individual status filter methods."""
        queryset_method = getattr(ReEntry.objects, method_name)
        result = queryset_method()

        assert result.count() == expected_count
        for re_entry in result:
            assert re_entry.status == status
            assert re_entry in re_entries_by_status[method_name]

    def test_by_status_custom(self, re_entries_by_status):
        """Test by_status method with custom status."""
        result = ReEntry.objects.by_status(ReEntryStatusChoices.PROCESSED)

        assert result.count() == 1
        for re_entry in result:
            assert re_entry.status == ReEntryStatusChoices.PROCESSED
            assert re_entry in re_entries_by_status["processed"]

    def test_for_ticket(self):
        """Test filtering re-entries by ticket."""
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        other_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)

        # Create re-entries for target ticket
        target_re_entries = ReEntryFactory.create_batch(3, ticket=processed_ticket)

        # Create re-entries for other ticket
        ReEntryFactory.create_batch(2, ticket=other_ticket)

        result = ReEntry.objects.for_ticket(processed_ticket)

        assert result.count() == 3
        for re_entry in result:
            assert re_entry.ticket == processed_ticket
            assert re_entry in target_re_entries

    def test_for_ticket_ordering(self):
        """Test that for_ticket orders by creation date descending."""
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)

        # Create re-entries at different times
        old_re_entry = ReEntryFactory(
            ticket=processed_ticket,
            created=timezone.now() - timedelta(days=10),
        )
        recent_re_entry = ReEntryFactory(
            ticket=processed_ticket,
            created=timezone.now() - timedelta(days=1),
        )
        middle_re_entry = ReEntryFactory(
            ticket=processed_ticket,
            created=timezone.now() - timedelta(days=5),
        )

        result = list(ReEntry.objects.for_ticket(processed_ticket))

        assert len(result) == 3
        # Should be ordered by created date descending
        assert result[0] == recent_re_entry
        assert result[1] == middle_re_entry
        assert result[2] == old_re_entry

    def test_for_vehicle(self):
        """Test filtering re-entries by vehicle."""
        target_vehicle = VehicleFactory()
        other_vehicle = VehicleFactory()

        target_ticket = TicketFactory(
            vehicle=target_vehicle,
            status=TicketStatusChoices.PROCESSED,
        )
        other_ticket = TicketFactory(
            vehicle=other_vehicle,
            status=TicketStatusChoices.PROCESSED,
        )

        # Create re-entries for target vehicle
        target_re_entries = ReEntryFactory.create_batch(2, ticket=target_ticket)

        # Create re-entries for other vehicle
        ReEntryFactory.create_batch(3, ticket=other_ticket)

        result = ReEntry.objects.for_vehicle(target_vehicle)

        assert result.count() == 2
        for re_entry in result:
            assert re_entry.ticket.vehicle == target_vehicle
            assert re_entry in target_re_entries

    def test_for_today(self):
        """Test filtering re-entries created today."""
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)

        # Create re-entries for today using default factory behavior
        today_re_entries = ReEntryFactory.create_batch(
            2,
            ticket=processed_ticket,
        )  # These will be created "now" = today

        # Create re-entry for yesterday - ensure it's definitely yesterday
        ReEntryFactory(
            ticket=processed_ticket,
            created=timezone.now() - timedelta(days=1),
        )

        result = ReEntry.objects.for_today()

        assert result.count() == 2
        # Verify all returned re-entries were created today
        today_date = timezone.now().date()
        for re_entry in result:
            assert re_entry.created.date() == today_date
            assert re_entry in today_re_entries

    # def test_with_payment(self):
    #     """Test filtering re-entries with payment."""
    #     from farmyard_manager.payments.tests.factories import PaymentFactory

    #     processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
    #     payment = PaymentFactory()

    #     # Create re-entries with and without payment
    #     re_entries_with_payment = ReEntryFactory.create_batch(
    #         2,
    #         ticket=processed_ticket,
    #         payment=payment,
    #     )
    #     ReEntryFactory.create_batch(3, ticket=processed_ticket, payment=None)

    #     result = ReEntry.objects.with_payment()

    #     assert result.count() == 2
    #     for re_entry in result:
    #         assert re_entry.payment is not None
    #         assert re_entry in re_entries_with_payment

    # def test_without_payment(self):
    #     """Test filtering re-entries without payment."""
    #     from farmyard_manager.payments.tests.factories import PaymentFactory

    #     processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
    #     payment = PaymentFactory()

    #     # Create re-entries with and without payment
    #     ReEntryFactory.create_batch(2, ticket=processed_ticket, payment=payment)
    #     re_entries_without_payment = ReEntryFactory.create_batch(
    #         3,
    #         ticket=processed_ticket,
    #         payment=None,
    #     )

    #     result = ReEntry.objects.without_payment()

    #     assert result.count() == 3
    #     for re_entry in result:
    #         assert re_entry.payment is None
    #         assert re_entry in re_entries_without_payment

    @pytest.mark.parametrize(
        ("visitors_left", "visitors_returned", "should_match"),
        [
            (5, 7, True),  # More returned than left
            (5, 5, False),  # Same number returned
            (5, 3, False),  # Fewer returned than left
            (3, 8, True),  # Much more returned than left
        ],
        ids=[
            "more_returned_matches",
            "same_returned_no_match",
            "fewer_returned_no_match",
            "much_more_returned_matches",
        ],
    )
    def test_with_additional_visitors(
        self,
        visitors_left,
        visitors_returned,
        should_match,
    ):
        """Test filtering re-entries with additional visitors."""
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)

        re_entry = ReEntryFactory(
            ticket=processed_ticket,
            visitors_left=visitors_left,
            visitors_returned=visitors_returned,
        )

        result = ReEntry.objects.with_additional_visitors()

        if should_match:
            assert result.count() == 1
            assert result.first() == re_entry
        else:
            assert result.count() == 0

    def test_completed_and_incomplete(self):
        """Test filtering completed and incomplete re-entries."""
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        completion_time = timezone.now()

        # Create completed and incomplete re-entries
        completed_re_entries = ReEntryFactory.create_batch(
            2,
            ticket=processed_ticket,
            completed_time=completion_time,
        )
        incomplete_re_entries = ReEntryFactory.create_batch(
            3,
            ticket=processed_ticket,
            completed_time=None,
        )

        completed_result = ReEntry.objects.completed()
        incomplete_result = ReEntry.objects.incomplete()

        assert completed_result.count() == 2
        for re_entry in completed_result:
            assert re_entry.completed_time is not None
            assert re_entry in completed_re_entries

        assert incomplete_result.count() == 3
        for re_entry in incomplete_result:
            assert re_entry.completed_time is None
            assert re_entry in incomplete_re_entries

    def test_by_date_range(self):
        """Test filtering re-entries by date range."""
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        now = timezone.now()
        base_date = now.date()
        start_date = base_date - timedelta(days=2)
        end_date = base_date + timedelta(days=2)

        # Create re-entries within range
        in_range_re_entries: list[ReEntry] = []
        for days_offset in [-1, 0, 1]:  # Yesterday, today, tomorrow
            re_entry_time = now + timedelta(days=days_offset)
            re_entry: ReEntry = ReEntryFactory(
                ticket=processed_ticket,
                created=re_entry_time,
            )
            in_range_re_entries.append(re_entry)

        # Create re-entry outside range
        ReEntryFactory(
            ticket=processed_ticket,
            created=now - timedelta(days=5),
        )

        result = ReEntry.objects.by_date_range(start_date, end_date)

        assert result.count() == 3
        for re_entry in result:
            assert start_date <= re_entry.created.date() <= end_date
            assert re_entry in in_range_re_entries

    def test_queryset_chaining(self):
        """Test that QuerySet methods can be chained."""
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        now = timezone.now()

        # Create target re-entry
        target_re_entry = ReEntryFactory(
            ticket=processed_ticket,
            status=ReEntryStatusChoices.PENDING,
            created=now.replace(hour=10, minute=0, second=0, microsecond=0),
        )

        # Create re-entries that don't match all criteria
        ReEntryFactory(
            ticket=processed_ticket,
            status=ReEntryStatusChoices.PROCESSED,  # Wrong status
            created=now.replace(hour=10, minute=0, second=0, microsecond=0),
        )

        # Chain multiple filters
        result = ReEntry.objects.pending().for_ticket(processed_ticket).for_today()

        assert result.count() == 1
        assert result.first() == target_re_entry


@pytest.mark.django_db(transaction=True)
class TestReEntryManager:
    """Test suite for the ReEntryManager class."""

    def test_manager_assignment(self):
        """Test that ReEntry model uses ReEntryManager."""
        assert isinstance(ReEntry.objects, ReEntryManager)

    @pytest.mark.parametrize(
        ("visitors_left", "expected_visitors_left"),
        [
            (1, 1),
            (5, 5),
            (10, 10),
        ],
        ids=[
            "single_visitor",
            "multiple_visitors",
            "many_visitors",
        ],
    )
    def test_create_re_entry_basic(self, visitors_left, expected_visitors_left):
        """Test basic re-entry creation with different visitor counts."""
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        user = UserFactory()

        re_entry = ReEntry.objects.create_re_entry(
            ticket=processed_ticket,
            visitors_left=visitors_left,
            created_by=user,
        )

        assert re_entry.ticket == processed_ticket
        assert re_entry.visitors_left == expected_visitors_left
        assert re_entry.status == ReEntryStatusChoices.PENDING
        assert re_entry.ref_number is not None

    def test_create_re_entry_with_additional_kwargs(self):
        """Test re-entry creation with additional kwargs."""
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        user = UserFactory()

        re_entry = ReEntry.objects.create_re_entry(
            ticket=processed_ticket,
            visitors_left=5,
            created_by=user,
            status=ReEntryStatusChoices.PENDING_PAYMENT,  # Override default
        )

        assert re_entry.status == ReEntryStatusChoices.PENDING_PAYMENT
        assert re_entry.visitors_left == 5

    def test_create_re_entry_for_unprocessed_ticket_fails(self):
        """Test that re-entry creation fails for unprocessed tickets."""
        unprocessed_ticket = TicketFactory(status=TicketStatusChoices.COUNTED)
        user = UserFactory()

        with pytest.raises(
            ValueError,
            match="Cannot issue Re-Entry on un processed tickets",
        ):
            ReEntry.objects.create_re_entry(
                ticket=unprocessed_ticket,
                visitors_left=3,
                created_by=user,
            )

    @pytest.mark.parametrize(
        ("ticket_status", "should_fail"),
        [
            (TicketStatusChoices.PENDING_SECURITY, True),
            (TicketStatusChoices.PASSED_SECURITY, True),
            (TicketStatusChoices.COUNTED, True),
            (TicketStatusChoices.PROCESSED, False),
            (TicketStatusChoices.REFUNDED, False),
        ],
        ids=[
            "pending_security_fails",
            "passed_security_fails",
            "counted_fails",
            "processed_succeeds",
            "refunded_succeeds",
        ],
    )
    def test_create_re_entry_ticket_status_validation(self, ticket_status, should_fail):
        """Test re-entry creation validation based on ticket status."""
        ticket = TicketFactory(status=ticket_status)
        user = UserFactory()

        if should_fail:
            with pytest.raises(
                ValueError,
                match="Cannot issue Re-Entry on un processed tickets",
            ):
                ReEntry.objects.create_re_entry(
                    ticket=ticket,
                    visitors_left=3,
                    created_by=user,
                )
        else:
            re_entry = ReEntry.objects.create_re_entry(
                ticket=ticket,
                visitors_left=3,
                created_by=user,
            )
            assert re_entry is not None
            assert re_entry.ticket == ticket

    def test_create_re_entry_saves_to_database(self):
        """Test that created re-entry is saved to database."""
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        user = UserFactory()

        re_entry = ReEntry.objects.create_re_entry(
            ticket=processed_ticket,
            visitors_left=3,
            created_by=user,
        )

        assert ReEntry.objects.filter(id=re_entry.id).exists()

        retrieved_re_entry = ReEntry.objects.get(id=re_entry.id)
        assert retrieved_re_entry.ticket == processed_ticket
        assert retrieved_re_entry.visitors_left == 3

    def test_create_re_entry_with_zero_visitors_left(self):
        """Test re-entry creation with zero visitors_left."""
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        user = UserFactory()

        re_entry = ReEntry.objects.create_re_entry(
            ticket=processed_ticket,
            visitors_left=0,
            created_by=user,
        )

        assert re_entry.visitors_left == 0

    def test_create_re_entry_multiple_for_same_ticket(self):
        """Test creating multiple re-entries for the same ticket."""
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        user = UserFactory()

        re_entry1 = ReEntry.objects.create_re_entry(
            ticket=processed_ticket,
            visitors_left=3,
            created_by=user,
        )

        re_entry2 = ReEntry.objects.create_re_entry(
            ticket=processed_ticket,
            visitors_left=2,
            created_by=user,
        )

        assert re_entry1.ticket == re_entry2.ticket
        assert re_entry1.id != re_entry2.id
        assert processed_ticket.re_entries.count() == 2

    @pytest.mark.parametrize(
        "method_name",
        [
            "pending",
            "pending_payment",
            "processed",
            "refunded",
            "for_today",
            "with_payment",
            "without_payment",
            "with_additional_visitors",
            "completed",
            "incomplete",
        ],
        ids=[
            "pending_delegate",
            "pending_payment_delegate",
            "processed_delegate",
            "refunded_delegate",
            "for_today_delegate",
            "with_payment_delegate",
            "without_payment_delegate",
            "with_additional_visitors_delegate",
            "completed_delegate",
            "incomplete_delegate",
        ],
    )
    def test_manager_delegate_methods(self, method_name):
        """Test that manager delegate methods exist and return QuerySets."""
        method = getattr(ReEntry.objects, method_name)
        assert callable(method)

        result = method()
        assert isinstance(result, ReEntryQuerySet)

    def test_manager_delegate_methods_with_params(self):
        """Test manager delegate methods that require parameters."""
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        vehicle = VehicleFactory()
        start_date = timezone.now().date()
        end_date = start_date + timedelta(days=1)

        result = ReEntry.objects.by_status(ReEntryStatusChoices.PENDING)
        assert isinstance(result, ReEntryQuerySet)

        result = ReEntry.objects.for_ticket(processed_ticket)
        assert isinstance(result, ReEntryQuerySet)

        result = ReEntry.objects.for_vehicle(vehicle)
        assert isinstance(result, ReEntryQuerySet)

        result = ReEntry.objects.by_date_range(start_date, end_date)
        assert isinstance(result, ReEntryQuerySet)

    def test_sync_offline_re_entry_placeholder(self):
        """Test sync_offline_re_entry method exists."""
        assert hasattr(ReEntry.objects, "sync_offline_re_entry")
        assert callable(ReEntry.objects.sync_offline_re_entry)

        user = UserFactory()
        ReEntry.objects.sync_offline_re_entry(
            re_entry_data={},
            created_by=user,
        )

    def test_manager_inheritance(self):
        """Test that ReEntryManager inherits from both
        SoftDeletableManager and Manager."""
        from model_utils.managers import SoftDeletableManager
        from django.db import models

        assert isinstance(ReEntry.objects, SoftDeletableManager)
        assert isinstance(ReEntry.objects, models.Manager)

    def test_create_re_entry_with_soft_deleted_ticket(self):
        """Test re-entry creation behavior with soft-deleted tickets."""
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        user = UserFactory()

        processed_ticket.delete()

        re_entry = ReEntry.objects.create_re_entry(
            ticket=processed_ticket,
            visitors_left=3,
            created_by=user,
        )

        assert re_entry.ticket == processed_ticket
        assert re_entry.visitors_left == 3

    @patch.object(ReEntry, "save")
    def test_create_re_entry_calls_save(self, mock_save):
        """Test that create_re_entry calls save on the re-entry instance."""
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        user = UserFactory()

        ReEntry.objects.create_re_entry(
            ticket=processed_ticket,
            visitors_left=3,
            created_by=user,
        )

        mock_save.assert_called_once()

    def test_create_re_entry_return_value(self):
        """Test that create_re_entry returns the created instance."""
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        user = UserFactory()

        re_entry = ReEntry.objects.create_re_entry(
            ticket=processed_ticket,
            visitors_left=3,
            created_by=user,
        )

        assert isinstance(re_entry, ReEntry)
        assert re_entry.pk is not None  # Should have been saved and assigned an ID
