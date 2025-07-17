from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING
from typing import Any

from django.conf import settings
from django.db import models
from django.utils import timezone
from model_utils.managers import SoftDeletableManager
from model_utils.managers import SoftDeletableQuerySet

if TYPE_CHECKING:
    from farmyard_manager.users.models import User
    from farmyard_manager.vehicles.models import Blacklist  # noqa: F401
    from farmyard_manager.vehicles.models import SecurityFail  # noqa: F401
    from farmyard_manager.vehicles.models import Vehicle


class VehicleQuerySet(SoftDeletableQuerySet["Vehicle"], models.QuerySet["Vehicle"]):
    """Custom QuerySet for Vehicle model with chainable methods"""

    def blacklisted(self) -> VehicleQuerySet:
        """Get all blacklisted vehicles"""
        return self.filter(is_blacklisted=True)

    def with_security_fails(self, min_count: int = 1) -> VehicleQuerySet:
        """Get vehicles with security fail count >= min_count"""
        return self.filter(security_fail_count__gte=min_count)

    def at_risk_for_blacklisting(self) -> VehicleQuerySet:
        """Get vehicles close to auto-blacklisting threshold"""
        max_fails = getattr(settings, "MAX_SECURITY_FAILS", 3)
        return self.filter(
            security_fail_count__gte=max_fails - 1,
            is_blacklisted=False,
        )

    def by_make(self, make: str) -> VehicleQuerySet:
        """Get vehicles by make"""
        return self.filter(make__icontains=make)

    def by_year_range(self, start_year: int, end_year: int) -> VehicleQuerySet:
        """Get vehicles within year range"""
        return self.filter(year__range=(start_year, end_year))

    def search_plate(self, plate_partial: str) -> VehicleQuerySet:
        """Search vehicles by partial plate number"""
        return self.filter(plate_number__icontains=plate_partial)

    def frequent_visitors(self, min_visits: int = 5, days: int = 30) -> VehicleQuerySet:
        """Get vehicles with multiple visits in time period"""
        cutoff_date = timezone.now() - timedelta(days=days)
        return (
            self.annotate(
                visit_count=models.Count(
                    "tickets",
                    filter=models.Q(tickets__created__gte=cutoff_date),
                ),
            )
            .filter(visit_count__gte=min_visits)
            .order_by("-visit_count")
        )


class VehicleManager(SoftDeletableManager["Vehicle"], models.Manager["Vehicle"]):
    """Custom Manager for Vehicle model with business logic methods"""

    def get_queryset(self) -> VehicleQuerySet:
        """Return custom QuerySet"""
        return VehicleQuerySet(self.model, using=self._db)

    def get_or_create_from_scan(  # noqa: PLR0913
        self,
        plate_number: str,
        license_disc_data: dict[str, Any],
        color: str,
        make: str,
        model: str,
        year: int,
        **kwargs: Any,
    ) -> tuple[Vehicle, bool]:
        """
        Get existing vehicle by plate or create new one.
        Updates license_disc_data and color on existing vehicles.
        """
        try:
            vehicle = self.get(plate_number=plate_number)
            # Update fields that can change
            vehicle.license_disc_data = license_disc_data
            vehicle.color = color
            vehicle.save(update_fields=["license_disc_data", "color", "modified"])
        except self.model.DoesNotExist:
            return (
                self.create(
                    plate_number=plate_number,
                    license_disc_data=license_disc_data,
                    color=color,
                    make=make,
                    model=model,
                    year=year,
                    **kwargs,
                ),
                True,
            )
        else:
            return vehicle, False  # (vehicle, created)

    def sync_offline_vehicle(
        self,
        vehicle_data: dict[str, Any],
        created_timestamp: Any = None,
    ) -> None:
        """Placeholder for offline vehicle sync"""

    # Delegate QuerySet methods to get IntelliSense support
    def blacklisted(self) -> VehicleQuerySet:
        """Get all blacklisted vehicles"""
        return self.get_queryset().blacklisted()

    def with_security_fails(self, min_count: int = 1) -> VehicleQuerySet:
        """Get vehicles with security fail count >= min_count"""
        return self.get_queryset().with_security_fails(min_count)

    def at_risk_for_blacklisting(self) -> VehicleQuerySet:
        """Get vehicles close to auto-blacklisting threshold"""
        return self.get_queryset().at_risk_for_blacklisting()

    def by_make(self, make: str) -> VehicleQuerySet:
        """Get vehicles by make"""
        return self.get_queryset().by_make(make)

    def by_year_range(self, start_year: int, end_year: int) -> VehicleQuerySet:
        """Get vehicles within year range"""
        return self.get_queryset().by_year_range(start_year, end_year)

    def search_plate(self, plate_partial: str) -> VehicleQuerySet:
        """Search vehicles by partial plate number"""
        return self.get_queryset().search_plate(plate_partial)

    def frequent_visitors(self, min_visits: int = 5, days: int = 30) -> VehicleQuerySet:
        """Get vehicles with multiple visits in time period"""
        return self.get_queryset().frequent_visitors(min_visits, days)


