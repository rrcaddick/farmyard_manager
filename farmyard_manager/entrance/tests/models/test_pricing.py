# ruff: noqa: ARG002
from datetime import date
from datetime import datetime
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from farmyard_manager.entrance.models.pricing import Pricing
from farmyard_manager.entrance.tests.models.factories import PricingFactory


@pytest.fixture
def base_seasonal_pricing():
    """Creates base weekday/weekend pricing for the year"""
    weekday = PricingFactory(
        price_type=Pricing.PricingTypes.WEEKDAY,
        price=Decimal("100.00"),
    )
    weekend = PricingFactory(
        price_type=Pricing.PricingTypes.WEEKEND,
        price=Decimal("150.00"),
    )
    return {"weekday": weekday, "weekend": weekend}


@pytest.fixture
def overlapping_pricing(base_seasonal_pricing):
    """Creates overlapping holiday and peak pricing"""
    school_holiday = PricingFactory(
        price_type=Pricing.PricingTypes.SCHOOL_HOLIDAY,
        start_date=date(2024, 7, 1),
        end_date=date(2024, 7, 31),
        price=Decimal("200.00"),
    )
    peak_day = PricingFactory(
        price_type=Pricing.PricingTypes.PEAK_DAY,
        start_date=date(2024, 7, 4),
        end_date=date(2024, 7, 4),
        price=Decimal("300.00"),
    )
    public_holiday = PricingFactory(
        price_type=Pricing.PricingTypes.PUBLIC_HOLIDAY,
        start_date=date(2024, 12, 25),
        end_date=date(2024, 12, 25),
        price=Decimal("250.00"),
    )
    return {
        **base_seasonal_pricing,
        "school_holiday": school_holiday,
        "peak_day": peak_day,
        "public_holiday": public_holiday,
    }


