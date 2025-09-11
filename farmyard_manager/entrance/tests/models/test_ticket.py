# ruff: noqa: ERA001, PLR0913

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError

from farmyard_manager.entrance.models.enums import ItemTypeChoices
from farmyard_manager.entrance.models.enums import TicketStatusChoices
from farmyard_manager.entrance.tests.models.factories import PricingFactory
from farmyard_manager.entrance.tests.models.factories import TicketFactory
from farmyard_manager.entrance.tests.models.factories import (
    TicketItemEditHistoryFactory,
)
from farmyard_manager.entrance.tests.models.factories import TicketItemFactory
from farmyard_manager.entrance.tests.models.factories import TicketStatusHistoryFactory
from farmyard_manager.users.tests.factories import UserFactory
from farmyard_manager.vehicles.tests.factories import VehicleFactory


@pytest.fixture
def ticket_with_items():
    """Fixture providing a ticket with multiple items for testing calculations."""
    ticket = TicketFactory(status=TicketStatusChoices.COUNTED)

    # Create pricing for different item types
    PricingFactory(ticket_item_type=ItemTypeChoices.PUBLIC, price=Decimal("50.00"))
    PricingFactory(ticket_item_type=ItemTypeChoices.GROUP, price=Decimal("75.00"))

    # Add items to ticket
    TicketItemFactory(
        ticket=ticket,
        item_type=ItemTypeChoices.PUBLIC,
        visitor_count=2,
        applied_price=Decimal("50.00"),
    )
    TicketItemFactory(
        ticket=ticket,
        item_type=ItemTypeChoices.GROUP,
        visitor_count=3,
        applied_price=Decimal("75.00"),
    )

    return ticket


@pytest.fixture
def processed_ticket():
    """Fixture providing a processed ticket for re-entry testing."""
    return TicketFactory(status=TicketStatusChoices.PROCESSED)


