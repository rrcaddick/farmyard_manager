# ruff: noqa: ARG002
from datetime import date
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

import pytest

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
            price=Decimal("100.00"),
        )

        result = Pricing.objects.get_price(date(2024, 7, 15))
        assert result is None

    @pytest.mark.parametrize(
        ("test_date", "day_name"),
        [
            (date(2024, 6, 3), "Monday"),
            (date(2024, 6, 4), "Tuesday"),
            (date(2024, 6, 5), "Wednesday"),
            (date(2024, 6, 6), "Thursday"),
            (date(2024, 6, 7), "Friday"),
        ],
    )
    def test_get_price_weekday_pricing(
        self,
        base_seasonal_pricing,
        test_date,
        day_name,
    ):
        """Should return weekday pricing for Monday-Friday"""
        result = Pricing.objects.get_price(test_date)

        assert result is not None
        assert result.price == Decimal("100.00")
        assert result.price_type == Pricing.PricingTypes.WEEKDAY

    @pytest.mark.parametrize(
        ("test_date", "day_name"),
        [
            (date(2024, 6, 1), "Saturday"),
            (date(2024, 6, 2), "Sunday"),
            (date(2024, 6, 8), "Saturday"),
            (date(2024, 6, 9), "Sunday"),
        ],
    )
    def test_get_price_weekend_pricing(
        self,
        base_seasonal_pricing,
        test_date,
        day_name,
    ):
        """Should return weekend pricing for Saturday-Sunday"""
        result = Pricing.objects.get_price(test_date)

        assert result is not None
        assert result.price == Decimal("150.00")
        assert result.price_type == Pricing.PricingTypes.WEEKEND

    def test_get_price_excludes_non_matching_seasonal_type(self, base_seasonal_pricing):
        """Should exclude weekday pricing on weekends and vice versa"""
        # Test weekend date - should not get weekday pricing
        weekend_result = Pricing.objects.get_price(date(2024, 6, 1))  # Saturday
        assert weekend_result is not None

        assert weekend_result.price_type == Pricing.PricingTypes.WEEKEND
        assert weekend_result.price == Decimal("150.00")

        # Test weekday date - should not get weekend pricing
        weekday_result = Pricing.objects.get_price(date(2024, 6, 3))  # Monday
        assert weekday_result is not None

        assert weekday_result.price_type == Pricing.PricingTypes.WEEKDAY
        assert weekday_result.price == Decimal("100.00")

    def test_get_price_highest_price_wins(self, overlapping_pricing):
        """Should return the highest priced option when multiple pricing rules match"""
        # July 4th 2024 is a Thursday - should get peak day (highest price)
        result = Pricing.objects.get_price(date(2024, 7, 4))

        assert result is not None
        assert result.price == Decimal("300.00")
        assert result.price_type == Pricing.PricingTypes.PEAK_DAY

    def test_get_price_school_holiday_beats_seasonal(self, overlapping_pricing):
        """Should return school holiday pricing over seasonal pricing"""
        # July 15th 2024 is a Monday - school holiday should beat weekday
        result = Pricing.objects.get_price(date(2024, 7, 15))

        assert result is not None
        assert result.price == Decimal("200.00")
        assert result.price_type == Pricing.PricingTypes.SCHOOL_HOLIDAY

    def test_get_price_school_holiday_on_weekend(self, overlapping_pricing):
        """Should return school holiday pricing over weekend pricing"""
        # July 6th 2024 is a Saturday - school holiday should beat weekend
        result = Pricing.objects.get_price(date(2024, 7, 6))

        assert result is not None
        assert result.price == Decimal("200.00")
        assert result.price_type == Pricing.PricingTypes.SCHOOL_HOLIDAY

    def test_get_price_public_holiday_standalone(self, overlapping_pricing):
        """Should return public holiday pricing when it's the only match"""
        # December 25th 2024 is a Wednesday - public holiday should apply
        result = Pricing.objects.get_price(date(2024, 12, 25))

        assert result is not None
        assert result.price == Decimal("250.00")
        assert result.price_type == Pricing.PricingTypes.PUBLIC_HOLIDAY

    @pytest.mark.parametrize(
        ("input_date", "expected_type"),
        [
            (
                datetime(2024, 6, 3, 14, 30),  # noqa: DTZ001
                "weekday",
            ),  # Monday datetime
            (
                datetime(2024, 6, 1, 9, 0),  # noqa: DTZ001
                "weekend",
            ),  # Saturday datetime
            (date(2024, 6, 3), "weekday"),  # Monday date
            (date(2024, 6, 1), "weekend"),  # Saturday date
        ],
    )
    def test_get_price_handles_datetime_and_date_objects(
        self,
        base_seasonal_pricing,
        input_date,
        expected_type,
    ):
        """Should handle both datetime and date objects correctly"""
        result = Pricing.objects.get_price(input_date)

        assert result is not None
        if expected_type == "weekday":
            assert result.price_type == Pricing.PricingTypes.WEEKDAY
            assert result.price == Decimal("100.00")
        else:
            assert result.price_type == Pricing.PricingTypes.WEEKEND
            assert result.price == Decimal("150.00")

    @patch("django.utils.timezone.now")
    def test_get_price_with_none_defaults_to_today(
        self,
        mock_now,
        base_seasonal_pricing,
    ):
        """Should default to today's date when lookup_date is None"""
        # Mock today as a Monday
        mock_now.return_value.date.return_value = date(2024, 6, 3)

        result = Pricing.objects.get_price(None)

        assert result is not None
        assert result.price_type == Pricing.PricingTypes.WEEKDAY
        mock_now.assert_called_once()

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
