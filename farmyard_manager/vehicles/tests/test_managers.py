# ruff : noqa: PLR2004

from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from django.utils import timezone

from farmyard_manager.entrance.tests.models.factories import TicketFactory
from farmyard_manager.users.tests.factories import UserFactory
from farmyard_manager.vehicles.models import Blacklist
from farmyard_manager.vehicles.models import SecurityFail
from farmyard_manager.vehicles.models import Vehicle
from farmyard_manager.vehicles.tests.factories import BlacklistFactory
from farmyard_manager.vehicles.tests.factories import SecurityFailFactory
from farmyard_manager.vehicles.tests.factories import VehicleFactory


@pytest.mark.django_db(transaction=True)
class TestVehicleManager:
    """Test suite for the VehicleManager class."""

    def test_manager_assignment(self):
        """Test that Vehicle model uses VehicleManager."""
        from farmyard_manager.vehicles.managers import VehicleManager

        assert isinstance(Vehicle.objects, VehicleManager)

    def test_get_or_create_from_scan_create_new(self):
        """Test creating new vehicle from scan data."""
        scan_data: dict[str, Any] = {
            "plate_number": "ABC123GP",
            "license_disc_data": {"valid_until": "2025-12-31"},
            "color": "Red",
            "make": "Toyota",
            "model": "Corolla",
            "year": 2020,
        }

        vehicle, created = Vehicle.objects.get_or_create_from_scan(**scan_data)

        assert created is True
        assert vehicle.plate_number == "ABC123GP"
        assert vehicle.color == "Red"
        assert vehicle.make == "Toyota"
        assert vehicle.model == "Corolla"
        assert vehicle.year == 2020
        assert vehicle.license_disc_data == {"valid_until": "2025-12-31"}

    def test_get_or_create_from_scan_update_existing(self):
        """Test updating existing vehicle from scan data."""
        # Create existing vehicle
        existing_vehicle: Vehicle = VehicleFactory(
            plate_number="ABC123GP",
            color="Blue",
            license_disc_data={"valid_until": "2024-12-31"},
        )

        scan_data: dict[str, Any] = {
            "plate_number": "ABC123GP",
            "license_disc_data": {"valid_until": "2025-12-31"},
            "color": "Red",
            "make": "Honda",  # This should not update
            "model": "Civic",  # This should not update
            "year": 2021,  # This should not update
        }

        vehicle, created = Vehicle.objects.get_or_create_from_scan(**scan_data)

        assert created is False
        assert vehicle.id == existing_vehicle.id
        assert vehicle.plate_number == "ABC123GP"
        assert vehicle.color == "Red"  # Updated
        assert vehicle.license_disc_data == {"valid_until": "2025-12-31"}  # Updated
        # These should remain unchanged
        assert vehicle.make == existing_vehicle.make
        assert vehicle.model == existing_vehicle.model
        assert vehicle.year == existing_vehicle.year

    def test_get_or_create_from_scan_with_kwargs(self):
        """Test creating vehicle with additional kwargs."""
        scan_data: dict[str, Any] = {
            "plate_number": "XYZ789GP",
            "license_disc_data": {"valid_until": "2025-12-31"},
            "color": "Green",
            "make": "Ford",
            "model": "Focus",
            "year": 2019,
            "is_blacklisted": True,  # Additional kwarg
        }

        vehicle, created = Vehicle.objects.get_or_create_from_scan(**scan_data)

        assert created is True
        assert vehicle.is_blacklisted is True

    def test_blacklisted_filter(self):
        """Test blacklisted vehicles filter."""
        # Create mix of blacklisted and non-blacklisted vehicles
        blacklisted_vehicles = VehicleFactory.create_batch(3, is_blacklisted=True)
        VehicleFactory.create_batch(2, is_blacklisted=False)

        result = Vehicle.objects.blacklisted()

        assert result.count() == 3
        for vehicle in result:
            assert vehicle.is_blacklisted is True
            assert vehicle in blacklisted_vehicles

    @pytest.mark.parametrize(
        ("min_count", "vehicle_fail_counts", "expected_count"),
        [
            (1, [0, 1, 2, 3], 3),  # vehicles with 1, 2, 3 fails
            (2, [0, 1, 2, 3], 2),  # vehicles with 2, 3 fails
            (3, [0, 1, 2, 3], 1),  # vehicles with 3 fails
            (5, [0, 1, 2, 3], 0),  # no vehicles with 5+ fails
        ],
        ids=[
            "min_one_fail",
            "min_two_fails",
            "min_three_fails",
            "min_five_fails",
        ],
    )
    def test_with_security_fails(self, min_count, vehicle_fail_counts, expected_count):
        """Test filtering vehicles by security fail count."""
        # Create vehicles with different fail counts
        for fail_count in vehicle_fail_counts:
            VehicleFactory(security_fail_count=fail_count)

        result = Vehicle.objects.with_security_fails(min_count)

        assert result.count() == expected_count
        for vehicle in result:
            assert vehicle.security_fail_count >= min_count

    @patch("django.conf.settings.MAX_SECURITY_FAILS", 3)
    def test_at_risk_for_blacklisting(self):
        """Test filtering vehicles at risk for blacklisting."""
        # Create vehicles with different fail counts
        VehicleFactory(security_fail_count=0, is_blacklisted=False)  # Not at risk
        VehicleFactory(security_fail_count=1, is_blacklisted=False)  # Not at risk
        at_risk_vehicle = VehicleFactory(
            security_fail_count=2,
            is_blacklisted=False,
        )  # At risk
        VehicleFactory(
            security_fail_count=3,
            is_blacklisted=True,
        )  # Already blacklisted

        result = Vehicle.objects.at_risk_for_blacklisting()

        assert result.count() == 1
        assert result.first() == at_risk_vehicle

    def test_by_make(self):
        """Test filtering vehicles by make."""
        toyota_vehicles = VehicleFactory.create_batch(2, make="Toyota")
        honda_vehicles = VehicleFactory.create_batch(1, make="Honda")
        VehicleFactory(make="Ford")

        toyota_result = Vehicle.objects.by_make("Toyota")
        honda_result = Vehicle.objects.by_make("honda")  # Case insensitive

        assert toyota_result.count() == 2
        for vehicle in toyota_result:
            assert vehicle in toyota_vehicles

        assert honda_result.count() == 1
        assert honda_result.first() in honda_vehicles

    @pytest.mark.parametrize(
        ("start_year", "end_year", "vehicle_years", "expected_count"),
        [
            (2018, 2020, [2017, 2018, 2019, 2020, 2021], 3),
            (2019, 2019, [2018, 2019, 2020], 1),
            (2025, 2030, [2018, 2019, 2020], 0),
        ],
        ids=[
            "range_2018_2020",
            "single_year_2019",
            "future_range_no_matches",
        ],
    )
    def test_by_year_range(self, start_year, end_year, vehicle_years, expected_count):
        """Test filtering vehicles by year range."""
        # Create vehicles with different years
        for year in vehicle_years:
            VehicleFactory(year=year)

        result = Vehicle.objects.by_year_range(start_year, end_year)

        assert result.count() == expected_count
        for vehicle in result:
            assert start_year <= vehicle.year <= end_year

    @pytest.mark.parametrize(
        ("search_term", "plate_numbers", "expected_count"),
        [
            ("ABC", ["ABC123", "XYZ789", "ABC456"], 2),
            ("123", ["ABC123", "XYZ789", "DEF123"], 2),
            ("ZZZ", ["ABC123", "XYZ789"], 0),
        ],
        ids=[
            "search_abc_prefix",
            "search_123_suffix",
            "search_no_matches",
        ],
    )
    def test_search_plate(self, search_term, plate_numbers, expected_count):
        """Test searching vehicles by partial plate number."""
        # Create vehicles with different plate numbers
        for plate in plate_numbers:
            VehicleFactory(plate_number=plate)

        result = Vehicle.objects.search_plate(search_term)

        assert result.count() == expected_count
        for vehicle in result:
            assert search_term.upper() in vehicle.plate_number.upper()

    def test_frequent_visitors(self):
        """Test filtering frequent visitor vehicles."""
        # Create vehicles with different visit frequencies
        frequent_vehicle = VehicleFactory()
        occasional_vehicle = VehicleFactory()
        rare_vehicle = VehicleFactory()

        # Frequent visitor (5+ visits)
        for _ in range(6):
            TicketFactory(
                vehicle=frequent_vehicle,
                created=timezone.now() - timedelta(days=5),
            )

        # Occasional visitor (3 visits)
        for _ in range(3):
            TicketFactory(
                vehicle=occasional_vehicle,
                created=timezone.now() - timedelta(days=10),
            )

        # Rare visitor (1 visit)
        TicketFactory(
            vehicle=rare_vehicle,
            created=timezone.now() - timedelta(days=15),
        )

        result = Vehicle.objects.frequent_visitors(min_visits=5, days=30)

        assert result.count() == 1
        assert frequent_vehicle in result
        assert occasional_vehicle not in result
        assert rare_vehicle not in result

    def test_frequent_visitors_ordering(self):
        """Test frequent visitors are ordered by visit count."""
        # Create vehicles with different visit counts
        vehicle_3_visits = VehicleFactory()
        vehicle_7_visits = VehicleFactory()
        vehicle_5_visits = VehicleFactory()

        # Create tickets for each vehicle
        for vehicle, visit_count in [
            (vehicle_3_visits, 3),
            (vehicle_7_visits, 7),
            (vehicle_5_visits, 5),
        ]:
            for _ in range(visit_count):
                TicketFactory(
                    vehicle=vehicle,
                    created=timezone.now() - timedelta(days=5),
                )

        result = list(Vehicle.objects.frequent_visitors(min_visits=3, days=30))

        assert len(result) == 3
        # Should be ordered by visit count descending
        assert result[0] == vehicle_7_visits
        assert result[1] == vehicle_5_visits
        assert result[2] == vehicle_3_visits

    def test_sync_offline_vehicle_placeholder(self):
        """Test sync_offline_vehicle method exists."""
        assert hasattr(Vehicle.objects, "sync_offline_vehicle")
        assert callable(Vehicle.objects.sync_offline_vehicle)

        # Test it doesn't crash when called
        Vehicle.objects.sync_offline_vehicle({}, None)


