# farmyard_manager/vehicles/tests/test_models.py

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from django.utils import timezone

from farmyard_manager.entrance.models.enums import TicketStatusChoices
from farmyard_manager.entrance.tests.models.factories import TicketFactory
from farmyard_manager.users.tests.factories import UserFactory
from farmyard_manager.vehicles.models import Blacklist
from farmyard_manager.vehicles.models import SecurityFail
from farmyard_manager.vehicles.tests.factories import BlacklistFactory
from farmyard_manager.vehicles.tests.factories import SecurityFailFactory
from farmyard_manager.vehicles.tests.factories import VehicleFactory


@pytest.mark.django_db(transaction=True)
class TestVehicle:
    """Test suite for the Vehicle model."""

    def test_str_representation(self):
        """Test string representation of vehicle."""
        vehicle = VehicleFactory(
            make="Toyota",
            model="Corolla",
            plate_number="ABC123GP",
        )
        expected = "Toyota Corolla - ABC123GP"
        assert str(vehicle) == expected

    def test_vehicle_creation_with_defaults(self):
        """Test vehicle creation with default values."""
        vehicle = VehicleFactory()
        assert vehicle.security_fail_count == 0
        assert vehicle.is_blacklisted is False
        assert vehicle.uuid is not None
        assert vehicle.created is not None
        assert vehicle.modified is not None

    @pytest.mark.parametrize(
        ("security_fail_count", "is_blacklisted", "expected_blacklisted"),
        [
            (0, False, False),
            (1, False, False),
            (2, False, False),
            (3, True, True),
            (5, True, True),
        ],
        ids=[
            "no_fails_not_blacklisted",
            "one_fail_not_blacklisted",
            "two_fails_not_blacklisted",
            "three_fails_blacklisted",
            "multiple_fails_blacklisted",
        ],
    )
    def test_vehicle_blacklist_status(
        self,
        security_fail_count,
        is_blacklisted,
        expected_blacklisted,
    ):
        """Test vehicle blacklist status based on security fails."""
        vehicle = VehicleFactory(
            security_fail_count=security_fail_count,
            is_blacklisted=is_blacklisted,
        )
        assert vehicle.is_blacklisted == expected_blacklisted

    @patch("farmyard_manager.vehicles.models.Vehicle.tickets")
    def test_get_or_create_ticket_existing_today(self, mock_tickets):
        """Test getting existing ticket from today."""
        vehicle = VehicleFactory()
        user = UserFactory()
        existing_ticket = TicketFactory(vehicle=vehicle)

        # Mock the filter chain
        mock_filter = MagicMock()
        mock_filter.first.return_value = existing_ticket
        mock_tickets.filter.return_value = mock_filter

        # Mock user's current shift
        mock_shift = MagicMock()
        user.get_current_shift = MagicMock(return_value=mock_shift)

        result = vehicle.get_or_create_ticket(performed_by=user)

        assert result == existing_ticket
        mock_tickets.filter.assert_called_once()

    @patch("farmyard_manager.vehicles.models.Vehicle.tickets")
    @patch("farmyard_manager.entrance.models.Ticket.objects.create_ticket")
    def test_get_or_create_ticket_create_new(
        self,
        mock_create_ticket,
        mock_tickets,
    ):
        """Test creating new ticket when none exists."""
        vehicle = VehicleFactory()
        user = UserFactory()
        new_ticket = TicketFactory(vehicle=vehicle)

        # Mock no existing tickets
        mock_filter = MagicMock()
        mock_filter.first.return_value = None
        mock_tickets.filter.return_value = mock_filter

        # Mock user's current shift that can create tickets
        mock_shift = MagicMock()
        mock_shift.can_create_tickets.return_value = True
        user.get_active_shift = MagicMock(return_value=mock_shift)

        mock_create_ticket.return_value = new_ticket

        result = vehicle.get_or_create_ticket(performed_by=user)

        assert result == new_ticket
        mock_create_ticket.assert_called_once_with(
            status=TicketStatusChoices.PENDING_SECURITY,
            vehicle=vehicle,
            performed_by=user,
        )

    @patch("farmyard_manager.vehicles.models.Vehicle.tickets")
    def test_get_or_create_ticket_permission_denied(self, mock_tickets):
        """Test permission error when user can't create tickets."""
        vehicle = VehicleFactory()
        user = UserFactory()

        # Mock no existing tickets
        mock_filter = MagicMock()
        mock_filter.first.return_value = None
        mock_tickets.filter.return_value = mock_filter

        # Mock user's current shift that cannot create tickets
        mock_shift = MagicMock()
        mock_shift.can_create_tickets.return_value = False
        mock_shift.shift_type = "security_marshal"
        user.get_active_shift = MagicMock(return_value=mock_shift)

        with pytest.raises(
            PermissionError,
            match="Shift type 'security_marshal' cannot create tickets",
        ):
            vehicle.get_or_create_ticket(performed_by=user)

    @patch("farmyard_manager.users.models.User.get_admin_user")
    def test_add_security_fail_basic(self, mock_get_admin):
        """Test adding a security fail."""
        vehicle = VehicleFactory(security_fail_count=0)
        user = UserFactory()
        admin_user = UserFactory()
        mock_get_admin.return_value = admin_user

        failure_date = timezone.now()

        vehicle.add_security_fail(
            failure_type=SecurityFail.FailureChoices.ALCOHOL_POSSESSION,
            reported_by=user,
            failure_date=failure_date,
        )

        vehicle.refresh_from_db()
        assert vehicle.security_fail_count == 1

        # Check security fail was created
        security_fail = vehicle.security_fails.get()
        assert (
            security_fail.failure_type == SecurityFail.FailureChoices.ALCOHOL_POSSESSION
        )
        assert security_fail.reported_by == user
        assert security_fail.failure_date == failure_date

    @patch("farmyard_manager.users.models.User.get_admin_user")
    @patch("django.conf.settings.MAX_SECURITY_FAILS", 3)
    def test_add_security_fail_auto_blacklist(self, mock_get_admin):
        """Test auto-blacklisting when security fails reach threshold."""
        admin_user = UserFactory()
        mock_get_admin.return_value = admin_user

        vehicle = VehicleFactory(security_fail_count=2)  # One away from threshold
        user = UserFactory()

        vehicle.add_security_fail(
            failure_type=SecurityFail.FailureChoices.DRUG_POSSESSION,
            reported_by=user,
        )

        vehicle.refresh_from_db()
        assert vehicle.security_fail_count == 3  # noqa: PLR2004
        assert vehicle.is_blacklisted is True

        # Check blacklist entry was created
        blacklist = vehicle.blacklist
        assert blacklist.reason == Blacklist.ReasonChoices.REPEATED_SECURITY_FAILURES
        assert blacklist.created_by == admin_user

    @patch("farmyard_manager.users.models.User.get_admin_user")
    @patch("django.conf.settings.MAX_SECURITY_FAILS", 3)
    def test_add_security_fail_no_auto_blacklist_under_threshold(self, mock_get_admin):
        """Test no auto-blacklisting when under threshold."""
        admin_user = UserFactory()
        mock_get_admin.return_value = admin_user

        vehicle = VehicleFactory(security_fail_count=1)
        user = UserFactory()

        vehicle.add_security_fail(
            failure_type=SecurityFail.FailureChoices.INTOXICATION,
            reported_by=user,
        )

        vehicle.refresh_from_db()
        assert vehicle.security_fail_count == 2  # noqa: PLR2004
        assert vehicle.is_blacklisted is False

        # Check no blacklist entry was created
        with pytest.raises(Blacklist.DoesNotExist):
            vehicle.blacklist  # noqa: B018

    def test_blacklist_vehicle_basic(self):
        """Test manual vehicle blacklisting."""
        vehicle = VehicleFactory()
        user = UserFactory()
        blacklist_date = timezone.now()

        vehicle.blacklist_vehicle(
            reason=Blacklist.ReasonChoices.OTHER,
            created_by=user,
            blacklist_date=blacklist_date,
        )

        # Check blacklist entry was created
        blacklist = vehicle.blacklist
        assert blacklist.reason == Blacklist.ReasonChoices.OTHER
        assert blacklist.created_by == user

    def test_blacklist_vehicle_auto_date(self):
        """Test blacklisting with auto-generated date."""
        vehicle = VehicleFactory()
        user = UserFactory()

        before_blacklist = timezone.now()
        vehicle.blacklist_vehicle(
            reason=Blacklist.ReasonChoices.OTHER,
            created_by=user,
        )
        after_blacklist = timezone.now()

        blacklist = vehicle.blacklist
        assert before_blacklist <= blacklist.blacklist_date <= after_blacklist

    def test_unblacklist_vehicle_success(self):
        """Test successful vehicle unblacklisting."""
        vehicle = VehicleFactory(is_blacklisted=True)
        BlacklistFactory(vehicle=vehicle)

        assert vehicle.is_blacklisted is True

        vehicle.unblacklist_vehicle()

        vehicle.refresh_from_db()
        assert vehicle.is_blacklisted is False

        # Check blacklist entry was deleted
        with pytest.raises(Blacklist.DoesNotExist):
            vehicle.blacklist  # noqa: B018

    def test_unblacklist_vehicle_no_blacklist_entry(self):
        """Test unblacklisting when no blacklist entry exists."""
        vehicle = VehicleFactory(is_blacklisted=True)

        # This should not raise an error due to suppress()
        vehicle.unblacklist_vehicle()

        vehicle.refresh_from_db()
        assert vehicle.is_blacklisted is False

    def test_unblacklist_vehicle_not_blacklisted(self):
        """Test unblacklisting a non-blacklisted vehicle."""
        vehicle = VehicleFactory(is_blacklisted=False)

        # This should not raise an error
        vehicle.unblacklist_vehicle()

        vehicle.refresh_from_db()
        assert vehicle.is_blacklisted is False


