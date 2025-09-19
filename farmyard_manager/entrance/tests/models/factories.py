from datetime import date
from decimal import Decimal

import factory
from factory.django import DjangoModelFactory

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


class PricingFactory(DjangoModelFactory[Pricing]):
    price_type = Pricing.PricingTypes.WEEKDAY
    start_date = date(2024, 1, 1)
    end_date = date(2024, 12, 31)
    price = Decimal("100.00")

    class Meta:
        model = Pricing


class TicketFactory(DjangoModelFactory[Ticket]):
    vehicle = factory.SubFactory(VehicleFactory)
    status = Ticket.StatusChoices.PENDING_SECURITY

    class Meta:
        model = Ticket


class TicketItemFactory(DjangoModelFactory[TicketItem]):
    ticket = factory.SubFactory(TicketFactory)
    created_by = factory.SubFactory(UserFactory)
    item_type = TicketItem.ItemTypeChoices.PUBLIC
    visitor_count = 2
    applied_price = factory.LazyAttribute(lambda obj: Pricing.objects.get_price())  # noqa: ARG005

    class Meta:
        model = TicketItem


class TicketItemEditHistoryFactory(DjangoModelFactory[TicketItemEditHistory]):
    ticket_item = factory.SubFactory(TicketItemFactory)
    field = TicketItemEditHistory.FieldChoices.ITEM_TYPE
    prev_value = TicketItem.ItemTypeChoices.PUBLIC
    new_value = TicketItem.ItemTypeChoices.GROUP
    performed_by = factory.SubFactory(UserFactory)

    class Meta:
        model = TicketItemEditHistory


class TicketStatusHistoryFactory(DjangoModelFactory[TicketStatusHistory]):
    ticket = factory.SubFactory(TicketFactory)
    prev_status = Ticket.StatusChoices.PENDING_SECURITY
    new_status = Ticket.StatusChoices.PASSED_SECURITY
    performed_by = factory.SubFactory(UserFactory)

    class Meta:
        model = TicketStatusHistory


class ReEntryFactory(DjangoModelFactory[ReEntry]):
    ticket = factory.SubFactory(TicketFactory)
    status = ReEntry.StatusChoices.PENDING
    visitors_left = 5
    visitors_returned = None
    completed_time = None

    class Meta:
        model = ReEntry


class ReEntryItemFactory(DjangoModelFactory[ReEntryItem]):
    re_entry = factory.SubFactory(ReEntryFactory)
    created_by = factory.SubFactory(UserFactory)
    item_type = ReEntryItem.ItemTypeChoices.PUBLIC
    visitor_count = 2
    applied_price = factory.LazyAttribute(lambda obj: Pricing.objects.get_price())  # noqa: ARG005

    class Meta:
        model = ReEntryItem


class ReEntryItemEditHistoryFactory(DjangoModelFactory[ReEntryItemEditHistory]):
    re_entry_item = factory.SubFactory(ReEntryItemFactory)
    field = ReEntryItemEditHistory.FieldChoices.ITEM_TYPE
    prev_value = ReEntryItem.ItemTypeChoices.GROUP
    new_value = ReEntryItem.ItemTypeChoices.PUBLIC
    performed_by = factory.SubFactory(UserFactory)

    class Meta:
        model = ReEntryItemEditHistory


class ReEntryStatusHistoryFactory(DjangoModelFactory[ReEntryStatusHistory]):
    re_entry = factory.SubFactory(ReEntryFactory)
    prev_status = ReEntry.StatusChoices.PENDING
    new_status = ReEntry.StatusChoices.PENDING_PAYMENT
    performed_by = factory.SubFactory(UserFactory)

    class Meta:
        model = ReEntryStatusHistory