@pytest.mark.django_db(transaction=True)
class TestTicket:
    """Test suite for the Ticket model."""

    def test_str_representation(self):
        """Test string representation of ticket."""
        ticket = TicketFactory(status=TicketStatusChoices.PENDING_SECURITY)
        expected = f"{ticket.ref_number} - {ticket.status}"
        assert str(ticket) == expected

    def test_status_field_validation(self):
        """Test that invalid status choices raise ValidationError."""
        ticket = TicketFactory.build(status="invalid_status")

        with pytest.raises(ValidationError, match="Invalid ticket status choice"):
            ticket.full_clean()

    @pytest.mark.parametrize(
        ("initial_status", "new_status", "should_raise"),
        [
            # Valid transitions
            (
                TicketStatusChoices.PENDING_SECURITY,
                TicketStatusChoices.PASSED_SECURITY,
                False,
            ),
            (TicketStatusChoices.PASSED_SECURITY, TicketStatusChoices.COUNTED, False),
            (TicketStatusChoices.COUNTED, TicketStatusChoices.PROCESSED, False),
            (TicketStatusChoices.PROCESSED, TicketStatusChoices.REFUNDED, False),
            # Invalid transitions
            (TicketStatusChoices.PENDING_SECURITY, TicketStatusChoices.COUNTED, True),
            (TicketStatusChoices.PENDING_SECURITY, TicketStatusChoices.PROCESSED, True),
            (TicketStatusChoices.PASSED_SECURITY, TicketStatusChoices.PROCESSED, True),
            (TicketStatusChoices.PROCESSED, TicketStatusChoices.PENDING_SECURITY, True),
            (TicketStatusChoices.REFUNDED, TicketStatusChoices.PROCESSED, True),
        ],
        ids=[
            "valid_security_to_passed",
            "valid_passed_to_counted",
            "valid_counted_to_processed",
            "valid_processed_to_refunded",
            "invalid_security_to_counted",
            "invalid_security_to_processed",
            "invalid_passed_to_processed",
            "invalid_processed_to_security",
            "invalid_refunded_to_processed",
        ],
    )
    def test_status_transition_validation(
        self,
        initial_status,
        new_status,
        should_raise,
    ):
        """Test status transition validation."""
        ticket = TicketFactory(status=initial_status)
        ticket.status = new_status

        if should_raise:
            with pytest.raises(ValidationError, match="Invalid transition"):
                ticket.full_clean()
        else:
            ticket.full_clean()  # Should not raise

    @pytest.mark.parametrize(
        ("status", "expected_processed"),
        [
            (TicketStatusChoices.PENDING_SECURITY, False),
            (TicketStatusChoices.PASSED_SECURITY, False),
            (TicketStatusChoices.COUNTED, False),
            (TicketStatusChoices.PROCESSED, True),
            (TicketStatusChoices.REFUNDED, True),
        ],
        ids=[
            "pending_security_not_processed",
            "passed_security_not_processed",
            "counted_not_processed",
            "processed_is_processed",
            "refunded_is_processed",
        ],
    )
    def test_is_processed_property(self, status, expected_processed):
        """Test is_processed property for different statuses."""
        ticket = TicketFactory(status=status)
        assert ticket.is_processed == expected_processed

    def test_total_due_calculation(self, ticket_with_items):
        """Test total_due calculation with multiple items."""
        # Expected: (2 * 50.00) + (3 * 75.00) = 100.00 + 225.00 = 325.00
        expected_total = Decimal("325.00")
        assert ticket_with_items.total_due == expected_total

    def test_total_visitors_calculation(self, ticket_with_items):
        """Test total_visitors calculation with multiple items."""
        # Expected: 2 + 3 = 5 visitors
        expected_total = 5
        assert ticket_with_items.total_visitors == expected_total

    def test_add_re_entry_success(self, processed_ticket):
        """Test successfully adding a re-entry to a processed ticket."""
        user = UserFactory()
        visitors_left = 3

        re_entry = processed_ticket.add_re_entry(
            visitors_left=visitors_left,
            created_by=user,
        )

        assert re_entry.ticket == processed_ticket
        assert re_entry.visitors_left == visitors_left
        assert re_entry.status == "pending"  # ReEntry.StatusChoices.PENDING

    @pytest.mark.parametrize(
        ("status", "should_raise"),
        [
            (TicketStatusChoices.PENDING_SECURITY, True),
            (TicketStatusChoices.PASSED_SECURITY, True),
            (TicketStatusChoices.COUNTED, True),
            (TicketStatusChoices.PROCESSED, False),
            (TicketStatusChoices.REFUNDED, True),
        ],
        ids=[
            "pending_security_fails",
            "passed_security_fails",
            "counted_fails",
            "processed_succeeds",
            "refunded_fails",
        ],
    )
    def test_add_re_entry_status_validation(self, status, should_raise):
        """Test re-entry creation only works for processed tickets."""
        ticket = TicketFactory(status=status)
        user = UserFactory()

        if should_raise:
            with pytest.raises(
                ValueError,
                match="Only processed tickets can have re-entries",
            ):
                ticket.add_re_entry(visitors_left=3, created_by=user)
        else:
            re_entry = ticket.add_re_entry(visitors_left=3, created_by=user)
            assert re_entry is not None

    def test_add_re_entry_invalid_visitors_left(self, processed_ticket):
        """Test re-entry creation fails with invalid visitors_left."""
        user = UserFactory()

        with pytest.raises(ValueError, match="Visitors left must be greater than 0"):
            processed_ticket.add_re_entry(visitors_left=0, created_by=user)

    def test_pending_re_entries_property(self, processed_ticket):
        """Test pending_re_entries property returns only pending re-entries."""
        from farmyard_manager.entrance.tests.models.factories import ReEntryFactory

        # user = UserFactory()

        # Create pending re-entry
        pending_re_entry = ReEntryFactory(
            ticket=processed_ticket,
            status="pending",
        )

        # Create processed re-entry
        ReEntryFactory(
            ticket=processed_ticket,
            status="processed",
        )

        pending_re_entries = processed_ticket.pending_re_entries
        assert pending_re_entries.count() == 1
        assert pending_re_entries.first() == pending_re_entry

    def test_vehicle_relationship(self):
        """Test ticket-vehicle relationship."""
        vehicle = VehicleFactory()
        ticket = TicketFactory(vehicle=vehicle)

        assert ticket.vehicle == vehicle
        assert ticket in vehicle.tickets.all()

    # TODO: Add payments related tests


