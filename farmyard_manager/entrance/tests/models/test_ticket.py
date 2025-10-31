from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from farmyard_manager.entrance.models.enums import ItemTypeChoices
from farmyard_manager.entrance.models.enums import ReEntryStatusChoices
from farmyard_manager.entrance.models.enums import TicketStatusChoices
from farmyard_manager.entrance.tests.models.factories import ReEntryFactory
from farmyard_manager.entrance.tests.models.factories import TicketFactory
from farmyard_manager.entrance.tests.models.factories import (
    TicketItemEditHistoryFactory,
)
from farmyard_manager.entrance.tests.models.factories import TicketItemFactory
from farmyard_manager.entrance.tests.models.factories import TicketStatusHistoryFactory
from farmyard_manager.users.tests.factories import UserFactory

PRICE_PER_VISITOR = Decimal("100.00")


@pytest.fixture(autouse=True)
def use_pricing(with_pricing):
    with_pricing(price=PRICE_PER_VISITOR)


@pytest.mark.django_db(transaction=True)
class TestTicket:
    """Test suite for the Ticket model."""

    def test_str_representation(self):
        """Test string representation of ticket."""
        ticket = TicketFactory()
        expected = f"{ticket.ref_number} - {ticket.status}"
        assert str(ticket) == expected

    def test_status_field_validation(self):
        """Test that invalid status choices raise ValidationError."""
        with pytest.raises(ValidationError, match="Invalid ticket status choice"):
            TicketFactory(status="invalid_status")

    @pytest.mark.parametrize(
        ("initial_status", "new_status"),
        [
            (TicketStatusChoices.PENDING_SECURITY, TicketStatusChoices.PASSED_SECURITY),
            (TicketStatusChoices.PASSED_SECURITY, TicketStatusChoices.COUNTED),
            (TicketStatusChoices.COUNTED, TicketStatusChoices.PROCESSED),
            (TicketStatusChoices.PROCESSED, TicketStatusChoices.REFUNDED),
        ],
        ids=[
            "valid_security_to_passed",
            "valid_passed_to_counted",
            "valid_counted_to_processed",
            "valid_processed_to_refunded",
        ],
    )
    def test_update_status_valid_transition(
        self,
        initial_status,
        new_status,
    ):
        """Test status transition validation."""
        ticket = TicketFactory(status=initial_status)
        ticket.update_status(new_status=new_status, performed_by=UserFactory())

        assert ticket.status == new_status

    @pytest.mark.parametrize(
        ("initial_status", "new_status"),
        [
            (TicketStatusChoices.PENDING_SECURITY, TicketStatusChoices.COUNTED),
            (TicketStatusChoices.PENDING_SECURITY, TicketStatusChoices.PROCESSED),
            (TicketStatusChoices.PASSED_SECURITY, TicketStatusChoices.PROCESSED),
            (TicketStatusChoices.PROCESSED, TicketStatusChoices.PENDING_SECURITY),
            (TicketStatusChoices.REFUNDED, TicketStatusChoices.PROCESSED),
        ],
        ids=[
            "invalid_security_to_counted",
            "invalid_security_to_processed",
            "invalid_passed_to_processed",
            "invalid_processed_to_security",
            "invalid_refunded_to_processed",
        ],
    )
    def test_udpate_status_invalid_transition(
        self,
        initial_status,
        new_status,
    ):
        """Test status transition validation."""
        ticket = TicketFactory(status=initial_status)

        with pytest.raises(ValidationError, match="Invalid transition"):
            ticket.update_status(new_status=new_status, performed_by=UserFactory())

    @pytest.mark.parametrize(
        ("ticket_kwargs", "expected_processed"),
        [
            ({}, False),
            ({"passed_security": True}, False),
            ({"counted": True}, False),
            ({"processed": True}, True),
            ({"refunded": True}, True),
        ],
        ids=[
            "pending_security_not_processed",
            "passed_security_not_processed",
            "counted_not_processed",
            "processed_is_processed",
            "refunded_is_processed",
        ],
    )
    def test_is_processed_property(self, ticket_kwargs, expected_processed):
        """Test is_processed property for different statuses."""
        ticket = TicketFactory.build(**ticket_kwargs)
        assert ticket.is_processed == expected_processed

    def test_totals(self):
        """Test total_due calculation with multiple items."""
        public_count = 3
        group_count = 2

        ticket = TicketFactory(
            counted=True,
            with_items=[
                {"visitor_count": public_count, "item_type": "public"},
                {"visitor_count": group_count, "item_type": "group"},
            ],
        )

        assert ticket.total_due == public_count * PRICE_PER_VISITOR
        assert ticket.total_due_count == public_count
        assert ticket.total_visitors == public_count + group_count

    def test_add_re_entry_success(self):
        """Test successfully adding a re-entry to a processed ticket."""
        visitors_left = 3

        ticket = TicketFactory(processed=True, with_items=True)
        ticket.add_re_entry(visitors_left=visitors_left, created_by=UserFactory())

        re_entry = ticket.re_entries.first()

        assert re_entry.ticket == ticket
        assert re_entry.visitors_left == visitors_left
        assert re_entry.status == ReEntryStatusChoices.PENDING

    @pytest.mark.parametrize(
        ("ticket_kwargs"),
        [
            ({}),
            ({"passed_security": True}),
            ({"counted": True}),
            ({"refunded": True}),
        ],
        ids=[
            "pending_security_fails",
            "passed_security_fails",
            "counted_fails",
            "refunded_fails",
        ],
    )
    def test_add_re_entry_invalid_status(self, ticket_kwargs):
        """Test re-entry creation only works for processed tickets."""
        ticket = TicketFactory(**ticket_kwargs)

        with pytest.raises(
            ValueError,
            match="Only processed tickets can have re-entries",
        ):
            ticket.add_re_entry(visitors_left=3, created_by=UserFactory())

    def test_add_re_entry_invalid_visitors_left(self):
        """Test re-entry creation fails with invalid visitors_left."""
        ticket = TicketFactory(processed=True, with_items=True)

        with pytest.raises(ValueError, match="Visitors left must be greater than 0"):
            ticket.add_re_entry(visitors_left=0, created_by=UserFactory())

    def test_pending_re_entries_property(self):
        """Test pending_re_entries property returns only pending re-entries."""
        ticket = TicketFactory(processed=True, with_items=True)

        pending_re_entry_count = 2

        for _ in range(pending_re_entry_count):
            ticket.add_re_entry(visitors_left=2, created_by=UserFactory())

        # Manually add a completed re-entry
        ReEntryFactory(ticket=ticket, processed=True)

        assert ticket.pending_re_entries.count() == pending_re_entry_count


