from decimal import Decimal

import factory
from dateutil.relativedelta import relativedelta
from django.utils import timezone
from factory.django import DjangoModelFactory

from farmyard_manager.core.tests.factories import SkipCleanBeforeSaveFactoryMixin
from farmyard_manager.entrance.models import ReEntry
from farmyard_manager.entrance.models import ReEntryItem
from farmyard_manager.entrance.models import ReEntryItemEditHistory
from farmyard_manager.entrance.models import ReEntryStatusHistory
from farmyard_manager.entrance.models import Ticket
from farmyard_manager.entrance.models import TicketItem
from farmyard_manager.entrance.models import TicketItemEditHistory
from farmyard_manager.entrance.models import TicketStatusHistory
from farmyard_manager.entrance.models.pricing import Pricing
from farmyard_manager.users.tests.factories import UserFactory
from farmyard_manager.vehicles.tests.factories import VehicleFactory


class PricingFactory(factory.django.DjangoModelFactory[Pricing]):
    """Create a pricing entry that includes today with the correct base price_type."""

    class Meta:
        model = Pricing
        skip_postgeneration_save = True

    start_date = factory.LazyFunction(timezone.localdate)
    end_date = factory.LazyFunction(
        lambda: timezone.localdate() + relativedelta(months=1),
    )

    # Choose WEEKEND vs WEEKDAY depending on today
    price_type = factory.LazyFunction(
        lambda: (
            Pricing.PricingTypes.WEEKEND
            if timezone.localdate().weekday() in (5, 6)
            else Pricing.PricingTypes.WEEKDAY
        ),
    )

    price = Decimal("100.00")

    class Params:
        as_peak_day = factory.Trait(
            price_type=Pricing.PricingTypes.PEAK_DAY,
            end_date=factory.LazyFunction(timezone.localdate),
        )
        as_public_holiday = factory.Trait(
            price_type=Pricing.PricingTypes.PUBLIC_HOLIDAY,
            end_date=factory.LazyFunction(timezone.localdate),
        )
        as_school_holiday = factory.Trait(
            price_type=Pricing.PricingTypes.SCHOOL_HOLIDAY,
        )
        as_weekday = factory.Trait(
            price_type=Pricing.PricingTypes.WEEKDAY,
        )
        as_weekend = factory.Trait(
            price_type=Pricing.PricingTypes.WEEKEND,
        )


class TicketFactory(
    SkipCleanBeforeSaveFactoryMixin,
    factory.django.DjangoModelFactory[Ticket],
):
    class Meta:
        model = Ticket
        skip_postgeneration_save = False

    vehicle = factory.SubFactory(VehicleFactory)
    status = Ticket.StatusChoices.PENDING_SECURITY

    class Params:
        passed_security = factory.Trait(
            status=Ticket.StatusChoices.PASSED_SECURITY,
        )
        counted = factory.Trait(
            status=Ticket.StatusChoices.COUNTED,
        )
        processed = factory.Trait(
            status=Ticket.StatusChoices.PROCESSED,
        )
        refunded = factory.Trait(
            status=Ticket.StatusChoices.REFUNDED,
        )
        with_payment = factory.Trait(
            status=Ticket.StatusChoices.PROCESSED,
            payment=factory.SubFactory(
                "farmyard_manager.payments.tests.factories.PaymentFactory",
            ),
        )

    @factory.post_generation
    def with_items(self, create, extracted, **kwargs):
        """
        Post generation hook to add ticket items.

        Usage:
            TicketFactory()  # No items added
            TicketFactory(with_items=False)  # No items added
            TicketFactory(with_items=True)  # Adds default items based on ticket status
            TicketFactory(
                with_items=True,
                with_items__visitor_count=3,
                with_items__item_type="group"
            )  # Used to manipulate default values
            TicketFactory(
                with_items=[{"visitor_count": 4, "item_type": "public"}]
            ) # Full Control
        """
        # Not saving or with_items=False passed or with_items not passed
        if not create or not extracted:
            return

        default_items = [
            {
                "visitor_count": kwargs.get("visitor_count", 2),
                "item_type": kwargs.get("item_type", TicketItem.ItemTypeChoices.PUBLIC),
            },
        ]

        items = extracted if isinstance(extracted, list) else default_items

        # Skip clean when adding to processed ticket
        skip_clean = self.is_processed

        created_by = UserFactory()

        for item_kwargs in items:
            TicketItemFactory(
                ticket=self,
                created_by=created_by,
                **item_kwargs,
                skip_clean=skip_clean,
            )


class TicketItemFactory(
    SkipCleanBeforeSaveFactoryMixin,
    factory.django.DjangoModelFactory[TicketItem],
):
    class Meta:
        model = TicketItem
        skip_postgeneration_save = True

    ticket = factory.SubFactory(TicketFactory, passed_security=True)
    created_by = factory.SubFactory(UserFactory)
    item_type = TicketItem.ItemTypeChoices.PUBLIC
    visitor_count = 2

    class Params:
        as_group_item = factory.Trait(
            item_type=TicketItem.ItemTypeChoices.GROUP,
        )
        as_online_item = factory.Trait(
            item_type=TicketItem.ItemTypeChoices.ONLINE,
        )
        as_school_item = factory.Trait(
            item_type=TicketItem.ItemTypeChoices.SCHOOL,
        )


