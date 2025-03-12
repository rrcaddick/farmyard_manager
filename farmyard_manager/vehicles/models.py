from contextlib import suppress
from datetime import datetime

from django.conf import settings
from django.db import models
from django.db import transaction
from model_utils.models import SoftDeletableModel
from model_utils.models import TimeStampedModel

from farmyard_manager.core.models import UUIDModelMixin
from farmyard_manager.users.models import User


class Vehicle(UUIDModelMixin, SoftDeletableModel, TimeStampedModel, models.Model):
    make = models.CharField(max_length=50)

    model = models.CharField(max_length=50)

    color = models.CharField(max_length=20)

    year = models.IntegerField()

    plate_number = models.CharField(max_length=15, db_index=True)

    license_disc_data = models.JSONField()

    security_fail_count = models.IntegerField(default=0)

    is_blacklisted = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.make} {self.model} - {self.plate_number}"

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

            self.save(update_fields=["security_fails", "is_blacklisted"])

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
        with transaction.atomic(), suppress(Blacklist.DoesNotExist, AttributeError):
            self.blacklist.delete()
            self.is_blacklisted = False
            self.save(update_fields=["is_blacklisted"])


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

    failure_date = models.DateTimeField(auto_now_add=True)

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

    def __str__(self):
        return self.reason

    def delete(self, *args, **kwargs):
        vehicle = self.vehicle
        super().delete(*args, **kwargs)
        vehicle.is_blacklisted = False
        vehicle.save()
