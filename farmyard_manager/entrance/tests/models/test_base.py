# ruff: noqa: F401
# ruff: noqa: N806
# ruff: noqa: ERA001

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import models
from django.db import transaction

from farmyard_manager.core.fields import SnakeCaseFK
from farmyard_manager.entrance.models.base import BaseEditHistory
from farmyard_manager.entrance.models.base import BaseEntranceRecord
from farmyard_manager.entrance.models.base import BaseItem
from farmyard_manager.entrance.models.base import BaseStatusHistory
from farmyard_manager.entrance.models.enums import ItemTypeChoices
from farmyard_manager.users.tests.factories import UserFactory
from farmyard_manager.utils.string_utils import to_snake_case


@pytest.mark.django_db(transaction=True)
class TestBaseStatusHistory:
    """Test the BaseStatusHistory abstract model behavior."""

    def test_status_history_deletion_prevented(self, fake_model_factory):
        """Test that status history entries cannot be deleted."""
        FakeStatusHistory, _ = fake_model_factory(
            "FakeStatusHistory",
            base_class=BaseStatusHistory,
            create_in_db=True,
        )

        user = UserFactory()
        status_history = FakeStatusHistory.objects.create(performed_by=user)

        with pytest.raises(
            ValidationError,
            match="Status change entries cannot be deleted",
        ):
            status_history.delete()


@pytest.mark.django_db(transaction=True)
class TestBaseEditHistory:
    """Test the BaseEditHistory abstract model behavior."""

    @pytest.mark.parametrize(
        ("field", "prev_value", "new_value", "expected_message"),
        [
            ("invalid_field", "public", "group", "invalid_field is not editable"),
            (
                "item_type",
                "public",
                "invalid_type",
                "invalid_type is a valid item type",
            ),
            (
                "item_type",
                "voided",
                "online",
                "Voided items cannot be edited",
            ),
            ("visitor_count", "5", "invalid", "Visitor count must be a valid integer"),
            ("visitor_count", "5", "-1", "Visitor count must be greater than 0"),
        ],
        ids=[
            "invalid_field_choice",
            "invalid_item_type_choice",
            "voided_item_edit",
            "non_integer_visitor_count",
            "negative_visitor_count",
        ],
    )
    def test_edit_history_field_validation(
        self,
        fake_model_factory,
        field,
        prev_value,
        new_value,
        expected_message,
    ):
        """Test various validation cases in BaseEditHistory."""
        FakeEditHistory, _ = fake_model_factory(
            "FakeEditHistory",
            base_class=BaseEditHistory,
            create_in_db=True,
        )

        user = UserFactory()
        edit_history = FakeEditHistory(
            field=field,
            prev_value=prev_value,
            new_value=new_value,
            performed_by=user,
        )

        with pytest.raises(ValidationError, match=expected_message):
            edit_history.full_clean()

    def test_edit_history_string_representation(self, fake_model_factory):
        """Test the string representation of edit history."""
        FakeEditHistory, _ = fake_model_factory(
            "FakeEditHistory",
            base_class=BaseEditHistory,
        )

        user = UserFactory()
        edit_history = FakeEditHistory(
            field="item_type",
            prev_value="public",
            new_value="group",
            performed_by=user,
        )

        expected_str = f"item_type edited by {user}"
        assert str(edit_history) == expected_str