@pytest.mark.django_db(transaction=True)
class TestTicketItem:
    """Test suite for the TicketItem model."""

    @patch("farmyard_manager.entrance.models.pricing.Pricing.get_price")
    def test_str_representation(self, mock_get_price):
        """Test string representation of ticket item."""
        mock_get_price.return_value = Decimal("75.00")

        # Create ticket with allowed status for adding items
        ticket = TicketFactory(status=TicketStatusChoices.COUNTED)
        item = TicketItemFactory(
            ticket=ticket,
            item_type=ItemTypeChoices.PUBLIC,
            visitor_count=3,
            applied_price=Decimal("75.00"),
        )
        expected = f"3 {ItemTypeChoices.PUBLIC} visitors at 75.00"
        assert str(item) == expected

    @patch("farmyard_manager.entrance.models.pricing.Pricing.get_price")
    def test_amount_due_calculation(self, mock_get_price):
        """Test amount_due calculation."""
        mock_get_price.return_value = Decimal("60.00")

        # Create ticket with allowed status for adding items
        ticket = TicketFactory(status=TicketStatusChoices.COUNTED)
        item = TicketItemFactory(
            ticket=ticket,
            visitor_count=4,
            applied_price=Decimal("60.00"),
        )
        expected_amount = Decimal("240.00")  # 4 * 60.00
        assert item.amount_due == expected_amount

    @pytest.mark.parametrize(
        ("ticket_status", "should_raise"),
        [
            (TicketStatusChoices.PENDING_SECURITY, True),
            (TicketStatusChoices.PASSED_SECURITY, False),
            (TicketStatusChoices.COUNTED, False),
            (TicketStatusChoices.PROCESSED, True),
            (TicketStatusChoices.REFUNDED, True),
        ],
        ids=[
            "pending_security_blocks_add",
            "passed_security_allows_add",
            "counted_allows_add",
            "processed_blocks_add",
            "refunded_blocks_add",
        ],
    )
    @patch("farmyard_manager.entrance.models.pricing.Pricing.get_price")
    def test_clean_validation_on_add(self, mock_get_price, ticket_status, should_raise):
        """Test validation when adding items to tickets in different statuses."""
        mock_get_price.return_value = Decimal("100.00")

        ticket = TicketFactory(status=ticket_status)
        item = TicketItemFactory.build(ticket=ticket, created_by=UserFactory())

        if should_raise:
            expected_message = (
                "Can't add items, ticket is processed"
                if ticket.is_processed
                else "Ticket needs to pass security check first"
            )
            with pytest.raises(ValidationError, match=expected_message):
                item.full_clean()
        else:
            item.full_clean()  # Should not raise

    @patch("farmyard_manager.entrance.models.pricing.Pricing.get_price")
    def test_clean_validation_on_edit(self, mock_get_price):
        """Test validation when editing existing items."""
        mock_get_price.return_value = Decimal("100.00")

        # Create ticket with allowed status first
        ticket = TicketFactory(status=TicketStatusChoices.COUNTED)
        item = TicketItemFactory(ticket=ticket)

        # Now change ticket to processed status
        ticket.status = TicketStatusChoices.PROCESSED
        ticket.save()

        # Change something to trigger edit validation
        item.visitor_count = 5

        with pytest.raises(
            ValidationError,
            match="Can't edit items, ticket is processed",
        ):
            item.full_clean()

    @patch("farmyard_manager.entrance.models.pricing.Pricing.get_price")
    def test_delete_validation_processed_ticket(self, mock_get_price):
        """Test that items cannot be deleted from processed tickets."""
        mock_get_price.return_value = Decimal("100.00")

        # Create ticket with allowed status first
        ticket = TicketFactory(status=TicketStatusChoices.COUNTED)
        item = TicketItemFactory(ticket=ticket)

        # Now change ticket to processed status
        ticket.status = TicketStatusChoices.PROCESSED
        ticket.save()

        with pytest.raises(
            ValidationError,
            match="Can't delete items on a processed ticket",
        ):
            item.delete()

    @patch("farmyard_manager.entrance.models.pricing.Pricing.get_price")
    def test_delete_success_non_processed_ticket(self, mock_get_price):
        """Test that items can be deleted from non-processed tickets."""
        mock_get_price.return_value = Decimal("100.00")

        ticket = TicketFactory(status=TicketStatusChoices.COUNTED)
        item = TicketItemFactory(ticket=ticket)

        item.delete()  # Should not raise

        # Verify soft deletion
        assert item.is_removed is True

    @patch("farmyard_manager.entrance.models.pricing.Pricing.get_price")
    def test_edit_item_type_updates_price(self, mock_get_price):
        """Test editing item type updates applied price."""
        # Set up different return values for different calls
        mock_get_price.return_value = Decimal("50.00")  # For factory creation

        ticket = TicketFactory(status=TicketStatusChoices.COUNTED)
        item = TicketItemFactory(
            ticket=ticket,
            item_type=ItemTypeChoices.PUBLIC,
            applied_price=Decimal("50.00"),
        )

        # Change mock return value for the edit call
        mock_get_price.return_value = Decimal("150.00")

        user = UserFactory()

        item.edit(
            performed_by=user,
            item_type=ItemTypeChoices.GROUP,
        )

        assert item.item_type == ItemTypeChoices.GROUP
        assert item.applied_price == Decimal("150.00")
        # Verify the last call was for GROUP type
        assert mock_get_price.call_args_list[-1][0][0] == ItemTypeChoices.GROUP

    @patch("farmyard_manager.entrance.models.pricing.Pricing.get_price")
    def test_edit_visitor_count_preserves_price(self, mock_get_price):
        """Test editing visitor count preserves applied price."""
        mock_get_price.return_value = Decimal("75.00")

        ticket = TicketFactory(status=TicketStatusChoices.COUNTED)
        original_price = Decimal("75.00")
        item = TicketItemFactory(
            ticket=ticket,
            visitor_count=2,
            applied_price=original_price,
        )
        user = UserFactory()

        item.edit(
            performed_by=user,
            visitor_count=5,
        )

        assert item.visitor_count == 5  # noqa: PLR2004
        assert item.applied_price == original_price

    @patch("farmyard_manager.entrance.models.pricing.Pricing.get_price")
    def test_edit_creates_history_entry(self, mock_get_price):
        """Test that editing creates appropriate history entries."""
        # First call for factory creation, second call for edit
        mock_get_price.side_effect = [Decimal("100.00"), Decimal("150.00")]

        ticket = TicketFactory(status=TicketStatusChoices.COUNTED)
        item = TicketItemFactory(
            ticket=ticket,
            item_type=ItemTypeChoices.PUBLIC,
            visitor_count=2,
        )
        user = UserFactory()

        item.edit(
            performed_by=user,
            item_type=ItemTypeChoices.GROUP,
            visitor_count=4,
        )

        history_entries = item.edit_history.all()
        assert history_entries.count() == 2  # noqa: PLR2004

        # Check item type history
        item_type_history = history_entries.filter(field="item_type").first()
        assert item_type_history.prev_value == ItemTypeChoices.PUBLIC
        assert item_type_history.new_value == ItemTypeChoices.GROUP
        assert item_type_history.performed_by == user

        # Check visitor count history
        visitor_count_history = history_entries.filter(field="visitor_count").first()
        assert visitor_count_history.prev_value == "2"
        assert visitor_count_history.new_value == "4"
        assert visitor_count_history.performed_by == user