@pytest.mark.django_db(transaction=True)
class TestSecurityFailManager:
    """Test suite for the SecurityFailManager class."""

    def test_manager_assignment(self):
        """Test that SecurityFail model uses SecurityFailManager."""
        from farmyard_manager.vehicles.managers import SecurityFailManager

        assert isinstance(SecurityFail.objects, SecurityFailManager)

    @pytest.mark.parametrize(
        "failure_type",
        [
            SecurityFail.FailureChoices.ALCOHOL_POSSESSION,
            SecurityFail.FailureChoices.DRUG_POSSESSION,
            SecurityFail.FailureChoices.WEAPONS_POSSESSION,
            SecurityFail.FailureChoices.INTOXICATION,
            SecurityFail.FailureChoices.DISORDERLY_CONDUCT,
            SecurityFail.FailureChoices.OTHER,
        ],
        ids=[
            "alcohol_possession",
            "drug_possession",
            "weapons_possession",
            "intoxication",
            "disorderly_conduct",
            "other",
        ],
    )
    def test_by_failure_type(self, failure_type):
        """Test filtering security fails by type."""
        # Create security fails of different types
        target_fails = SecurityFailFactory.create_batch(2, failure_type=failure_type)
        random_failure_type = (
            SecurityFail.FailureChoices.OTHER
            if failure_type != SecurityFail.FailureChoices.OTHER
            else SecurityFail.FailureChoices.ALCOHOL_POSSESSION
        )
        SecurityFailFactory.create_batch(
            3,
            failure_type=random_failure_type,
        )

        result = SecurityFail.objects.by_failure_type(failure_type)

        assert result.count() == 2
        for fail in result:
            assert fail.failure_type == failure_type
            assert fail in target_fails

    def test_for_vehicle(self):
        """Test filtering security fails for specific vehicle."""
        target_vehicle = VehicleFactory()
        other_vehicle = VehicleFactory()

        # Create fails for target vehicle
        target_fails = SecurityFailFactory.create_batch(3, vehicle=target_vehicle)

        # Create fails for other vehicle
        SecurityFailFactory.create_batch(2, vehicle=other_vehicle)

        result = SecurityFail.objects.for_vehicle(target_vehicle)

        assert result.count() == 3
        for fail in result:
            assert fail.vehicle == target_vehicle
            assert fail in target_fails

    def test_for_vehicle_ordering(self):
        """Test security fails for vehicle are ordered by date descending."""
        vehicle = VehicleFactory()

        # Create fails at different times
        old_fail = SecurityFailFactory(
            vehicle=vehicle,
            failure_date=timezone.now() - timedelta(days=10),
        )
        recent_fail = SecurityFailFactory(
            vehicle=vehicle,
            failure_date=timezone.now() - timedelta(days=2),
        )
        middle_fail = SecurityFailFactory(
            vehicle=vehicle,
            failure_date=timezone.now() - timedelta(days=5),
        )

        result = list(SecurityFail.objects.for_vehicle(vehicle))

        assert len(result) == 3
        assert result[0] == recent_fail
        assert result[1] == middle_fail
        assert result[2] == old_fail

    def test_by_reporter(self):
        """Test filtering security fails by reporter."""
        target_user = UserFactory()
        other_user = UserFactory()

        # Create fails reported by target user
        target_fails = SecurityFailFactory.create_batch(2, reported_by=target_user)

        # Create fails reported by other user
        SecurityFailFactory.create_batch(3, reported_by=other_user)

        result = SecurityFail.objects.by_reporter(target_user)

        assert result.count() == 2
        for fail in result:
            assert fail.reported_by == target_user
            assert fail in target_fails


