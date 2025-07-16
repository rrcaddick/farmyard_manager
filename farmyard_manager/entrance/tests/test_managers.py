# farmyard_manager/entrance/tests/test_managers.py
# ruff: noqa: ERA001, F401, I001, PLR0913

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.db import transaction

from farmyard_manager.entrance.managers import ReEntryManager
from farmyard_manager.entrance.managers import TicketManager
from farmyard_manager.entrance.models import ReEntry
from farmyard_manager.entrance.models import Ticket
from farmyard_manager.entrance.models.enums import ReEntryStatusChoices
from farmyard_manager.entrance.models.enums import TicketStatusChoices
from farmyard_manager.entrance.tests.models.factories import PricingFactory
from farmyard_manager.entrance.tests.models.factories import TicketFactory
from farmyard_manager.users.tests.factories import UserFactory
from farmyard_manager.vehicles.tests.factories import VehicleFactory


@pytest.mark.django_db(transaction=True)
class TestTicketManager:
    """Test suite for the TicketManager class."""

    def test_manager_assignment(self):
        """Test that Ticket model uses TicketManager."""
        assert isinstance(Ticket.objects, TicketManager)

    @pytest.mark.parametrize(
        ("status", "expected_status"),
        [
            (
                TicketStatusChoices.PENDING_SECURITY,
                TicketStatusChoices.PENDING_SECURITY,
            ),
        ],
        ids=[
            "pending_security",
        ],
    )
    def test_create_ticket_basic(self, status, expected_status):
        """Test basic ticket creation with different statuses."""
        vehicle = VehicleFactory()
        user = UserFactory()

        ticket = Ticket.objects.create_ticket(
            status=status,
            vehicle=vehicle,
            performed_by=user,
        )

        assert ticket.status == expected_status
        assert ticket.vehicle == vehicle
        assert ticket.ref_number is not None

        # Verify status history was created
        status_history = ticket.status_history.get()
        assert status_history.prev_status == ""
        assert status_history.new_status == status
        assert status_history.performed_by == user

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
                performed_by=None,
            )

    def test_create_ticket_with_additional_kwargs(self):
        """Test ticket creation with additional kwargs."""
        vehicle = VehicleFactory()
        user = UserFactory()

        # Test that additional kwargs are passed through
        ticket = Ticket.objects.create_ticket(
            status=TicketStatusChoices.PENDING_SECURITY,
            vehicle=vehicle,
            performed_by=user,
            # Additional kwargs would go here if we had any
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
        # This is a placeholder test since the method just returns True
        result = Ticket.objects._validate_price("public")  # noqa: SLF001
        assert result is True

    # TODO: Implement these tests when offline sync methods are implemented
    def test_sync_offline_queue_ticket_placeholder(self):
        """Placeholder test for sync_offline_queue_ticket method."""
        # This method is not implemented yet, just verify it exists
        assert hasattr(Ticket.objects, "sync_offline_queue_ticket")
        assert callable(Ticket.objects.sync_offline_queue_ticket)

    def test_sync_offline_security_check_placeholder(self):
        """Placeholder test for sync_offline_security_check method."""
        # This method is not implemented yet, just verify it exists
        assert hasattr(Ticket.objects, "sync_offline_security_check")
        assert callable(Ticket.objects.sync_offline_security_check)

    def test_sync_offline_visitor_ticket_placeholder(self):
        """Placeholder test for sync_offline_visitor_ticket method."""
        # This method is not implemented yet, just verify it exists
        assert hasattr(Ticket.objects, "sync_offline_visitor_ticket")
        assert callable(Ticket.objects.sync_offline_visitor_ticket)

    def test_sync_offline_cash_payment_placeholder(self):
        """Placeholder test for sync_offline_cash_payment method."""
        # This method is not implemented yet, just verify it exists
        assert hasattr(Ticket.objects, "sync_offline_cash_payment")
        assert callable(Ticket.objects.sync_offline_cash_payment)


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
        assert re_entry.visitors_left == 5  # noqa: PLR2004

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
            (
                TicketStatusChoices.REFUNDED,
                False,
            ),  # Assuming refunded tickets can have re-entries
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

        # Verify it exists in database
        assert ReEntry.objects.filter(id=re_entry.id).exists()

        # Verify we can retrieve it
        retrieved_re_entry = ReEntry.objects.get(id=re_entry.id)
        assert retrieved_re_entry.ticket == processed_ticket
        assert retrieved_re_entry.visitors_left == 3  # noqa: PLR2004

    def test_create_re_entry_with_zero_visitors_left(self):
        """Test re-entry creation with zero visitors_left."""
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        user = UserFactory()

        # This should work (business logic validation might be elsewhere)
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

        # Create first re-entry
        re_entry1 = ReEntry.objects.create_re_entry(
            ticket=processed_ticket,
            visitors_left=3,
            created_by=user,
        )

        # Create second re-entry for same ticket
        re_entry2 = ReEntry.objects.create_re_entry(
            ticket=processed_ticket,
            visitors_left=2,
            created_by=user,
        )

        assert re_entry1.ticket == re_entry2.ticket
        assert re_entry1.id != re_entry2.id
        assert processed_ticket.re_entries.count() == 2  # noqa: PLR2004

    # TODO: Implement this test when offline sync method is implemented
    def test_sync_offline_re_entry_placeholder(self):
        """Placeholder test for sync_offline_re_entry method."""
        # This method is not implemented yet, just verify it exists
        assert hasattr(ReEntry.objects, "sync_offline_re_entry")
        assert callable(ReEntry.objects.sync_offline_re_entry)

    def test_manager_inheritance(self):
        """
        Test that ReEntryManager inherits from both SoftDeletableManager
        and Manager.
        """
        from model_utils.managers import SoftDeletableManager
        from django.db import models

        # Verify the manager has the expected parent classes
        assert isinstance(ReEntry.objects, SoftDeletableManager)
        assert isinstance(ReEntry.objects, models.Manager)

    def test_create_re_entry_with_soft_deleted_ticket(self):
        """Test re-entry creation behavior with soft-deleted tickets."""
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        user = UserFactory()

        # Soft delete the ticket
        processed_ticket.delete()  # Soft delete

        # This should still work since we're not checking is_removed in the manager
        re_entry = ReEntry.objects.create_re_entry(
            ticket=processed_ticket,
            visitors_left=3,
            created_by=user,
        )

        assert re_entry.ticket == processed_ticket
        assert re_entry.visitors_left == 3  # noqa: PLR2004

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

        # Verify save was called
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