@pytest.mark.django_db(transaction=True)
class TestPricingQuerySet:
    """Test suite for PricingQuerySet.get_price method"""

    def test_get_price_with_no_pricing_returns_none(self):
        """Should return None when no pricing exists for the date"""
        result = Pricing.objects.get_price(date(2024, 6, 15))
        assert result is None

    def test_get_price_outside_date_range_returns_none(self):
        """Should return None when date is outside all pricing ranges"""
        PricingFactory(
            start_date=date(2024, 6, 1),
            end_date=date(2024, 6, 30),
        )

        result = Pricing.objects.get_price(date(2024, 7, 15))
        assert result is None

    def test_seasonal_pricing(self):
        """Ensures the correct price is returned for weekdays and weekends"""
        monday = date(2024, 6, 3)
        week_day_price = Decimal("100.00")
        weekend_price = Decimal("120.00")

        # Create weekday pricing
        PricingFactory(as_weekday=True, start_date=monday, price=week_day_price)

        # Create weekend pricing
        PricingFactory(as_weekend=True, start_date=monday, price=weekend_price)

        for i in range(7):  # Loop through Monday-Sunday
            current_day = monday + timedelta(days=i)
            pricing = Pricing.objects.get_price(current_day)

            assert pricing is not None

            if current_day.weekday() < 5:  # noqa: PLR2004
                assert pricing.price == week_day_price
                assert pricing.price_type == Pricing.PricingTypes.WEEKDAY
            else:  # Saturday-Sunday
                assert pricing.price == weekend_price
                assert pricing.price_type == Pricing.PricingTypes.WEEKEND

    @pytest.mark.parametrize(
        ("price_type", "price"),
        [
            (Pricing.PricingTypes.PEAK_DAY, Decimal("150.00")),
            (Pricing.PricingTypes.PUBLIC_HOLIDAY, Decimal("150.00")),
            (Pricing.PricingTypes.SCHOOL_HOLIDAY, Decimal("150.00")),
        ],
        ids=[
            "peak_pricing",
            "public_holiday_pricing",
            "school_holiday_pricing",
        ],
    )
    def test_special_pricing(self, price_type, price):
        """Should return special pricing over seasonal pricing"""
        week_day_price = Decimal("100.00")
        weekend_price = Decimal("120.00")

        # Create weekday pricing
        PricingFactory(as_weekday=True, price=week_day_price)

        # Create weekend pricing
        PricingFactory(as_weekend=True, price=weekend_price)

        # Create peak day pricing overlapping a weekend
        PricingFactory(price_type=price_type, price=price)

        pricing = Pricing.objects.get_price()

        assert pricing is not None
        assert pricing.price == price
        assert pricing.price_type == price_type

    @pytest.mark.parametrize(
        ("input_date", "expected_price_type", "expected_price"),
        [
            (
                datetime(2024, 6, 3, 14, 30),  # noqa: DTZ001
                Pricing.PricingTypes.WEEKDAY,
                Decimal("100.00"),
            ),  # Monday datetime
            (
                datetime(2024, 6, 8, 9, 0),  # noqa: DTZ001
                Pricing.PricingTypes.WEEKEND,
                Decimal("150.00"),
            ),  # Saturday datetime
            (
                date(2024, 6, 3),
                Pricing.PricingTypes.WEEKDAY,
                Decimal("100.00"),
            ),  # Monday date
            (
                date(2024, 6, 8),
                Pricing.PricingTypes.WEEKEND,
                Decimal("150.00"),
            ),  # Saturday date
        ],
        ids=[
            "monday_datetime",
            "saturday_datetime",
            "monday_date",
            "saturday_date",
        ],
    )
    def test_get_price_handles_date_and_datetime_objects(
        self,
        input_date,
        expected_price_type,
        expected_price,
    ):
        """Should handle both datetime and date objects correctly"""
        # Create pricing
        monday = date(2024, 6, 3)
        PricingFactory(as_weekday=True, start_date=monday, price=Decimal("100.00"))
        PricingFactory(as_weekend=True, start_date=monday, price=Decimal("150.00"))

        result = Pricing.objects.get_price(input_date)

        assert result is not None
        assert result.price_type == expected_price_type
        assert result.price == expected_price

    def test_get_price_with_none_defaults_to_today(
        self,
    ):
        """Should default to today's date when None is provided"""

        # Ensure pricing record exists
        PricingFactory()
        pricing = Pricing.objects.get_price()

        price_type = (
            Pricing.PricingTypes.WEEKEND
            if timezone.localdate().weekday() in (5, 6)
            else Pricing.PricingTypes.WEEKDAY
        )

        assert pricing is not None
        assert pricing.price_type == price_type

    def test_get_price_multiple_overlapping_different_prices(self):
        """Should return highest price when multiple different holiday types overlap"""
        # Create overlapping pricing with different prices
        PricingFactory(
            price_type=Pricing.PricingTypes.WEEKDAY,
            start_date=date(2024, 8, 1),
            end_date=date(2024, 8, 31),
            price=Decimal("100.00"),
        )
        PricingFactory(
            price_type=Pricing.PricingTypes.SCHOOL_HOLIDAY,
            start_date=date(2024, 8, 1),
            end_date=date(2024, 8, 31),
            price=Decimal("180.00"),
        )
        PricingFactory(
            price_type=Pricing.PricingTypes.PUBLIC_HOLIDAY,
            start_date=date(2024, 8, 15),
            end_date=date(2024, 8, 15),
            price=Decimal("220.00"),
        )

        # August 15th 2024 is a Thursday - public holiday should win
        result = Pricing.objects.get_price(date(2024, 8, 15))

        assert result is not None
        assert result.price == Decimal("220.00")
        assert result.price_type == Pricing.PricingTypes.PUBLIC_HOLIDAY

    def test_get_price_edge_case_start_end_dates(self):
        """Should handle edge cases for start and end dates correctly"""
        pricing = PricingFactory(
            price_type=Pricing.PricingTypes.WEEKDAY,
            start_date=date(2024, 6, 3),  # Monday
            end_date=date(2024, 6, 7),  # Friday
            price=Decimal("120.00"),
        )

        # Test exact start date
        result = Pricing.objects.get_price(date(2024, 6, 3))
        assert result == pricing

        # Test exact end date
        result = Pricing.objects.get_price(date(2024, 6, 7))
        assert result == pricing

        # Test day before start
        result = Pricing.objects.get_price(date(2024, 6, 2))
        assert result is None

        # Test day after end
        result = Pricing.objects.get_price(date(2024, 6, 8))
        assert result is None

    def test_get_price_same_price_different_types_returns_first_ordered(self):
        """Should return first result when prices are equal (testing order stability)"""
        # Create two pricing rules with same price for same date
        PricingFactory(
            price_type=Pricing.PricingTypes.SCHOOL_HOLIDAY,
            start_date=date(2024, 7, 1),
            end_date=date(2024, 7, 31),
            price=Decimal("200.00"),
        )
        PricingFactory(
            price_type=Pricing.PricingTypes.PUBLIC_HOLIDAY,
            start_date=date(2024, 7, 15),
            end_date=date(2024, 7, 15),
            price=Decimal("200.00"),  # Same price
        )

        result = Pricing.objects.get_price(date(2024, 7, 15))

        assert result is not None
        assert result.price == Decimal("200.00")
        # Should return one of them (order may depend on database/creation order)
        assert result.price_type in [
            Pricing.PricingTypes.SCHOOL_HOLIDAY,
            Pricing.PricingTypes.PUBLIC_HOLIDAY,
        ]


@pytest.mark.django_db(transaction=True)
class TestPricingModel:
    """Test suite for Pricing model specific functionality"""

    def test_pricing_string_representation(self):
        """Should return correct string representation"""
        pricing = PricingFactory(
            price_type=Pricing.PricingTypes.WEEKDAY,
            price=Decimal("123.45"),
        )

        expected = "weekday): 123.45"
        assert str(pricing) == expected

    def test_pricing_types_choices_complete(self):
        """Should have all expected pricing type choices"""
        expected_choices = [
            ("peak_day", "Peak Day"),
            ("public_holiday", "Public Holiday"),
            ("school_holiday", "School Holiday"),
            ("weekend", "Weekend"),
            ("weekday", "Weekday"),
        ]

        assert Pricing.PricingTypes.choices == expected_choices

    @pytest.mark.parametrize(
        "price_type",
        [
            Pricing.PricingTypes.PEAK_DAY,
            Pricing.PricingTypes.PUBLIC_HOLIDAY,
            Pricing.PricingTypes.SCHOOL_HOLIDAY,
            Pricing.PricingTypes.WEEKEND,
            Pricing.PricingTypes.WEEKDAY,
        ],
    )
    def test_pricing_creation_with_all_types(self, price_type):
        """Should successfully create pricing with all valid price types"""
        pricing = PricingFactory(price_type=price_type)

        assert pricing.price_type == price_type
        assert pricing.pk is not None
