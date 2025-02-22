from django.conf import settings
from django.db import models
from django_extensions.db.models import TimeStampedModel

from farmyard_manager.core.models import UUIDModelMixin
from farmyard_manager.users.models import User


class Vehicle(UUIDModelMixin, TimeStampedModel, models.Model):
    make = models.CharField(max_length=50)
    model = models.CharField(max_length=50)
    color = models.CharField(max_length=20)
    year = models.IntegerField()
    plate_number = models.CharField(max_length=15, db_index=True)
    license_disc_data = models.JSONField()
    security_fails = models.IntegerField(default=0)
    is_blacklisted = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.make} {self.model} - {self.plate_number}"


class SecurityFail(UUIDModelMixin, TimeStampedModel, models.Model):
    FAILURE_CHOICES = [
        ("alcohol_possession", "Alcohol Possession"),
        ("drug_possession", "Drug Possession"),
        ("weapons_possession", "Weapons Possession"),
        ("intoxication", "Intoxication"),
        ("disorderly_conduct", "Disorderly Conduct"),
        ("other", "Other "),
    ]
    vehicle = models.ForeignKey("vehicles.Vehicle", on_delete=models.CASCADE)
    failure_type = models.CharField(
        max_length=50,
        db_index=True,
        choices=FAILURE_CHOICES,
    )
    reported_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=False,
    )
    failure_date = models.DateTimeField()

    def __str__(self):
        return f"{self.failure_date} - {self.failure_type}"

    def save(self, *args, **kwargs):
        is_new = self.is_new()

        super().save(*args, **kwargs)

        if is_new:
            self.vehicle.security_fails += 1

            if self.vehicle.security_fails >= settings.MAX_SECURITY_FAILS:
                admin = User.get_admin_user()

                Blacklist.objects.create(
                    vehicle=self.vehicle,
                    reason="repeated_security_failures",
                    created_by=admin,
                )

            self.vehicle.save()

    def delete(self, *args, **kwargs):
        vehicle = self.vehicle
        super().delete(*args, **kwargs)
        vehicle.security_fails = max(0, vehicle.security_fails - 1)
        vehicle.save()


class Blacklist(UUIDModelMixin, TimeStampedModel, models.Model):
    REASON_CHOICES = [
        ("repeated_security_failures", "Repeated Security Failures"),
        ("other", "Other "),
    ]
    vehicle = models.OneToOneField(
        "vehicles.Vehicle",
        on_delete=models.CASCADE,
    )
    reason = models.TextField(max_length=50, choices=REASON_CHOICES)
    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=False,
    )

    def __str__(self):
        return self.reason

    def save(self, *args, **kwargs):
        is_new = self.is_new()

        super().save(*args, **kwargs)

        if is_new:
            self.vehicle.is_blacklisted = True
            self.vehicle.save()

    def delete(self, *args, **kwargs):
        vehicle = self.vehicle
        super().delete(*args, **kwargs)
        vehicle.is_blacklisted = False
        vehicle.save()
