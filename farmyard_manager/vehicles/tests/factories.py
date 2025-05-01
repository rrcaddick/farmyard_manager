import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from farmyard_manager.users.tests.factories import UserFactory
from farmyard_manager.vehicles.models import Blacklist
from farmyard_manager.vehicles.models import SecurityFail
from farmyard_manager.vehicles.models import Vehicle


class VehicleFactory(DjangoModelFactory[Vehicle]):
    make = factory.Faker("company")
    model = factory.Faker("word")
    color = factory.Faker("color_name")
    year = factory.Faker("year")
    plate_number = factory.Faker("license_plate")
    license_disc_data = factory.Dict({"valid_until": "2025-12-31"})
    security_fail_count = 0
    is_blacklisted = False

    class Meta:
        model = Vehicle


class SecurityFailFactory(DjangoModelFactory[SecurityFail]):
    vehicle = factory.SubFactory(VehicleFactory)
    failure_type = factory.Iterator(SecurityFail.FailureChoices.values)
    reported_by = factory.SubFactory(UserFactory)
    failure_date = factory.LazyFunction(timezone.now)

    class Meta:
        model = SecurityFail


class BlacklistFactory(DjangoModelFactory[Blacklist]):
    vehicle = factory.SubFactory(VehicleFactory)
    reason = factory.Iterator(Blacklist.ReasonChoices.values)
    created_by = factory.SubFactory(UserFactory)
    blacklist_date = factory.LazyFunction(timezone.now)

    class Meta:
        model = Blacklist
