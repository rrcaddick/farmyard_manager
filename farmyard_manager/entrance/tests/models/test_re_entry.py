# farmyard_manager/entrance/tests/models/test_re_entry.py
# ruff: noqa: ERA001, F401, I001, PLR0913

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError

from farmyard_manager.entrance.models.enums import ItemTypeChoices
from farmyard_manager.entrance.models.enums import ReEntryStatusChoices
from farmyard_manager.entrance.tests.models.factories import PricingFactory
from farmyard_manager.entrance.tests.models.factories import ReEntryFactory
from farmyard_manager.entrance.tests.models.factories import (
    ReEntryItemEditHistoryFactory,
)
from farmyard_manager.entrance.tests.models.factories import ReEntryItemFactory
from farmyard_manager.entrance.tests.models.factories import ReEntryStatusHistoryFactory
from farmyard_manager.entrance.tests.models.factories import TicketFactory
from farmyard_manager.entrance.models.enums import TicketStatusChoices
from farmyard_manager.users.tests.factories import UserFactory


@pytest.fixture
def re_entry_with_items():
    """Fixture providing a re-entry with multiple items for testing calculations."""
    # Create processed ticket for re-entry
    processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
    re_entry = ReEntryFactory(
        ticket=processed_ticket,
        status=ReEntryStatusChoices.PENDING_PAYMENT,
        visitors_left=5,
        visitors_returned=7,  # More returned than left
    )

    # Create pricing for different item types
    PricingFactory(ticket_item_type=ItemTypeChoices.PUBLIC, price=Decimal("50.00"))
    PricingFactory(ticket_item_type=ItemTypeChoices.GROUP, price=Decimal("75.00"))

    # Add items to re-entry
    ReEntryItemFactory(
        re_entry=re_entry,
        item_type=ItemTypeChoices.PUBLIC,
        visitor_count=2,
        applied_price=Decimal("50.00"),
    )
    ReEntryItemFactory(
        re_entry=re_entry,
        item_type=ItemTypeChoices.GROUP,
        visitor_count=3,
        applied_price=Decimal("75.00"),
    )

    return re_entry


@pytest.fixture
def pending_re_entry():
    """Fixture providing a pending re-entry for testing."""
    processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
    return ReEntryFactory(
        ticket=processed_ticket,
        status=ReEntryStatusChoices.PENDING,
        visitors_left=3,
    )


