# ruff: noqa: ERA001, ARG002
from decimal import Decimal

import factory
from dateutil.relativedelta import relativedelta
from django.utils import timezone

from farmyard_manager.shifts.enums import ShiftStatusChoices
from farmyard_manager.shifts.models import Shift
from farmyard_manager.users.tests.factories import UserFactory


class ShiftFactory(factory.django.DjangoModelFactory[Shift]):
    """Factory for Shift model, ensuring valid states for statuses."""

    class Meta:
        model = Shift
        skip_postgeneration_save = True

    user = factory.SubFactory(UserFactory)
    start_time = factory.LazyFunction(timezone.now)
    float_amount = Decimal("100.00")
    status = ShiftStatusChoices.ACTIVE

    class Params:
        closed = factory.Trait(
            status=ShiftStatusChoices.CLOSED,
            end_time=factory.LazyFunction(
                lambda: timezone.now() + relativedelta(hours=8),
            ),
            expected_cash_amount=Decimal("200.00"),
            actual_cash_amount=Decimal("200.00"),
        )
        suspended = factory.Trait(
            status=ShiftStatusChoices.SUSPENDED,
            discrepancy_notes="Suspended for break",
        )

    @factory.post_generation
    def closed(self, create, extracted, **kwargs):
        if not create or not extracted:
            return
        # Simulate closing logic
        self.close_shift(
            actual_cash_amount=self.actual_cash_amount,
            performed_by=self.user,
        )