class SecurityFailQuerySet(models.QuerySet["SecurityFail"]):
    """Custom QuerySet for SecurityFail model with chainable methods"""

    def by_failure_type(self, failure_type: str) -> SecurityFailQuerySet:
        """Get security fails by type"""
        return self.filter(failure_type=failure_type)

    def for_vehicle(self, vehicle: Vehicle) -> SecurityFailQuerySet:
        """Get all security fails for a vehicle"""
        return self.filter(vehicle=vehicle).order_by("-failure_date")

    def by_reporter(self, user: User) -> SecurityFailQuerySet:
        """Get security fails reported by specific user"""
        return self.filter(reported_by=user)


class SecurityFailManager(models.Manager["SecurityFail"]):
    """Custom Manager for SecurityFail model with business logic methods"""

    def get_queryset(self) -> SecurityFailQuerySet:
        """Return custom QuerySet"""
        return SecurityFailQuerySet(self.model, using=self._db)

    def sync_offline_security_fail(
        self,
        fail_data: dict[str, Any],
        created_timestamp: Any = None,
    ) -> None:
        """Placeholder for offline security fail sync"""
        # TODO: Implement offline security fail synchronization

    # Delegate QuerySet methods to get IntelliSense support
    def by_failure_type(self, failure_type: str) -> SecurityFailQuerySet:
        """Get security fails by type"""
        return self.get_queryset().by_failure_type(failure_type)

    def for_vehicle(self, vehicle: Vehicle) -> SecurityFailQuerySet:
        """Get all security fails for a vehicle"""
        return self.get_queryset().for_vehicle(vehicle)

    def by_reporter(self, user: User) -> SecurityFailQuerySet:
        """Get security fails reported by specific user"""
        return self.get_queryset().by_reporter(user)


class BlacklistQuerySet(models.QuerySet["Blacklist"]):
    """Custom QuerySet for Blacklist model with chainable methods"""

    def by_reason(self, reason: str) -> BlacklistQuerySet:
        """Get blacklisted vehicles by reason"""
        return self.filter(reason=reason)

    def auto_blacklisted(self) -> BlacklistQuerySet:
        """Get vehicles auto-blacklisted for security failures"""
        return self.filter(reason="repeated_security_failures")

    def manually_blacklisted(self) -> BlacklistQuerySet:
        """Get manually blacklisted vehicles"""
        return self.exclude(reason="repeated_security_failures")

    def by_creator(self, user: User) -> BlacklistQuerySet:
        """Get blacklists created by specific user"""
        return self.filter(created_by=user)


class BlacklistManager(models.Manager["Blacklist"]):
    """Custom Manager for Blacklist model with business logic methods"""

    def get_queryset(self) -> BlacklistQuerySet:
        """Return custom QuerySet"""
        return BlacklistQuerySet(self.model, using=self._db)

    def sync_offline_blacklist(
        self,
        blacklist_data: dict[str, Any],
        created_timestamp: Any = None,
    ) -> None:
        """Placeholder for offline blacklist sync"""
        # TODO: Implement offline blacklist synchronization

    # Delegate QuerySet methods to get IntelliSense support
    def by_reason(self, reason: str) -> BlacklistQuerySet:
        """Get blacklisted vehicles by reason"""
        return self.get_queryset().by_reason(reason)

    def auto_blacklisted(self) -> BlacklistQuerySet:
        """Get vehicles auto-blacklisted for security failures"""
        return self.get_queryset().auto_blacklisted()

    def manually_blacklisted(self) -> BlacklistQuerySet:
        """Get manually blacklisted vehicles"""
        return self.get_queryset().manually_blacklisted()

    def by_creator(self, user: User) -> BlacklistQuerySet:
        """Get blacklists created by specific user"""
        return self.get_queryset().by_creator(user)
