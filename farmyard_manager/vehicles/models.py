from contextlib import suppress
from datetime import datetime
from typing import TYPE_CHECKING

from django.conf import settings
from django.db import models
from django.db import transaction
from django.utils import timezone
from model_utils.models import SoftDeletableModel
from model_utils.models import TimeStampedModel

from farmyard_manager.core.models import UUIDModelMixin
from farmyard_manager.entrance.models.ticket import Ticket
from farmyard_manager.entrance.models.ticket import TicketItem
from farmyard_manager.users.models import User
from farmyard_manager.vehicles.managers import BlacklistManager
from farmyard_manager.vehicles.managers import SecurityFailManager
from farmyard_manager.vehicles.managers import VehicleManager

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from farmyard_manager.entrance.models import ReEntryItem
    from farmyard_manager.payments.models import Payment


class Vehicle(UUIDModelMixin, SoftDeletableModel, TimeStampedModel, models.Model):
    tickets: "QuerySet[Ticket]"

    make = models.CharField(max_length=50)

    model = models.CharField(max_length=50)

    color = models.CharField(max_length=20)

    year = models.IntegerField()

    plate_number = models.CharField(max_length=15, db_index=True)

    license_disc_data = models.JSONField()

    security_fail_count = models.IntegerField(default=0)

    is_blacklisted = models.BooleanField(default=False)

    objects: VehicleManager = VehicleManager()

    def __str__(self):
        return f"{self.make} {self.model} - {self.plate_number}"

    def get_or_create_ticket(self, performed_by: User) -> Ticket:
        """
        Get today's ticket for this vehicle, create if doesn't exist
        """
        # Get ANY ticket from today, regardless of status
        ticket = self.tickets.filter(
            created__date=timezone.now().date(),
        ).first()

        if ticket:
            return ticket

        # Create new ticket if none exists and user has permission
        current_shift = performed_by.get_active_shift()
        if current_shift.can_create_tickets():
            return Ticket.objects.create_ticket(
                status=Ticket.StatusChoices.PENDING_SECURITY,
                vehicle=self,
                performed_by=performed_by,
            )

        error_message = f"Shift type '{current_shift.shift_type}' cannot create tickets"
        raise PermissionError(
            error_message,
        )

    def add_security_fail(
        self,
        failure_type: str,
        reported_by: User,
        failure_date: datetime | None = None,
    ):
        with transaction.atomic():
            self.security_fail_count += 1

            security_fail_fields = {
                "vehicle": self,
                "failure_type": failure_type,
                "reported_by": reported_by,
            }
            if failure_date:
                security_fail_fields["failure_date"] = failure_date

            SecurityFail.objects.create(**security_fail_fields)

            if self.security_fail_count >= settings.MAX_SECURITY_FAILS:
                self.is_blacklisted = True
                self.blacklist_vehicle(
                    reason=Blacklist.ReasonChoices.REPEATED_SECURITY_FAILURES,
                    created_by=User.get_admin_user(),
                )

            self.save(update_fields=["security_fail_count", "is_blacklisted"])

    def blacklist_vehicle(
        self,
        reason: str,
        created_by: User,
        blacklist_date: datetime | None = None,
    ):
        blacklist_fields = {
            "vehicle": self,
            "reason": reason,
            "created_by": created_by,
        }

        if blacklist_date:
            blacklist_fields["blacklist_date"] = blacklist_date

        Blacklist.objects.create(**blacklist_fields)

    def unblacklist_vehicle(self):
        with transaction.atomic():
            # Try to delete the blacklist entry if it exists
            with suppress(Blacklist.DoesNotExist, AttributeError):
                self.blacklist.delete()

            # Always update the vehicle status regardless of whether
            # blacklist entry existed
            self.is_blacklisted = False
            self.save(update_fields=["is_blacklisted"])

    def get_paid_item(
        self,
        payment: "Payment",
    ) -> "TicketItem | ReEntryItem":
        """Returns the entrance item that was covered by the payment"""

        # TODO: Turn these in QuerySet filters
        ticket = payment.tickets.filter(vehicle=self).first()
        re_entry = payment.re_entries.filter(ticket__vehicle=self).first()

        if ticket and re_entry:
            error_message = (
                "Multiple entrance items found for vehicle and payment. Invlaid state"
            )
            raise ValueError(error_message)

        if not ticket and not re_entry:
            error_message = (
                "No entrance item found for vehicle and payment. "
                "Vehicle likely belongs to another payment"
            )
            raise ValueError(error_message)

        entrance_record = ticket if ticket else re_entry
        assert entrance_record is not None

        return entrance_record.payable_item

    def linked_to_payment(self, payment: "Payment"):
        try:
            self.get_paid_item(payment)
        except ValueError:
            return False
        else:
            return True


# TODO: Add process to cancel ticket if security chcek is failed without resolution
class SecurityFail(UUIDModelMixin, TimeStampedModel, models.Model):
    class FailureChoices(models.TextChoices):
        ALCOHOL_POSSESSION = "alcohol_possession", "Alcohol Possession"
        DRUG_POSSESSION = "drug_possession", "Drug Possession"
        WEAPONS_POSSESSION = "weapons_possession", "Weapons Possession"
        INTOXICATION = "intoxication", "Intoxication"
        DISORDERLY_CONDUCT = "disorderly_conduct", "Disorderly Conduct"
        OTHER = "other", "Other "

    vehicle = models.ForeignKey(
        "vehicles.Vehicle",
        on_delete=models.CASCADE,
        related_name="security_fails",
    )

    failure_type = models.CharField(
        max_length=50,
        db_index=True,
        choices=FailureChoices.choices,
    )

    reported_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=False,
    )

    failure_date = models.DateTimeField(default=timezone.now)

    objects: SecurityFailManager = SecurityFailManager()

    def __str__(self):
        return f"{self.failure_date} - {self.failure_type}"

    # TODO: Should this be allowed?
    def delete(self, *args, **kwargs):
        vehicle = self.vehicle
        super().delete(*args, **kwargs)
        vehicle.security_fail_count = max(0, vehicle.security_fail_count - 1)
        vehicle.save()


class Blacklist(UUIDModelMixin, TimeStampedModel, models.Model):
    class ReasonChoices(models.TextChoices):
        REPEATED_SECURITY_FAILURES = (
            "repeated_security_failures",
            "Repeated Security Failures",
        )
        OTHER = "other", "Other "

    vehicle = models.OneToOneField(
        "vehicles.Vehicle",
        on_delete=models.CASCADE,
        related_name="blacklist",
    )

    reason = models.TextField(max_length=50, choices=ReasonChoices.choices)

    blacklist_date = models.DateTimeField(auto_now_add=True)

    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=False,
    )

    objects: BlacklistManager = BlacklistManager()

    def __str__(self):
        return self.reason

    def delete(self, *args, **kwargs):
        vehicle = self.vehicle
        super().delete(*args, **kwargs)
        vehicle.is_blacklisted = False
        vehicle.save()