@pytest.mark.django_db(transaction=True)
class TestTicketItemEditHistory:
    """Test suite for the TicketItemEditHistory model."""

    @patch("farmyard_manager.entrance.models.pricing.Pricing.get_price")
    def test_str_representation(self, mock_get_price):
        """Test string representation of edit history."""
        mock_get_price.return_value = Decimal("100.00")

        # Create ticket with valid status for item creation
        ticket = TicketFactory(status=TicketStatusChoices.COUNTED)
        ticket_item = TicketItemFactory(ticket=ticket)

        user = UserFactory()
        history = TicketItemEditHistoryFactory(
            ticket_item=ticket_item,
            field="item_type",
            performed_by=user,
        )
        expected = f"item_type edited by {user}"
        assert str(history) == expected

    @pytest.mark.parametrize(
        ("field", "prev_value", "new_value", "should_raise", "expected_message"),
        [
            # Valid field edits
            ("item_type", ItemTypeChoices.PUBLIC, ItemTypeChoices.GROUP, False, ""),
            ("visitor_count", "2", "5", False, ""),
            # Invalid field
            ("invalid_field", "old", "new", True, "invalid_field is not editable"),
            # Invalid item type
            (
                "item_type",
                ItemTypeChoices.PUBLIC,
                "invalid_type",
                True,
                "invalid_type is a valid item type",
            ),
            # Voided item edit
            (
                "item_type",
                ItemTypeChoices.VOIDED,
                ItemTypeChoices.PUBLIC,
                True,
                "Voided items cannot be edited",
            ),
            # Invalid visitor count
            (
                "visitor_count",
                "2",
                "invalid",
                True,
                "Visitor count must be a valid integer",
            ),
            ("visitor_count", "2", "-1", True, "Visitor count must be greater than 0"),
        ],
        ids=[
            "valid_item_type_edit",
            "valid_visitor_count_edit",
            "invalid_field_choice",
            "invalid_item_type_choice",
            "voided_item_edit",
            "non_integer_visitor_count",
            "negative_visitor_count",
        ],
    )
    @patch("farmyard_manager.entrance.models.pricing.Pricing.get_price")
    def test_field_validation(
        self,
        mock_get_price,
        field,
        prev_value,
        new_value,
        should_raise,
        expected_message,
    ):
        """Test field validation in edit history."""
        mock_get_price.return_value = Decimal("100.00")

        # Create ticket with valid status for item creation
        ticket = TicketFactory(status=TicketStatusChoices.COUNTED)
        ticket_item = TicketItemFactory(ticket=ticket)

        user = UserFactory()
        history = TicketItemEditHistoryFactory.build(
            ticket_item=ticket_item,
            field=field,
            prev_value=prev_value,
            new_value=new_value,
            performed_by=user,
        )

        if should_raise:
            with pytest.raises(ValidationError, match=expected_message):
                history.full_clean()
        else:
            history.full_clean()  # Should not raise

    @patch("farmyard_manager.entrance.models.pricing.Pricing.get_price")
    def test_deletion_prevented(self, mock_get_price):
        """Test that edit history entries cannot be deleted."""
        mock_get_price.return_value = Decimal("100.00")

        # Create ticket with valid status for item creation
        ticket = TicketFactory(status=TicketStatusChoices.COUNTED)
        ticket_item = TicketItemFactory(ticket=ticket)
        history = TicketItemEditHistoryFactory(ticket_item=ticket_item)

        with pytest.raises(
            ValidationError,
            match="Edit history entries cannot be deleted",
        ):
            history.delete()

    @patch("farmyard_manager.entrance.models.pricing.Pricing.get_price")
    def test_ticket_item_relationship(self, mock_get_price):
        """Test relationship with ticket item."""
        mock_get_price.return_value = Decimal("100.00")

        # Create ticket with valid status for item creation
        ticket = TicketFactory(status=TicketStatusChoices.COUNTED)
        ticket_item = TicketItemFactory(ticket=ticket)
        history = TicketItemEditHistoryFactory(ticket_item=ticket_item)

        assert history.ticket_item == ticket_item
        assert history in ticket_item.edit_history.all()


