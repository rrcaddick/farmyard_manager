from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from farmyard_manager.entrance.models.enums import ItemTypeChoices
from farmyard_manager.entrance.models.enums import ReEntryStatusChoices
from farmyard_manager.entrance.tests.models.factories import ReEntryFactory
from farmyard_manager.entrance.tests.models.factories import (
    ReEntryItemEditHistoryFactory,
)
from farmyard_manager.entrance.tests.models.factories import ReEntryItemFactory
from farmyard_manager.entrance.tests.models.factories import ReEntryStatusHistoryFactory
from farmyard_manager.users.tests.factories import UserFactory

PRICE_PER_VISITOR = Decimal("100.00")


@pytest.fixture(autouse=True)
def use_pricing(with_pricing):
    with_pricing(price=PRICE_PER_VISITOR)


@pytest.mark.django_db(transaction=True)
class TestReEntry:
    """Test suite for the ReEntry model."""

    def test_str_representation(self):
        """Test string representation of re-entry."""
        re_entry = ReEntryFactory()

        expected = (
            f"Re-Entry {re_entry.ticket.vehicle.plate_number} - {re_entry.status}"
        )
        assert str(re_entry) == expected

    def test_status_field_validation(self):
        """Test that invalid status choices raise ValidationError."""
        with pytest.raises(ValidationError, match="Invalid re entry status choice"):
            ReEntryFactory(
                status="invalid_status",
            )

    @pytest.mark.parametrize(
        ("re_entry_kwargs", "expected_processed"),
        [
            ({}, False),
            ({"pending_payment": True}, False),
            ({"processed": True}, True),
            ({"refunded": True}, True),
        ],
        ids=[
            "pending_not_processed",
            "pending_payment_not_processed",
            "processed_is_processed",
            "refunded_is_processed",
        ],
    )
    def test_is_processed_property(self, re_entry_kwargs, expected_processed):
        """Test is_processed property for different statuses."""
        re_entry = ReEntryFactory(**re_entry_kwargs)
        assert re_entry.is_processed == expected_processed

    def test_totals(self):
        """Test total_due calculation with multiple items."""
        visitors_left = 2
        public_returned = 2
        group_returned = 1
        visitors_returned = visitors_left + public_returned + group_returned

        re_entry = ReEntryFactory(
            pending_payment=True,
            visitors_left=visitors_left,
            visitors_returned=visitors_returned,
            with_items=[
                {"visitor_count": public_returned, "item_type": "public"},
                {"visitor_count": group_returned, "item_type": "group"},
            ],
        )

        assert re_entry.additional_visitors == visitors_returned - visitors_left

        assert re_entry.total_visitors == public_returned + group_returned
        assert re_entry.total_due_count == public_returned
        assert re_entry.total_due == public_returned * PRICE_PER_VISITOR

    def test_payment_reqiured_property(
        self,
    ):
        """Test payment_required property calculation."""
        visitors_left = 3
        visitors_returned = 5

        re_entry = ReEntryFactory(
            visitors_left=visitors_left,
            visitors_returned=visitors_returned,
            with_items=False,
        )

        assert not re_entry.all_additional_visitors_added

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
        re_entry = ReEntryFactory(
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


@pytest.mark.django_db(transaction=True)
class TestReEntryItem:
    """Test suite for the ReEntryItem model."""

    def test_str_representation(self):
        """Test string representation of re-entry item."""
        visitor_count = 3

        re_entry_item = ReEntryItemFactory(
            visitor_count=visitor_count,
        )
        expected = (
            f"{visitor_count} {re_entry_item.item_type} visitors at {PRICE_PER_VISITOR}"
        )
        assert str(re_entry_item) == expected

    def test_amount_due_calculation(self):
        """Test amount_due calculation."""
        visitor_count = 4

        item = ReEntryItemFactory(
            visitor_count=visitor_count,
        )

        assert item.amount_due == visitor_count * PRICE_PER_VISITOR

    @pytest.mark.parametrize(
        ("re_entry_kwargs"),
        [
            ({}),
            ({"processed": True}),
            ({"refunded": True}),
        ],
        ids=[
            "pending_blocks_add",
            "processed_blocks_add",
            "refunded_blocks_add",
        ],
    )
    def test_clean_validation_on_add(
        self,
        re_entry_kwargs,
    ):
        """Test validation when adding items to re-entries in different statuses."""
        re_entry = ReEntryFactory(**re_entry_kwargs)

        with pytest.raises(
            ValueError,
            match="Only re entries pending payment can add/edit items",
        ):
            ReEntryItemFactory(re_entry=re_entry)

    def test_clean_validation_on_edit(self):
        """Test validation when editing existing items."""
        re_entry = ReEntryFactory(
            processed=True,
            visitors_left=2,
            visitors_returned=4,
            with_items=True,
        )
        re_entry_item = re_entry.re_entry_items.first()

        # Attempt to edit item
        re_entry_item.visitor_count = 5

        with pytest.raises(
            ValueError,
            match="Only re entries pending payment can add/edit items",
        ):
            re_entry_item.save()

    def test_delete_validation_processed_re_entry(self):
        """Test that items cannot be deleted from processed re-entries."""

        re_entry = ReEntryFactory(
            processed=True,
            visitors_left=2,
            visitors_returned=4,
            with_items=True,
        )

        re_entry_item = re_entry.re_entry_items.first()

        with pytest.raises(
            ValidationError,
            match="Can't delete items on a processed re-entry",
        ):
            re_entry_item.delete()

    def test_delete_success_non_processed_re_entry(self):
        """Test that items can be deleted from non-processed re-entries."""

        re_entry = ReEntryFactory(
            pending_payment=True,
            visitors_left=2,
            visitors_returned=4,
            with_items=True,
        )

        re_entry_item = re_entry.re_entry_items.first()

        re_entry_item.delete()  # Should not raise

        # Verify soft deletion
        assert re_entry_item.is_removed is True

    def test_edit_item_type_updates_price(self):
        """Test editing item type updates applied price."""
        # Set up different return values for different calls

        re_entry_item = ReEntryItemFactory(visitor_count=2)

        re_entry_item.edit(
            performed_by=UserFactory(),
            item_type=ItemTypeChoices.GROUP,
        )

        assert re_entry_item.item_type == ItemTypeChoices.GROUP
        assert re_entry_item.applied_price is None

    def test_edit_creates_history_entry(self):
        """Test that editing creates appropriate history entries."""
        # First call for factory creation, second call for edit
        item = ReEntryItemFactory(
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

    def test_str_representation(self):
        """Test string representation of edit history."""
        field = "item_type"
        user = UserFactory()

        history = ReEntryItemEditHistoryFactory(
            field=field,
            performed_by=user,
        )
        expected = f"{field} edited by {user}"

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
        history = ReEntryItemEditHistoryFactory.build(
            field=field,
            prev_value=prev_value,
            new_value=new_value,
            re_entry_item=ReEntryItemFactory(),
            performed_by=UserFactory(),
        )

        if should_raise:
            with pytest.raises(ValidationError, match=expected_message):
                history.save()
            return

        history.save()  # Should not raise

    def test_deletion_prevented(self):
        """Test that edit history entries cannot be deleted."""
        history = ReEntryItemEditHistoryFactory()

        with pytest.raises(
            ValidationError,
            match="Edit history entries cannot be deleted",
        ):
            history.delete()


@pytest.mark.django_db(transaction=True)
class TestReEntryStatusHistory:
    """Test suite for the ReEntryStatusHistory model."""

    def test_str_representation(self):
        """Test string representation of status history."""
        history = ReEntryStatusHistoryFactory(
            prev_status=ReEntryStatusChoices.PENDING,
            new_status=ReEntryStatusChoices.PENDING_PAYMENT,
        )
        expected = (
            f"{history.performed_by}: {history.prev_status} → {history.new_status}"
        )
        assert str(history) == expected

    def test_new_status_validation(self):
        """Test that invalid new status choices raise ValidationError."""
        with pytest.raises(ValidationError, match="Invalid re-entry status choice"):
            ReEntryStatusHistoryFactory(
                new_status="invalid_status",
            )

    def test_deletion_prevented(self):
        """Test that status history entries cannot be deleted."""
        history = ReEntryStatusHistoryFactory()

        with pytest.raises(
            ValidationError,
            match="Status change entries cannot be deleted",
        ):
            history.delete()