@pytest.mark.django_db(transaction=True)
class TestBlacklistManager:
    """Test suite for the BlacklistManager class."""

    def test_manager_assignment(self):
        """Test that Blacklist model uses BlacklistManager."""
        from farmyard_manager.vehicles.managers import BlacklistManager

        assert isinstance(Blacklist.objects, BlacklistManager)

    @pytest.mark.parametrize(
        "reason",
        [
            Blacklist.ReasonChoices.REPEATED_SECURITY_FAILURES,
            Blacklist.ReasonChoices.OTHER,
        ],
        ids=[
            "repeated_security_failures",
            "other",
        ],
    )
    def test_by_reason(self, reason):
        """Test filtering blacklists by reason."""
        # Create blacklists with different reasons
        target_blacklists = BlacklistFactory.create_batch(2, reason=reason)

        randon_reason = (
            Blacklist.ReasonChoices.OTHER
            if reason != Blacklist.ReasonChoices.OTHER
            else Blacklist.ReasonChoices.REPEATED_SECURITY_FAILURES
        )

        BlacklistFactory.create_batch(
            3,
            reason=randon_reason,
        )

        result = Blacklist.objects.by_reason(reason)

        assert result.count() == 2
        for blacklist in result:
            assert blacklist.reason == reason
            assert blacklist in target_blacklists

    def test_auto_blacklisted(self):
        """Test filtering auto-blacklisted vehicles."""
        # Create auto and manual blacklists
        auto_blacklists = BlacklistFactory.create_batch(
            2,
            reason=Blacklist.ReasonChoices.REPEATED_SECURITY_FAILURES,
        )
        BlacklistFactory.create_batch(
            3,
            reason=Blacklist.ReasonChoices.OTHER,
        )

        result = Blacklist.objects.auto_blacklisted()

        assert result.count() == 2
        for blacklist in result:
            assert (
                blacklist.reason == Blacklist.ReasonChoices.REPEATED_SECURITY_FAILURES
            )
            assert blacklist in auto_blacklists

    def test_manually_blacklisted(self):
        """Test filtering manually blacklisted vehicles."""
        # Create auto and manual blacklists
        BlacklistFactory.create_batch(
            2,
            reason=Blacklist.ReasonChoices.REPEATED_SECURITY_FAILURES,
        )
        manual_blacklists = BlacklistFactory.create_batch(
            3,
            reason=Blacklist.ReasonChoices.OTHER,
        )

        result = Blacklist.objects.manually_blacklisted()

        assert result.count() == 3
        for blacklist in result:
            assert (
                blacklist.reason != Blacklist.ReasonChoices.REPEATED_SECURITY_FAILURES
            )
            assert blacklist in manual_blacklists

    def test_by_creator(self):
        """Test filtering blacklists by creator."""
        target_user = UserFactory()
        other_user = UserFactory()

        # Create blacklists by target user
        target_blacklists = BlacklistFactory.create_batch(2, created_by=target_user)

        # Create blacklists by other user
        BlacklistFactory.create_batch(3, created_by=other_user)

        result = Blacklist.objects.by_creator(target_user)

        assert result.count() == 2
        for blacklist in result:
            assert blacklist.created_by == target_user
            assert blacklist in target_blacklists