@pytest.mark.django_db(transaction=True)
class TestSecurityFail:
    """Test suite for the SecurityFail model."""

    def test_str_representation(self):
        """Test string representation of security fail."""
        failure_date = timezone.now()
        security_fail = SecurityFailFactory(
            failure_type=SecurityFail.FailureChoices.ALCOHOL_POSSESSION,
            failure_date=failure_date,
        )
        expected = f"{failure_date} - {SecurityFail.FailureChoices.ALCOHOL_POSSESSION}"
        assert str(security_fail) == expected

    def test_security_fail_creation(self):
        """Test security fail creation with all fields."""
        vehicle = VehicleFactory()
        user = UserFactory()
        failure_date = timezone.now()

        security_fail = SecurityFailFactory(
            vehicle=vehicle,
            failure_type=SecurityFail.FailureChoices.WEAPONS_POSSESSION,
            reported_by=user,
            failure_date=failure_date,
        )

        assert security_fail.vehicle == vehicle
        assert (
            security_fail.failure_type == SecurityFail.FailureChoices.WEAPONS_POSSESSION
        )
        assert security_fail.reported_by == user
        assert security_fail.failure_date == failure_date
        assert security_fail.uuid is not None

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
    def test_security_fail_types(self, failure_type):
        """Test all security fail types can be created."""
        security_fail = SecurityFailFactory(failure_type=failure_type)
        assert security_fail.failure_type == failure_type

    def test_security_fail_deletion_updates_vehicle_count(self):
        """Test deleting security fail decrements vehicle count."""
        vehicle = VehicleFactory(security_fail_count=3)
        security_fail = SecurityFailFactory(vehicle=vehicle)

        assert vehicle.security_fail_count == 3  # noqa: PLR2004

        security_fail.delete()

        vehicle.refresh_from_db()
        assert vehicle.security_fail_count == 2  # noqa: PLR2004

    def test_security_fail_deletion_never_negative(self):
        """Test vehicle security fail count never goes negative."""
        vehicle = VehicleFactory(security_fail_count=0)
        security_fail = SecurityFailFactory(vehicle=vehicle)

        security_fail.delete()

        vehicle.refresh_from_db()
        assert vehicle.security_fail_count == 0  # Should not go negative

    def test_security_fail_vehicle_relationship(self):
        """Test security fail to vehicle relationship."""
        vehicle = VehicleFactory()
        security_fail = SecurityFailFactory(vehicle=vehicle)

        assert security_fail.vehicle == vehicle
        assert security_fail in vehicle.security_fails.all()

    def test_security_fail_user_relationship(self):
        """Test security fail to user relationship."""
        user = UserFactory()
        security_fail = SecurityFailFactory(reported_by=user)

        assert security_fail.reported_by == user