@pytest.mark.django_db(transaction=True)
class TestReEntry:
    """Test suite for the ReEntry model."""

    def test_str_representation(self):
        """Test string representation of re-entry."""
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        re_entry = ReEntryFactory(
            ticket=processed_ticket,
            status=ReEntryStatusChoices.PENDING,
        )
        expected = (
            f"Re-Entry {re_entry.ticket.vehicle.plate_number} - {re_entry.status}"
        )
        assert str(re_entry) == expected

    def test_status_field_validation(self):
        """Test that invalid status choices raise ValidationError."""
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        re_entry = ReEntryFactory.build(
            ticket=processed_ticket,
            status="invalid_status",
        )

        with pytest.raises(ValidationError, match="Invalid ticket status choice"):
            re_entry.full_clean()

    @pytest.mark.parametrize(
        ("initial_status", "new_status", "should_raise"),
        [
            # Valid transitions
            (ReEntryStatusChoices.PENDING, ReEntryStatusChoices.PENDING_PAYMENT, False),
            (ReEntryStatusChoices.PENDING, ReEntryStatusChoices.PROCESSED, False),
            (
                ReEntryStatusChoices.PENDING_PAYMENT,
                ReEntryStatusChoices.PROCESSED,
                False,
            ),
            (ReEntryStatusChoices.PROCESSED, ReEntryStatusChoices.REFUNDED, False),
            # Invalid transitions
            (ReEntryStatusChoices.PENDING_PAYMENT, ReEntryStatusChoices.PENDING, True),
            (ReEntryStatusChoices.PROCESSED, ReEntryStatusChoices.PENDING, True),
            (
                ReEntryStatusChoices.PROCESSED,
                ReEntryStatusChoices.PENDING_PAYMENT,
                True,
            ),
            (ReEntryStatusChoices.REFUNDED, ReEntryStatusChoices.PROCESSED, True),
        ],
        ids=[
            "valid_pending_to_pending_payment",
            "valid_pending_to_processed",
            "valid_pending_payment_to_processed",
            "valid_processed_to_refunded",
            "invalid_pending_payment_to_pending",
            "invalid_processed_to_pending",
            "invalid_processed_to_pending_payment",
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
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        re_entry = ReEntryFactory(
            ticket=processed_ticket,
            status=initial_status,
        )
        re_entry.status = new_status

        if should_raise:
            with pytest.raises(ValidationError, match="Invalid transition"):
                re_entry.full_clean()
        else:
            re_entry.full_clean()  # Should not raise

    @pytest.mark.parametrize(
        ("status", "expected_processed"),
        [
            (ReEntryStatusChoices.PENDING, False),
            (ReEntryStatusChoices.PENDING_PAYMENT, False),
            (ReEntryStatusChoices.PROCESSED, True),
            (ReEntryStatusChoices.REFUNDED, True),
        ],
        ids=[
            "pending_not_processed",
            "pending_payment_not_processed",
            "processed_is_processed",
            "refunded_is_processed",
        ],
    )
    def test_is_processed_property(self, status, expected_processed):
        """Test is_processed property for different statuses."""
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        re_entry = ReEntryFactory(
            ticket=processed_ticket,
            status=status,
        )
        assert re_entry.is_processed == expected_processed

    def test_total_due_calculation(self, re_entry_with_items):
        """Test total_due calculation with multiple items."""
        # Expected: (2 * 50.00) + (3 * 75.00) = 100.00 + 225.00 = 325.00
        expected_total = Decimal("325.00")
        assert re_entry_with_items.total_due == expected_total

    def test_total_visitors_calculation(self, re_entry_with_items):
        """Test total_visitors calculation with multiple items."""
        # Expected: 2 + 3 = 5 visitors
        expected_total = 5
        assert re_entry_with_items.total_visitors == expected_total

    @pytest.mark.parametrize(
        ("visitors_left", "visitors_returned", "added_items", "expected_has_unpaid"),
        [
            (5, 3, 0, False),  # No additional visitors (3 < 5), so no unpaid
            (5, 7, 2, False),  # 2 additional visitors, 2 items added → no unpaid
            (5, 7, 1, True),  # 2 additional visitors, 1 item added → 1 unpaid
            (5, 7, 0, True),  # 2 additional visitors, 0 items added → 2 unpaid
            (
                5,
                7,
                3,
                False,
            ),  # 2 additional visitors, 3 items added → no unpaid (over-covered)
            (5, 5, 0, False),  # No additional visitors (5 = 5), so no unpaid
            (
                3,
                3,
                1,
                False,
            ),  # No additional visitors, but items added → still no unpaid
        ],
        ids=[
            "fewer_returned_no_unpaid",
            "additional_visitors_fully_covered",
            "additional_visitors_partially_covered",
            "additional_visitors_not_covered",
            "additional_visitors_over_covered",
            "same_returned_no_unpaid",
            "same_returned_with_items_no_unpaid",
        ],
    )
    @patch("farmyard_manager.entrance.models.pricing.Pricing.get_price")
    def test_has_unpaid_visitors_property(
        self,
        mock_get_price,
        visitors_left,
        visitors_returned,
        added_items,
        expected_has_unpaid,
    ):
        """Test has_unpaid_visitors property calculation."""
        mock_get_price.return_value = Decimal("100.00")

        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        re_entry = ReEntryFactory(
            ticket=processed_ticket,
            status=ReEntryStatusChoices.PENDING_PAYMENT,
            visitors_left=visitors_left,
            visitors_returned=visitors_returned,
        )

        # Add specified number of items (each covering 1 visitor)
        for _ in range(added_items):
            ReEntryItemFactory(
                re_entry=re_entry,
                visitor_count=1,
                applied_price=Decimal("100.00"),
            )

        assert re_entry.has_unpaid_visitors == expected_has_unpaid

    @pytest.mark.parametrize(
        ("visitors_left", "visitors_returned", "expected_status"),
        [
            (5, 3, ReEntryStatusChoices.PROCESSED),  # Less returned
            (5, 5, ReEntryStatusChoices.PROCESSED),  # Same returned
            (5, 7, ReEntryStatusChoices.PENDING_PAYMENT),  # More returned
        ],
        ids=[
            "less_returned_processes",
            "same_returned_processes",
            "more_returned_pending_payment",
        ],
    )
    def test_process_return(self, visitors_left, visitors_returned, expected_status):
        """Test process_return method updates status correctly."""
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        re_entry = ReEntryFactory(
            ticket=processed_ticket,
            status=ReEntryStatusChoices.PENDING,
            visitors_left=visitors_left,
        )
        user = UserFactory()

        re_entry.process_return(
            visitors_returned=visitors_returned,
            performed_by=user,
        )

        assert re_entry.visitors_returned == visitors_returned
        assert re_entry.status == expected_status

        # Verify status history was created
        status_history = re_entry.status_history.get()
        assert status_history.prev_status == ReEntryStatusChoices.PENDING
        assert status_history.new_status == expected_status
        assert status_history.performed_by == user

    def test_ticket_relationship(self):
        """Test re-entry-ticket relationship."""
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        re_entry = ReEntryFactory(ticket=processed_ticket)

        assert re_entry.ticket == processed_ticket
        assert re_entry in processed_ticket.re_entries.all()

    # TODO: Uncomment when PaymentFactory is available
    # def test_payment_assignment(self):
    #     """Test assigning payment to re-entry."""
    #     processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
    #     re_entry = ReEntryFactory(ticket=processed_ticket)
    #     payment = PaymentFactory()

    #     re_entry.assign_payment(payment)

    #     assert re_entry.payment == payment
    #     assert re_entry in payment.re_entries.all()


@pytest.mark.django_db(transaction=True)
class TestReEntryItem:
    """Test suite for the ReEntryItem model."""

    @patch("farmyard_manager.entrance.models.pricing.Pricing.get_price")
    def test_str_representation(self, mock_get_price):
        """Test string representation of re-entry item."""
        mock_get_price.return_value = Decimal("75.00")

        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        re_entry = ReEntryFactory(
            ticket=processed_ticket,
            status=ReEntryStatusChoices.PENDING_PAYMENT,
        )
        item = ReEntryItemFactory(
            re_entry=re_entry,
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

        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        re_entry = ReEntryFactory(
            ticket=processed_ticket,
            status=ReEntryStatusChoices.PENDING_PAYMENT,
        )
        item = ReEntryItemFactory(
            re_entry=re_entry,
            visitor_count=4,
            applied_price=Decimal("60.00"),
        )
        expected_amount = Decimal("240.00")  # 4 * 60.00
        assert item.amount_due == expected_amount

    @pytest.mark.parametrize(
        ("re_entry_status", "should_raise"),
        [
            (ReEntryStatusChoices.PENDING, True),
            (ReEntryStatusChoices.PENDING_PAYMENT, False),
            (ReEntryStatusChoices.PROCESSED, True),
            (ReEntryStatusChoices.REFUNDED, True),
        ],
        ids=[
            "pending_blocks_add",
            "pending_payment_allows_add",
            "processed_blocks_add",
            "refunded_blocks_add",
        ],
    )
    @patch("farmyard_manager.entrance.models.pricing.Pricing.get_price")
    def test_clean_validation_on_add(
        self,
        mock_get_price,
        re_entry_status,
        should_raise,
    ):
        """Test validation when adding items to re-entries in different statuses."""
        mock_get_price.return_value = Decimal("100.00")

        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        re_entry = ReEntryFactory(
            ticket=processed_ticket,
            status=re_entry_status,
        )
        item = ReEntryItemFactory.build(
            re_entry=re_entry,
            created_by=UserFactory(),
        )

        if should_raise:
            with pytest.raises(
                ValueError,
                match="Only re entries pending payment can add/edit items",
            ):
                item.full_clean()
        else:
            item.full_clean()  # Should not raise

    @patch("farmyard_manager.entrance.models.pricing.Pricing.get_price")
    def test_clean_validation_on_edit(self, mock_get_price):
        """Test validation when editing existing items."""
        mock_get_price.return_value = Decimal("100.00")

        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        # Create re-entry with allowed status first
        re_entry = ReEntryFactory(
            ticket=processed_ticket,
            status=ReEntryStatusChoices.PENDING_PAYMENT,
        )
        item = ReEntryItemFactory(re_entry=re_entry)

        # Now change re-entry to processed status
        re_entry.status = ReEntryStatusChoices.PROCESSED
        re_entry.save()

        # Change something to trigger edit validation
        item.visitor_count = 5

        with pytest.raises(
            ValueError,
            match="Only re entries pending payment can add/edit items",
        ):
            item.full_clean()

    @patch("farmyard_manager.entrance.models.pricing.Pricing.get_price")
    def test_delete_validation_processed_re_entry(self, mock_get_price):
        """Test that items cannot be deleted from processed re-entries."""
        mock_get_price.return_value = Decimal("100.00")

        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        # Create re-entry with allowed status first
        re_entry = ReEntryFactory(
            ticket=processed_ticket,
            status=ReEntryStatusChoices.PENDING_PAYMENT,
        )
        item = ReEntryItemFactory(re_entry=re_entry)

        # Now change re-entry to processed status
        re_entry.status = ReEntryStatusChoices.PROCESSED
        re_entry.save()

        with pytest.raises(
            ValidationError,
            match="Can't delete items on a processed re-entry",
        ):
            item.delete()

    @patch("farmyard_manager.entrance.models.pricing.Pricing.get_price")
    def test_delete_success_non_processed_re_entry(self, mock_get_price):
        """Test that items can be deleted from non-processed re-entries."""
        mock_get_price.return_value = Decimal("100.00")

        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        re_entry = ReEntryFactory(
            ticket=processed_ticket,
            status=ReEntryStatusChoices.PENDING_PAYMENT,
        )
        item = ReEntryItemFactory(re_entry=re_entry)

        item.delete()  # Should not raise

        # Verify soft deletion
        assert item.is_removed is True

    @patch("farmyard_manager.entrance.models.pricing.Pricing.get_price")
    def test_edit_item_type_updates_price(self, mock_get_price):
        """Test editing item type updates applied price."""
        # Set up different return values for different calls
        mock_get_price.return_value = Decimal("50.00")  # For factory creation

        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        re_entry = ReEntryFactory(
            ticket=processed_ticket,
            status=ReEntryStatusChoices.PENDING_PAYMENT,
        )
        item = ReEntryItemFactory(
            re_entry=re_entry,
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

        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        re_entry = ReEntryFactory(
            ticket=processed_ticket,
            status=ReEntryStatusChoices.PENDING_PAYMENT,
        )
        original_price = Decimal("75.00")
        item = ReEntryItemFactory(
            re_entry=re_entry,
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

        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        re_entry = ReEntryFactory(
            ticket=processed_ticket,
            status=ReEntryStatusChoices.PENDING_PAYMENT,
        )
        item = ReEntryItemFactory(
            re_entry=re_entry,
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
class TestReEntryItemEditHistory:
    """Test suite for the ReEntryItemEditHistory model."""

    @patch("farmyard_manager.entrance.models.pricing.Pricing.get_price")
    def test_str_representation(self, mock_get_price):
        """Test string representation of edit history."""
        mock_get_price.return_value = Decimal("100.00")

        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        re_entry = ReEntryFactory(
            ticket=processed_ticket,
            status=ReEntryStatusChoices.PENDING_PAYMENT,
        )
        re_entry_item = ReEntryItemFactory(re_entry=re_entry)

        user = UserFactory()
        history = ReEntryItemEditHistoryFactory(
            re_entry_item=re_entry_item,
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

        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        re_entry = ReEntryFactory(
            ticket=processed_ticket,
            status=ReEntryStatusChoices.PENDING_PAYMENT,
        )
        re_entry_item = ReEntryItemFactory(re_entry=re_entry)

        user = UserFactory()
        history = ReEntryItemEditHistoryFactory.build(
            re_entry_item=re_entry_item,
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

        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        re_entry = ReEntryFactory(
            ticket=processed_ticket,
            status=ReEntryStatusChoices.PENDING_PAYMENT,
        )
        re_entry_item = ReEntryItemFactory(re_entry=re_entry)
        history = ReEntryItemEditHistoryFactory(re_entry_item=re_entry_item)

        with pytest.raises(
            ValidationError,
            match="Edit history entries cannot be deleted",
        ):
            history.delete()

    @patch("farmyard_manager.entrance.models.pricing.Pricing.get_price")
    def test_re_entry_item_relationship(self, mock_get_price):
        """Test relationship with re-entry item."""
        mock_get_price.return_value = Decimal("100.00")

        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        re_entry = ReEntryFactory(
            ticket=processed_ticket,
            status=ReEntryStatusChoices.PENDING_PAYMENT,
        )
        re_entry_item = ReEntryItemFactory(re_entry=re_entry)
        history = ReEntryItemEditHistoryFactory(re_entry_item=re_entry_item)

        assert history.re_entry_item == re_entry_item
        assert history in re_entry_item.edit_history.all()


@pytest.mark.django_db(transaction=True)
class TestReEntryStatusHistory:
    """Test suite for the ReEntryStatusHistory model."""

    def test_str_representation(self):
        """Test string representation of status history."""
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        re_entry = ReEntryFactory(ticket=processed_ticket)
        user = UserFactory()
        history = ReEntryStatusHistoryFactory(
            re_entry=re_entry,
            prev_status=ReEntryStatusChoices.PENDING,
            new_status=ReEntryStatusChoices.PENDING_PAYMENT,
            performed_by=user,
        )
        expected = (
            f"{user}: {ReEntryStatusChoices.PENDING} → "
            f"f{ReEntryStatusChoices.PENDING_PAYMENT}: {re_entry.ticket.id}"
        )
        assert str(history) == expected

    def test_new_status_validation(self):
        """Test that invalid new status choices raise ValidationError."""
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        re_entry = ReEntryFactory(ticket=processed_ticket)
        user = UserFactory()
        history = ReEntryStatusHistoryFactory.build(
            re_entry=re_entry,
            performed_by=user,
            new_status="invalid_status",
        )

        with pytest.raises(ValidationError, match="Invalid re-entry status choice"):
            history.full_clean()

    @pytest.mark.parametrize(
        ("prev_status", "new_status", "should_raise"),
        [
            # Valid transitions
            (ReEntryStatusChoices.PENDING, ReEntryStatusChoices.PENDING_PAYMENT, False),
            (ReEntryStatusChoices.PENDING, ReEntryStatusChoices.PROCESSED, False),
            (
                ReEntryStatusChoices.PENDING_PAYMENT,
                ReEntryStatusChoices.PROCESSED,
                False,
            ),
            (ReEntryStatusChoices.PROCESSED, ReEntryStatusChoices.REFUNDED, False),
            # Invalid transitions
            (ReEntryStatusChoices.PENDING_PAYMENT, ReEntryStatusChoices.PENDING, True),
            (ReEntryStatusChoices.PROCESSED, ReEntryStatusChoices.PENDING, True),
            (ReEntryStatusChoices.REFUNDED, ReEntryStatusChoices.PROCESSED, True),
        ],
        ids=[
            "valid_pending_to_pending_payment",
            "valid_pending_to_processed",
            "valid_pending_payment_to_processed",
            "valid_processed_to_refunded",
            "invalid_pending_payment_to_pending",
            "invalid_processed_to_pending",
            "invalid_refunded_to_processed",
        ],
    )
    def test_transition_validation(self, prev_status, new_status, should_raise):
        """Test status transition validation."""
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        re_entry = ReEntryFactory(ticket=processed_ticket)
        user = UserFactory()
        history = ReEntryStatusHistoryFactory.build(
            re_entry=re_entry,
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
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        re_entry = ReEntryFactory(ticket=processed_ticket)
        history = ReEntryStatusHistoryFactory(re_entry=re_entry)

        with pytest.raises(
            ValidationError,
            match="Status change entries cannot be deleted",
        ):
            history.delete()

    def test_re_entry_relationship(self):
        """Test relationship with re-entry."""
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        re_entry = ReEntryFactory(ticket=processed_ticket)
        history = ReEntryStatusHistoryFactory(re_entry=re_entry)

        assert history.re_entry == re_entry
        assert history in re_entry.status_history.all()

    def test_performed_by_relationship(self):
        """Test relationship with user who performed the action."""
        user = UserFactory()
        processed_ticket = TicketFactory(status=TicketStatusChoices.PROCESSED)
        re_entry = ReEntryFactory(ticket=processed_ticket)
        history = ReEntryStatusHistoryFactory(
            re_entry=re_entry,
            performed_by=user,
        )

        assert history.performed_by == user