@pytest.mark.django_db(transaction=True)
class TestTicketItem:
    """Test suite for the TicketItem model."""

    def test_str_representation(self):
        """Test string representation of ticket item."""
        ticket_item = TicketItemFactory(visitor_count=3)
        expected = f"3 {ItemTypeChoices.PUBLIC} visitors at {PRICE_PER_VISITOR}"
        assert str(ticket_item) == expected

    def test_amount_due_calculation(self):
        """Test amount_due calculation."""
        visitor_count = 4
        ticket_item = TicketItemFactory(visitor_count=visitor_count)
        assert ticket_item.amount_due == visitor_count * PRICE_PER_VISITOR

    @pytest.mark.parametrize(
        ("ticket_kwargs", "error_message"),
        [
            (
                {"with_items": False},
                "Ticket needs to pass security check first",
            ),
            (
                {"processed": True},
                "Can't add items, ticket is processed",
            ),
        ],
        ids=[
            "pending_security_blocks_add",
            "processed_ticket_blocks_add",
        ],
    )
    def test_clean_validation_on_add(self, ticket_kwargs, error_message):
        """Test validation when adding items to tickets in different statuses."""
        ticket = TicketFactory(**ticket_kwargs)

        with pytest.raises(ValidationError, match=error_message):
            TicketItemFactory(ticket=ticket)

    def test_clean_validation_on_edit(self):
        """Test validation when editing existing items."""

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

    def test_delete_validation_processed_ticket(self):
        """Test that items cannot be deleted from processed tickets."""
        ticket = TicketFactory(processed=True, with_items=True)
        ticket_item = ticket.ticket_items.first()

        with pytest.raises(
            ValidationError,
            match="Can't delete items on a processed ticket",
        ):
            ticket_item.delete()

    def test_edit_item_type_updates_price(self):
        """Test editing item type updates applied price."""
        ticket_item = TicketItemFactory()

        ticket_item.edit(
            performed_by=UserFactory(),
            item_type=ItemTypeChoices.GROUP,
        )

        assert ticket_item.item_type == ItemTypeChoices.GROUP
        assert ticket_item.applied_price is None

    def test_edit_creates_history_entry(self):
        """Test that editing creates appropriate history entries."""
        ticket_item = TicketItemFactory()

        performed_by = UserFactory()

        ticket_item.edit(
            performed_by=performed_by,
            item_type=ItemTypeChoices.GROUP,
            visitor_count=4,
        )

        history_entries = ticket_item.edit_history.all()
        assert history_entries.count() == 2  # noqa: PLR2004

        # Check item type history
        item_type_history = history_entries.filter(field="item_type").first()
        assert item_type_history.prev_value == ItemTypeChoices.PUBLIC
        assert item_type_history.new_value == ItemTypeChoices.GROUP
        assert item_type_history.performed_by == performed_by

        # Check visitor count history
        visitor_count_history = history_entries.filter(field="visitor_count").first()
        assert visitor_count_history.prev_value == "2"
        assert visitor_count_history.new_value == "4"
        assert visitor_count_history.performed_by == performed_by


@pytest.mark.django_db(transaction=True)
class TestTicketItemEditHistory:
    """Test suite for the TicketItemEditHistory model."""

    def test_str_representation(self):
        """Test string representation of edit history."""
        # Create ticket with valid status for item creation
        ticket = TicketFactory(counted=True)
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
            "non_integer_visitor_count",
            "negative_visitor_count",
        ],
    )
    def test_field_validation(
        self,
        field,
        prev_value,
        new_value,
        should_raise,
        expected_message,
    ):
        """Test field validation in edit history."""
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

    def test_deletion_prevented(self):
        """Test that edit history entries cannot be deleted."""
        # Create ticket with valid status for item creation
        ticket = TicketFactory(status=TicketStatusChoices.COUNTED)
        ticket_item = TicketItemFactory(ticket=ticket)
        history = TicketItemEditHistoryFactory(ticket_item=ticket_item)

        with pytest.raises(
            ValidationError,
            match="Edit history entries cannot be deleted",
        ):
            history.delete()


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