@pytest.mark.django_db(transaction=True)
class TestBlacklist:
    """Test suite for the Blacklist model."""

    def test_str_representation(self):
        """Test string representation of blacklist."""
        blacklist = BlacklistFactory(
            reason=Blacklist.ReasonChoices.REPEATED_SECURITY_FAILURES,
        )
        expected = Blacklist.ReasonChoices.REPEATED_SECURITY_FAILURES
        assert str(blacklist) == expected

    def test_blacklist_creation(self):
        """Test blacklist creation with all fields."""
        vehicle = VehicleFactory()
        user = UserFactory()
        blacklist_date = timezone.now()

        blacklist = BlacklistFactory(
            vehicle=vehicle,
            reason=Blacklist.ReasonChoices.OTHER,
            created_by=user,
            blacklist_date=blacklist_date,
        )

        assert blacklist.vehicle == vehicle
        assert blacklist.reason == Blacklist.ReasonChoices.OTHER
        assert blacklist.created_by == user
        assert blacklist.uuid is not None

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
    def test_blacklist_reasons(self, reason):
        """Test all blacklist reasons can be created."""
        blacklist = BlacklistFactory(reason=reason)
        assert blacklist.reason == reason

    def test_blacklist_one_to_one_relationship(self):
        """Test one-to-one relationship between vehicle and blacklist."""
        vehicle = VehicleFactory()
        blacklist = BlacklistFactory(vehicle=vehicle)

        assert blacklist.vehicle == vehicle
        assert vehicle.blacklist == blacklist

    def test_blacklist_deletion_updates_vehicle(self):
        """Test deleting blacklist updates vehicle status."""
        vehicle = VehicleFactory(is_blacklisted=True)
        blacklist = BlacklistFactory(vehicle=vehicle)

        assert vehicle.is_blacklisted is True

        blacklist.delete()

        vehicle.refresh_from_db()
        assert vehicle.is_blacklisted is False

    def test_blacklist_user_relationship(self):
        """Test blacklist to user relationship."""
        user = UserFactory()
        blacklist = BlacklistFactory(created_by=user)

        assert blacklist.created_by == user

    def test_blacklist_cascade_deletion(self):
        """Test blacklist is deleted when vehicle is deleted."""
        vehicle = VehicleFactory()
        blacklist = BlacklistFactory(vehicle=vehicle)
        blacklist_id = blacklist.id

        # Perform hard delete instead of soft delete
        vehicle.delete(soft=False)

        with pytest.raises(Blacklist.DoesNotExist):
            Blacklist.objects.get(id=blacklist_id)