@pytest.mark.django_db(transaction=True)
class TestTicketStatusHistory:
    """Test suite for the TicketStatusHistory model."""

    def test_str_representation(self):
        """Test string representation of status history."""
        ticket = TicketFactory()
        history = TicketStatusHistoryFactory(
            ticket=ticket,
            prev_status=TicketStatusChoices.PENDING_SECURITY,
            new_status=TicketStatusChoices.PASSED_SECURITY,
        )
        expected = (
            f"Status {TicketStatusChoices.PENDING_SECURITY} → "
            f"{TicketStatusChoices.PASSED_SECURITY} for Ticket {ticket.id}"
        )
        assert str(history) == expected

    def test_new_status_validation(self):
        """Test that invalid new status choices raise ValidationError."""
        ticket = TicketFactory()
        user = UserFactory()
        history = TicketStatusHistoryFactory.build(
            ticket=ticket,
            performed_by=user,
            new_status="invalid_status",
        )

        with pytest.raises(ValidationError, match="Invalid ticket status choice"):
            history.full_clean()

    @pytest.mark.parametrize(
        ("prev_status", "new_status", "should_raise"),
        [
            # Valid transitions
            (
                TicketStatusChoices.PENDING_SECURITY,
                TicketStatusChoices.PASSED_SECURITY,
                False,
            ),
            (TicketStatusChoices.PASSED_SECURITY, TicketStatusChoices.COUNTED, False),
            (TicketStatusChoices.COUNTED, TicketStatusChoices.PROCESSED, False),
            (TicketStatusChoices.PROCESSED, TicketStatusChoices.REFUNDED, False),
            # Invalid transitions
            (TicketStatusChoices.PENDING_SECURITY, TicketStatusChoices.COUNTED, True),
            (TicketStatusChoices.PROCESSED, TicketStatusChoices.PENDING_SECURITY, True),
            (TicketStatusChoices.REFUNDED, TicketStatusChoices.PROCESSED, True),
        ],
        ids=[
            "valid_security_to_passed",
            "valid_passed_to_counted",
            "valid_counted_to_processed",
            "valid_processed_to_refunded",
            "invalid_security_to_counted",
            "invalid_processed_to_security",
            "invalid_refunded_to_processed",
        ],
    )
    def test_transition_validation(self, prev_status, new_status, should_raise):
        """Test status transition validation."""
        ticket = TicketFactory()
        user = UserFactory()
        history = TicketStatusHistoryFactory.build(
            ticket=ticket,
            performed_by=user,
            prev_status=prev_status,
            new_status=new_status,
        )

        if should_raise:
            with pytest.raises(ValidationError, match="Invalid transition"):
                history.full_clean()
        else:
            history.full_clean()  # Should not raise

    def test_deletion_prevented(self):
        """Test that status history entries cannot be deleted."""
        history = TicketStatusHistoryFactory()

        with pytest.raises(
            ValidationError,
            match="Status change entries cannot be deleted",
        ):
            history.delete()

    def test_ticket_relationship(self):
        """Test relationship with ticket."""
        ticket = TicketFactory()
        history = TicketStatusHistoryFactory(ticket=ticket)

        assert history.ticket == ticket
        assert history in ticket.status_history.all()

    def test_performed_by_relationship(self):
        """Test relationship with user who performed the action."""
        user = UserFactory()
        history = TicketStatusHistoryFactory(performed_by=user)

        assert history.performed_by == user
