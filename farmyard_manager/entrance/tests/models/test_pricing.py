from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from farmyard_manager.entrance.models import Pricing
from farmyard_manager.entrance.models.enums import ItemTypeChoices
from farmyard_manager.entrance.tests.models.factories import PricingFactory


@pytest.mark.django_db(transaction=True)
class TestPricingModel:
    def test_str_representation(self):
        instance = PricingFactory(ticket_item_type=ItemTypeChoices.PUBLIC)
        assert str(instance) == f"{instance.ticket_item_type} - {instance.price}"

    def test_valid_price_range(self):
        instance = PricingFactory.build(
            price_start=timezone.now(),
            price_end=timezone.now() + timedelta(days=1),
        )
        instance.full_clean()  # should not raise

    def test_invalid_date_range(self):
        instance = PricingFactory.build(
            price_start=timezone.now(),
            price_end=timezone.now() - timedelta(days=1),
        )
        with pytest.raises(ValidationError, match="End date must be after start date"):
            instance.full_clean()

    def test_date_range_overlap_is_invalid(self):
        ticket_item_type = ItemTypeChoices.GROUP
        now = timezone.now()

        PricingFactory(
            ticket_item_type=ticket_item_type,
            price_start=now,
            price_end=now + timedelta(days=10),
            is_active=False,
        )

        overlapping_price = PricingFactory.build(
            ticket_item_type=ticket_item_type,
            price_start=now + timedelta(days=5),
            price_end=now + timedelta(days=15),
        )

        with pytest.raises(
            ValidationError,
            match="Date range overlaps with existing pricing for",
        ):
            overlapping_price.full_clean()

    def test_unique_active_constraint(self):
        ticket_item_type = ItemTypeChoices.SCHOOL

        PricingFactory(ticket_item_type=ticket_item_type, is_active=True)

        duplicate_price = PricingFactory.build(
            ticket_item_type=ticket_item_type,
            is_active=True,
        )

        with pytest.raises(ValidationError, match="already exists"):
            duplicate_price.full_clean()

    def test_multiple_inactive_allowed(self):
        ticket_item_type = ItemTypeChoices.ONLINE
        now = timezone.now()

        PricingFactory(
            ticket_item_type=ticket_item_type,
            price_start=now,
            price_end=now + timedelta(days=10),
            is_active=False,
        )
        PricingFactory(
            ticket_item_type=ticket_item_type,
            price_start=now + timedelta(days=10),
            price_end=now + timedelta(days=20),
            is_active=False,
        )

        expected_inactive_count = 2

        assert (
            Pricing.objects.filter(
                ticket_item_type=ticket_item_type,
                is_active=False,
            ).count()
            == expected_inactive_count
        )

    @pytest.mark.parametrize(
        ("ticket_item_type", "price", "use_datetime", "is_active"),
        [
            (ItemTypeChoices.PUBLIC, Decimal("111.11"), False, True),
            (ItemTypeChoices.GROUP, Decimal("222.22"), True, True),
            (ItemTypeChoices.ONLINE, Decimal("333.33"), False, False),
            (ItemTypeChoices.SCHOOL, Decimal("444.44"), True, False),
        ],
        ids=[
            "active-public-no-datetime",
            "active-group-with-datetime",
            "inactive-online-no-datetime",
            "inactive-school-with-datetime",
        ],
    )
    def test_get_price_resolves(self, ticket_item_type, price, use_datetime, is_active):
        now = timezone.now()

        PricingFactory(
            ticket_item_type=ticket_item_type,
            price=price,
            price_start=now - timedelta(days=1),
            price_end=now + timedelta(days=10),
            is_active=is_active,
        )

        get_price_kwargs = {"ticket_item_type": ticket_item_type}

        if use_datetime:
            get_price_kwargs["date_time"] = now

        if not is_active:
            get_price_kwargs["is_active"] = is_active

        assert Pricing.get_price(**get_price_kwargs) == price

    def test_get_price_raises_value_error(self):
        now = timezone.now()
        ticket_item_type = ItemTypeChoices.GROUP

        PricingFactory(
            ticket_item_type=ticket_item_type,
            price_start=now - timedelta(days=10),
            price_end=now - timedelta(days=5),
        )
        with pytest.raises(ValueError, match="No pricing found for"):
            Pricing.get_price(ticket_item_type, date_time=now)

    def test_price_field_validation(self):
        # Test negative prices
        with pytest.raises(ValidationError):
            PricingFactory.build(price=Decimal("-10.00")).full_clean()

        # Test max digits (should be 10)
        with pytest.raises(ValidationError):
            PricingFactory.build(price=Decimal("123456789.90")).full_clean()