class TicketItemEditHistoryFactory(DjangoModelFactory[TicketItemEditHistory]):
    ticket_item = factory.SubFactory(TicketItemFactory)
    field = TicketItemEditHistory.FieldChoices.ITEM_TYPE
    prev_value = TicketItem.ItemTypeChoices.PUBLIC
    new_value = TicketItem.ItemTypeChoices.GROUP
    performed_by = factory.SubFactory(UserFactory)

    class Meta:
        model = TicketItemEditHistory
        skip_postgeneration_save = True


class TicketStatusHistoryFactory(DjangoModelFactory[TicketStatusHistory]):
    ticket = factory.SubFactory(TicketFactory)
    prev_status = Ticket.StatusChoices.PENDING_SECURITY
    new_status = Ticket.StatusChoices.PASSED_SECURITY
    performed_by = factory.SubFactory(UserFactory)

    class Meta:
        model = TicketStatusHistory
        skip_postgeneration_save = True


class ReEntryFactory(
    SkipCleanBeforeSaveFactoryMixin,
    factory.django.DjangoModelFactory[ReEntry],
):
    """Factory for ReEntry model, ensuring valid states based on ticket and statuses."""

    class Meta:
        model = ReEntry

    ticket = factory.SubFactory(TicketFactory, processed=True, with_items=True)
    status = ReEntry.StatusChoices.PENDING
    visitors_left = 2
    visitors_returned = 2

    class Params:
        pending_payment = factory.Trait(
            status=ReEntry.StatusChoices.PENDING_PAYMENT,
        )
        processed = factory.Trait(
            status=ReEntry.StatusChoices.PROCESSED,
            completed_time=factory.LazyFunction(timezone.now),
        )
        refunded = factory.Trait(
            status=ReEntry.StatusChoices.REFUNDED,
            completed_time=factory.LazyFunction(timezone.now),
        )

    @factory.post_generation
    def with_items(self, create, extracted, **kwargs):
        """
        Post generation hook to add re-entry items.
        Usage:
            ReEntryFactory()  # No items added
            ReEntryFactory(with_items=False)  # No items added
            ReEntryFactory(with_items=True)  # Adds default items
            ReEntryFactory(
                with_items=True,
                with_items__visitor_count=3,
                with_items__item_type="public"
            )  # Used to manipulate default values
            ReEntryFactory(
                with_items=[{"visitor_count": 4, "item_type": "public"}]
            )  # Full Control
        """
        # Not saving or with_items=False passed or with_items not passed
        if not create or not extracted:
            return

        # Calculate how many additional visitors we can add items for
        additional_visitors = self.visitors_returned - self.visitors_left

        if additional_visitors <= 0:
            error_message = (
                "Cannot add re-entry items when no additional visitors are returning"
            )
            raise ValueError(error_message)

        default_items = [
            {
                "visitor_count": kwargs.get("visitor_count", additional_visitors),
                "item_type": kwargs.get(
                    "item_type",
                    ReEntryItem.ItemTypeChoices.PUBLIC,
                ),
            },
        ]

        items = extracted if isinstance(extracted, list) else default_items

        # Validate total visitor count doesn't exceed what's allowed
        total_item_visitors = sum(item.get("visitor_count", 0) for item in items)
        if total_item_visitors > additional_visitors:
            error_message = (
                f"Total visitor count in items ({total_item_visitors}) "
                f"exceeds additional visitors ({additional_visitors})"
            )
            raise ValueError(error_message)

        # Skip clean when adding to processed re-entry
        skip_clean = self.is_processed
        created_by = UserFactory()

        for item_kwargs in items:
            ReEntryItemFactory(
                re_entry=self,
                created_by=created_by,
                **item_kwargs,
                skip_clean=skip_clean,
            )


class ReEntryItemFactory(
    SkipCleanBeforeSaveFactoryMixin,
    factory.django.DjangoModelFactory[ReEntryItem],
):
    """Factory for ReEntryItem model."""

    class Meta:
        model = ReEntryItem
        skip_postgeneration_save = True

    re_entry = factory.SubFactory(ReEntryFactory, pending_payment=True)
    created_by = factory.SubFactory(UserFactory)
    item_type = ReEntryItem.ItemTypeChoices.PUBLIC
    visitor_count = 1

    class Params:
        as_group_item = factory.Trait(
            item_type=ReEntryItem.ItemTypeChoices.GROUP,
        )
        as_online_item = factory.Trait(
            item_type=ReEntryItem.ItemTypeChoices.ONLINE,
        )
        as_school_item = factory.Trait(
            item_type=ReEntryItem.ItemTypeChoices.SCHOOL,
        )


class ReEntryItemEditHistoryFactory(DjangoModelFactory[ReEntryItemEditHistory]):
    class Meta:
        model = ReEntryItemEditHistory
        skip_postgeneration_save = True

    re_entry_item = factory.SubFactory(ReEntryItemFactory)
    field = ReEntryItemEditHistory.FieldChoices.ITEM_TYPE
    prev_value = ReEntryItem.ItemTypeChoices.GROUP
    new_value = ReEntryItem.ItemTypeChoices.PUBLIC
    performed_by = factory.SubFactory(UserFactory)


class ReEntryStatusHistoryFactory(DjangoModelFactory[ReEntryStatusHistory]):
    re_entry = factory.SubFactory(ReEntryFactory)
    prev_status = ReEntry.StatusChoices.PENDING
    new_status = ReEntry.StatusChoices.PENDING_PAYMENT
    performed_by = factory.SubFactory(UserFactory)

    class Meta:
        model = ReEntryStatusHistory
        skip_postgeneration_save = True