@pytest.mark.django_db(transaction=True)
class TestBaseItem:
    """Test the BaseItem abstract model behavior."""

    @pytest.fixture
    def get_fake_item(self, fake_model_factory):
        """Create the fake model classes once per test class."""

        # Create FakeItem with dummy edit_history_model first
        FakeItem, fake_item_name = fake_model_factory(
            "FakeItem",
            fields={
                "edit_history_model": BaseEditHistory,
            },
            base_class=BaseItem,
            create_in_db=True,
        )

        # Now create the real FakeEditHistory with FK to FakeItem
        FakeEditHistory, _ = fake_model_factory(
            "FakeEditHistory",
            fields={
                to_snake_case(fake_item_name): models.ForeignKey(
                    FakeItem,
                    on_delete=models.PROTECT,
                    related_name="edit_history",
                ),
            },
            base_class=BaseEditHistory,
            create_in_db=True,
        )

        # Replace the dummy with the real edit_history_model
        FakeItem.edit_history_model = FakeEditHistory

        return FakeItem

    @pytest.fixture
    def fake_item_factory(self, get_fake_item):
        """Factory fixture that creates fake items with customizable parameters."""

        def _create_fake_item(
            item_type,
            visitor_count,
            applied_price,
            *,
            save_to_db=False,
        ):
            FakeItem = get_fake_item

            # Create the fake item instance
            item = FakeItem(
                created_by=UserFactory(),
                item_type=item_type,
                visitor_count=visitor_count,
                applied_price=applied_price,
            )

            if save_to_db:
                item.save()
                return item

            return item

        return _create_fake_item

    def test_base_item_validation(self, fake_item_factory):
        """Test item type validation."""
        item = fake_item_factory(
            item_type="invalid_type",
            visitor_count=5,
            applied_price=Decimal("100.00"),
        )

        with pytest.raises(
            ValidationError,
            match="invalid_type is not a valid item type",
        ):
            item.full_clean()

    def test_base_item_amount_due_calculation(self, fake_item_factory):
        """Test amount due calculation."""
        item = fake_item_factory(
            item_type=ItemTypeChoices.PUBLIC,
            visitor_count=3,
            applied_price=Decimal("50.00"),
        )

        expected_amount = Decimal("150.00")  # 3 * 50.00
        assert item.amount_due == expected_amount

    @patch("farmyard_manager.entrance.models.pricing.Pricing.get_price")
    def test_base_item_get_price(self, mock_get_price, fake_item_factory):
        """Test get_price method."""
        mock_get_price.return_value = Decimal("75.00")

        item = fake_item_factory(
            item_type=ItemTypeChoices.PUBLIC,
            visitor_count=3,
            applied_price=Decimal("100.00"),
        )

        price = item.get_price()
        assert price == Decimal("75.00")
        mock_get_price.assert_called_once_with(ItemTypeChoices.PUBLIC)

    def test_base_item_get_price_without_item_type(self, fake_item_factory):
        """Test get_price method raises error when item_type is None."""
        item = fake_item_factory(
            item_type=ItemTypeChoices.PUBLIC,
            visitor_count=1,
            applied_price=Decimal("100.00"),
        )
        item.item_type = None  # Simulate no item_type being passed

        with pytest.raises(ValueError, match="Set item type befor getting price"):
            item.get_price()

    @pytest.mark.parametrize(
        ("edit_kwargs", "expected_item_changes", "expected_history"),
        [
            (
                {"item_type": ItemTypeChoices.GROUP},
                {
                    "item_type": ItemTypeChoices.GROUP,
                    "applied_price": Decimal("150.00"),
                },
                {
                    "field": "item_type",
                    "prev_value": ItemTypeChoices.PUBLIC,
                    "new_value": ItemTypeChoices.GROUP,
                },
            ),
            (
                {"visitor_count": 5},
                {
                    "visitor_count": 5,
                    "applied_price": Decimal("100.00"),
                },  # Price shouldn't change
                {"field": "visitor_count", "prev_value": "2", "new_value": "5"},
            ),
        ],
        ids=["edit_item_type", "edit_visitor_count"],
    )
    @patch("farmyard_manager.entrance.models.pricing.Pricing.get_price")
    def test_base_item_edit_single_field(
        self,
        mock_get_price,
        fake_item_factory,
        edit_kwargs,
        expected_item_changes,
        expected_history,
    ):
        """Test editing individual fields updates item and creates history."""
        mock_get_price.return_value = Decimal("150.00")

        item = fake_item_factory(
            item_type=ItemTypeChoices.PUBLIC,
            visitor_count=2,
            applied_price=Decimal("100.00"),
            save_to_db=True,
        )

        user = UserFactory()
        item.edit(performed_by=user, **edit_kwargs)

        # Check item was updated correctly
        item.refresh_from_db()
        for field, expected_value in expected_item_changes.items():
            assert getattr(item, field) == expected_value

        # Check edit history was created
        edit_history = item.edit_history.get()

        for field, expected_value in expected_history.items():
            assert getattr(edit_history, field) == expected_value

        assert edit_history.performed_by == user

    def test_base_item_string_representation(self, fake_item_factory):
        """Test string representation."""
        item = fake_item_factory(
            item_type=ItemTypeChoices.PUBLIC,
            visitor_count=3,
            applied_price=Decimal("75.00"),
        )

        expected_str = f"3 {ItemTypeChoices.PUBLIC} visitors at 75.00"
        assert str(item) == expected_str


@pytest.mark.django_db(transaction=True)
class TestBaseEntranceRecord:
    """Test the BaseEntranceRecord abstract model behavior."""

    @pytest.fixture
    def get_fake_entrance_record(self, fake_model_factory):
        """Create the fake model classes once per test class."""
        # Create FakeEntranceRecord
        FakeEntranceRecord, fake_record_name = fake_model_factory(
            "FakeEntranceRecord",
            fields={
                "status": models.CharField(max_length=50),
                "item_model": BaseItem,
                "status_history_model": BaseStatusHistory,
            },
            base_class=BaseEntranceRecord,
            create_in_db=True,
        )

        # Create FakeItem first
        FakeItem, fake_item_name = fake_model_factory(
            "FakeItem",
            fields={
                to_snake_case(fake_record_name): SnakeCaseFK(
                    FakeEntranceRecord,
                    on_delete=models.PROTECT,
                    pluralize_related_name=True,
                ),
                "edit_history_model": BaseEditHistory,
            },
            base_class=BaseItem,
            create_in_db=True,
        )

        # Create FakeEditHistory for the item
        FakeEditHistory, _ = fake_model_factory(
            "FakeEditHistory",
            fields={
                to_snake_case(fake_item_name): models.ForeignKey(
                    FakeItem,
                    on_delete=models.PROTECT,
                    related_name="edit_history",
                ),
            },
            base_class=BaseEditHistory,
            create_in_db=True,
        )

        # Create FakeStatusHistory
        FakeStatusHistory, _ = fake_model_factory(
            "FakeStatusHistory",
            fields={
                to_snake_case(fake_record_name): models.ForeignKey(
                    FakeEntranceRecord,
                    on_delete=models.PROTECT,
                    related_name="status_history",
                ),
                "prev_status": models.CharField(max_length=50, default=""),
                "new_status": models.CharField(max_length=50, default=""),
            },
            base_class=BaseStatusHistory,
            create_in_db=True,
        )

        # Add created models to parent classes
        FakeEntranceRecord.status_history_model = FakeStatusHistory
        FakeEntranceRecord.item_model = FakeItem

        FakeItem.edit_history_model = FakeEditHistory

        return FakeEntranceRecord, FakeItem, FakeStatusHistory

    @pytest.fixture
    def fake_entrance_record_factory(self, get_fake_entrance_record):
        """Factory fixture for creating entrance records."""

        def _create_fake_entrance_record(status="pending", *, save_to_db=False):
            FakeEntranceRecord, FakeItem, FakeStatusHistory = get_fake_entrance_record

            record = FakeEntranceRecord(
                status=status,
            )

            if save_to_db:
                record.save()

            return record

        return _create_fake_entrance_record

    def test_entrance_record_original_status_tracking(
        self,
        fake_entrance_record_factory,
    ):
        """Test that original status is tracked properly."""
        record = fake_entrance_record_factory(status="pending")
        assert record._original_status == "pending"  # noqa: SLF001

        record.status = "active"
        assert record._original_status == "pending"  # Should not change  # noqa: SLF001

    def test_string_representation(self, fake_entrance_record_factory):
        """Test string representation."""
        record = fake_entrance_record_factory(status="pending", save_to_db=True)
        expected_str = f"{record.ref_number} - pending"
        assert str(record) == expected_str

    @pytest.mark.parametrize(
        ("model_name", "expected_snake_case"),
        [
            ("FakeEntranceRecord", "fake_entrance_record"),
            ("TestModelName", "test_model_name"),
        ],
        ids=["standard_name", "camel_case_name"],
    )
    def test_snake_case_model_name(
        self,
        fake_model_factory,
        model_name,
        expected_snake_case,
    ):
        """Test snake case model name property."""
        FakeRecord, _ = fake_model_factory(
            model_name,
            fields={
                "status": models.CharField(max_length=50),
                "item_model": BaseItem,
                "status_history_model": BaseStatusHistory,
            },
            base_class=BaseEntranceRecord,
        )

        record = FakeRecord(status="pending")
        assert expected_snake_case in record.snake_case_model_name

    @pytest.mark.parametrize(
        ("initial_status", "new_status"),
        [
            ("pending", "active"),
            ("active", "completed"),
            ("pending", "cancelled"),
        ],
        ids=["pending_to_active", "active_to_completed", "pending_to_cancelled"],
    )
    def test_update_status(
        self,
        fake_entrance_record_factory,
        initial_status,
        new_status,
    ):
        """Test updating status creates history."""
        record = fake_entrance_record_factory(status=initial_status, save_to_db=True)
        user = UserFactory()

        updated_record = record.update_status(new_status, performed_by=user)

        # Check record was updated
        assert updated_record.status == new_status
        updated_record.refresh_from_db()
        assert updated_record.status == new_status

        # Check status history was created
        status_history = record.status_history.get()
        assert status_history.prev_status == initial_status
        assert status_history.new_status == new_status
        assert status_history.performed_by == user

    @pytest.mark.parametrize(
        ("item_type", "visitor_count", "expected_price"),
        [
            (ItemTypeChoices.PUBLIC, 2, Decimal("100.00")),
            (ItemTypeChoices.GROUP, 5, Decimal("75.00")),
            (ItemTypeChoices.ONLINE, 1, Decimal("50.00")),
        ],
        ids=["public_item", "group_item", "online_item"],
    )
    @patch("farmyard_manager.entrance.models.pricing.Pricing.get_price")
    def test_add_item(
        self,
        mock_get_price,
        fake_entrance_record_factory,
        item_type,
        visitor_count,
        expected_price,
    ):
        """Test adding items to entrance record."""
        mock_get_price.return_value = expected_price

        record = fake_entrance_record_factory(save_to_db=True)
        user = UserFactory()

        item = record.add_item(
            item_type=item_type,
            visitor_count=visitor_count,
            created_by=user,
        )

        assert item.item_type == item_type
        assert item.visitor_count == visitor_count
        assert item.applied_price == expected_price
        assert item.created_by == user
        mock_get_price.assert_called_once_with(item_type)

    def test_add_item_with_custom_price(self, fake_entrance_record_factory):
        """Test adding item with custom applied price."""
        record = fake_entrance_record_factory(save_to_db=True)
        user = UserFactory()
        custom_price = Decimal("200.00")

        item = record.add_item(
            item_type=ItemTypeChoices.PUBLIC,
            visitor_count=3,
            created_by=user,
            applied_price=custom_price,
        )

        assert item.applied_price == custom_price

    @patch("farmyard_manager.entrance.models.pricing.Pricing.get_price")
    def test_remove_item_success(self, mock_get_price, fake_entrance_record_factory):
        """Test successfully removing an item."""
        mock_get_price.return_value = Decimal("100.00")

        record = fake_entrance_record_factory(save_to_db=True)
        user = UserFactory()

        # Add an item first
        item = record.add_item(
            item_type=ItemTypeChoices.PUBLIC,
            visitor_count=2,
            created_by=user,
        )

        # Remove the item
        result = record.remove_item(item.id, performed_by=user)

        assert result is True
        # Item should be soft-deleted
        assert not record.items.exists()

    def test_remove_item_not_found(self, fake_entrance_record_factory):
        """Test removing non-existent item raises error."""
        record = fake_entrance_record_factory(save_to_db=True)
        user = UserFactory()

        with pytest.raises(ValueError, match=r"FakeItem_[a-f0-9]{8} 999 not found"):
            record.remove_item(999, performed_by=user)

    def test_total_due_calculation(self, fake_entrance_record_factory):
        """Test total due calculation with multiple items."""
        record = fake_entrance_record_factory(save_to_db=True)
        user = UserFactory()

        # Add multiple items
        record.add_item(ItemTypeChoices.PUBLIC, 2, user, Decimal("50.00"))
        record.add_item(ItemTypeChoices.GROUP, 3, user, Decimal("75.00"))

        expected_total = (2 * Decimal("50.00")) + (3 * Decimal("75.00"))
        assert record.total_due == expected_total

    @patch("farmyard_manager.entrance.models.pricing.Pricing.get_price")
    def test_total_visitors_calculation(
        self,
        mock_get_price,
        fake_entrance_record_factory,
    ):
        """Test total visitors calculation with multiple items."""
        mock_get_price.return_value = Decimal("100.00")

        record = fake_entrance_record_factory(save_to_db=True)
        user = UserFactory()

        # Add multiple items
        record.add_item(ItemTypeChoices.PUBLIC, 2, user, Decimal("50.00"))
        record.add_item(ItemTypeChoices.GROUP, 5, user, Decimal("75.00"))

        excepted_total_visitors = 7
        assert record.total_visitors == excepted_total_visitors

    @patch("farmyard_manager.entrance.models.pricing.Pricing.get_price")
    def test_voided_items_property(self, mock_get_price, fake_entrance_record_factory):
        """Test voided items property returns soft-deleted items."""
        mock_get_price.return_value = Decimal("100.00")

        record = fake_entrance_record_factory(save_to_db=True)
        user = UserFactory()

        # Add and then remove an item
        item = record.add_item(ItemTypeChoices.PUBLIC, 2, user)
        record.remove_item(item.id, performed_by=user)

        voided_items = record.voided_items
        assert voided_items.count() == 1
        assert voided_items.first().id == item.id

    # TODO: Add payments related tests
